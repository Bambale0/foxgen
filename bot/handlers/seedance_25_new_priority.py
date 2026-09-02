"""Make Seedance 2.5 the most prominent NEW video model.

Installed after the public-release compatibility layer so both Telegram and the
Mini App receive the same product ordering without changing tanyapi.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from aiohttp import web
from aiogram import types

from bot.services.preset_manager import preset_manager

from . import generation as generation_module
from . import seedance_25_fullstack as fullstack
from . import seedance_25_public_release as public_release
from .seedance_25_official_contract import install_seedance_25_official_contract

MODEL_KEY = "seedance_2_5"
MODEL_LABEL = "🔥🆕 NEW · Seedance 2.5"


def _priority_button_text(current_model: str) -> str:
    check = "✅ " if current_model == MODEL_KEY else ""
    per_second = preset_manager.get_video_cost_per_second(MODEL_KEY, 5, "720p")
    return f"{check}{MODEL_LABEL} • {per_second}🍌/с"


def _priority_model_meta() -> dict[str, Any]:
    original = getattr(
        public_release,
        "_public_model_meta_original",
        public_release._public_model_meta,
    )
    meta = original()
    meta.update(
        {
            "label": MODEL_LABEL,
            "description": "Новая Bytedance video-модель: текст, first/last frame и мультимодальные фото/видео/аудио референсы",
            "admin_only": False,
            "is_new": True,
            "priority": 1000,
        }
    )
    return meta


def _prioritize_video_keyboard(original):
    @wraps(original)
    def wrapped(current_model: str = "v3_pro", user_id: int | None = None):
        markup = original(current_model, user_id=user_id)
        rows: list[list[types.InlineKeyboardButton]] = []
        seedance_button: types.InlineKeyboardButton | None = None

        for row in markup.inline_keyboard:
            kept: list[types.InlineKeyboardButton] = []
            for button in row:
                if str(button.callback_data or "") == "v_model_seedance_2_5":
                    seedance_button = types.InlineKeyboardButton(
                        text=_priority_button_text(current_model),
                        callback_data="v_model_seedance_2_5",
                    )
                else:
                    kept.append(button)
            if kept:
                rows.append(kept)

        if seedance_button is None:
            seedance_button = types.InlineKeyboardButton(
                text=_priority_button_text(current_model),
                callback_data="v_model_seedance_2_5",
            )

        return types.InlineKeyboardMarkup(
            inline_keyboard=[[seedance_button], *rows]
        )

    return wrapped


def _move_seedance_first(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seedance: dict[str, Any] | None = None
    others: list[dict[str, Any]] = []
    for model in models:
        if str(model.get("id") or "") == MODEL_KEY:
            seedance = dict(model)
        else:
            others.append(model)

    if seedance is None:
        seedance = _priority_model_meta()
    else:
        seedance.update(
            label=MODEL_LABEL,
            admin_only=False,
            is_new=True,
            priority=1000,
        )
    return [seedance, *others]


def install_seedance_25_new_priority() -> None:
    """Prioritize the public Seedance entry in Telegram and Mini App model data."""
    import bot.keyboards as keyboard_module
    import bot.miniapp as miniapp_module

    if getattr(generation_module, "_seedance_25_new_priority_installed", False):
        return

    # The public-release wrapper resolves these globals at call time, so switch
    # its public copy to the brighter product label as well.
    if not hasattr(public_release, "_public_model_meta_original"):
        public_release._public_model_meta_original = public_release._public_model_meta
    public_release._seedance_public_button_text = _priority_button_text
    public_release._public_model_meta = _priority_model_meta

    prioritized_keyboard = _prioritize_video_keyboard(
        keyboard_module.get_video_model_selection_keyboard
    )
    keyboard_module.get_video_model_selection_keyboard = prioritized_keyboard
    generation_module.get_video_model_selection_keyboard = prioritized_keyboard

    current_bootstrap = miniapp_module.miniapp_bootstrap

    @wraps(current_bootstrap)
    async def prioritized_bootstrap(request: web.Request) -> web.Response:
        response = await current_bootstrap(request)
        if response.status != 200:
            return response
        payload = fullstack._json_response_payload(response)
        if not payload:
            return response
        payload["video_models"] = _move_seedance_first(
            list(payload.get("video_models") or [])
        )
        return web.json_response(payload)

    miniapp_module.miniapp_bootstrap = prioritized_bootstrap
    generation_module._seedance_25_new_priority_installed = True
    install_seedance_25_official_contract()
