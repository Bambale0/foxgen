from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import F, Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import database
from bot import db as db_backend

logger = logging.getLogger(__name__)
router = Router(name="feed_model_filter_compat")

DEFAULT_FEED_MODEL = "banana_pro"
_MODEL_ALIASES = {
    "banana-pro": DEFAULT_FEED_MODEL,
    "banana_pro": DEFAULT_FEED_MODEL,
    "nano-banana-pro": DEFAULT_FEED_MODEL,
    "nano_banana_pro": DEFAULT_FEED_MODEL,
    "gemini-3-pro-image-preview": DEFAULT_FEED_MODEL,
}
_MODEL_LABELS: dict[str, str] = {DEFAULT_FEED_MODEL: "Nano Banana Pro"}
_SELECTED_MODEL_BY_TELEGRAM_ID: dict[int, str] = {}
_FILTER_CACHE: dict[
    tuple[str, str, int | None, bool],
    tuple[float, list[dict[str, Any]]],
] = {}
_CACHE_TTL_SECONDS = 90.0
_INSTALLED = False
_FEED_SOURCE_CODES = {"r", "d", "t"}


def normalize_feed_model(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return DEFAULT_FEED_MODEL
    normalized = raw.replace(" ", "_")
    return _MODEL_ALIASES.get(raw, _MODEL_ALIASES.get(normalized, normalized))


def feed_model_matches(card_model: Any, selected_model: Any) -> bool:
    return normalize_feed_model(card_model) == normalize_feed_model(selected_model)


def _model_label(model_id: str) -> str:
    normalized = normalize_feed_model(model_id)
    label = _MODEL_LABELS.get(normalized)
    if label:
        return label.replace("🔥 НОВИНКА", "").strip()
    return normalized.replace("_", " ").replace("-", " ").title()


def _selected_model(telegram_id: int | None) -> str:
    if not telegram_id:
        return DEFAULT_FEED_MODEL
    return _SELECTED_MODEL_BY_TELEGRAM_ID.get(int(telegram_id), DEFAULT_FEED_MODEL)


def _set_selected_model(telegram_id: int, model_id: str) -> str:
    normalized = normalize_feed_model(model_id)
    _SELECTED_MODEL_BY_TELEGRAM_ID[int(telegram_id)] = normalized
    return normalized


def _normalize_source_code(value: Any) -> str:
    source_code = str(value or "r").strip().lower()
    return source_code if source_code in _FEED_SOURCE_CODES else "r"


def _parse_model_picker_callback(data: str | None) -> tuple[str, str, str | None]:
    parts = str(data or "").split(":", 3)
    if len(parts) < 3 or parts[0] != "bfm":
        return "", "r", None
    action = parts[1]
    source_code = _normalize_source_code(parts[2])
    model_id = normalize_feed_model(parts[3]) if len(parts) == 4 and parts[3] else None
    return action, source_code, model_id


def _build_model_picker_markup(
    *,
    source_code: str,
    selected_model: str,
    model_ids: list[str],
) -> InlineKeyboardMarkup:
    source = _normalize_source_code(source_code)
    selected = normalize_feed_model(selected_model)
    ordered: list[str] = []
    for raw_model_id in [DEFAULT_FEED_MODEL, *model_ids]:
        model_id = normalize_feed_model(raw_model_id)
        if model_id and model_id not in ordered:
            ordered.append(model_id)

    buttons = [
        InlineKeyboardButton(
            text=("✅ " if model_id == selected else "🧠 ") + _model_label(model_id),
            callback_data=f"bfm:set:{source}:{model_id}",
        )
        for model_id in ordered
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к ленте",
                callback_data=f"bfm:close:{source}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cache_key(
    source: str,
    model_id: str,
    viewer_user_id: int | None,
    include_unavailable: bool,
) -> tuple[str, str, int | None, bool]:
    normalized_viewer = int(viewer_user_id) if viewer_user_id is not None else None
    return source, model_id, normalized_viewer, bool(include_unavailable)


def _cache_get(
    source: str,
    model_id: str,
    viewer_user_id: int | None,
    include_unavailable: bool,
) -> list[dict[str, Any]] | None:
    key = _cache_key(source, model_id, viewer_user_id, include_unavailable)
    item = _FILTER_CACHE.get(key)
    if not item:
        return None
    expires_at, cards = item
    if expires_at <= time.monotonic():
        _FILTER_CACHE.pop(key, None)
        return None
    return [dict(card) for card in cards]


def _cache_put(
    source: str,
    model_id: str,
    viewer_user_id: int | None,
    include_unavailable: bool,
    cards: list[dict[str, Any]],
) -> None:
    key = _cache_key(source, model_id, viewer_user_id, include_unavailable)
    _FILTER_CACHE[key] = (
        time.monotonic() + _CACHE_TTL_SECONDS,
        [dict(card) for card in cards],
    )


def clear_feed_model_cache() -> None:
    _FILTER_CACHE.clear()


async def filter_feed_cards(
    getter: Callable[..., Awaitable[list[dict[str, Any]]]],
    *,
    model: str | None = None,
    limit: int = 0,
    offset: int = 0,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    selected = normalize_feed_model(model)
    accepted_models = sorted(
        {
            selected,
            *(
                alias
                for alias, target in _MODEL_ALIASES.items()
                if normalize_feed_model(target) == selected
            ),
        }
    )
    cards = await getter(
        limit=max(0, int(limit or 0)),
        offset=max(0, int(offset or 0)),
        models=accepted_models,
        **kwargs,
    )
    return [
        card
        for card in cards
        if feed_model_matches(card.get("model"), selected)
    ]


async def _published_model_ids() -> list[str]:
    models: list[str] = [DEFAULT_FEED_MODEL]
    try:
        async with db_backend.connect(database.DATABASE_PATH, timeout=15) as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                """
                SELECT DISTINCT COALESCE(NULLIF(model, ''), preset_id) AS model_id
                FROM generation_tasks
                WHERE type IN ('image', 'video')
                  AND status = 'completed'
                  AND result_url IS NOT NULL
                  AND is_public_feed = 1
                  AND COALESCE(is_adult_content, 0) = 0
                ORDER BY model_id
                """
            )
            rows = await cursor.fetchall()
        for row in rows:
            normalized = normalize_feed_model(row["model_id"])
            if normalized and normalized not in models:
                models.append(normalized)
    except Exception:
        logger.debug("Unable to load published feed models", exc_info=True)
    return models


def _register_model_catalog(miniapp_module: Any) -> None:
    catalogs = (
        *getattr(miniapp_module, "IMAGE_MODELS", ()),
        *getattr(miniapp_module, "VIDEO_MODELS", ()),
    )
    for item in catalogs:
        model_id = normalize_feed_model(item.get("id"))
        label = str(item.get("label") or model_id).strip()
        if model_id:
            _MODEL_LABELS[model_id] = label


async def _safe_callback_answer(
    callback: types.CallbackQuery,
    text: str | None = None,
) -> None:
    try:
        await callback.answer(text)
    except Exception:
        logger.debug("Unable to answer feed model callback", exc_info=True)


async def _render_selected_feed(
    callback: types.CallbackQuery,
    *,
    source_code: str,
) -> None:
    if not callback.from_user or not callback.message:
        return
    from bot.handlers import common as common_module

    await common_module._render_feed_by_source(
        callback.message,
        telegram_id=callback.from_user.id,
        source_code=_normalize_source_code(source_code),
        index=0,
        photo_index=0,
        replace_message=False,
    )


@router.callback_query(F.data.startswith("bfm:"))
async def select_feed_model(callback: types.CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return

    action, source_code, model_id = _parse_model_picker_callback(callback.data)
    if action == "menu":
        # Telegram callback queries expire quickly. A published-model lookup may
        # touch a busy database, so acknowledge the click before doing any I/O.
        await _safe_callback_answer(callback, "Выберите нейросеть")
        available = await _published_model_ids()
        selected = _selected_model(callback.from_user.id)
        markup = _build_model_picker_markup(
            source_code=source_code,
            selected_model=selected,
            model_ids=available,
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=markup)
        except Exception:
            logger.debug("Unable to open feed model picker", exc_info=True)
        return

    if action == "close":
        await _safe_callback_answer(callback)
        await _render_selected_feed(callback, source_code=source_code)
        return

    if action != "set" or not model_id:
        await _safe_callback_answer(callback)
        return

    await _safe_callback_answer(callback, f"Загружаю: {_model_label(model_id)}")
    available = await _published_model_ids()
    if model_id not in available:
        # The catalog can change between opening the picker and selecting an
        # item. Restore the feed instead of leaving a dead picker on screen.
        await _render_selected_feed(callback, source_code=source_code)
        return

    _set_selected_model(callback.from_user.id, model_id)
    await _render_selected_feed(callback, source_code=source_code)


def install_feed_model_filter_compat(common_module: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from bot import miniapp as miniapp_module

    _register_model_catalog(miniapp_module)

    original_get_feed_generations = database.get_feed_generations
    original_render_feed_carousel = common_module._render_feed_carousel
    original_build_feed_keyboard = common_module._build_feed_keyboard
    original_clear_feed_caches = common_module._clear_feed_caches

    async def render_feed_by_source(
        message: types.Message,
        *,
        telegram_id: int,
        source_code: str = "r",
        index: int = 0,
        photo_index: int = 0,
        replace_message: bool = False,
    ) -> None:
        user = await database.get_or_create_user(telegram_id)
        source = common_module.FEED_SOURCE_CODES.get(source_code, "recent")
        model_id = _selected_model(telegram_id)
        cards = await filter_feed_cards(
            original_get_feed_generations,
            model=model_id,
            limit=common_module.FEED_PAGE_LIMIT,
            offset=0,
            source=source,
            viewer_user_id=user.id,
            include_unavailable=True,
        )
        await original_render_feed_carousel(
            message,
            cards,
            index=index,
            photo_index=photo_index,
            source_code=source_code,
            replace_message=replace_message,
        )

    async def build_feed_keyboard(
        *args: Any,
        **kwargs: Any,
    ) -> InlineKeyboardMarkup:
        markup = await original_build_feed_keyboard(*args, **kwargs)
        if kwargs.get("profile_code"):
            return markup

        viewer_telegram_id = kwargs.get("viewer_telegram_id")
        selected = _selected_model(viewer_telegram_id)
        source_code = _normalize_source_code(kwargs.get("source_code"))
        picker_row = [
            InlineKeyboardButton(
                text=f"🧠 Модель: {_model_label(selected)}",
                callback_data=f"bfm:menu:{source_code}",
            )
        ]
        return InlineKeyboardMarkup(
            inline_keyboard=[picker_row, *markup.inline_keyboard]
        )

    def clear_caches() -> None:
        clear_feed_model_cache()
        original_clear_feed_caches()

    async def miniapp_feed(request: Any):
        try:
            body = await miniapp_module._miniapp_payload(request)
            init_data = body.get("init_data", "")
            source = str(body.get("source", "recent") or "recent")
            model_id = normalize_feed_model(
                body.get("model") or DEFAULT_FEED_MODEL
            )
            limit = miniapp_module._bounded_int(
                body.get("limit"),
                default=80,
                maximum=999999,
            )
            offset = miniapp_module._bounded_int(
                body.get("offset"),
                default=0,
                minimum=0,
                maximum=999999,
            )
            telegram_id, ctx = await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            feed = await filter_feed_cards(
                original_get_feed_generations,
                model=model_id,
                limit=limit,
                offset=offset,
                source=source,
                viewer_user_id=ctx["user"].id,
                include_unavailable=True,
            )
            is_admin = miniapp_module.config.is_admin(telegram_id)
            for item in feed:
                is_mine = bool(item.get("is_mine"))
                if is_admin:
                    item["can_remove"] = True
                if is_admin or is_mine:
                    item["can_blur"] = True
            response = miniapp_module.web.json_response(
                {
                    "ok": True,
                    "feed": feed,
                    "model": model_id,
                    "models": [
                        {"id": item, "label": _model_label(item)}
                        for item in await _published_model_ids()
                    ],
                }
            )
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            return response
        except Exception as error:  # noqa: BLE001 - API boundary converts failures to JSON
            return miniapp_module._miniapp_error_response(
                error,
                log_message="Mini App model-filtered feed failed",
            )

    common_module._render_feed_by_source = render_feed_by_source
    common_module._build_feed_keyboard = build_feed_keyboard
    common_module._clear_feed_caches = clear_caches
    miniapp_module.miniapp_feed = miniapp_feed
    _INSTALLED = True
