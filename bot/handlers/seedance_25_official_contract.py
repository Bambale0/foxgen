"""Final public Seedance 2.5 contract for Telegram and Mini App.

Foxgen originally shipped Seedance 2.5 through several compatibility layers.
This module is installed last and makes the user-facing flow match the current
KIE Market contract while preserving the proven billing, upload, callback and
polling infrastructure.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

from bot.config import config
from bot.services.preset_manager import preset_manager
from bot.services.seedance_25_service import (
    get_seedance25_callback_url,
    seedance_25_service,
)

from . import generation as generation_module
from . import seedance_25_fullstack as fullstack
from . import seedance_25_preview as preview_module
from . import seedance_25_public_release as public_release

MODEL_KEY = "seedance_2_5"
MODEL_LABEL = "🔥🆕 NEW · Seedance 2.5"
SCENARIOS = {"text", "first_frame", "first_last", "multimodal"}
RATIOS = ("adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
RESOLUTIONS = ("480p", "720p")
MIN_DURATION = 4
MAX_DURATION = 30


def official_defaults() -> dict[str, Any]:
    """State defaults containing only supported product controls."""
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
        "video_flow_step": "seedance25",
    }


def _scenario_label(value: str) -> str:
    return {
        "text": "Текст → видео",
        "first_frame": "Первый кадр → видео",
        "first_last": "Первый + последний кадр",
        "multimodal": "Фото / видео / аудио референсы",
    }.get(value, value)


def _normalized_duration(value: Any) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        return 5
    return max(MIN_DURATION, min(MAX_DURATION, duration))


def _official_keyboard(data: dict[str, Any]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    scenario = str(data.get("seedance25_scenario") or "text")
    resolution = str(data.get("seedance25_resolution") or "720p")
    ratio = str(data.get("v_ratio") or "adaptive")
    duration = _normalized_duration(data.get("v_duration", 5))

    for key, label in (
        ("text", "✍️ По тексту"),
        ("first_frame", "🖼 Оживить фото"),
        ("first_last", "🎞 Между кадрами"),
        ("multimodal", "🧩 По референсам"),
    ):
        builder.button(
            text=("✅ " if scenario == key else "") + label,
            callback_data=f"s25_scenario_{key}",
        )

    for value in RESOLUTIONS:
        builder.button(
            text=("✅ " if resolution == value else "") + value,
            callback_data=f"s25_resolution_{value}",
        )

    if scenario in {"first_frame", "first_last"}:
        builder.button(
            text="📐 Формат кадра: по исходному фото",
            callback_data="ignore",
        )
    else:
        for value in RATIOS:
            builder.button(
                text=("✅ " if ratio == value else "") + ("Авто" if value == "adaptive" else value),
                callback_data=f"s25_ratio_{value.replace(':', '_')}",
            )

    builder.button(text="➖ 1с", callback_data="s25_duration_minus")
    builder.button(text=f"⏱ {duration}с", callback_data="ignore")
    builder.button(text="➕ 1с", callback_data="s25_duration_plus")
    builder.button(
        text=f"🔊 Звук: {'вкл' if data.get('seedance25_generate_audio', True) else 'выкл'}",
        callback_data="s25_toggle_audio",
    )
    builder.button(
        text=(
            "🖼 Последний кадр: "
            + ("да" if data.get("seedance25_return_last_frame") else "нет")
        ),
        callback_data="s25_toggle_return_last",
    )
    builder.button(text="🧹 Очистить медиа", callback_data="s25_clear_media")
    builder.button(text="🤖 К моделям", callback_data="video_change_model")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 1, 3, 2, 1, 2)
    return builder.as_markup()


def _price_quote(data: dict[str, Any]) -> float:
    duration = _normalized_duration(data.get("v_duration", 5))
    resolution = str(data.get("seedance25_resolution") or "720p")
    return float(
        preset_manager.get_video_cost_with_quality(
            MODEL_KEY,
            duration,
            resolution,
        )
    )


async def official_show_screen(target, state: FSMContext, *, edit: bool = True) -> None:
    data = await state.get_data()
    scenario = str(data.get("seedance25_scenario") or "text")
    if scenario not in SCENARIOS:
        scenario = "text"
        await state.update_data(seedance25_scenario=scenario)

    duration = _normalized_duration(data.get("v_duration", 5))
    if data.get("v_duration") != duration:
        await state.update_data(v_duration=duration)
        data["v_duration"] = duration

    if scenario in {"first_frame", "first_last"} and data.get("v_ratio") != "adaptive":
        await state.update_data(v_ratio="adaptive")
        data["v_ratio"] = "adaptive"

    first = bool(data.get("seedance25_first_frame_url"))
    last = bool(data.get("seedance25_last_frame_url"))
    images = len(data.get("reference_images") or [])
    videos = len(data.get("v_reference_videos") or [])
    audios = len(data.get("seedance25_reference_audio_urls") or [])
    quote = _price_quote(data)
    user_id = getattr(getattr(target, "from_user", None), "id", None)
    is_admin = bool(user_id and config.is_admin(int(user_id)))

    if scenario == "first_frame":
        media_hint = f"Пришлите <b>одно фото</b>. Загружено: {'✅' if first else '—'}"
    elif scenario == "first_last":
        media_hint = (
            "Пришлите <b>два фото</b> по очереди: начало и финал. "
            f"Первый {'✅' if first else '—'} · последний {'✅' if last else '—'}"
        )
    elif scenario == "multimodal":
        media_hint = (
            "Пришлите любые референсы прямо в этот чат: "
            f"фото <code>{images}/30</code> · видео <code>{videos}/10</code> · "
            f"аудио <code>{audios}/10</code>. Видео суммарно до 30с."
        )
    else:
        media_hint = "Медиа не нужно — достаточно описать будущий ролик."

    billing = (
        f"💰 Цена: <code>{quote:g}</code>🍌 · для администратора без списания."
        if is_admin
        else f"💰 Цена: <code>{quote:g}</code>🍌."
    )
    ratio_text = (
        "по исходному фото"
        if scenario in {"first_frame", "first_last"}
        else str(data.get("v_ratio") or "adaptive")
    )
    text = (
        "🔥 <b>Seedance 2.5</b>\n\n"
        f"Сценарий: <b>{_scenario_label(scenario)}</b>\n"
        f"Качество: <code>{data.get('seedance25_resolution', '720p')}</code> · "
        f"кадр: <code>{ratio_text}</code> · "
        f"длительность: <code>{duration}с</code>\n"
        f"Звук: <code>{'вкл' if data.get('seedance25_generate_audio', True) else 'выкл'}</code> · "
        f"вернуть последний кадр: <code>{'да' if data.get('seedance25_return_last_frame') else 'нет'}</code>\n\n"
        f"{media_hint}\n\n"
        "🎥 Движение камеры и фиксацию объектива опишите обычными словами в промпте.\n"
        "В режиме референсов можно указать, какой именно файл использовать для персонажа, движения или звука.\n\n"
        f"{billing}\n\n"
        "После настройки отправьте промпт до 5000 символов."
    )
    markup = _official_keyboard(data)

    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    elif edit:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")

    await state.set_state(generation_module.GenerationStates.waiting_for_video_prompt)


def official_model_meta() -> dict[str, Any]:
    durations = list(range(MIN_DURATION, MAX_DURATION + 1))
    quality_costs = preset_manager.get_video_quality_costs(MODEL_KEY)
    return {
        "id": MODEL_KEY,
        "label": MODEL_LABEL,
        "description": (
            "Видео по тексту, первому/последнему кадру или фото, видео и аудио-референсам"
        ),
        "durations": durations,
        "ratios": list(RATIOS),
        "supports": ["text", "imgtxt", "video"],
        "costs": {
            str(duration): preset_manager.get_video_cost_with_quality(
                MODEL_KEY,
                duration,
                "720p",
            )
            for duration in durations
        },
        "quality_costs": quality_costs,
        "seedance25_resolutions": list(RESOLUTIONS),
        "seedance25_scenarios": ["text", "first_frame", "first_last", "multimodal"],
        "supports_generate_audio": True,
        "supports_return_last_frame": True,
        "camera_control_via_prompt": True,
        "max_image_references": 30,
        "max_video_references": 10,
        "max_audio_references": 10,
        "admin_only": False,
        "is_new": True,
        "priority": 1000,
    }


def official_scenario_payload(data: dict[str, Any], prompt: str) -> dict[str, Any]:
    scenario = str(data.get("seedance25_scenario") or "text").strip().lower()
    if scenario not in SCENARIOS:
        scenario = "text"

    first = (
        data.get("seedance25_first_frame_url")
        if scenario in {"first_frame", "first_last"}
        else None
    )
    last = data.get("seedance25_last_frame_url") if scenario == "first_last" else None
    images = (
        fullstack._clean_urls(data.get("reference_images") or [], 30)
        if scenario == "multimodal"
        else []
    )
    videos = (
        fullstack._clean_urls(data.get("v_reference_videos") or [], 10)
        if scenario == "multimodal"
        else []
    )
    audios = (
        fullstack._clean_urls(data.get("seedance25_reference_audio_urls") or [], 10)
        if scenario == "multimodal"
        else []
    )
    ratio = str(data.get("v_ratio") or "adaptive").strip().lower()
    if scenario in {"first_frame", "first_last"}:
        ratio = "adaptive"

    return {
        "scenario": scenario,
        "prompt": str(prompt or "").strip(),
        "duration": _normalized_duration(data.get("v_duration", 5)),
        "ratio": ratio,
        "resolution": str(data.get("seedance25_resolution") or "720p").strip().lower(),
        "first_frame": str(first or "").strip() or None,
        "last_frame": str(last or "").strip() or None,
        "image_urls": images,
        "video_urls": videos,
        "audio_urls": audios,
        "return_last_frame": bool(data.get("seedance25_return_last_frame", False)),
        "generate_audio": bool(data.get("seedance25_generate_audio", True)),
    }


async def official_validate_public_payload(
    payload: dict[str, Any],
    *,
    is_admin: bool,
) -> None:
    del is_admin
    scenario = str(payload.get("scenario") or "text")
    if scenario not in SCENARIOS:
        raise ValueError("Некорректный сценарий Seedance 2.5")
    if len(str(payload.get("prompt") or "")) > seedance_25_service.MAX_PROMPT_LENGTH:
        raise ValueError("Промпт Seedance 2.5 — максимум 5000 символов")
    if scenario == "text" and not str(payload.get("prompt") or "").strip():
        raise ValueError("Опишите, какое видео нужно создать")
    if scenario in {"first_frame", "first_last"} and not payload.get("first_frame"):
        raise ValueError("Сначала загрузите первый кадр")
    if scenario == "first_last" and not payload.get("last_frame"):
        raise ValueError("Загрузите последний кадр")
    if scenario == "multimodal" and not (
        payload.get("image_urls") or payload.get("video_urls") or payload.get("audio_urls")
    ):
        raise ValueError("Добавьте хотя бы один фото, видео или аудио-референс")

    duration = int(payload.get("duration", 5))
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise ValueError("Длительность Seedance 2.5 — от 4 до 30 секунд")
    resolution = str(payload.get("resolution") or "720p")
    if resolution not in RESOLUTIONS:
        raise ValueError("Качество Seedance 2.5: 480p или 720p")
    ratio = str(payload.get("ratio") or "adaptive")
    if ratio not in RATIOS:
        raise ValueError("Некорректный формат кадра Seedance 2.5")
    if scenario in {"first_frame", "first_last"} and ratio != "adaptive":
        raise ValueError("Для первого/последнего кадра формат должен быть adaptive")

    await fullstack._validate_seedance_sources(
        first_frame_url=payload.get("first_frame"),
        last_frame_url=payload.get("last_frame"),
        image_urls=list(payload.get("image_urls") or []),
        video_urls=list(payload.get("video_urls") or []),
        audio_urls=list(payload.get("audio_urls") or []),
    )


async def official_launch_provider(payload: dict[str, Any]) -> dict[str, Any]:
    return await seedance_25_service.generate_video(
        prompt=str(payload.get("prompt") or ""),
        duration=int(payload.get("duration", 5)),
        aspect_ratio=str(payload.get("ratio") or "adaptive"),
        resolution=str(payload.get("resolution") or "720p"),
        first_frame_url=payload.get("first_frame"),
        last_frame_url=payload.get("last_frame"),
        reference_image_urls=list(payload.get("image_urls") or []) or None,
        reference_video_urls=list(payload.get("video_urls") or []) or None,
        reference_audio_urls=list(payload.get("audio_urls") or []) or None,
        return_last_frame=bool(payload.get("return_last_frame")),
        generate_audio=bool(payload.get("generate_audio", True)),
        callBackUrl=get_seedance25_callback_url(),
    )


def official_request_data(
    payload: dict[str, Any],
    *,
    is_admin: bool,
    quote: float,
    source: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "release": "seedance_2_5_official",
        "v_model": MODEL_KEY,
        "v_type": (
            "text"
            if payload["scenario"] == "text"
            else "imgtxt"
            if payload["scenario"] in {"first_frame", "first_last"}
            else "video"
        ),
        "seedance25_scenario": payload["scenario"],
        "first_frame_url": payload.get("first_frame"),
        "last_frame_url": payload.get("last_frame"),
        "reference_images": list(payload.get("image_urls") or []),
        "v_reference_videos": list(payload.get("video_urls") or []),
        "reference_audios": list(payload.get("audio_urls") or []),
        "resolution": payload["resolution"],
        "aspect_ratio": payload["ratio"],
        "duration": payload["duration"],
        "generate_audio": bool(payload.get("generate_audio", True)),
        "return_last_frame": bool(payload.get("return_last_frame")),
        "charged": not is_admin,
        "charged_cost": float(quote),
        "admin_free": is_admin,
        "refund_on_failure": not is_admin,
        "refund_claimed": False,
        "callback_url": get_seedance25_callback_url(),
        "provider_model": seedance_25_service.MODEL_NAME,
    }


def _sanitize_model_list(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = [
        dict(item)
        for item in models
        if isinstance(item, dict) and str(item.get("id") or "") != MODEL_KEY
    ]
    return [official_model_meta(), *clean]


def install_seedance_25_official_contract() -> None:
    """Install the current KIE contract as the last Seedance compatibility layer."""
    import bot.miniapp as miniapp_module

    from . import seedance_25_new_priority as priority_module

    if getattr(generation_module, "_seedance_25_official_contract_installed", False):
        return

    preview_module._defaults = official_defaults
    preview_module._seedance_25_keyboard = _official_keyboard
    preview_module._price_quote = _price_quote
    preview_module._show_seedance_25_screen = official_show_screen

    public_release._public_show_screen = official_show_screen
    public_release._scenario_payload = official_scenario_payload
    public_release._validate_public_payload = official_validate_public_payload
    public_release._launch_provider = official_launch_provider
    public_release._request_data = official_request_data
    public_release._public_model_meta = official_model_meta

    fullstack._seedance25_model_meta = official_model_meta
    priority_module._priority_model_meta = official_model_meta

    current_bootstrap = miniapp_module.miniapp_bootstrap

    @wraps(current_bootstrap)
    async def official_bootstrap(request: web.Request) -> web.Response:
        response = await current_bootstrap(request)
        if response.status != 200:
            return response
        payload = fullstack._json_response_payload(response)
        if not payload:
            return response
        payload["video_models"] = _sanitize_model_list(
            list(payload.get("video_models") or [])
        )
        return web.json_response(payload)

    miniapp_module.miniapp_bootstrap = official_bootstrap
    generation_module._seedance_25_official_contract_installed = True
