from __future__ import annotations

import uuid
from typing import Any

from bot.max_catalog import MaxPresetManager, max_preset_manager
from bot.max_generation import (
    MaxGenerationJob,
    MaxGenerationService,
    _activate_job,
    _insert_job,
    _mark_job_failed,
    _mark_job_succeeded,
    _mark_provider_task,
    _mark_result,
    _poll_provider,
    _provider_error,
    _task_id_from_result,
    get_max_generation_job,
)
from bot.max_store import (
    MaxInsufficientBalanceError,
    apply_max_balance_delta,
    record_max_generation,
)
from bot.services.kling_service import kling_service

MOTION_MODELS: dict[str, str] = {
    "motion_control_v26": "kling-2.6/motion-control",
    "motion_control_v30": "kling-3.0/motion-control",
}
MOTION_QUALITIES = frozenset({"720p", "1080p"})
MOTION_ORIENTATIONS = frozenset({"video", "image"})


def _clean_https_url(value: Any, *, field: str) -> str:
    url = str(value or "").strip()
    if not url.startswith("https://"):
        raise ValueError(f"{field} must be an HTTPS URL")
    return url


def motion_cost(
    model: str,
    *,
    duration: int,
    quality: str,
    catalog: MaxPresetManager = max_preset_manager,
) -> float:
    model_key = str(model or "").strip()
    if model_key not in MOTION_MODELS:
        raise ValueError("Unsupported MAX Motion Control model")
    seconds = int(duration)
    if not 3 <= seconds <= 30:
        raise ValueError("Motion Control reference video must be 3-30 seconds")
    quality_key = str(quality or "").strip().lower()
    if quality_key not in MOTION_QUALITIES:
        raise ValueError("Motion Control quality must be 720p or 1080p")
    return float(
        catalog.video_cost(
            model_key,
            duration=seconds,
            quality=quality_key,
        )
    )


async def enqueue_max_motion_generation(
    max_user_id: int,
    *,
    model: str,
    image_url: str,
    video_url: str,
    duration: int,
    quality: str,
    orientation: str = "video",
    prompt: str = "",
    catalog: MaxPresetManager = max_preset_manager,
) -> MaxGenerationJob:
    model_key = str(model or "").strip()
    quality_key = str(quality or "").strip().lower()
    orientation_key = str(orientation or "").strip().lower()
    seconds = int(duration)

    if model_key not in MOTION_MODELS:
        raise ValueError("Unsupported MAX Motion Control model")
    if quality_key not in MOTION_QUALITIES:
        raise ValueError("Motion Control quality must be 720p or 1080p")
    if orientation_key not in MOTION_ORIENTATIONS:
        raise ValueError("Motion Control orientation must be video or image")
    if not 3 <= seconds <= 30:
        raise ValueError("Motion Control reference video must be 3-30 seconds")
    if orientation_key == "image" and seconds > 10:
        raise ValueError(
            "Image-oriented Motion Control supports reference videos up to 10 seconds"
        )

    image = _clean_https_url(image_url, field="Motion Control image")
    video = _clean_https_url(video_url, field="Motion Control video")
    cost = motion_cost(
        model_key,
        duration=seconds,
        quality=quality_key,
        catalog=catalog,
    )
    job = MaxGenerationJob(
        id=uuid.uuid4().hex,
        max_user_id=int(max_user_id),
        kind="video",
        generation_type="motion_control",
        model=model_key,
        prompt=str(prompt or "").strip(),
        cost=cost,
        input_data={"image_urls": [image], "video_urls": [video]},
        options={
            "duration": seconds,
            "resolution": quality_key,
            "motion_direction": orientation_key,
        },
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
                "duration": seconds,
                "resolution": quality_key,
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
        request_data={
            "input": job.input_data,
            "options": job.options,
            "generation_type": job.generation_type,
        },
    )
    await _activate_job(job.id)
    return job


class MaxCreatorGenerationService(MaxGenerationService):
    async def _process(self, job: MaxGenerationJob) -> None:
        if job.generation_type != "motion_control":
            await super()._process(job)
            return

        current = job
        if not current.result_url and not current.provider_task_id:
            image_urls = [
                str(value).strip()
                for value in current.input_data.get("image_urls", [])
                if str(value or "").strip()
            ]
            video_urls = [
                str(value).strip()
                for value in current.input_data.get("video_urls", [])
                if str(value or "").strip()
            ]
            if not image_urls or not video_urls:
                raise RuntimeError("Motion Control requires image and video references")

            provider_model = MOTION_MODELS.get(current.model)
            if not provider_model:
                raise RuntimeError(f"Unsupported MAX Motion Control model: {current.model}")

            result = await kling_service.generate_motion_control(
                image_url=image_urls[0],
                video_urls=video_urls[:1],
                prompt=current.prompt or None,
                motion_direction=str(
                    current.options.get("motion_direction") or "video"
                ),
                mode=str(current.options.get("resolution") or "720p"),
                motion_model=provider_model,
            )
            task_id = _task_id_from_result(result)
            if not task_id:
                raise RuntimeError(_provider_error(result))
            await _mark_provider_task(current.id, "kie", task_id)
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
