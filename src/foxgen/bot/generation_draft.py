from __future__ import annotations

from typing import Any, NotRequired, TypedDict
from uuid import uuid4

from foxgen.bot.generation_capabilities import (
    IMAGE_MODELS,
    VIDEO_MODELS,
    ImageModelCapability,
    VideoGenerationType,
    VideoModelCapability,
    image_model,
    video_model,
)
from foxgen.core.errors import ErrorCode, SubmissionError


WIZARD_VERSION = "screen-v2"
MAX_VIDEO_REFERENCE_TOTAL = 6


class StoredInput(TypedDict):
    kind: str
    storage_key: NotRequired[str]
    reference_id: NotRequired[str]


class ResolvedInput(TypedDict):
    kind: str
    url: str


def default_image_flow_data(user_id: int) -> dict[str, object]:
    """Return the stable image draft used by every image entrypoint."""

    default_model = IMAGE_MODELS["seedream-5-pro"]
    return {
        "entrypoint": "wizard",
        "wizard_version": WIZARD_VERSION,
        "generation_type": "image",
        "image_flow_step": "select_model",
        "image_model_key": default_model.key,
        "model_slug": default_model.text_slug,
        "model_title": default_model.title,
        "aspect_ratio": default_model.default_aspect_ratio,
        "quality": default_model.default_quality or "basic",
        "resolution": default_model.default_resolution or "1K",
        "output_format": default_model.default_output_format,
        "media": [],
        "prompt": "",
        "can_submit": False,
        "idempotency_key": f"generation:{user_id}:{uuid4().hex}",
    }


def default_video_flow_data(user_id: int) -> dict[str, object]:
    """Return the stable video draft used by every video entrypoint."""

    default_model = VIDEO_MODELS["seedance-2"]
    return {
        "entrypoint": "wizard",
        "wizard_version": WIZARD_VERSION,
        "generation_type": "video",
        "video_flow_step": "select_model",
        "video_model_key": default_model.key,
        "video_type": VideoGenerationType.TEXT.value,
        "model_slug": default_model.slug,
        "model_title": default_model.title,
        "aspect_ratio": default_model.default_aspect_ratio,
        "duration": default_model.default_duration,
        "resolution": default_model.default_resolution,
        "generate_audio": False,
        "return_last_frame": False,
        "web_search": False,
        "media": [],
        "prompt": "",
        "can_submit": False,
        "idempotency_key": f"generation:{user_id}:{uuid4().hex}",
    }


def stored_media(data: dict[str, Any] | dict[str, object]) -> list[StoredInput]:
    raw = data.get("media")
    if not isinstance(raw, list):
        return []
    result: list[StoredInput] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        storage_key = item.get("storage_key")
        reference_id = item.get("reference_id")
        if not isinstance(kind, str):
            continue
        has_storage_key = isinstance(storage_key, str) and bool(storage_key)
        has_reference_id = isinstance(reference_id, str) and bool(reference_id)
        if has_storage_key == has_reference_id:
            continue
        if has_storage_key:
            result.append({"kind": kind, "storage_key": str(storage_key)})
        else:
            result.append({"kind": kind, "reference_id": str(reference_id)})
    return result


def temporary_storage_keys(media: list[StoredInput]) -> tuple[str, ...]:
    return tuple(
        item["storage_key"]
        for item in media
        if isinstance(item.get("storage_key"), str)
    )


def saved_reference_ids(media: list[StoredInput]) -> tuple[str, ...]:
    return tuple(
        item["reference_id"]
        for item in media
        if isinstance(item.get("reference_id"), str)
    )


def image_capability(data: dict[str, Any] | dict[str, object]) -> ImageModelCapability:
    key = str(data.get("image_model_key") or "")
    try:
        return image_model(key)
    except ValueError as exc:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик фото устарел. Откройте /start и начните заново.",
        ) from exc


def video_capability(data: dict[str, Any] | dict[str, object]) -> VideoModelCapability:
    key = str(data.get("video_model_key") or "")
    try:
        return video_model(key)
    except ValueError as exc:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик видео устарел. Откройте /start и начните заново.",
        ) from exc


def video_type(data: dict[str, Any] | dict[str, object]) -> VideoGenerationType:
    try:
        return VideoGenerationType(str(data.get("video_type") or ""))
    except ValueError as exc:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Тип видео потерян. Откройте /start и начните заново.",
        ) from exc


def normalize_prompt(value: str | None) -> str | None:
    prompt = (value or "").strip()
    return prompt if 3 <= len(prompt) <= 3500 else None


def required_text(data: dict[str, Any] | dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик генерации повреждён. Откройте /start и начните заново.",
            details={"missing_field": key},
        )
    return value


def submission_model_slug(data: dict[str, Any] | dict[str, object]) -> str:
    if required_text(data, "generation_type") == "image":
        capability = image_capability(data)
        return capability.submission_slug(has_references=bool(stored_media(data)))
    return video_capability(data).slug


def submission_payload(
    data: dict[str, Any] | dict[str, object],
    media: list[ResolvedInput],
) -> tuple[str, dict[str, object]]:
    generation_type = required_text(data, "generation_type")
    prompt = required_text(data, "prompt")
    if generation_type == "image":
        capability = image_capability(data)
        has_references = bool(stored_media(data))
        slug = capability.submission_slug(has_references=has_references)
        if slug.startswith("seedream-5-pro"):
            payload: dict[str, object] = {
                "prompt": prompt,
                "aspect_ratio": required_text(data, "aspect_ratio"),
                "quality": str(data.get("quality") or capability.default_quality or "basic"),
                "output_format": str(
                    data.get("output_format") or capability.default_output_format
                ),
                "nsfw_checker": False,
            }
            if has_references:
                images = [item["url"] for item in media if item["kind"] == "image"]
                if len(images) != len(stored_media(data)):
                    raise SubmissionError(
                        ErrorCode.VALIDATION,
                        "Не удалось подготовить все референсы изображения.",
                    )
                payload["image_urls"] = images
            return slug, payload
        return slug, {
            "prompt": prompt,
            "image_input": [item["url"] for item in media if item["kind"] == "image"],
            "aspect_ratio": required_text(data, "aspect_ratio"),
            "resolution": str(
                data.get("resolution") or capability.default_resolution or "1K"
            ),
            "output_format": str(
                data.get("output_format") or capability.default_output_format
            ),
        }

    capability = video_capability(data)
    generation_type_value = video_type(data)
    payload = {
        "prompt": prompt,
        "return_last_frame": bool(data.get("return_last_frame")),
        "generate_audio": bool(data.get("generate_audio")),
        "resolution": str(data.get("resolution") or capability.default_resolution),
        "aspect_ratio": required_text(data, "aspect_ratio"),
        "duration": int(data.get("duration") or capability.default_duration),
        "web_search": bool(data.get("web_search")),
    }
    if generation_type_value == VideoGenerationType.FIRST_FRAME:
        images = [item["url"] for item in media if item["kind"] == "image"]
        if len(images) != 1:
            raise SubmissionError(ErrorCode.VALIDATION, "Нужен ровно один первый кадр.")
        payload["first_frame_url"] = images[0]
    elif generation_type_value == VideoGenerationType.FIRST_LAST:
        images = [item["url"] for item in media if item["kind"] == "image"]
        if len(images) != 2:
            raise SubmissionError(ErrorCode.VALIDATION, "Нужны первый и последний кадр.")
        payload["first_frame_url"] = images[0]
        payload["last_frame_url"] = images[1]
    elif generation_type_value == VideoGenerationType.REFERENCES:
        payload["reference_image_urls"] = [
            item["url"] for item in media if item["kind"] == "image"
        ]
        payload["reference_video_urls"] = [
            item["url"] for item in media if item["kind"] == "video"
        ]
        payload["reference_audio_urls"] = [
            item["url"] for item in media if item["kind"] == "audio"
        ]
    return capability.slug, payload


def validate_video_media(
    capability: VideoModelCapability,
    generation_type: VideoGenerationType,
    media: list[StoredInput],
    kind: str,
) -> None:
    if generation_type in {VideoGenerationType.FIRST_FRAME, VideoGenerationType.FIRST_LAST}:
        if kind != "image":
            raise SubmissionError(ErrorCode.VALIDATION, "Для кадров отправьте изображение.")
        limit = 1 if generation_type == VideoGenerationType.FIRST_FRAME else 2
        if len(media) >= limit:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                f"Для этого сценария нужно не больше {limit} изображений.",
            )
        return
    if generation_type != VideoGenerationType.REFERENCES:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Для текстового сценария медиа не требуется.",
        )
    if len(media) >= MAX_VIDEO_REFERENCE_TOTAL:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Можно добавить не больше шести референсов суммарно.",
        )
    counts = media_counts(media)
    limits = {
        "image": capability.max_reference_images,
        "video": capability.max_reference_videos,
        "audio": capability.max_reference_audio,
    }
    if kind not in limits or limits[kind] <= 0:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Этот тип референса модель не поддерживает.",
        )
    if counts.get(kind, 0) >= limits[kind]:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            f"Лимит референсов типа {kind}: {limits[kind]}.",
        )


def video_media_complete(
    generation_type: VideoGenerationType,
    media: list[StoredInput],
) -> bool:
    if generation_type == VideoGenerationType.FIRST_FRAME:
        return len(media) == 1 and all(item["kind"] == "image" for item in media)
    if generation_type == VideoGenerationType.FIRST_LAST:
        return len(media) == 2 and all(item["kind"] == "image" for item in media)
    if generation_type == VideoGenerationType.REFERENCES:
        return bool(media)
    return True


def video_media_requirement(generation_type: VideoGenerationType) -> str:
    if generation_type == VideoGenerationType.FIRST_FRAME:
        return "Отправьте одно изображение — первый кадр видео."
    if generation_type == VideoGenerationType.FIRST_LAST:
        return "Отправьте два изображения по порядку: сначала первый кадр, затем последний."
    if generation_type == VideoGenerationType.REFERENCES:
        return "Отправляйте изображения, видео или аудио по одному. Суммарно — до шести файлов."
    return "Для текстового сценария медиа не требуется."


def video_media_status(
    generation_type: VideoGenerationType,
    media: list[StoredInput],
) -> str:
    if generation_type == VideoGenerationType.FIRST_FRAME:
        return "Первый кадр сохранён. Можно продолжать."
    if generation_type == VideoGenerationType.FIRST_LAST:
        return f"Сохранено кадров: {len(media)}/2."
    counts = media_counts(media)
    return (
        f"Референсы: {len(media)}/{MAX_VIDEO_REFERENCE_TOTAL} · "
        f"фото {counts.get('image', 0)}, видео {counts.get('video', 0)}, "
        f"аудио {counts.get('audio', 0)}."
    )


def media_counts(media: list[StoredInput]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in media:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return counts
