from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import database
from bot import db as db_backend
from bot.database import get_or_create_user
from bot.max_api import MaxClient, callback_button, inline_keyboard
from bot.max_store import (
    MaxInsufficientBalanceError,
    apply_max_balance_delta,
)
from bot.services.suno_service import SunoApiError, suno_service
from bot.suno_pricing import get_suno_price

logger = logging.getLogger(__name__)

_WORKER_POLL_SECONDS = 1.0
_PROVIDER_RECHECK_SECONDS = 10
_JOB_LEASE_SECONDS = 20 * 60
_MAX_ATTEMPTS = 10
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK: asyncio.Lock | None = None


class SunoJobRetry(RuntimeError):
    pass


@dataclass(frozen=True)
class SunoJob:
    id: str
    channel: str
    user_id: int
    operation: str
    model: str | None
    cost: float
    request_data: dict[str, Any]
    status: str
    provider_task_id: str | None
    result_data: dict[str, Any]
    error: str | None
    attempt_count: int
    delivered_at_epoch: int | None
    refunded: bool


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}:suno-jobs"
    return f"sqlite:{database.DATABASE_PATH}:suno-jobs"


def _schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS suno_jobs (
            id TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            user_id BIGINT NOT NULL,
            operation TEXT NOT NULL,
            model TEXT,
            cost REAL NOT NULL DEFAULT 0,
            request_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            provider_task_id TEXT,
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at_epoch BIGINT NOT NULL DEFAULT 0,
            lease_expires_at_epoch BIGINT,
            delivered_at_epoch BIGINT,
            refunded INTEGER NOT NULL DEFAULT 0,
            created_at_epoch BIGINT NOT NULL,
            updated_at_epoch BIGINT NOT NULL,
            completed_at_epoch BIGINT
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_suno_jobs_worker "
            "ON suno_jobs(status, next_attempt_at_epoch, created_at_epoch)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_suno_jobs_user "
            "ON suno_jobs(channel, user_id, created_at_epoch)"
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


async def ensure_suno_schema() -> None:
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


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_to_job(row: Any | None) -> SunoJob | None:
    if row is None:
        return None
    return SunoJob(
        id=str(row["id"]),
        channel=str(row["channel"]),
        user_id=int(row["user_id"]),
        operation=str(row["operation"]),
        model=str(row["model"]) if row["model"] else None,
        cost=float(row["cost"] or 0),
        request_data=_json_obj(row["request_json"]),
        status=str(row["status"]),
        provider_task_id=str(row["provider_task_id"]) if row["provider_task_id"] else None,
        result_data=_json_obj(row["result_json"]),
        error=str(row["error"]) if row["error"] else None,
        attempt_count=int(row["attempt_count"] or 0),
        delivered_at_epoch=(
            int(row["delivered_at_epoch"])
            if row["delivered_at_epoch"] is not None
            else None
        ),
        refunded=bool(row["refunded"]),
    )


async def _insert_prepared(job: SunoJob) -> None:
    await ensure_suno_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO suno_jobs (
                id, channel, user_id, operation, model, cost, request_json,
                status, provider_task_id, result_json, error, attempt_count,
                next_attempt_at_epoch, lease_expires_at_epoch, delivered_at_epoch,
                refunded, created_at_epoch, updated_at_epoch, completed_at_epoch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', NULL, '{}', NULL, 0,
                      0, NULL, NULL, 0, ?, ?, NULL)
            """,
            (
                job.id,
                job.channel,
                job.user_id,
                job.operation,
                job.model,
                job.cost,
                _json(job.request_data),
                now,
                now,
            ),
        )
        await db.commit()


async def _mark_failed(job_id: str, error: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE suno_jobs
            SET status='failed', error=?, lease_expires_at_epoch=NULL,
                updated_at_epoch=?, completed_at_epoch=?
            WHERE id=?
            """,
            (str(error)[:1000], now, now, job_id),
        )
        await db.commit()


async def _activate_max_job(job: SunoJob) -> None:
    try:
        await apply_max_balance_delta(
            job.user_id,
            -job.cost,
            tx_type="generation",
            idempotency_key=f"suno:{job.id}:debit",
            metadata={
                "job_id": job.id,
                "operation": job.operation,
                "model": job.model,
                "channel": "max",
            },
        )
    except MaxInsufficientBalanceError:
        await _mark_failed(job.id, "insufficient_balance")
        raise
    except Exception:
        await _mark_failed(job.id, "billing_error")
        raise
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE suno_jobs
            SET status='queued', updated_at_epoch=?, next_attempt_at_epoch=0
            WHERE id=? AND status='prepared'
            """,
            (int(time.time()), job.id),
        )
        await db.commit()


async def _activate_telegram_job(job: SunoJob) -> None:
    await get_or_create_user(job.user_id)
    now = int(time.time())
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE users
            SET credits = credits - ?
            WHERE telegram_id = ? AND credits >= ?
            """,
            (job.cost, job.user_id, job.cost),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            await db.rollback()
            await _mark_failed(job.id, "insufficient_balance")
            raise ValueError("insufficient_balance")
        await db.execute(
            """
            UPDATE suno_jobs
            SET status='queued', updated_at_epoch=?, next_attempt_at_epoch=0
            WHERE id=? AND status='prepared'
            """,
            (now, job.id),
        )
        await db.commit()


async def enqueue_suno_job(
    channel: str,
    user_id: int,
    *,
    operation: str,
    request_data: dict[str, Any],
    model: str | None = None,
) -> SunoJob:
    clean_channel = str(channel or "").strip().lower()
    if clean_channel not in {"telegram", "max"}:
        raise ValueError("Unsupported Suno channel")
    clean_operation = str(operation or "").strip().lower()
    clean_model = str(model or "").strip().upper() or None
    cost = await get_suno_price(clean_channel, clean_operation, clean_model)
    job = SunoJob(
        id=uuid.uuid4().hex,
        channel=clean_channel,
        user_id=int(user_id),
        operation=clean_operation,
        model=clean_model,
        cost=float(cost),
        request_data=dict(request_data or {}),
        status="prepared",
        provider_task_id=None,
        result_data={},
        error=None,
        attempt_count=0,
        delivered_at_epoch=None,
        refunded=False,
    )
    await _insert_prepared(job)
    if clean_channel == "telegram":
        await _activate_telegram_job(job)
    else:
        await _activate_max_job(job)
    return job


async def get_suno_job(job_id: str) -> SunoJob | None:
    await ensure_suno_schema()
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT * FROM suno_jobs WHERE id=?",
            (str(job_id),),
        )
        return _row_to_job(await cursor.fetchone())


async def list_suno_jobs(
    channel: str,
    user_id: int,
    *,
    limit: int = 10,
) -> list[SunoJob]:
    await ensure_suno_schema()
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT * FROM suno_jobs
            WHERE channel=? AND user_id=?
            ORDER BY created_at_epoch DESC
            LIMIT ?
            """,
            (str(channel), int(user_id), max(1, min(int(limit), 50))),
        )
        rows = await cursor.fetchall()
    return [job for row in rows if (job := _row_to_job(row)) is not None]


async def _claim_next() -> SunoJob | None:
    await ensure_suno_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT * FROM suno_jobs
            WHERE (
                status='queued'
                OR (
                    status='processing'
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
        cursor = await db.execute(
            """
            UPDATE suno_jobs
            SET status='processing', attempt_count=attempt_count+1,
                lease_expires_at_epoch=?, updated_at_epoch=?
            WHERE id=? AND (
                status='queued'
                OR (
                    status='processing'
                    AND lease_expires_at_epoch IS NOT NULL
                    AND lease_expires_at_epoch < ?
                )
            )
            """,
            (now + _JOB_LEASE_SECONDS, now, job.id, now),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            await db.rollback()
            return None
        await db.commit()
    return await get_suno_job(job.id)


async def _set_provider_task(job_id: str, task_id: str) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE suno_jobs SET provider_task_id=?, updated_at_epoch=?
            WHERE id=?
            """,
            (str(task_id), int(time.time()), job_id),
        )
        await db.commit()


async def _set_result(job_id: str, result: dict[str, Any]) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE suno_jobs SET result_json=?, updated_at_epoch=?
            WHERE id=?
            """,
            (_json(result), int(time.time()), job_id),
        )
        await db.commit()


async def _retry(job_id: str, reason: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE suno_jobs
            SET status='queued', error=?, next_attempt_at_epoch=?,
                lease_expires_at_epoch=NULL, updated_at_epoch=?
            WHERE id=?
            """,
            (str(reason)[:1000], now + _PROVIDER_RECHECK_SECONDS, now, job_id),
        )
        await db.commit()


async def _mark_delivered(job_id: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE suno_jobs
            SET delivered_at_epoch=COALESCE(delivered_at_epoch, ?), updated_at_epoch=?
            WHERE id=?
            """,
            (now, now, job_id),
        )
        await db.commit()


async def _mark_success(job_id: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE suno_jobs
            SET status='succeeded', error=NULL, lease_expires_at_epoch=NULL,
                updated_at_epoch=?, completed_at_epoch=?
            WHERE id=?
            """,
            (now, now, job_id),
        )
        await db.commit()


async def _refund_telegram(job: SunoJob) -> None:
    if job.refunded or job.cost <= 0:
        return
    now = int(time.time())
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE suno_jobs
            SET refunded=1, updated_at_epoch=?
            WHERE id=? AND refunded=0
            """,
            (now, job.id),
        )
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            await db.rollback()
            return
        await db.execute(
            """
            UPDATE users SET credits=credits+?
            WHERE telegram_id=?
            """,
            (job.cost, job.user_id),
        )
        await db.commit()


async def _refund_max(job: SunoJob) -> None:
    if job.refunded or job.cost <= 0:
        return
    await apply_max_balance_delta(
        job.user_id,
        job.cost,
        tx_type="refund",
        idempotency_key=f"suno:{job.id}:refund",
        metadata={"job_id": job.id, "operation": job.operation},
    )
    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE suno_jobs SET refunded=1, updated_at_epoch=? WHERE id=?",
            (int(time.time()), job.id),
        )
        await db.commit()


async def _refund(job: SunoJob) -> None:
    if job.channel == "telegram":
        await _refund_telegram(job)
    else:
        await _refund_max(job)


def _result_urls(result: dict[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in result.get("urls") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        label = str(item.get("label") or "result").strip()
        if url.startswith("https://") and url not in seen:
            seen.add(url)
            found.append((label, url))
    return found


def _telegram_track_markup(job: SunoJob, index: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="➕ Продолжить",
                callback_data=f"suno:from:extend:{job.id}:{index}",
            ),
            InlineKeyboardButton(
                text="🎧 WAV",
                callback_data=f"suno:from:wav:{job.id}:{index}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎬 Music Video",
                callback_data=f"suno:from:music_video:{job.id}:{index}",
            ),
            InlineKeyboardButton(
                text="📝 Таймкоды",
                callback_data=f"suno:from:timestamped_lyrics:{job.id}:{index}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎭 Persona",
                callback_data=f"suno:from:persona:{job.id}:{index}",
            ),
            InlineKeyboardButton(
                text="🎚 Стемы",
                callback_data=f"suno:from:separate_vocal:{job.id}:{index}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _max_track_attachments(job: SunoJob, index: int) -> list[dict[str, Any]]:
    return [
        inline_keyboard(
            [
                [
                    callback_button(
                        "➕ Продолжить",
                        f"max:suno:from:extend:{job.id}:{index}",
                    ),
                    callback_button(
                        "🎧 WAV",
                        f"max:suno:from:wav:{job.id}:{index}",
                    ),
                ],
                [
                    callback_button(
                        "🎬 Video",
                        f"max:suno:from:music_video:{job.id}:{index}",
                    ),
                    callback_button(
                        "📝 Таймкоды",
                        f"max:suno:from:timestamped_lyrics:{job.id}:{index}",
                    ),
                ],
                [
                    callback_button(
                        "🎭 Persona",
                        f"max:suno:from:persona:{job.id}:{index}",
                    ),
                    callback_button(
                        "🎚 Стемы",
                        f"max:suno:from:separate_vocal:{job.id}:{index}",
                    ),
                ],
            ]
        )
    ]


async def _deliver_telegram(bot: Bot, job: SunoJob, result: dict[str, Any]) -> None:
    if job.delivered_at_epoch is not None:
        return
    tracks = result.get("tracks") or []
    if tracks:
        for index, track in enumerate(tracks):
            if not isinstance(track, dict):
                continue
            url = str(track.get("audio_url") or "").strip()
            if not url.startswith("https://"):
                continue
            title = str(track.get("title") or "Suno").strip()[:64]
            audio_id = str(track.get("audio_id") or "").strip()
            caption = (
                f"🎵 <b>{html.escape(title)}</b>\n"
                f"Audio ID: <code>{html.escape(audio_id)}</code>\n"
                f"Task ID: <code>{html.escape(str(job.provider_task_id or ''))}</code>"
            )
            try:
                await bot.send_audio(
                    job.user_id,
                    audio=url,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=_telegram_track_markup(job, index),
                )
            except Exception:
                await bot.send_message(
                    job.user_id,
                    f"{caption}\n\n{html.escape(url)}",
                    parse_mode="HTML",
                    reply_markup=_telegram_track_markup(job, index),
                )
        await _mark_delivered(job.id)
        return

    if job.operation == "lyrics":
        raw = result.get("lyrics")
        text = json.dumps(raw, ensure_ascii=False, indent=2) if not isinstance(raw, str) else raw
        await bot.send_message(
            job.user_id,
            f"✍️ <b>Текст Suno готов</b>\n\n{html.escape(text[:3500])}",
            parse_mode="HTML",
        )
    elif job.operation == "voice_validate":
        phrase = str(result.get("validate_info") or "").strip()
        await bot.send_message(
            job.user_id,
            "🎙 <b>Фраза для проверки голоса готова</b>\n\n"
            f"<code>{html.escape(phrase)}</code>\n\n"
            f"Task ID: <code>{html.escape(str(job.provider_task_id or ''))}</code>\n"
            "Запишите эту фразу и откройте «Suno Voice → Создать голос».",
            parse_mode="HTML",
        )
    elif job.operation == "voice_generate":
        voice_id = str(result.get("voice_id") or "").strip()
        await bot.send_message(
            job.user_id,
            "🎙 <b>Suno Voice готов</b>\n\n"
            f"Voice ID: <code>{html.escape(voice_id)}</code>",
            parse_mode="HTML",
        )
    elif job.operation == "persona":
        persona_id = str(result.get("persona_id") or "").strip()
        await bot.send_message(
            job.user_id,
            "🎭 <b>Persona готова</b>\n\n"
            f"Persona ID: <code>{html.escape(persona_id)}</code>",
            parse_mode="HTML",
        )
    elif job.operation == "timestamped_lyrics":
        words = result.get("aligned_words") or []
        compact = "\n".join(
            f"{float(item.get('startS') or 0):.2f}s — {item.get('word')}"
            for item in words[:120]
            if isinstance(item, dict)
        )
        await bot.send_message(
            job.user_id,
            "📝 <b>Текст с таймкодами</b>\n\n"
            + html.escape(compact[:3500] or "Suno не вернул текст для этого трека."),
            parse_mode="HTML",
        )
    elif job.operation == "midi":
        payload = json.dumps(result.get("midi_data"), ensure_ascii=False)
        await bot.send_message(
            job.user_id,
            "🎹 <b>MIDI-данные готовы</b>\n\n"
            f"<code>{html.escape(payload[:3500])}</code>",
            parse_mode="HTML",
        )
    else:
        urls = _result_urls(result)
        if not urls:
            await bot.send_message(
                job.user_id,
                "✅ Suno завершил задачу. Результат сохранён, но прямой URL в ответе отсутствует.",
            )
        else:
            lines = ["✅ <b>Suno готов</b>"]
            for label, url in urls[:20]:
                lines.append(f"• {html.escape(label)}\n{html.escape(url)}")
            await bot.send_message(job.user_id, "\n\n".join(lines), parse_mode="HTML")
    await _mark_delivered(job.id)


async def _deliver_max(client: MaxClient, job: SunoJob, result: dict[str, Any]) -> None:
    if job.delivered_at_epoch is not None:
        return
    tracks = result.get("tracks") or []
    if tracks:
        for index, track in enumerate(tracks):
            if not isinstance(track, dict):
                continue
            url = str(track.get("audio_url") or "").strip()
            if not url.startswith("https://"):
                continue
            title = str(track.get("title") or "Suno").strip()[:64]
            audio_id = str(track.get("audio_id") or "").strip()
            await client.send_media_url(
                job.user_id,
                media_type="audio",
                url=url,
                filename=f"suno-{job.id[:8]}-{index}.mp3",
                text=(
                    f"🎵 <b>{html.escape(title)}</b>\n"
                    f"Audio ID: <code>{html.escape(audio_id)}</code>\n"
                    f"Task ID: <code>{html.escape(str(job.provider_task_id or ''))}</code>"
                ),
                attachments=_max_track_attachments(job, index),
            )
        await _mark_delivered(job.id)
        return

    if job.operation == "lyrics":
        raw = result.get("lyrics")
        text = json.dumps(raw, ensure_ascii=False, indent=2) if not isinstance(raw, str) else raw
        message = f"✍️ <b>Текст Suno готов</b>\n\n{html.escape(text[:3500])}"
    elif job.operation == "voice_validate":
        phrase = str(result.get("validate_info") or "").strip()
        message = (
            "🎙 <b>Фраза для проверки голоса</b>\n\n"
            f"<code>{html.escape(phrase)}</code>\n\n"
            f"Task ID: <code>{html.escape(str(job.provider_task_id or ''))}</code>"
        )
    elif job.operation == "voice_generate":
        message = (
            "🎙 <b>Suno Voice готов</b>\n\n"
            f"Voice ID: <code>{html.escape(str(result.get('voice_id') or ''))}</code>"
        )
    elif job.operation == "persona":
        message = (
            "🎭 <b>Persona готова</b>\n\n"
            f"Persona ID: <code>{html.escape(str(result.get('persona_id') or ''))}</code>"
        )
    elif job.operation == "timestamped_lyrics":
        words = result.get("aligned_words") or []
        compact = "\n".join(
            f"{float(item.get('startS') or 0):.2f}s — {item.get('word')}"
            for item in words[:120]
            if isinstance(item, dict)
        )
        message = "📝 <b>Текст с таймкодами</b>\n\n" + html.escape(compact[:3500])
    else:
        urls = _result_urls(result)
        message = "✅ <b>Suno готов</b>"
        for label, url in urls[:16]:
            message += f"\n\n• {html.escape(label)}\n{html.escape(url)}"
    await client.send_message(job.user_id, message[:4000])
    await _mark_delivered(job.id)


class SunoJobService:
    def __init__(self, app: web.Application) -> None:
        self.app = app
        self._stop = asyncio.Event()

    async def _deliver(self, job: SunoJob, result: dict[str, Any]) -> None:
        if job.channel == "telegram":
            bot = self.app.get("bot")
            if not isinstance(bot, Bot):
                raise SunoJobRetry("Telegram transport is unavailable")
            await _deliver_telegram(bot, job, result)
            return
        client = self.app.get("max_client")
        if not isinstance(client, MaxClient):
            raise SunoJobRetry("MAX transport is unavailable")
        await _deliver_max(client, job, result)

    async def _process(self, job: SunoJob) -> None:
        current = job
        if not current.result_data and not current.provider_task_id:
            submitted = await suno_service.submit(current.operation, current.request_data)
            if current.operation in suno_service.SYNC_OPERATIONS:
                result = suno_service.immediate_result(current.operation, submitted)
                await _set_result(current.id, result)
                current = await get_suno_job(current.id) or current
            else:
                task_id = suno_service.task_id(submitted)
                if not task_id:
                    raise SunoApiError(
                        suno_service.error_message(submitted)
                        or "Suno не вернул идентификатор задачи"
                    )
                await _set_provider_task(current.id, task_id)
                current = await get_suno_job(current.id) or current

        result = current.result_data
        if not result:
            if not current.provider_task_id:
                raise RuntimeError("Suno job has no provider task")
            payload = await suno_service.get_task(
                current.operation,
                current.provider_task_id,
            )
            state = suno_service.task_state(current.operation, payload)
            if state == "pending":
                if current.attempt_count >= _MAX_ATTEMPTS:
                    raise RuntimeError("Suno слишком долго не завершает задачу")
                raise SunoJobRetry("Suno task is processing")
            if state == "failed":
                raise SunoApiError(
                    suno_service.error_message(payload) or "Suno завершил задачу с ошибкой"
                )
            result = suno_service.normalize_result(current.operation, payload)
            await _set_result(current.id, result)
            current = await get_suno_job(current.id) or current

        await self._deliver(current, result)
        await _mark_success(current.id)

    async def _handle(self, job: SunoJob) -> None:
        try:
            await self._process(job)
        except SunoJobRetry as exc:
            await _retry(job.id, str(exc))
        except Exception as exc:
            logger.exception("Suno job failed: %s", job.id)
            current = await get_suno_job(job.id) or job
            with contextlib.suppress(Exception):
                await _refund(current)
            await _mark_failed(job.id, str(exc))
            try:
                if current.channel == "telegram":
                    bot = self.app.get("bot")
                    if isinstance(bot, Bot):
                        await bot.send_message(
                            current.user_id,
                            "Не удалось завершить Suno-задачу. Баланс возвращён. "
                            "Можно попробовать ещё раз.",
                        )
                else:
                    client = self.app.get("max_client")
                    if isinstance(client, MaxClient):
                        await client.send_message(
                            current.user_id,
                            "Не удалось завершить Suno-задачу. MAX-баланс возвращён. "
                            "Можно попробовать ещё раз.",
                        )
            except Exception:
                logger.exception("Failed to notify about Suno failure: %s", current.id)

    async def worker_loop(self) -> None:
        await ensure_suno_schema()
        while not self._stop.is_set():
            job = await _claim_next()
            if job is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=_WORKER_POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
                continue
            await self._handle(job)

    async def stop(self) -> None:
        self._stop.set()


def install_suno_worker(app: web.Application) -> None:
    if app.get("suno_worker_installed"):
        return

    async def callback_ack(_request: web.Request) -> web.Response:
        # Provider callbacks are intentionally ack-only. Durable jobs are polled
        # from KIE, so unauthenticated callback bodies cannot mutate billing/state.
        return web.json_response({"ok": True})

    app.router.add_post("/webhook/suno", callback_ack)
    app["suno_worker_installed"] = True
    service = SunoJobService(app)
    app["suno_worker"] = service

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
