"""Seedance-only compatibility layer for the established Telegram UX.

The visible bot flow deliberately stays unchanged. This router only fixes the
media plumbing behind the existing "Фото + Текст" and "Видео + Текст" screens:
Seedance may receive images and videos in the same multimodal request.
"""

from __future__ import annotations

from functools import wraps

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from bot.keyboards import (
    get_main_menu_button_keyboard,
    get_reference_videos_upload_keyboard,
)
from bot.states import GenerationStates

from . import generation as generation_module

router = Router()

# The established Telegram dispatcher currently has an explicit provider branch
# for the standard model only. Do not claim Fast support until its own provider
# dispatch and pricing are wired into the legacy flow.
SEEDANCE_MODELS = {"seedance_2"}
SEEDANCE_MAX_IMAGES = 9
SEEDANCE_MAX_VIDEOS = 3
SEEDANCE_MAX_VIDEO_BYTES = 50 * 1024 * 1024
SEEDANCE_MIN_REFERENCE_VIDEO_SECONDS = 2
SEEDANCE_MAX_REFERENCE_VIDEO_SECONDS = 15
SEEDANCE_MAX_TOTAL_REFERENCE_VIDEO_SECONDS = 15


def is_seedance_model(model: object) -> bool:
    return str(model or "").strip() in SEEDANCE_MODELS


def seedance_needs_multimodal_promotion(data: dict) -> bool:
    """Return true when legacy routing would otherwise discard video refs."""
    return bool(
        is_seedance_model(data.get("v_model"))
        and data.get("v_reference_videos")
        and data.get("v_type") not in {"video", "motion"}
    )


async def _promote_seedance_runtime_state(state: FSMContext) -> None:
    """Make the legacy launcher retain Seedance video refs for this task.

    The legacy launcher only forwards ``v_reference_videos`` when ``v_type`` is
    ``video`` or ``motion``. Seedance is multimodal, so an image-led task that
    also contains video references must be routed internally as multimodal
    video. No user-facing screen, callback or keyboard is changed.
    """
    data = await state.get_data()
    if not seedance_needs_multimodal_promotion(data):
        return
    await state.update_data(
        seedance_original_v_type=data.get("v_type"),
        v_type="video",
    )


def install_seedance_multimodal_runtime_compat() -> None:
    """Patch the two legacy launch entrypoints once, without replacing UX."""
    if getattr(generation_module, "_seedance_multimodal_runtime_installed", False):
        return

    original_message_launch = generation_module.run_no_preset_video_from_message
    original_callback_launch = generation_module.run_no_preset_video_from_callback

    @wraps(original_message_launch)
    async def message_launch_with_seedance_refs(message, state, prompt):
        await _promote_seedance_runtime_state(state)
        return await original_message_launch(message, state, prompt)

    @wraps(original_callback_launch)
    async def callback_launch_with_seedance_refs(
        callback,
        state,
        prompt,
        cost,
        is_admin,
    ):
        await _promote_seedance_runtime_state(state)
        return await original_callback_launch(
            callback,
            state,
            prompt,
            cost,
            is_admin,
        )

    generation_module.run_no_preset_video_from_message = (
        message_launch_with_seedance_refs
    )
    generation_module.run_no_preset_video_from_callback = (
        callback_launch_with_seedance_refs
    )
    generation_module._seedance_multimodal_runtime_installed = True


@router.message(
    StateFilter(
        GenerationStates.waiting_for_video_prompt,
        GenerationStates.uploading_reference_videos,
    ),
    F.photo
    | (
        F.document
        & F.document.mime_type.in_(("image/jpeg", "image/png", "image/webp"))
    ),
)
async def accept_seedance_photo_reference(
    message: types.Message,
    state: FSMContext,
) -> None:
    """Accept identity photos even while the old UI is in video-ref mode."""
    data = await state.get_data()
    if not is_seedance_model(data.get("v_model")):
        raise SkipHandler

    primary_image = str(data.get("v_image_url") or "").strip()
    reference_images = [
        str(url).strip()
        for url in (data.get("reference_images") or [])
        if str(url).strip()
    ]
    current_count = (1 if primary_image else 0) + len(reference_images)
    if current_count >= SEEDANCE_MAX_IMAGES:
        await message.answer(
            f"❌ Для Seedance можно загрузить максимум {SEEDANCE_MAX_IMAGES} фото.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    image_url, error_message = await generation_module._save_reference_image_from_message(
        message,
        original_filename_prefix="seedance_identity",
    )
    if not image_url:
        await message.answer(
            error_message or "❌ Не удалось сохранить фото-референс.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    if not primary_image:
        primary_image = image_url
        await state.update_data(v_image_url=image_url)
    elif image_url not in reference_images:
        reference_images.append(image_url)
        await state.update_data(reference_images=reference_images)

    image_count = (1 if primary_image else 0) + len(reference_images)
    video_count = len(data.get("v_reference_videos") or [])
    await message.answer(
        "✅ Фото-референс Seedance добавлен.\n"
        f"Фото: <code>{image_count}/{SEEDANCE_MAX_IMAGES}</code> · "
        f"Видео: <code>{video_count}/{SEEDANCE_MAX_VIDEOS}</code>\n"
        "Первое фото будет главным референсом персонажа.",
        parse_mode="HTML",
    )
    if data.get("video_flow_step") == "media":
        await generation_module._show_video_media_screen(message, state, edit=False)
    else:
        await generation_module._show_video_creation_screen(message, state, edit=False)


@router.message(
    StateFilter(
        GenerationStates.waiting_for_video_prompt,
        GenerationStates.uploading_reference_videos,
    ),
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def accept_seedance_video_reference(
    message: types.Message,
    state: FSMContext,
) -> None:
    """Accept Seedance motion videos in both old media sub-flows."""
    data = await state.get_data()
    if not is_seedance_model(data.get("v_model")):
        raise SkipHandler

    video_obj = message.video or message.document
    if not video_obj:
        raise SkipHandler

    file_size = int(getattr(video_obj, "file_size", 0) or 0)
    if file_size > SEEDANCE_MAX_VIDEO_BYTES:
        await message.answer(
            "❌ Видео слишком большое. Для Seedance максимум 50 MB.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    duration = int(getattr(video_obj, "duration", 0) or 0)
    if duration and not (
        SEEDANCE_MIN_REFERENCE_VIDEO_SECONDS
        <= duration
        <= SEEDANCE_MAX_REFERENCE_VIDEO_SECONDS
    ):
        await message.answer(
            "❌ Видео-референс Seedance должен длиться от 2 до 15 секунд.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    existing_urls = []
    seen = set()
    for value in data.get("v_reference_videos") or []:
        url = str(value or "").strip()
        if url and url not in seen:
            seen.add(url)
            existing_urls.append(url)

    durations = [
        max(0, int(value or 0))
        for value in (data.get("seedance_reference_video_durations") or [])
    ]
    if len(existing_urls) >= SEEDANCE_MAX_VIDEOS:
        await message.answer(
            f"❌ Для Seedance можно загрузить максимум {SEEDANCE_MAX_VIDEOS} видео.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    known_total_duration = sum(durations)
    if duration and known_total_duration + duration > SEEDANCE_MAX_TOTAL_REFERENCE_VIDEO_SECONDS:
        await message.answer(
            "❌ Общая длительность видео-референсов Seedance не должна превышать 15 секунд.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    file = await message.bot.get_file(video_obj.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    mime_type = str(getattr(video_obj, "mime_type", "") or "video/mp4")
    file_ext = "mov" if mime_type == "video/quicktime" else "mp4"
    video_url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        downloaded.read(),
        file_ext,
        kind="video",
        original_filename=f"seedance_ref_{video_obj.file_id}.{file_ext}",
        content_type=mime_type,
    )
    if not video_url:
        await message.answer(
            "❌ Не удалось сохранить видео-референс.",
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    if video_url not in existing_urls:
        existing_urls.append(video_url)
        durations.append(duration)
    await state.update_data(
        v_reference_videos=existing_urls,
        seedance_reference_video_durations=durations,
    )

    image_count = (1 if data.get("v_image_url") else 0) + len(
        data.get("reference_images") or []
    )
    text = (
        "✅ Видео-референс Seedance добавлен.\n"
        f"Фото: <code>{image_count}/{SEEDANCE_MAX_IMAGES}</code> · "
        f"Видео: <code>{len(existing_urls)}/{SEEDANCE_MAX_VIDEOS}</code>"
    )
    if (await state.get_state()) == GenerationStates.uploading_reference_videos.state:
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_reference_videos_upload_keyboard(
                len(existing_urls),
                SEEDANCE_MAX_VIDEOS,
                "video_new",
            ),
        )
    else:
        await message.answer(text, parse_mode="HTML")
