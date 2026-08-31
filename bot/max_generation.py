from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from bot import database
from bot import db as db_backend
from bot.max_api import MaxClient
from bot.max_catalog import MAX_VIDEO_TYPES, MaxPresetManager, max_preset_manager
from bot.max_store import (
    MaxInsufficientBalanceError,
    apply_max_balance_delta,
    ensure_max_schema,
    record_max_generation,
)
from bot.services.gemini_omni_service import gemini_omni_service
from bot.services.gpt_image_service import gpt_image_service
from bot.services.grok_service import grok_service
from bot.services.kling_service import kling_service
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.seedance_service import seedance_service
from bot.services.seedream_service import seedream_service
from bot.services.veo_service import veo_service
from bot.services.wan27_service import wan27_service

logger = logging.getLogger(__name__)

_WORKER_CONCURRENCY = 4
_WORKER_POLL_SECONDS = 1.0
_JOB_LEASE_SECONDS = 20 * 60
_RETRY_DELAY_SECONDS = 20
_PROVIDER_POLL_SECONDS = 5
_MAX_PROVIDER_STATUS_ERRORS = 5
_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()


class MaxGenerationRetry(RuntimeError):
    """Retry the same durable MAX job without refunding or regenerating."""


@dataclass(frozen=True)
class MaxGenerationJob:
    id: str
    max_user_id: int
    kind: str
    generation_type: str
    model: str
    prompt: str
    cost: float
    input_data: dict[str, Any]
    options: dict[str, Any]
    status: str
    provider_kind: str | None
    provider_task_id: str | None
    result_url: str | None
    delivered_at_epoch: int | None
    attempt_count: int


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}:max-generation"
    return f"sqlite:{database.DATABASE_PATH}:max-generation"


def _schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS max_generation_jobs (
            id TEXT PRIMARY KEY,
            max_user_id BIGINT NOT NULL,
            kind TEXT NOT NULL,
            generation_type TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL,
            prompt TEXT NOT NULL DEFAULT '',
            cost REAL NOT NULL DEFAULT 0,
            input_json TEXT NOT NULL DEFAULT '{}',
            options_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            provider_kind TEXT,
            provider_task_id TEXT,
            result_url TEXT,
            delivered_at_epoch BIGINT,
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at_epoch BIGINT NOT NULL DEFAULT 0,
            lease_expires_at_epoch BIGINT,
            created_at_epoch BIGINT NOT NULL,
            updated_at_epoch BIGINT NOT NULL,
            completed_at_epoch BIGINT,
            FOREIGN KEY (max_user_id) REFERENCES max_users(max_user_id) ON DELETE CASCADE
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_max_generation_jobs_worker "
            "ON max_generation_jobs(status, next_attempt_at_epoch, created_at_epoch)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_max_generation_jobs_user "
            "ON max_generation_jobs(max_user_id, created_at_epoch)"
        ),
    )


async def _create_postgres_schema(db: db_backend.Connection) -> None:
    raw = getattr(db, "_conn", None)
    if raw is None:
        raise RuntimeError("PostgreSQL connection does not expose migration handle")
    async with raw.cursor() as cursor:
        for statement in _schema_statements():
            await cursor.execute(statement)
    await raw.commit()


async def ensure_max_generation_schema() -> None:
    await ensure_max_schema()
    key = _schema_key()
    if key in _SCHEMA_READY:
        return
    async with _schema_lock():
        if key in _SCHEMA_READY:
            return
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                await _create_postgres_schema(db)
            else:
                for statement in _schema_statements():
                    await db.execute(statement)
                await db.commit()
        _SCHEMA_READY.add(key)


def _use_mapping_rows(db: db_backend.Connection) -> None:
    db.row_factory = db_backend.Row


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_to_job(row: Any | None) -> MaxGenerationJob | None:
    if row is None:
        return None
    return MaxGenerationJob(
        id=str(row["id"]),
        max_user_id=int(row["max_user_id"]),
        kind=str(row["kind"]),
        generation_type=str(row["generation_type"] or ""),
        model=str(row["model"]),
        prompt=str(row["prompt"] or ""),
        cost=float(row["cost"] or 0),
        input_data=_json_object(row["input_json"]),
        options=_json_object(row["options_json"]),
        status=str(row["status"]),
        provider_kind=str(row["provider_kind"]) if row["provider_kind"] else None,
        provider_task_id=(
            str(row["provider_task_id"]) if row["provider_task_id"] else None
        ),
        result_url=str(row["result_url"]) if row["result_url"] else None,
        delivered_at_epoch=(
            int(row["delivered_at_epoch"])
            if row["delivered_at_epoch"] is not None
            else None
        ),
        attempt_count=int(row["attempt_count"] or 0),
    )


def _encoded(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _insert_job(job: MaxGenerationJob) -> None:
    await ensure_max_generation_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO max_generation_jobs (
                id, max_user_id, kind, generation_type, model, prompt, cost,
                input_json, options_json, status, provider_kind, provider_task_id,
                result_url, delivered_at_epoch, error, attempt_count,
                next_attempt_at_epoch, lease_expires_at_epoch, created_at_epoch,
                updated_at_epoch, completed_at_epoch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', NULL, NULL, NULL,
                      NULL, NULL, 0, 0, NULL, ?, ?, NULL)
            """,
            (
                job.id,
                job.max_user_id,
                job.kind,
                job.generation_type,
                job.model,
                job.prompt,
                job.cost,
                _encoded(job.input_data),
                _encoded(job.options),
                now,
                now,
            ),
        )
        await db.commit()


async def _activate_job(job_id: str) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE max_generation_jobs
            SET status = 'queued', next_attempt_at_epoch = 0,
                updated_at_epoch = ?
            WHERE id = ? AND status = 'prepared'
            """,
            (int(time.time()), job_id),
        )
        await db.commit()


async def enqueue_max_generation(
    max_user_id: int,
    *,
    kind: str,
    generation_type: str,
    model: str,
    prompt: str,
    input_data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    catalog: MaxPresetManager = max_preset_manager,
) -> MaxGenerationJob:
    """Prepare, debit and queue one MAX-owned generation exactly once."""
    clean_kind = str(kind or "").strip().lower()
    clean_type = str(generation_type or "").strip().lower()
    clean_model = str(model or "").strip()
    clean_prompt = str(prompt or "").strip()
    inputs = dict(input_data or {})
    opts = dict(options or {})

    if clean_kind not in {"image", "video"}:
        raise ValueError("Unsupported MAX generation kind")
    if not clean_prompt:
        raise ValueError("Generation prompt is required")

    if clean_kind == "image":
        if clean_model not in catalog.image_models():
            raise ValueError(f"Unsupported MAX image model: {clean_model}")
        cost = catalog.image_cost(clean_model)
    else:
        if clean_type not in MAX_VIDEO_TYPES:
            raise ValueError(f"Unsupported MAX video type: {clean_type}")
        if clean_model not in catalog.video_models(clean_type):
            raise ValueError(
                f"MAX video model {clean_model} is not available for {clean_type}"
            )
        duration = int(opts.get("duration") or _default_video_duration(clean_model))
        quality = str(opts.get("resolution") or "").strip() or None
        pricing_quality = (
            quality
            if clean_model.startswith("veo3") or clean_model == "gemini_omni"
            else None
        )
        cost = catalog.video_cost(
            clean_model,
            duration=duration,
            quality=pricing_quality,
        )

    job = MaxGenerationJob(
        id=uuid.uuid4().hex,
        max_user_id=int(max_user_id),
        kind=clean_kind,
        generation_type=clean_type,
        model=clean_model,
        prompt=clean_prompt,
        cost=float(cost),
        input_data=inputs,
        options=opts,
        status="prepared",
        provider_kind=None,
        provider_task_id=None,
        result_url=None,
        delivered_at_epoch=None,
        attempt_count=0,
    )
    await _insert_job(job)
    try:
        await apply_max_balance_delta(
            max_user_id,
            -job.cost,
            tx_type="generation",
            idempotency_key=f"maxgen:{job.id}:debit",
            metadata={
                "job_id": job.id,
                "kind": job.kind,
                "model": job.model,
                "generation_type": job.generation_type,
            },
        )
    except MaxInsufficientBalanceError:
        await _mark_job_failed(job.id, "insufficient_balance")
        raise
    except Exception:
        await _mark_job_failed(job.id, "billing_error")
        raise

    await record_max_generation(
        max_user_id,
        generation_key=job.id,
        kind=job.kind,
        model=job.model,
        prompt=job.prompt,
        status="queued",
        cost=job.cost,
        request_data={"input": inputs, "options": opts, "generation_type": clean_type},
    )
    await _activate_job(job.id)
    return job


async def get_max_generation_job(job_id: str) -> MaxGenerationJob | None:
    await ensure_max_generation_schema()
    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        cursor = await db.execute(
            "SELECT * FROM max_generation_jobs WHERE id = ?",
            (str(job_id),),
        )
        return _row_to_job(await cursor.fetchone())


async def _claim_next_job() -> MaxGenerationJob | None:
    await ensure_max_generation_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        cursor = await db.execute(
            """
            SELECT * FROM max_generation_jobs
            WHERE (
                    status = 'queued'
                    OR (
                        status = 'processing'
                        AND lease_expires_at_epoch IS NOT NULL
                        AND lease_expires_at_epoch < ?
                    )
                  )
              AND next_attempt_at_epoch <= ?
            ORDER BY created_at_epoch ASC
            LIMIT 1
            """,
            (now, now),
        )
        job = _row_to_job(await cursor.fetchone())
        if job is None:
            return None
        claim = await db.execute(
            """
            UPDATE max_generation_jobs
            SET status = 'processing', lease_expires_at_epoch = ?,
                attempt_count = attempt_count + 1, updated_at_epoch = ?
            WHERE id = ?
              AND (
                    status = 'queued'
                    OR (
                        status = 'processing'
                        AND lease_expires_at_epoch IS NOT NULL
                        AND lease_expires_at_epoch < ?
                    )
                  )
            """,
            (now + _JOB_LEASE_SECONDS, now, job.id, now),
        )
        if int(getattr(claim, "rowcount", 0) or 0) != 1:
            await db.rollback()
            return None
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM max_generation_jobs WHERE id = ?",
            (job.id,),
        )
        return _row_to_job(await cursor.fetchone())


async def _mark_provider_task(job_id: str, provider_kind: str, task_id: str) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE max_generation_jobs
            SET provider_kind = ?, provider_task_id = ?, updated_at_epoch = ?
            WHERE id = ?
            """,
            (provider_kind, task_id, int(time.time()), job_id),
        )
        await db.commit()


async def _mark_result(job_id: str, result_url: str) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE max_generation_jobs
            SET result_url = ?, updated_at_epoch = ?
            WHERE id = ?
            """,
            (result_url, int(time.time()), job_id),
        )
        await db.commit()


async def _mark_delivered(job_id: str) -> int:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE max_generation_jobs
            SET delivered_at_epoch = COALESCE(delivered_at_epoch, ?), updated_at_epoch = ?
            WHERE id = ?
            """,
            (now, now, job_id),
        )
        await db.commit()
    return now


async def _mark_job_succeeded(job_id: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE max_generation_jobs
            SET status = 'succeeded', error = NULL, lease_expires_at_epoch = NULL,
                updated_at_epoch = ?, completed_at_epoch = ?
            WHERE id = ?
            """,
            (now, now, job_id),
        )
        await db.commit()


async def _mark_job_failed(job_id: str, error: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE max_generation_jobs
            SET status = 'failed', error = ?, lease_expires_at_epoch = NULL,
                updated_at_epoch = ?, completed_at_epoch = ?
            WHERE id = ?
            """,
            (str(error)[:1000], now, now, job_id),
        )
        await db.commit()


async def _retry_job(job_id: str, error: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE max_generation_jobs
            SET status = 'queued', error = ?, lease_expires_at_epoch = NULL,
                next_attempt_at_epoch = ?, updated_at_epoch = ?
            WHERE id = ?
            """,
            (str(error)[:1000], now + _RETRY_DELAY_SECONDS, now, job_id),
        )
        await db.commit()


async def _refund_job(job: MaxGenerationJob, reason: str) -> None:
    await apply_max_balance_delta(
        job.max_user_id,
        job.cost,
        tx_type="refund",
        idempotency_key=f"maxgen:{job.id}:refund",
        metadata={"job_id": job.id, "reason": str(reason)[:500]},
    )


def _first_url(value: Any) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.startswith(("http://", "https://")):
            return candidate
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
        return _first_url(parsed)
    if isinstance(value, list):
        for item in value:
            result = _first_url(item)
            if result:
                return result
        return ""
    if isinstance(value, dict):
        for key in (
            "url",
            "resultUrl",
            "result_url",
            "videoUrl",
            "imageUrl",
            "output",
            "resultUrls",
            "fullResultUrls",
            "originUrls",
            "urls",
            "videos",
            "images",
            "resultJson",
            "result_json",
            "data",
            "response",
            "info",
        ):
            if key in value:
                result = _first_url(value[key])
                if result:
                    return result
    return ""


def _status_name(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    for key in ("status", "state", "taskStatus", "task_status"):
        value = data.get(key) if isinstance(data, dict) else None
        if value not in (None, ""):
            return str(value).strip().lower()
    return ""


def _provider_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "Provider returned an invalid response"
    for key in ("message", "msg", "error", "failMsg", "fail_msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        nested = _provider_error(data)
        if nested != "Provider returned an invalid response":
            return nested
    return "Generation provider failed"


def _task_id_from_result(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    for key in ("task_id", "taskId"):
        value = result.get(key)
        if value:
            return str(value)
    data = result.get("data")
    if isinstance(data, dict):
        for key in ("task_id", "taskId"):
            value = data.get(key)
            if value:
                return str(value)
    return ""


def _default_video_duration(model: str) -> int:
    return {
        "grok_imagine": 6,
        "grok_imagine_v15": 8,
        "gemini_omni": 6,
        "veo3": 6,
        "veo3_fast": 6,
        "veo3_lite": 6,
    }.get(model, 5)


def _image_refs(job: MaxGenerationJob) -> list[str]:
    values = job.input_data.get("image_urls") or []
    return [str(value) for value in values if str(value or "").strip()]


def _video_refs(job: MaxGenerationJob) -> list[str]:
    values = job.input_data.get("video_urls") or []
    return [str(value) for value in values if str(value or "").strip()]


async def _submit_image(job: MaxGenerationJob) -> tuple[str, str]:
    refs = _image_refs(job)
    ratio = str(job.options.get("aspect_ratio") or "1:1")
    quality = str(job.options.get("quality") or "2K")

    if job.model in {"banana_2", "nano-banana-2-lite"}:
        provider_model = (
            "nano-banana-2-lite"
            if job.model == "nano-banana-2-lite"
            else "nano-banana-2"
        )
        task_id = await nano_banana_2_service.create_task(
            job.prompt,
            refs,
            ratio,
            quality,
            "png",
            None,
            provider_model,
        )
        if not task_id:
            raise RuntimeError("Nano Banana 2 did not create a task")
        return "nano_banana_2", str(task_id)

    if job.model == "banana_pro":
        task_id = await nano_banana_pro_service.create_task(
            job.prompt,
            refs,
            ratio,
            quality,
            "png",
            None,
        )
        if not task_id:
            raise RuntimeError("Nano Banana Pro did not create a task")
        return "nano_banana_pro", str(task_id)

    if job.model in {"seedream_edit", "seedream_5_pro"}:
        if job.model == "seedream_edit" and not refs:
            raise RuntimeError("Seedream 4.5 requires an image reference")
        if refs:
            model = (
                "seedream/4.5-edit"
                if job.model == "seedream_edit"
                else "seedream/5-pro-image-to-image"
            )
            result = await seedream_service.generate_image(
                job.prompt,
                refs,
                aspect_ratio=ratio,
                quality=quality,
                model=model,
            )
        else:
            result = await seedream_service.generate_text_to_image(
                job.prompt,
                aspect_ratio=ratio,
                quality=quality,
                model="seedream/5-pro-text-to-image",
            )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    if job.model == "flux_pro":
        if refs:
            result = await gpt_image_service.generate_image_to_image(
                job.prompt,
                refs,
                aspect_ratio=ratio,
            )
        else:
            result = await gpt_image_service.generate_image(
                job.prompt,
                aspect_ratio=ratio,
            )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    if job.model == "grok_imagine_i2i":
        if not refs:
            raise RuntimeError("Grok Imagine requires an image reference")
        result = await grok_service.generate_image_to_image(refs, job.prompt)
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    if job.model == "wan_27":
        result = await wan27_service.generate_image(
            prompt=job.prompt,
            aspect_ratio=ratio,
            input_urls=refs,
            n=1,
            resolution=quality,
        )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    raise RuntimeError(f"Unsupported MAX image model: {job.model}")


async def _submit_video(job: MaxGenerationJob) -> tuple[str, str]:
    duration = int(job.options.get("duration") or _default_video_duration(job.model))
    ratio = str(job.options.get("aspect_ratio") or "16:9")
    resolution = str(job.options.get("resolution") or "720p")
    image_refs = _image_refs(job)
    video_refs = _video_refs(job)

    if job.model in {"v3_pro", "v3_std", "v26_pro"}:
        result = await kling_service.generate_video(
            job.prompt,
            model=job.model,
            duration=duration,
            aspect_ratio=ratio,
            image_url=image_refs[0] if image_refs else None,
            image_input=image_refs,
            generate_audio=bool(job.options.get("generate_audio", True)),
        )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    if job.model == "seedance_2":
        first_frame = image_refs[0] if job.generation_type == "imgtxt" and image_refs else None
        reference_images = [] if first_frame else image_refs
        result = await seedance_service.generate_video(
            prompt=job.prompt,
            duration=duration,
            aspect_ratio=ratio,
            resolution=resolution,
            first_frame_url=first_frame,
            reference_image_urls=reference_images,
            reference_video_urls=video_refs,
            generate_audio=bool(job.options.get("generate_audio", True)),
        )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    if job.model in {"grok_imagine", "grok_imagine_v15"}:
        if not image_refs:
            raise RuntimeError("Grok video requires an image reference")
        if job.model == "grok_imagine_v15":
            result = await grok_service.generate_image_to_video_v15(
                image_refs,
                prompt=job.prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=ratio,
            )
        else:
            result = await grok_service.generate_image_to_video(
                image_refs,
                prompt=job.prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=ratio,
            )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    if job.model == "gemini_omni":
        video_list = [
            {"url": url, "start": 0, "ends": min(20, max(1, duration))}
            for url in video_refs[:1]
        ]
        result = await gemini_omni_service.generate_video(
            prompt=job.prompt,
            duration=duration,
            aspect_ratio=ratio,
            resolution=resolution,
            image_urls=image_refs,
            video_list=video_list,
        )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    if job.model.startswith("veo3"):
        result = await veo_service.generate_video(
            job.prompt,
            model=job.model,
            duration=duration,
            generation_type=job.generation_type,
            image_urls=image_refs,
            aspect_ratio=ratio,
            resolution=resolution,
        )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "veo", task_id

    if job.model == "glow":
        if not image_refs or not video_refs:
            raise RuntimeError("Kling Glow requires image and video references")
        result = await kling_service.generate_video(
            job.prompt,
            model="glow",
            image_url=image_refs[0],
            video_urls=video_refs[:1],
        )
        task_id = _task_id_from_result(result)
        if not task_id:
            raise RuntimeError(_provider_error(result))
        return "kie", task_id

    raise RuntimeError(f"Unsupported MAX video model: {job.model}")


async def _submit_provider(job: MaxGenerationJob) -> tuple[str, str]:
    if job.kind == "image":
        return await _submit_image(job)
    return await _submit_video(job)


async def _provider_status(job: MaxGenerationJob) -> Any:
    task_id = str(job.provider_task_id or "")
    if not task_id:
        raise RuntimeError("MAX job has no provider task id")
    if job.provider_kind == "nano_banana_2":
        return await nano_banana_2_service.get_task_status(task_id)
    if job.provider_kind == "nano_banana_pro":
        return await nano_banana_pro_service.get_task_status(task_id)
    if job.provider_kind == "veo":
        return await veo_service.get_video_details(task_id)
    return await kling_service.get_task_status(task_id)


def _status_result(payload: Any) -> tuple[str, str]:
    state = _status_name(payload)
    result_url = _first_url(payload)
    success_states = {"success", "succeeded", "completed", "done", "finish", "finished"}
    failed_states = {"fail", "failed", "error", "cancelled", "canceled"}

    if state in success_states:
        if not result_url:
            raise RuntimeError("Provider completed without a result URL")
        return "success", result_url
    if state in failed_states:
        raise RuntimeError(_provider_error(payload))
    if result_url and state not in failed_states:
        return "success", result_url
    return "pending", ""


async def _poll_provider(job: MaxGenerationJob) -> str:
    status = await _provider_status(job)
    if status is None:
        if job.attempt_count >= _MAX_PROVIDER_STATUS_ERRORS:
            raise RuntimeError("Provider status remained unavailable")
        raise MaxGenerationRetry("Provider status is temporarily unavailable")
    outcome, url = _status_result(status)
    if outcome == "success":
        return url
    raise MaxGenerationRetry("Provider task is still processing")


class MaxGenerationService:
    def __init__(self, client: MaxClient):
        self.client = client
        self._stop_event = asyncio.Event()
        self._active: set[asyncio.Task[Any]] = set()

    async def _deliver(self, job: MaxGenerationJob, result_url: str) -> None:
        if job.delivered_at_epoch is not None:
            return
        media_type = "image" if job.kind == "image" else "video"
        filename = f"happyfox-{job.id}.{'jpg' if media_type == 'image' else 'mp4'}"
        await self.client.send_media_url(
            job.max_user_id,
            media_type=media_type,
            url=result_url,
            text=(
                "Готово ✨\n\nРезультат сохранён в истории MAX."
                if job.kind == "image"
                else "Готово 🎬\n\nВидео сохранено в истории MAX."
            ),
            filename=filename,
        )
        await _mark_delivered(job.id)

    async def _process(self, job: MaxGenerationJob) -> None:
        current = job
        if not current.result_url and not current.provider_task_id:
            provider_kind, task_id = await _submit_provider(current)
            await _mark_provider_task(current.id, provider_kind, task_id)
            current = await get_max_generation_job(current.id) or current

        result_url = current.result_url
        if not result_url:
            result_url = await _poll_provider(current)
            await _mark_result(current.id, result_url)
            current = await get_max_generation_job(current.id) or current

        await self._deliver(current, result_url)
        await record_max_generation(
            current.max_user_id,
            generation_key=current.id,
            kind=current.kind,
            model=current.model,
            prompt=current.prompt,
            status="completed",
            cost=current.cost,
            provider_task_id=current.provider_task_id,
            result_url=result_url,
            request_data={
                "input": current.input_data,
                "options": current.options,
                "generation_type": current.generation_type,
            },
        )
        await _mark_job_succeeded(current.id)

    async def _handle_job(self, job: MaxGenerationJob) -> None:
        try:
            await self._process(job)
        except MaxGenerationRetry as exc:
            await _retry_job(job.id, str(exc))
        except Exception as exc:
            logger.exception("MAX generation failed: job_id=%s", job.id)
            current = await get_max_generation_job(job.id) or job
            await _refund_job(current, str(exc))
            await record_max_generation(
                current.max_user_id,
                generation_key=current.id,
                kind=current.kind,
                model=current.model,
                prompt=current.prompt,
                status="failed",
                cost=current.cost,
                provider_task_id=current.provider_task_id,
                result_url=current.result_url,
                request_data={
                    "input": current.input_data,
                    "options": current.options,
                    "generation_type": current.generation_type,
                    "error": str(exc)[:500],
                },
            )
            await _mark_job_failed(current.id, str(exc))
            with contextlib.suppress(Exception):
                await self.client.send_message(
                    current.max_user_id,
                    "Не удалось завершить генерацию. Баланс MAX восстановлен. "
                    "Можно попробовать ещё раз.",
                )

    async def run_once(self) -> bool:
        if len(self._active) >= _WORKER_CONCURRENCY:
            return False
        job = await _claim_next_job()
        if job is None:
            return False
        task = asyncio.create_task(self._handle_job(job))
        self._active.add(task)
        task.add_done_callback(self._active.discard)
        return True

    async def worker_loop(self) -> None:
        await ensure_max_generation_schema()
        while not self._stop_event.is_set():
            launched = False
            while len(self._active) < _WORKER_CONCURRENCY:
                if not await self.run_once():
                    break
                launched = True
            if not launched:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=_WORKER_POLL_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)

    async def stop(self) -> None:
        self._stop_event.set()


def install_max_generation_worker(
    app: web.Application,
    service: MaxGenerationService,
) -> None:
    async def worker_ctx(_app: web.Application):
        task = asyncio.create_task(service.worker_loop())
        try:
            yield
        finally:
            await service.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.cleanup_ctx.append(worker_ctx)
