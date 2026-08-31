from __future__ import annotations

import html
import uuid
from typing import Any
from urllib.parse import quote

from bot.max_api import callback_button, inline_keyboard
from bot.max_catalog import MaxPresetManager, max_preset_manager
from bot.max_creator_generation import MaxCreatorGenerationService
from bot.max_generation import (
    MaxGenerationJob,
    MaxGenerationRetry,
    _activate_job,
    _insert_job,
    _mark_delivered,
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
from bot.services.gemini_omni_service import gemini_omni_service

OMNI_AUDIO_MODEL = "gemini_omni_audio"
OMNI_AUDIO_DURATION = 6


def omni_audio_cost(
    catalog: MaxPresetManager = max_preset_manager,
) -> float:
    return float(
        catalog.video_cost(
            OMNI_AUDIO_MODEL,
            duration=OMNI_AUDIO_DURATION,
        )
    )


async def enqueue_max_omni_audio(
    max_user_id: int,
    *,
    base_voice: str,
    name: str,
    voice_description: str = "",
    example_dialogue: str = "",
    catalog: MaxPresetManager = max_preset_manager,
) -> MaxGenerationJob:
    voice = str(base_voice or "").strip().lower()
    clean_name = str(name or "").strip()
    description = str(voice_description or "").strip()
    dialogue = str(example_dialogue or "").strip()

    if voice not in gemini_omni_service.BASE_VOICES:
        raise ValueError("Unsupported Gemini Omni base voice")
    if not clean_name:
        raise ValueError("Audio ID name is required")
    if len(clean_name) > 20:
        raise ValueError("Audio ID name must be 20 characters or fewer")
    if len(description) > 2000:
        raise ValueError("Voice description is too long")
    if len(dialogue) > 2000:
        raise ValueError("Example dialogue is too long")

    cost = omni_audio_cost(catalog)
    job = MaxGenerationJob(
        id=uuid.uuid4().hex,
        max_user_id=int(max_user_id),
        kind="audio_id",
        generation_type="omni_audio",
        model=OMNI_AUDIO_MODEL,
        prompt=description or clean_name,
        cost=cost,
        input_data={},
        options={
            "base_voice": voice,
            "name": clean_name,
            "voice_description": description,
            "example_dialogue": dialogue,
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


async def _poll_audio_asset(task_id: str) -> str:
    data = await gemini_omni_service._kie_get(
        "/api/v1/jobs/recordInfo",
        params={"taskId": str(task_id)},
    )
    if not isinstance(data, dict):
        raise MaxGenerationRetry("Gemini Omni Audio status is temporarily unavailable")

    asset_id = gemini_omni_service._extract_asset_id(data, "audio")
    if asset_id:
        return str(asset_id)

    state = str(
        gemini_omni_service._find_nested(data, ["state", "status"]) or ""
    ).strip().lower()
    if state in {"fail", "failed", "error", "cancelled", "canceled"}:
        raise RuntimeError(_provider_error(data))
    raise MaxGenerationRetry("Gemini Omni Audio ID is still processing")


class MaxOmniGenerationService(MaxCreatorGenerationService):
    async def _deliver_audio_id(self, job: MaxGenerationJob, audio_id: str) -> None:
        if job.delivered_at_epoch is not None:
            return
        payload = f"max:omni:audio:{quote(audio_id, safe='')}"
        rows: list[list[dict[str, Any]]] = []
        if len(payload) <= 220:
            rows.append(
                [callback_button("🎬 Использовать в Gemini Omni", payload)]
            )
        rows.append([callback_button("🏠 Главное меню", "max:home")])
        await self.client.send_message(
            job.max_user_id,
            "Готово 🎙\n\n"
            f"Audio ID: <code>{html.escape(audio_id)}</code>\n\n"
            "Это идентификатор голоса для Gemini Omni, а не аудиофайл. "
            "Я сохранил его в истории MAX.",
            attachments=[inline_keyboard(rows)],
        )
        await _mark_delivered(job.id)

    async def _process_audio_id(self, job: MaxGenerationJob) -> None:
        current = job
        if not current.result_url and not current.provider_task_id:
            result = await gemini_omni_service.create_audio(
                audio_id=str(current.options.get("base_voice") or "achernar"),
                name=str(current.options.get("name") or ""),
                voice_description=str(
                    current.options.get("voice_description") or ""
                ),
                example_dialogue=str(
                    current.options.get("example_dialogue") or ""
                ),
            )
            if not isinstance(result, dict) or result.get("error"):
                raise RuntimeError(_provider_error(result))

            asset_id = str(result.get("asset_id") or "").strip()
            if asset_id:
                await _mark_result(current.id, asset_id)
                current = await get_max_generation_job(current.id) or current
            else:
                task_id = str(result.get("task_id") or "").strip()
                if not task_id:
                    raise RuntimeError(
                        "Gemini Omni Audio did not return an Audio ID or task id"
                    )
                await _mark_provider_task(current.id, "kie_omni_audio", task_id)
                raise MaxGenerationRetry("Gemini Omni Audio ID is still processing")

        audio_id = str(current.result_url or "").strip()
        if not audio_id:
            if current.provider_kind != "kie_omni_audio" or not current.provider_task_id:
                raise RuntimeError("Gemini Omni Audio job has no provider task id")
            audio_id = await _poll_audio_asset(current.provider_task_id)
            await _mark_result(current.id, audio_id)
            current = await get_max_generation_job(current.id) or current

        await self._deliver_audio_id(current, audio_id)
        await record_max_generation(
            current.max_user_id,
            generation_key=current.id,
            kind=current.kind,
            model=current.model,
            prompt=current.prompt,
            status="completed",
            cost=current.cost,
            provider_task_id=current.provider_task_id,
            result_url=audio_id,
            request_data={
                "input": current.input_data,
                "options": current.options,
                "generation_type": current.generation_type,
            },
        )
        await _mark_job_succeeded(current.id)

    async def _process_omni_video_with_audio(self, job: MaxGenerationJob) -> None:
        current = job
        if not current.result_url and not current.provider_task_id:
            audio_ids = [
                str(value).strip()
                for value in current.input_data.get("audio_ids", [])
                if str(value or "").strip()
            ]
            if not audio_ids:
                raise RuntimeError("Gemini Omni video Audio ID is missing")
            images = [
                str(value).strip()
                for value in current.input_data.get("image_urls", [])
                if str(value or "").strip()
            ]
            videos = [
                str(value).strip()
                for value in current.input_data.get("video_urls", [])
                if str(value or "").strip()
            ]
            duration = int(current.options.get("duration") or 6)
            result = await gemini_omni_service.generate_video(
                prompt=current.prompt,
                duration=duration,
                aspect_ratio=str(current.options.get("aspect_ratio") or "16:9"),
                resolution=str(current.options.get("resolution") or "720p"),
                image_urls=images,
                audio_ids=audio_ids[:1],
                video_list=[
                    {
                        "url": url,
                        "start": 0,
                        "ends": min(20, max(1, duration)),
                    }
                    for url in videos[:1]
                ],
            )
            task_id = _task_id_from_result(result)
            if not task_id:
                raise RuntimeError(_provider_error(result))
            await _mark_provider_task(current.id, "kie", task_id)
            current = await get_max_generation_job(current.id) or current

        result_url = str(current.result_url or "").strip()
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

    async def _process(self, job: MaxGenerationJob) -> None:
        if job.generation_type == "omni_audio":
            await self._process_audio_id(job)
            return
        if job.model == "gemini_omni" and job.input_data.get("audio_ids"):
            await self._process_omni_video_with_audio(job)
            return
        await super()._process(job)
