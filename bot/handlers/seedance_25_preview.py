"""Admin-only Seedance 2.5 preview with the complete released Kie spec.

The preview is intentionally isolated from stable Seedance 2.0.  It adds a
provider-specific settings screen and validates the mutually-exclusive
first-frame / first+last / multimodal scenarios before the task reaches Kie.
"""

from __future__ import annotations

import io
from functools import wraps

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PIL import Image

from bot.config import config
from bot.services.preset_manager import preset_manager
from bot.services.seedance_25_service import seedance_25_service

from . import generation as generation_module

router = Router(name="seedance_25_preview")
MODEL_KEY = "seedance_2_5"

IMAGE_MIME_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    "image/gif": "gif",
}
VIDEO_MIME_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov"}
AUDIO_MIME_TYPES = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}

MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MIN_MEDIA_SIDE = 300
MAX_MEDIA_SIDE = 6000
MIN_IMAGE_RATIO = 0.4
MAX_IMAGE_RATIO = 2.5
MIN_VIDEO_PIXELS = 640 * 640
MAX_VIDEO_PIXELS = 834 * 1112
MIN_REFERENCE_DURATION = 2
MAX_REFERENCE_DURATION = 30
MAX_TOTAL_VIDEO_DURATION = 30

DEFAULT_PRICE_CONFIG = {
    "base": 20,
    "default_duration": 5,
    "duration_min": 4,
    "duration_max": 30,
    # quality_costs are retail bananas per generated second.  The existing
    # admin pricing screen edits these values directly without a restart.
    "quality_costs": {"480p": 3, "720p": 4},
}


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and config.is_admin(int(user_id)))


def _ensure_price_config() -> None:
    """One-time config migration so the existing admin pricing UI owns prices."""
    price_config = preset_manager.get_price_config()
    video_models = price_config.setdefault("costs_reference", {}).setdefault(
        "video_models", {}
    )
    if MODEL_KEY not in video_models:
        video_models[MODEL_KEY] = dict(DEFAULT_PRICE_CONFIG)
        video_models[MODEL_KEY]["quality_costs"] = dict(
            DEFAULT_PRICE_CONFIG["quality_costs"]
        )
        preset_manager.update_price_config(price_config)

    # The admin panel resolves model labels from this table dynamically.
    try:
        from . import admin as admin_module

        admin_module.VIDEO_MODEL_LABELS.setdefault(MODEL_KEY, "Seedance 2.5")
    except Exception:
        generation_module.logger.exception("Could not register Seedance 2.5 admin price label")


def _defaults() -> dict:
    return {
        "generation_type": "video",
        "v_model": MODEL_KEY,
        "v_type": "text",
        "v_duration": 5,
        "v_ratio": "adaptive",
        "v_image_url": None,
        "reference_images": [],
        "v_reference_videos": [],
        "seedance25_scenario": "text",
        "seedance25_first_frame_url": None,
        "seedance25_last_frame_url": None,
        "seedance25_reference_audio_urls": [],
        "seedance25_reference_video_durations": [],
        "seedance25_resolution": "720p",
        "seedance25_generate_audio": True,
        "seedance25_return_last_frame": False,
        "seedance25_output_format": "mp4",
        "seedance25_web_search": False,
        "seedance25_nsfw_checker": False,
        "video_flow_step": "seedance25",
    }


def _scenario_label(value: str) -> str:
    return {
        "text": "Текст → видео",
        "first_frame": "Первый кадр → видео",
        "first_last": "Первый + последний кадр",
        "multimodal": "Мультимодальные референсы",
    }.get(value, value)


def _duration_label(value: int) -> str:
    return "Auto" if int(value) == -1 else f"{int(value)}с"


def _seedance_25_keyboard(data: dict):
    builder = InlineKeyboardBuilder()
    scenario = data.get("seedance25_scenario", "text")
    resolution = data.get("seedance25_resolution", "720p")
    ratio = data.get("v_ratio", "adaptive")
    duration = int(data.get("v_duration", 5))

    for key, label in (
        ("text", "✍️ Текст"),
        ("first_frame", "🖼 1-й кадр"),
        ("first_last", "🎞 1-й + посл."),
        ("multimodal", "🧩 Референсы"),
    ):
        builder.button(
            text=("✅ " if scenario == key else "") + label,
            callback_data=f"s25_scenario_{key}",
        )

    for value in ("480p", "720p"):
        builder.button(
            text=("✅ " if resolution == value else "") + value,
            callback_data=f"s25_resolution_{value}",
        )

    for value in ("adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"):
        builder.button(
            text=("✅ " if ratio == value else "") + value,
            callback_data=f"s25_ratio_{value.replace(':', '_')}",
        )

    builder.button(text="➖ 1с", callback_data="s25_duration_minus")
    builder.button(
        text=("✅ " if duration == -1 else "") + "Auto",
        callback_data="s25_duration_auto",
    )
    builder.button(text=f"⏱ {_duration_label(duration)}", callback_data="ignore")
    builder.button(text="➕ 1с", callback_data="s25_duration_plus")

    builder.button(
        text=f"🔊 Аудио: {'вкл' if data.get('seedance25_generate_audio', True) else 'выкл'}",
        callback_data="s25_toggle_audio",
    )
    builder.button(
        text=f"🧾 Последний кадр: {'да' if data.get('seedance25_return_last_frame') else 'нет'}",
        callback_data="s25_toggle_return_last",
    )
    builder.button(
        text=f"📦 Формат: {data.get('seedance25_output_format', 'mp4')}",
        callback_data="s25_toggle_output",
    )
    builder.button(
        text=f"🌐 Web search: {'вкл' if data.get('seedance25_web_search') else 'выкл'}",
        callback_data="s25_toggle_search",
    )
    builder.button(
        text=f"🛡 NSFW checker: {'вкл' if data.get('seedance25_nsfw_checker') else 'выкл'}",
        callback_data="s25_toggle_nsfw",
    )
    builder.button(text="🧹 Очистить медиа", callback_data="s25_clear_media")
    builder.button(text="🤖 К моделям", callback_data="video_change_model")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 2, 3, 2, 2, 4, 2, 2, 1, 2)
    return builder.as_markup()


def _price_quote(data: dict) -> float:
    duration = int(data.get("v_duration", 5))
    # Auto has no deterministic output duration.  Show the configured default
    # 5-second quote while preserving -1 in the provider request.
    pricing_duration = 5 if duration == -1 else duration
    return preset_manager.get_video_cost_with_quality(
        MODEL_KEY,
        pricing_duration,
        data.get("seedance25_resolution", "720p"),
    )


async def _show_seedance_25_screen(target, state: FSMContext, *, edit: bool = True) -> None:
    data = await state.get_data()
    scenario = data.get("seedance25_scenario", "text")
    first = bool(data.get("seedance25_first_frame_url"))
    last = bool(data.get("seedance25_last_frame_url"))
    images = len(data.get("reference_images") or [])
    videos = len(data.get("v_reference_videos") or [])
    audios = len(data.get("seedance25_reference_audio_urls") or [])
    duration = int(data.get("v_duration", 5))
    quote = _price_quote(data)

    if scenario == "first_frame":
        media_hint = f"Загрузите <b>1 фото</b> как первый кадр. Сейчас: {'✅' if first else '—'}"
    elif scenario == "first_last":
        media_hint = (
            "Загрузите последовательно <b>2 фото</b>: первый и последний кадр. "
            f"Сейчас: первый {'✅' if first else '—'}, последний {'✅' if last else '—'}"
        )
    elif scenario == "multimodal":
        media_hint = (
            "Можно присылать фото / видео / аудио прямо сюда. "
            f"Фото <code>{images}/30</code>, видео <code>{videos}/10</code>, "
            f"аудио <code>{audios}/10</code>. Видео суммарно ≤30с."
        )
    else:
        media_hint = "Медиа не требуется — отправьте текстовый промпт."

    auto_note = " (ориентир за 5с)" if duration == -1 else ""
    text = (
        "🧪 <b>Seedance 2.5 — admin preview</b>\n\n"
        f"Сценарий: <b>{_scenario_label(scenario)}</b>\n"
        f"Качество: <code>{data.get('seedance25_resolution', '720p')}</code> · "
        f"Формат кадра: <code>{data.get('v_ratio', 'adaptive')}</code> · "
        f"Длительность: <code>{_duration_label(duration)}</code>\n"
        f"Выход: <code>{data.get('seedance25_output_format', 'mp4')}</code> · "
        f"генерация аудио: <code>{'on' if data.get('seedance25_generate_audio', True) else 'off'}</code>\n"
        f"Web search: <code>{'on' if data.get('seedance25_web_search') else 'off'}</code> · "
        f"NSFW checker: <code>{'on' if data.get('seedance25_nsfw_checker') else 'off'}</code> · "
        f"вернуть последний кадр: <code>{'yes' if data.get('seedance25_return_last_frame') else 'no'}</code>\n\n"
        f"{media_hint}\n\n"
        "🎥 <b>Dynamic Camera</b>: отдельного API-поля в опубликованной схеме нет; "
        "движение камеры и lock объектива задавайте в промпте.\n\n"
        f"💰 Текущая цена из админ-прайса: <code>{quote}</code>🍌{auto_note}.\n"
        "Администратору списание не производится.\n\n"
        "После настройки просто отправьте промпт (до 5000 символов)."
    )
    markup = _seedance_25_keyboard(data)

    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    elif edit:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")

    await state.set_state(generation_module.GenerationStates.waiting_for_video_prompt)


def install_seedance_25_preview() -> None:
    """Patch narrow generation seams once for the admin preview model."""
    if getattr(generation_module, "_seedance_25_preview_installed", False):
        return

    _ensure_price_config()
    original_show_models = generation_module._show_video_model_selection_screen
    original_apply_model = generation_module._apply_video_model_selection
    original_message_launch = generation_module.run_no_preset_video_from_message
    original_callback_launch = generation_module.run_no_preset_video_from_callback

    @wraps(original_show_models)
    async def show_models_with_admin_preview(message_or_callback, state, edit=True):
        data = await state.get_data()
        current_model = data.get("v_model", "v3_pro")
        user_id = getattr(getattr(message_or_callback, "from_user", None), "id", None)
        user_credits = await generation_module.get_user_credits(user_id) if user_id else 0
        text = (
            "🎬 <b>Создание видео</b>\n"
            f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
            "<b>Шаг 1. Выберите модель</b>\n"
            "Сначала выберите модель видео.\n"
            "После этого бот покажет следующий шаг именно для неё."
        )
        keyboard = generation_module.get_video_model_selection_keyboard(
            current_model,
            user_id=user_id,
        )
        try:
            if isinstance(message_or_callback, types.CallbackQuery):
                await message_or_callback.message.edit_text(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
            elif edit:
                await message_or_callback.edit_text(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
            else:
                await message_or_callback.answer(
                    text, reply_markup=keyboard, parse_mode="HTML"
                )
        except Exception:
            await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(generation_module.GenerationStates.waiting_for_input)

    @wraps(original_apply_model)
    async def apply_model_with_admin_guard(callback, state, model):
        if model != MODEL_KEY:
            return await original_apply_model(callback, state, model)
        if not _is_admin(callback.from_user.id):
            await callback.answer("Модель доступна только администраторам", show_alert=True)
            return
        await state.clear()
        await state.update_data(**_defaults())
        await _show_seedance_25_screen(callback, state)
        await callback.answer()

    @wraps(original_message_launch)
    async def message_launch_with_seedance_25(message, state, prompt):
        data = await state.get_data()
        if data.get("v_model") != MODEL_KEY:
            return await original_message_launch(message, state, prompt)
        if not _is_admin(message.from_user.id):
            await message.answer("❌ Seedance 2.5 сейчас доступна только администраторам.")
            await state.clear()
            return
        return await _run_seedance_25_message(message, state, prompt)

    @wraps(original_callback_launch)
    async def callback_launch_with_seedance_25(callback, state, prompt, cost, is_admin):
        data = await state.get_data()
        if data.get("v_model") != MODEL_KEY:
            return await original_callback_launch(callback, state, prompt, cost, is_admin)
        if not _is_admin(callback.from_user.id):
            await callback.message.answer("❌ Seedance 2.5 сейчас доступна только администраторам.")
            await state.clear()
            return
        return await _run_seedance_25_callback(callback, state, prompt)

    generation_module._show_video_model_selection_screen = show_models_with_admin_preview
    generation_module._apply_video_model_selection = apply_model_with_admin_guard
    generation_module.run_no_preset_video_from_message = message_launch_with_seedance_25
    generation_module.run_no_preset_video_from_callback = callback_launch_with_seedance_25
    generation_module._seedance_25_preview_installed = True


def _clean_urls(values, limit: int) -> list[str]:
    return generation_module._clean_unique_urls(values or [])[:limit]


async def _run_seedance_25_message(message: types.Message, state: FSMContext, prompt: str) -> None:
    data = await state.get_data()
    scenario = data.get("seedance25_scenario", "text")
    duration = int(data.get("v_duration", 5))
    ratio = data.get("v_ratio", "adaptive")
    resolution = data.get("seedance25_resolution", "720p")

    first_frame = data.get("seedance25_first_frame_url") if scenario in {"first_frame", "first_last"} else None
    last_frame = data.get("seedance25_last_frame_url") if scenario == "first_last" else None
    image_urls = _clean_urls(data.get("reference_images"), 30) if scenario == "multimodal" else []
    video_urls = _clean_urls(data.get("v_reference_videos"), 10) if scenario == "multimodal" else []
    audio_urls = _clean_urls(data.get("seedance25_reference_audio_urls"), 10) if scenario == "multimodal" else []

    if scenario in {"first_frame", "first_last"} and not first_frame:
        await message.answer("❌ Сначала загрузите первый кадр.")
        return
    if scenario == "first_last" and not last_frame:
        await message.answer("❌ Для этого режима загрузите и последний кадр.")
        return
    if len(str(prompt or "")) > seedance_25_service.MAX_PROMPT_LENGTH:
        await message.answer("❌ Промпт Seedance 2.5 — максимум 5000 символов.")
        return

    quote = _price_quote(data)
    processing = await message.answer(
        "🧪 <b>Seedance 2.5 — admin preview</b>\n"
        f"Сценарий: <code>{scenario}</code> · цена по прайсу: <code>{quote}</code>🍌\n"
        "Задача отправляется в Kie.ai…",
        parse_mode="HTML",
    )
    try:
        result = await seedance_25_service.generate_video(
            prompt=prompt,
            duration=duration,
            aspect_ratio=ratio,
            resolution=resolution,
            first_frame_url=first_frame,
            last_frame_url=last_frame,
            reference_image_urls=image_urls or None,
            reference_video_urls=video_urls or None,
            reference_audio_urls=audio_urls or None,
            return_last_frame=bool(data.get("seedance25_return_last_frame", False)),
            generate_audio=bool(data.get("seedance25_generate_audio", True)),
            output_format=data.get("seedance25_output_format", "mp4"),
            web_search=bool(data.get("seedance25_web_search", False)),
            nsfw_checker=bool(data.get("seedance25_nsfw_checker", False)),
            callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
        )
        await processing.delete()
        if not result or not result.get("task_id"):
            error = result.get("error") if isinstance(result, dict) else "provider response has no task_id"
            await message.answer(f"❌ Seedance 2.5 не запустилась: <code>{error}</code>", parse_mode="HTML")
            return

        user = await generation_module.get_or_create_user(message.from_user.id)
        await generation_module.add_generation_task(
            user.id,
            message.from_user.id,
            result["task_id"],
            "video",
            "no_preset_video",
            model=MODEL_KEY,
            duration=duration,
            aspect_ratio=ratio,
            prompt=prompt,
            cost=quote,
            request_data={
                "source": "telegram",
                "preview": "seedance_2_5_admin",
                "v_model": MODEL_KEY,
                "scenario": scenario,
                "first_frame_url": first_frame,
                "last_frame_url": last_frame,
                "reference_images": image_urls,
                "reference_videos": video_urls,
                "reference_audios": audio_urls,
                "resolution": resolution,
                "generate_audio": bool(data.get("seedance25_generate_audio", True)),
                "return_last_frame": bool(data.get("seedance25_return_last_frame", False)),
                "output_format": data.get("seedance25_output_format", "mp4"),
                "web_search": bool(data.get("seedance25_web_search", False)),
                "nsfw_checker": bool(data.get("seedance25_nsfw_checker", False)),
                "admin_price_quote": quote,
                "admin_free": True,
            },
        )
        await message.answer(
            "✅ <b>Seedance 2.5 запущена</b>\n"
            f"🆔 <code>{result['task_id']}</code>\n"
            f"⏱ <code>{_duration_label(duration)}</code> · 📐 <code>{ratio}</code> · "
            f"🖥 <code>{resolution}</code>\n"
            f"💰 Прайс: <code>{quote}</code>🍌, администратору бесплатно.\n\n"
            "Результат придёт через общий Kie webhook.",
            parse_mode="HTML",
        )
    except Exception as exc:
        generation_module.logger.exception("Seedance 2.5 admin preview failed")
        try:
            await processing.delete()
        except Exception:
            pass
        await message.answer(
            f"❌ Seedance 2.5: <code>{str(exc)[:500]}</code>",
            parse_mode="HTML",
        )
    finally:
        await state.clear()


async def _run_seedance_25_callback(callback: types.CallbackQuery, state: FSMContext, prompt: str) -> None:
    await _run_seedance_25_message(callback.message, state, prompt)
    try:
        await callback.answer("Seedance 2.5 запускаю")
    except Exception:
        pass


async def _assert_preview(callback: types.CallbackQuery, state: FSMContext) -> dict | None:
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(callback.from_user.id):
        await callback.answer("Seedance 2.5 preview недоступен", show_alert=True)
        return None
    return data


@router.callback_query(F.data == "v_model_seedance_2_5")
async def guard_seedance_25_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Модель доступна только администраторам", show_alert=True)
        return
    # Patched generic selector performs the state transition.
    raise SkipHandler


@router.callback_query(F.data.startswith("s25_scenario_"))
async def seedance25_scenario(callback: types.CallbackQuery, state: FSMContext):
    if await _assert_preview(callback, state) is None:
        return
    scenario = callback.data.replace("s25_scenario_", "", 1)
    if scenario not in {"text", "first_frame", "first_last", "multimodal"}:
        await callback.answer()
        return
    updates = {
        "seedance25_scenario": scenario,
        "v_type": "text" if scenario == "text" else "imgtxt" if scenario in {"first_frame", "first_last"} else "video",
    }
    # Enforce the provider's mutually-exclusive scenarios in state as well as
    # in the service adapter.
    if scenario in {"text", "first_frame", "first_last"}:
        updates.update(
            reference_images=[],
            v_reference_videos=[],
            seedance25_reference_audio_urls=[],
            seedance25_reference_video_durations=[],
        )
    if scenario in {"text", "multimodal"}:
        updates.update(
            seedance25_first_frame_url=None,
            seedance25_last_frame_url=None,
        )
    await state.update_data(**updates)
    await _show_seedance_25_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("s25_resolution_"))
async def seedance25_resolution(callback: types.CallbackQuery, state: FSMContext):
    if await _assert_preview(callback, state) is None:
        return
    value = callback.data.replace("s25_resolution_", "", 1)
    if value in seedance_25_service.ALLOWED_RESOLUTIONS:
        await state.update_data(seedance25_resolution=value)
    await _show_seedance_25_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("s25_ratio_"))
async def seedance25_ratio(callback: types.CallbackQuery, state: FSMContext):
    if await _assert_preview(callback, state) is None:
        return
    value = callback.data.replace("s25_ratio_", "", 1).replace("_", ":")
    if value == "adaptive" or value in seedance_25_service.ALLOWED_RATIOS:
        await state.update_data(v_ratio=value)
    await _show_seedance_25_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.in_({"s25_duration_minus", "s25_duration_plus", "s25_duration_auto"}))
async def seedance25_duration(callback: types.CallbackQuery, state: FSMContext):
    data = await _assert_preview(callback, state)
    if data is None:
        return
    current = int(data.get("v_duration", 5))
    if callback.data == "s25_duration_auto":
        value = -1
    else:
        if current == -1:
            current = 5
        delta = 1 if callback.data.endswith("plus") else -1
        value = max(4, min(30, current + delta))
    await state.update_data(v_duration=value)
    await _show_seedance_25_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data.in_({"s25_toggle_audio", "s25_toggle_return_last", "s25_toggle_output", "s25_toggle_search", "s25_toggle_nsfw"}))
async def seedance25_toggles(callback: types.CallbackQuery, state: FSMContext):
    data = await _assert_preview(callback, state)
    if data is None:
        return
    if callback.data == "s25_toggle_audio":
        await state.update_data(seedance25_generate_audio=not bool(data.get("seedance25_generate_audio", True)))
    elif callback.data == "s25_toggle_return_last":
        await state.update_data(seedance25_return_last_frame=not bool(data.get("seedance25_return_last_frame", False)))
    elif callback.data == "s25_toggle_output":
        await state.update_data(seedance25_output_format="mov" if data.get("seedance25_output_format") == "mp4" else "mp4")
    elif callback.data == "s25_toggle_search":
        await state.update_data(seedance25_web_search=not bool(data.get("seedance25_web_search", False)))
    elif callback.data == "s25_toggle_nsfw":
        await state.update_data(seedance25_nsfw_checker=not bool(data.get("seedance25_nsfw_checker", False)))
    await _show_seedance_25_screen(callback, state)
    await callback.answer()


@router.callback_query(F.data == "s25_clear_media")
async def seedance25_clear_media(callback: types.CallbackQuery, state: FSMContext):
    if await _assert_preview(callback, state) is None:
        return
    await state.update_data(
        seedance25_first_frame_url=None,
        seedance25_last_frame_url=None,
        reference_images=[],
        v_reference_videos=[],
        seedance25_reference_audio_urls=[],
        seedance25_reference_video_durations=[],
    )
    await _show_seedance_25_screen(callback, state)
    await callback.answer("Медиа очищено")


async def _download_media(message: types.Message, obj) -> bytes:
    tg_file = await message.bot.get_file(obj.file_id)
    downloaded = await message.bot.download_file(tg_file.file_path)
    return downloaded.read()


def _valid_dimensions(width: int, height: int, *, video: bool = False) -> bool:
    if not width or not height:
        return True
    if not (MIN_MEDIA_SIDE <= width <= MAX_MEDIA_SIDE and MIN_MEDIA_SIDE <= height <= MAX_MEDIA_SIDE):
        return False
    ratio = width / height
    if not MIN_IMAGE_RATIO <= ratio <= MAX_IMAGE_RATIO:
        return False
    if video:
        pixels = width * height
        return MIN_VIDEO_PIXELS <= pixels <= MAX_VIDEO_PIXELS
    return True


@router.message(
    generation_module.GenerationStates.waiting_for_video_prompt,
    F.photo | (F.document & F.document.mime_type.startswith("image/")),
)
async def seedance25_image_upload(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    scenario = data.get("seedance25_scenario", "text")
    if scenario == "text":
        await message.answer("В режиме Text-to-Video фото не используется. Выберите другой сценарий.")
        return

    obj = message.document or (message.photo[-1] if message.photo else None)
    if not obj:
        return
    mime = str(getattr(obj, "mime_type", "") or "image/jpeg")
    ext = IMAGE_MIME_TYPES.get(mime)
    if not ext:
        await message.answer("❌ Seedance 2.5 принимает jpeg/png/webp/bmp/tiff/gif.")
        return
    size = int(getattr(obj, "file_size", 0) or 0)
    if size > MAX_IMAGE_BYTES:
        await message.answer("❌ Изображение должно быть меньше 30 MB.")
        return

    raw = await _download_media(message, obj)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
    except Exception:
        await message.answer("❌ Не удалось прочитать изображение.")
        return
    if not _valid_dimensions(width, height):
        await message.answer("❌ Для Seedance изображение: 300–6000 px по стороне, ratio 0.4–2.5.")
        return

    url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        raw,
        ext,
        kind="image",
        original_filename=f"seedance25_{obj.file_id}.{ext}",
        content_type=mime,
    )
    if not url:
        await message.answer("❌ Не удалось сохранить изображение.")
        return

    if scenario == "first_frame":
        await state.update_data(seedance25_first_frame_url=url, seedance25_last_frame_url=None)
    elif scenario == "first_last":
        if not data.get("seedance25_first_frame_url"):
            await state.update_data(seedance25_first_frame_url=url)
        else:
            await state.update_data(seedance25_last_frame_url=url)
    else:
        refs = _clean_urls([*(data.get("reference_images") or []), url], 30)
        await state.update_data(reference_images=refs)

    await message.answer("✅ Фото Seedance 2.5 добавлено.")
    await _show_seedance_25_screen(message, state, edit=False)


@router.message(
    generation_module.GenerationStates.waiting_for_video_prompt,
    F.video | (F.document & F.document.mime_type.startswith("video/")),
)
async def seedance25_video_upload(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    if data.get("seedance25_scenario") != "multimodal":
        await message.answer("Видео-референсы доступны только в мультимодальном сценарии.")
        return

    obj = message.video or message.document
    mime = str(getattr(obj, "mime_type", "") or "video/mp4")
    ext = VIDEO_MIME_TYPES.get(mime)
    if not ext:
        await message.answer("❌ Видео-референс должен быть mp4 или mov.")
        return
    if int(getattr(obj, "file_size", 0) or 0) > MAX_VIDEO_BYTES:
        await message.answer("❌ Видео-референс не должен превышать 200 MB.")
        return
    duration = int(getattr(obj, "duration", 0) or 0)
    if duration and not MIN_REFERENCE_DURATION <= duration <= MAX_REFERENCE_DURATION:
        await message.answer("❌ Длительность одного видео-рефа: 2–30 секунд.")
        return
    widths = int(getattr(obj, "width", 0) or 0)
    heights = int(getattr(obj, "height", 0) or 0)
    if not _valid_dimensions(widths, heights, video=True):
        await message.answer("❌ Размеры/ratio видео не соответствуют Seedance 2.5 spec.")
        return

    urls = _clean_urls(data.get("v_reference_videos"), 10)
    durations = [int(x or 0) for x in data.get("seedance25_reference_video_durations") or []]
    if len(urls) >= 10:
        await message.answer("❌ Максимум 10 видео-референсов.")
        return
    if duration and sum(durations) + duration > MAX_TOTAL_VIDEO_DURATION:
        await message.answer("❌ Суммарная длительность видео-референсов — максимум 30 секунд.")
        return

    raw = await _download_media(message, obj)
    url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        raw,
        ext,
        kind="video",
        original_filename=f"seedance25_{obj.file_id}.{ext}",
        content_type=mime,
    )
    if not url:
        await message.answer("❌ Не удалось сохранить видео.")
        return
    urls.append(url)
    durations.append(duration)
    await state.update_data(
        v_reference_videos=urls,
        seedance25_reference_video_durations=durations,
    )
    await message.answer("✅ Видео-референс Seedance 2.5 добавлен.")
    await _show_seedance_25_screen(message, state, edit=False)


@router.message(
    generation_module.GenerationStates.waiting_for_video_prompt,
    F.audio | (F.document & F.document.mime_type.startswith("audio/")) | F.voice,
)
async def seedance25_audio_upload(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    if data.get("seedance25_scenario") != "multimodal":
        await message.answer("Аудио-референсы доступны только в мультимодальном сценарии.")
        return
    if message.voice:
        await message.answer("❌ Telegram voice = OGG. По Seedance 2.5 spec нужны WAV или MP3.")
        return

    obj = message.audio or message.document
    mime = str(getattr(obj, "mime_type", "") or "")
    ext = AUDIO_MIME_TYPES.get(mime)
    if not ext:
        await message.answer("❌ Аудио-референс должен быть WAV или MP3.")
        return
    if int(getattr(obj, "file_size", 0) or 0) > MAX_AUDIO_BYTES:
        await message.answer("❌ Аудио-референс не должен превышать 15 MB.")
        return
    duration = int(getattr(obj, "duration", 0) or 0)
    if duration and not MIN_REFERENCE_DURATION <= duration <= MAX_REFERENCE_DURATION:
        await message.answer("❌ Длительность одного аудио-рефа: 2–30 секунд.")
        return

    urls = _clean_urls(data.get("seedance25_reference_audio_urls"), 10)
    if len(urls) >= 10:
        await message.answer("❌ Максимум 10 аудио-референсов.")
        return
    raw = await _download_media(message, obj)
    url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        raw,
        ext,
        kind="audio",
        original_filename=f"seedance25_{obj.file_id}.{ext}",
        content_type=mime,
    )
    if not url:
        await message.answer("❌ Не удалось сохранить аудио.")
        return
    urls.append(url)
    await state.update_data(seedance25_reference_audio_urls=urls)
    await message.answer("✅ Аудио-референс Seedance 2.5 добавлен.")
    await _show_seedance_25_screen(message, state, edit=False)
