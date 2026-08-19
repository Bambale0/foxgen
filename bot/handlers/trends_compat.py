from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    WebAppInfo,
)

from bot import database
from bot.config import config
from bot.handlers.trend_text_upload import _build_image_generation_settings
from bot.keyboards import _mini_app_url_with_start_param
from bot.utils.validators import detect_explicit_prompt_policy_violation

logger = logging.getLogger(__name__)
router = Router(name="admin_curated_trends")

TREND_TAG = "trend"
TREND_LIMIT = 80
_COMMAND_TASKS: set[asyncio.Task[Any]] = set()
_INSTALLED = False


def is_trend_prompt(prompt: dict[str, Any] | None) -> bool:
    if not prompt:
        return False
    tags = {str(item or "").strip().lower() for item in prompt.get("tags", []) or []}
    return TREND_TAG in tags


def _clean_model_label(value: Any) -> str:
    model = str(value or "banana_pro").strip()
    return model.replace("_", " ").replace("-", " ").title()


def _trend_caption(prompt: dict[str, Any], *, index: int, total: int) -> str:
    title = html.escape(str(prompt.get("title") or "Тренд"))
    description = html.escape(str(prompt.get("description") or "").strip())
    model = html.escape(_clean_model_label(prompt.get("model")))
    description_line = f"\n{description}" if description else ""
    return (
        f"🔥 <b>Тренды</b> · <code>{index + 1}/{total}</code>\n\n"
        f"<b>{title}</b>{description_line}\n\n"
        f"Нейросеть: <code>{model}</code>\n"
        "Нажмите «Повторить шаблон» — параметры и скрытый prompt уже будут подставлены."
    )


def _trend_keyboard(
    prompt: dict[str, Any],
    *,
    index: int,
    total: int,
    is_admin: bool,
) -> InlineKeyboardMarkup:
    prompt_id = int(prompt.get("id") or 0)
    prev_index = (index - 1) % total
    next_index = (index + 1) % total
    miniapp_url = _mini_app_url_with_start_param(f"prompt_{prompt_id}")

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="◀️", callback_data=f"trend_nav:{prev_index}"),
            InlineKeyboardButton(text=f"{index + 1}/{total}", callback_data="noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"trend_nav:{next_index}"),
        ]
    ]
    if miniapp_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔥 Повторить шаблон",
                    web_app=WebAppInfo(url=miniapp_url),
                )
            ]
        )
    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Убрать тренд",
                    callback_data=f"trend_remove:{prompt_id}:{index}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _get_trends() -> list[dict[str, Any]]:
    return await database.get_prompts_by_tag(TREND_TAG, TREND_LIMIT)


async def _render_trends(
    message: types.Message,
    *,
    index: int = 0,
    admin_telegram_id: int | None = None,
) -> None:
    trends = await _get_trends()
    if not trends:
        text = (
            "🔥 <b>Тренды</b>\n\n"
            "Здесь скоро появятся готовые шаблоны от команды NEUROMIX. "
            "Пользователи не могут публиковать сюда свои материалы."
        )
        if config.is_admin(admin_telegram_id):
            text += "\n\nЗагрузить первый тренд можно во вкладке «Тренды» в Mini App."
        await message.answer(text, parse_mode="HTML")
        return

    safe_index = max(0, min(index, len(trends) - 1))
    trend = trends[safe_index]
    preview_url = str(trend.get("preview_url") or "").strip()
    caption = _trend_caption(trend, index=safe_index, total=len(trends))
    markup = _trend_keyboard(
        trend,
        index=safe_index,
        total=len(trends),
        is_admin=config.is_admin(admin_telegram_id),
    )

    if preview_url and getattr(message, "photo", None):
        try:
            await message.edit_media(
                InputMediaPhoto(media=preview_url, caption=caption, parse_mode="HTML"),
                reply_markup=markup,
            )
            return
        except Exception:
            logger.debug("Unable to edit trend media", exc_info=True)

    if preview_url:
        try:
            await message.answer_photo(
                preview_url,
                caption=caption,
                reply_markup=markup,
                parse_mode="HTML",
            )
            return
        except Exception:
            logger.debug("Unable to send trend preview", exc_info=True)

    await message.answer(caption, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.in_({"menu_trends", "menu_prompts", "admin_prompts"}))
async def show_trends(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await _render_trends(
            callback.message,
            index=0,
            admin_telegram_id=callback.from_user.id if callback.from_user else None,
        )


@router.message(Command("trends"), StateFilter(None))
@router.message(Command("prompts"), StateFilter(None))
async def cmd_trends(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await _render_trends(
        message,
        index=0,
        admin_telegram_id=message.from_user.id if message.from_user else None,
    )


@router.callback_query(F.data.startswith("trend_nav:"))
async def navigate_trends(callback: types.CallbackQuery) -> None:
    index = int((callback.data or "0").split(":", 1)[1] or 0)
    await callback.answer()
    if callback.message:
        await _render_trends(
            callback.message,
            index=index,
            admin_telegram_id=callback.from_user.id if callback.from_user else None,
        )


@router.callback_query(F.data.startswith("trend_remove:"))
async def remove_trend(callback: types.CallbackQuery) -> None:
    if not callback.from_user or not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    prompt_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    prompt = await database.get_prompt_by_id(prompt_id)
    if not is_trend_prompt(prompt):
        await callback.answer("Тренд не найден", show_alert=True)
        return
    await database.deactivate_prompt(prompt_id)
    await callback.answer("Тренд убран")
    if callback.message:
        await _render_trends(
            callback.message,
            index=max(0, index - 1),
            admin_telegram_id=callback.from_user.id,
        )


def _replace_prompt_buttons(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        next_row: list[InlineKeyboardButton] = []
        for button in row:
            callback_data = str(button.callback_data or "")
            if callback_data in {"menu_prompts", "admin_prompts"}:
                next_row.append(
                    button.model_copy(
                        update={
                            "text": "🔥 Тренды",
                            "callback_data": "menu_trends",
                        }
                    )
                )
            else:
                next_row.append(button)
        rows.append(next_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _wrap_keyboard(factory: Callable[..., InlineKeyboardMarkup]) -> Callable[..., InlineKeyboardMarkup]:
    @wraps(factory)
    def wrapped(*args: Any, **kwargs: Any) -> InlineKeyboardMarkup:
        return _replace_prompt_buttons(factory(*args, **kwargs))

    return wrapped


async def _set_trend_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Текстовый бот и главное меню"),
        BotCommand(command="feed", description="Лента работ"),
        BotCommand(command="trends", description="Готовые шаблоны от NEUROMIX"),
        BotCommand(command="help", description="Помощь и возможности"),
        BotCommand(command="ref", description="Партнёрская программа"),
        BotCommand(command="earn", description="Заработок на рефералах"),
    ]
    for scope in (BotCommandScopeDefault(), BotCommandScopeAllPrivateChats()):
        for language_code in (None, "ru"):
            await bot.set_my_commands(commands, scope=scope, language_code=language_code)


async def _delayed_command_refresh(bot: Bot) -> None:
    await asyncio.sleep(2)
    try:
        await _set_trend_commands(bot)
    except Exception:
        logger.exception("Unable to register trend commands")


async def _schedule_command_refresh(bot: Bot) -> None:
    task = asyncio.create_task(_delayed_command_refresh(bot))
    _COMMAND_TASKS.add(task)
    task.add_done_callback(_COMMAND_TASKS.discard)


router.startup.register(_schedule_command_refresh)


def _install_miniapp_trends(miniapp_module: Any) -> None:
    async def miniapp_trends(request: Any):
        try:
            body = await miniapp_module._miniapp_payload(request)
            init_data = body.get("init_data", "")
            limit = miniapp_module._bounded_int(body.get("limit"), default=80, maximum=120)
            await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            trends = await database.get_prompts_by_tag(TREND_TAG, limit)
            return miniapp_module.web.json_response({"ok": True, "prompts": trends})
        except Exception as error:  # noqa: BLE001 - Mini App API boundary
            return miniapp_module._miniapp_error_response(
                error,
                log_message="Mini App trends list failed",
            )

    async def miniapp_trend_detail(request: Any):
        try:
            body = await miniapp_module._miniapp_payload(request)
            init_data = body.get("init_data", "")
            prompt_id = int(body.get("prompt_id") or 0)
            telegram_id, _ctx = await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            prompt = await database.get_prompt_by_id(prompt_id)
            is_public = bool(prompt and prompt.get("status") == "approved" and prompt.get("is_public"))
            if not is_trend_prompt(prompt) or (not is_public and not config.is_admin(telegram_id)):
                return miniapp_module.web.json_response(
                    {"ok": False, "error": "Тренд не найден"},
                    status=404,
                )
            return miniapp_module.web.json_response({"ok": True, "prompt": prompt})
        except Exception as error:  # noqa: BLE001 - Mini App API boundary
            return miniapp_module._miniapp_error_response(
                error,
                log_message="Mini App trend detail failed",
            )

    async def miniapp_trend_submit(request: Any):
        try:
            body = await miniapp_module._miniapp_payload(request)
            init_data = body.get("init_data", "")
            telegram_id, ctx = await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            if not config.is_admin(telegram_id):
                return miniapp_module.web.json_response(
                    {"ok": False, "error": "Тренды может публиковать только администратор"},
                    status=403,
                )

            title = str(body.get("title", "") or "").strip()
            prompt_text = str(body.get("prompt_text", "") or body.get("prompt", "") or "").strip()
            preview_url = str(body.get("preview_url", "") or "").strip()
            model = str(body.get("model", "") or "").strip()
            if not title or not prompt_text or not preview_url or not model:
                return miniapp_module.web.json_response(
                    {
                        "ok": False,
                        "error": "Для тренда нужны название, preview, нейросеть и prompt",
                    },
                    status=400,
                )

            policy_error = detect_explicit_prompt_policy_violation(prompt_text)
            if policy_error:
                return miniapp_module.web.json_response(
                    {"ok": False, "error": policy_error},
                    status=400,
                )

            raw_generation_settings = body.get("generation_settings")
            generation_settings = (
                dict(raw_generation_settings)
                if isinstance(raw_generation_settings, dict) and raw_generation_settings
                else _build_image_generation_settings(model)
            )

            prompt = await database.create_prompt(
                author_id=ctx["user"].id,
                prompt_text=prompt_text,
                title=title,
                description=str(body.get("description", "") or "").strip() or None,
                category="photo",
                preview_url=preview_url,
                model=model,
                tags=[TREND_TAG],
                generation_settings=generation_settings,
                is_public=True,
            )
            if prompt:
                prompt = await database.approve_prompt(prompt["id"])
            return miniapp_module.web.json_response({"ok": True, "prompt": prompt})
        except Exception as error:  # noqa: BLE001 - Mini App API boundary
            return miniapp_module._miniapp_error_response(
                error,
                log_message="Mini App trend submit failed",
            )

    async def miniapp_trend_deactivate(request: Any):
        try:
            body = await miniapp_module._miniapp_payload(request)
            init_data = body.get("init_data", "")
            prompt_id = int(body.get("prompt_id") or 0)
            telegram_id, _ctx = await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            if not config.is_admin(telegram_id):
                return miniapp_module.web.json_response(
                    {"ok": False, "error": "Нет доступа"},
                    status=403,
                )
            prompt = await database.get_prompt_by_id(prompt_id)
            if not is_trend_prompt(prompt):
                return miniapp_module.web.json_response(
                    {"ok": False, "error": "Тренд не найден"},
                    status=404,
                )
            prompt = await database.deactivate_prompt(prompt_id)
            return miniapp_module.web.json_response({"ok": True, "prompt": prompt})
        except Exception as error:  # noqa: BLE001 - Mini App API boundary
            return miniapp_module._miniapp_error_response(
                error,
                log_message="Mini App trend deactivate failed",
            )

    async def miniapp_trend_use(request: Any):
        try:
            body = await miniapp_module._miniapp_payload(request)
            init_data = body.get("init_data", "")
            prompt_id = int(body.get("prompt_id") or 0)
            _telegram_id, ctx = await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            prompt = await database.get_prompt_by_id(prompt_id, approved_public_only=True)
            if not is_trend_prompt(prompt):
                return miniapp_module.web.json_response(
                    {"ok": False, "error": "Тренд не найден"},
                    status=404,
                )
            prompt = await database.use_prompt(prompt_id, ctx["user"].id)
            return miniapp_module.web.json_response({"ok": True, "prompt": prompt})
        except Exception as error:  # noqa: BLE001 - Mini App API boundary
            return miniapp_module._miniapp_error_response(
                error,
                log_message="Mini App trend use failed",
            )

    miniapp_module.miniapp_prompts = miniapp_trends
    miniapp_module.miniapp_prompt_detail = miniapp_trend_detail
    miniapp_module.miniapp_prompt_submit = miniapp_trend_submit
    miniapp_module.miniapp_prompt_deactivate = miniapp_trend_deactivate
    miniapp_module.miniapp_prompt_use = miniapp_trend_use


def install_trends_compat(
    common_module: Any,
    generation_module: Any,
    admin_module: Any,
) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from bot import keyboards as keyboards_module

    main_factory = _wrap_keyboard(keyboards_module.get_main_menu_keyboard)
    admin_factory = _wrap_keyboard(keyboards_module.get_admin_keyboard)
    keyboards_module.get_main_menu_keyboard = main_factory
    keyboards_module.get_admin_keyboard = admin_factory
    common_module.get_main_menu_keyboard = main_factory
    generation_module.get_main_menu_keyboard = main_factory
    admin_module.get_admin_keyboard = admin_factory

    original_feed_keyboard = common_module._build_feed_keyboard

    async def build_feed_keyboard(*args: Any, **kwargs: Any) -> InlineKeyboardMarkup:
        markup = await original_feed_keyboard(*args, **kwargs)
        return _replace_prompt_buttons(markup)

    common_module._build_feed_keyboard = build_feed_keyboard

    from bot import miniapp as miniapp_module

    _install_miniapp_trends(miniapp_module)
    _INSTALLED = True
