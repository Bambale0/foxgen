from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from bot import db as db_backend
from bot.config import config
from bot.internal_admin_operations import (
    _fetch_operation,
    _operation_by_task_id,
    _parse_request_data,
)
from bot.internal_admin_user_commands import CommandConflictError, CommandValidationError


def _provider_task_id(result: object, *, provider: str) -> str:
    if not isinstance(result, dict):
        raise CommandConflictError(f"{provider} did not return a task")
    if result.get("error"):
        message = str(result.get("message") or result.get("error") or "provider error")
        raise CommandConflictError(f"{provider} rejected replay: {message[:300]}")
    task_id = str(result.get("task_id") or "").strip()
    if not task_id:
        raise CommandConflictError(f"{provider} did not return a task id")
    return task_id


async def _annotate_replay_child(
    child_id: int,
    *,
    source_operation_id: int,
    admin_user_id: str,
    request_id: str,
    idempotency_key: str,
    reason: str,
    comment: str | None,
) -> None:
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            "SELECT request_data FROM generation_tasks WHERE id = ? FOR UPDATE",
            (child_id,),
        )
        row = await cursor.fetchone()
        request_data = _parse_request_data(row["request_data"] if row else None)
        request_data["admin_replay"] = {
            "source_operation_id": source_operation_id,
            "admin_user_id": admin_user_id,
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "reason": reason,
            "comment": comment,
        }
        await connection.execute(
            """
            UPDATE generation_tasks
            SET parent_generation_id = ?,
                action_type = 'admin_replay',
                request_data = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                source_operation_id,
                json.dumps(request_data, ensure_ascii=False),
                child_id,
            ),
        )
        await connection.commit()


async def _replay_image(
    source: Mapping[str, Any],
    *,
    admin_user_id: str,
    request_id: str,
    idempotency_key: str,
    reason: str,
    comment: str | None,
) -> Mapping[str, Any]:
    from bot.database import get_or_create_user
    from bot.handlers.generation import (
        _available_reference_images,
        _source_reference_images_from_request,
        _start_image_generation_task,
    )

    request_data = _parse_request_data(source["request_data"])
    telegram_id = int(source["telegram_id"] or 0)
    if telegram_id <= 0:
        raise CommandValidationError("operation has no Telegram recipient")
    user = await get_or_create_user(telegram_id)
    references, missing = _available_reference_images(
        _source_reference_images_from_request(request_data)
    )
    if missing:
        raise CommandConflictError("source references are no longer available")

    result = await _start_image_generation_task(
        user=user,
        telegram_id=telegram_id,
        img_service=str(request_data.get("img_service") or source["model"] or "banana_pro"),
        prompt=str(request_data.get("prompt") or source["prompt"] or ""),
        img_ratio=str(request_data.get("img_ratio") or source["aspect_ratio"] or "1:1"),
        reference_images=references,
        unit_cost=0,
        img_quality=str(request_data.get("img_quality") or "2K"),
        img_nsfw_checker=bool(request_data.get("img_nsfw_checker", False)),
        nsfw_enabled=bool(request_data.get("nsfw_enabled", False)),
        callback_url=config.kie_notification_url if config.WEBHOOK_HOST else None,
        parent_generation_id=int(source["id"]),
        action_type="admin_replay",
    )
    task_id = _provider_task_id(result, provider="image provider")
    child = await _operation_by_task_id(task_id)
    if child is None:
        raise RuntimeError("replay operation was not persisted")
    await _annotate_replay_child(
        int(child["id"]),
        source_operation_id=int(source["id"]),
        admin_user_id=admin_user_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
        reason=reason,
        comment=comment,
    )
    refreshed = await _fetch_operation(int(child["id"]))
    if refreshed is None:
        raise RuntimeError("replay operation disappeared")
    return refreshed


async def _replay_video(
    source: Mapping[str, Any],
    *,
    admin_user_id: str,
    request_id: str,
    idempotency_key: str,
    reason: str,
    comment: str | None,
) -> Mapping[str, Any]:
    from bot.database import (
        _merge_task_id_aliases,
        add_generation_task,
        complete_video_task,
        get_or_create_user,
    )
    from bot.handlers.generation import (
        _available_reference_images,
        _build_gemini_omni_video_list,
        _collect_gemini_omni_image_urls,
        _collect_gemini_omni_video_urls,
        _validate_gemini_omni_video_inputs,
        get_max_video_references,
        normalize_reference_urls,
    )
    from bot.services import gemini_omni_service, kling_service, veo_service
    from bot.services.grok_service import grok_service
    from bot.services.seedance_service import seedance_service

    request_data = _parse_request_data(source["request_data"])
    telegram_id = int(source["telegram_id"] or 0)
    if telegram_id <= 0:
        raise CommandValidationError("operation has no Telegram recipient")
    user = await get_or_create_user(telegram_id)

    v_model = str(request_data.get("v_model") or source["model"] or "v3_std")
    v_type = str(request_data.get("v_type") or "text")
    prompt = str(request_data.get("user_prompt") or source["prompt"] or "")
    duration = int(request_data.get("v_duration") or source["duration"] or 5)
    aspect_ratio = str(request_data.get("v_ratio") or source["aspect_ratio"] or "16:9")
    image_url = request_data.get("v_image_url")
    reference_images, missing_images = _available_reference_images(
        list(request_data.get("reference_images") or [])
    )
    if missing_images:
        raise CommandConflictError("source image references are no longer available")
    reference_videos = normalize_reference_urls(
        request_data.get("v_reference_videos", []),
        max_count=get_max_video_references(v_model),
    )
    avatar_audio_url = request_data.get("avatar_audio_url")

    local_task_id = f"admvid_{uuid.uuid4().hex[:16]}"
    replay_snapshot = {
        **request_data,
        "source": "admin_replay",
        "v_type": v_type,
        "v_model": v_model,
        "user_prompt": prompt,
        "v_duration": duration,
        "v_ratio": aspect_ratio,
        "v_image_url": image_url,
        "reference_images": reference_images,
        "v_reference_videos": reference_videos or [],
        "admin_replay": {
            "source_operation_id": int(source["id"]),
            "admin_user_id": admin_user_id,
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "reason": reason,
            "comment": comment,
        },
    }
    await add_generation_task(
        user.id,
        telegram_id,
        local_task_id,
        "video",
        str(source["preset_id"] or "admin_replay"),
        model=v_model,
        duration=duration,
        aspect_ratio=aspect_ratio,
        prompt=prompt,
        cost=0,
        request_data=replay_snapshot,
        parent_generation_id=int(source["id"]),
        action_type="admin_replay",
    )

    try:
        provider_name = v_model
        if v_model == "gemini_omni_video":
            omni_images = _collect_gemini_omni_image_urls(image_url, reference_images)
            omni_video_urls = _collect_gemini_omni_video_urls(reference_videos)
            validation_error = _validate_gemini_omni_video_inputs(
                image_urls=omni_images,
                video_urls=omni_video_urls,
                character_ids=request_data.get("omni_character_ids", []),
                audio_ids=request_data.get("omni_audio_ids", []),
            )
            if validation_error:
                raise CommandValidationError(validation_error)
            result = await gemini_omni_service.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                resolution=str(request_data.get("omni_resolution") or "720p"),
                image_urls=omni_images or None,
                audio_ids=request_data.get("omni_audio_ids", []),
                video_list=_build_gemini_omni_video_list(omni_video_urls, duration) or None,
                character_ids=request_data.get("omni_character_ids", []),
                seed=request_data.get("omni_seed"),
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model.startswith("veo3"):
            generation_type = str(
                request_data.get("veo_generation_type") or "TEXT_2_VIDEO"
            )
            veo_images: list[str] = []
            if image_url:
                veo_images.append(str(image_url))
            max_images = 2 if generation_type == "FIRST_AND_LAST_FRAMES_2_VIDEO" else 3
            for reference in reference_images:
                if reference not in veo_images:
                    veo_images.append(reference)
                if len(veo_images) >= max_images:
                    break
            result = await veo_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=duration,
                generation_type=generation_type,
                image_urls=veo_images or None,
                aspect_ratio=aspect_ratio,
                enable_translation=bool(request_data.get("veo_translation", True)),
                watermark=request_data.get("veo_watermark") or None,
                resolution=str(request_data.get("veo_resolution") or "720p"),
                seeds=request_data.get("veo_seed"),
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "grok_imagine":
            if not image_url:
                raise CommandValidationError("Grok Imagine replay requires a source image")
            result = await grok_service.generate_image_to_video(
                image_urls=[str(image_url), *reference_images[:6]],
                prompt=prompt,
                mode=str(request_data.get("grok_mode") or "normal"),
                duration=duration,
                resolution="720p",
                aspect_ratio=aspect_ratio,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "grok_imagine_v15":
            if not image_url:
                raise CommandValidationError("Grok Imagine 1.5 replay requires a source image")
            result = await grok_service.generate_image_to_video_v15(
                image_urls=[str(image_url)],
                prompt=prompt,
                duration=duration,
                resolution=str(request_data.get("grok_resolution") or "480p"),
                aspect_ratio=aspect_ratio,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model == "seedance_2":
            seedance_refs = [str(image_url)] if image_url else []
            for reference in reference_images:
                if reference not in seedance_refs:
                    seedance_refs.append(reference)
            result = await seedance_service.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                resolution="720p",
                generate_audio=True,
                first_frame_url=(
                    str(image_url)
                    if v_type == "imgtxt" and image_url and not seedance_refs[1:]
                    else None
                ),
                reference_image_urls=seedance_refs or None,
                reference_video_urls=reference_videos or None,
                callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
            )
        elif v_model in {"avatar_std", "avatar_pro"}:
            if not image_url or not avatar_audio_url:
                raise CommandValidationError("Kling Avatar replay requires image and audio")
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_url=str(image_url),
                video_urls=[str(avatar_audio_url)],
                webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            )
        else:
            result = await kling_service.generate_video(
                prompt=prompt,
                model=v_model,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_url=str(image_url) if image_url else None,
                video_urls=reference_videos if v_type in {"video", "motion"} else None,
                image_input=reference_images if v_type != "imgtxt" else None,
                negative_prompt=request_data.get("kling_negative_prompt") or None,
                cfg_scale=float(request_data.get("kling_cfg_scale", 0.5)),
                webhook_url=config.kling_notification_url if config.WEBHOOK_HOST else None,
            )
        provider_task_id = _provider_task_id(result, provider=provider_name)
    except Exception:
        await complete_video_task(local_task_id, None)
        raise

    replay_snapshot = _merge_task_id_aliases(
        replay_snapshot,
        local_task_id,
        provider_task_id,
    )
    async with db_backend.connect() as connection:
        await connection.execute(
            """
            UPDATE generation_tasks
            SET task_id = ?, request_data = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND id = (
                SELECT id FROM generation_tasks WHERE task_id = ? ORDER BY id DESC LIMIT 1
            )
            """,
            (
                provider_task_id,
                json.dumps(replay_snapshot, ensure_ascii=False),
                local_task_id,
                local_task_id,
            ),
        )
        await connection.commit()
    child = await _operation_by_task_id(provider_task_id)
    if child is None:
        raise RuntimeError("video replay operation was not persisted")
    return child


async def run_replay(
    source: Mapping[str, Any],
    *,
    admin_user_id: str,
    request_id: str,
    idempotency_key: str,
    reason: str,
    comment: str | None,
) -> Mapping[str, Any]:
    operation_type = str(source["type"] or "").lower()
    if operation_type == "image":
        return await _replay_image(
            source,
            admin_user_id=admin_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason=reason,
            comment=comment,
        )
    if operation_type == "video":
        return await _replay_video(
            source,
            admin_user_id=admin_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason=reason,
            comment=comment,
        )
    raise CommandValidationError("operation type cannot be replayed")
