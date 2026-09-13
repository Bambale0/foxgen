"""Low-latency Telegram callback acknowledgement.

Selected callbacks are acknowledged as soon as access checks pass. Existing
legacy handlers may still answer the callback later; a Bot session middleware
reuses the already-started request instead of issuing a duplicate.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, TypeVar

from aiogram import BaseMiddleware, Bot, types
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import AnswerCallbackQuery
from aiogram.methods.base import TelegramMethod

from bot.config import config

logger = logging.getLogger(__name__)

TelegramResult = TypeVar("TelegramResult")
RequestHandler = Callable[[Bot, TelegramMethod[Any]], Awaitable[TelegramResult]]

_SAFE_CALLBACK_DATA = {
    "back_main",
    "menu_balance",
    "create_image_text_new",
    "model_nanobanana",
    "model_banana_pro",
    "model_banana_2",
    "model_nano_banana_2_lite",
    "model_seedream_edit",
    "model_seedream_5_pro",
    "model_grok_i2i",
    "img_ratio_auto",
    "img_ratio_1_1",
    "img_ratio_16_9",
    "img_ratio_9_16",
    "img_ratio_4_3",
    "img_ratio_4_5",
    "img_ratio_5_4",
    "img_ratio_3_2",
    "img_ratio_2_3",
    "img_ratio_3_4",
    "img_ratio_21_9",
}
_SAFE_ADMIN_CALLBACK_DATA = {
    "admin_ai_help",
    "admin_stats",
    "admin_users",
}
_CONDITIONAL_CALLBACK_DATA = {"img_ref_continue_new"}


@dataclass
class _EarlyAckState:
    callback_query_id: str
    task: asyncio.Task[Any] | None = None


_EARLY_ACK_STATE: ContextVar[_EarlyAckState | None] = ContextVar(
    "early_callback_ack_state",
    default=None,
)
_EARLY_ACK_BYPASS: ContextVar[bool] = ContextVar(
    "early_callback_ack_bypass",
    default=False,
)


def _is_plain_answer(method: AnswerCallbackQuery) -> bool:
    return (
        not method.text
        and not method.show_alert
        and not method.url
        and not method.cache_time
    )


async def _should_ack_early(
    callback: types.CallbackQuery,
    data: dict[str, Any],
) -> bool:
    callback_data = str(callback.data or "")

    if callback_data in _SAFE_CALLBACK_DATA:
        return True

    if callback_data in _SAFE_ADMIN_CALLBACK_DATA:
        user = callback.from_user
        return bool(user and config.is_admin(user.id))

    if callback_data not in _CONDITIONAL_CALLBACK_DATA:
        return False

    state = data.get("state")
    if state is None:
        return False

    try:
        state_data = await state.get_data()
    except Exception:
        logger.debug(
            "Unable to inspect FSM state for early callback ACK",
            exc_info=True,
        )
        return False

    if state_data.get("repeat_source_task_id"):
        return False

    generation_type = state_data.get("generation_type")
    current_service = state_data.get("img_service", "banana_pro")
    reference_images = state_data.get("reference_images") or []

    return not (
        generation_type == "image"
        and current_service == "seedream_edit"
        and not reference_images
    )


async def _send_early_ack(callback: types.CallbackQuery) -> Any:
    token = _EARLY_ACK_BYPASS.set(True)
    try:
        return await callback.answer()
    finally:
        _EARLY_ACK_BYPASS.reset(token)


class EarlyCallbackAckMiddleware(BaseMiddleware):
    """Start a safe plain ACK before the legacy handler performs UI work."""

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, types.CallbackQuery):
            return await handler(event, data)
        if not await _should_ack_early(event, data):
            return await handler(event, data)

        state = _EarlyAckState(callback_query_id=event.id)
        token = _EARLY_ACK_STATE.set(state)
        state.task = asyncio.create_task(
            _send_early_ack(event),
            name=f"early-callback-ack:{event.id}",
        )
        try:
            return await handler(event, data)
        finally:
            try:
                await asyncio.shield(state.task)
            except TelegramAPIError as exc:
                logger.info(
                    "Early callback ACK failed: callback_id=%s error=%s",
                    event.id,
                    exc,
                )
            finally:
                _EARLY_ACK_STATE.reset(token)


async def early_callback_ack_session_middleware(
    make_request: RequestHandler[TelegramResult],
    bot: Bot,
    method: TelegramMethod[Any],
) -> TelegramResult:
    """Reuse an in-flight early ACK when a legacy handler answers later."""

    if (
        isinstance(method, AnswerCallbackQuery)
        and not _EARLY_ACK_BYPASS.get()
        and _is_plain_answer(method)
    ):
        state = _EARLY_ACK_STATE.get()
        if (
            state is not None
            and state.task is not None
            and state.callback_query_id == method.callback_query_id
        ):
            try:
                return await asyncio.shield(state.task)
            except TelegramAPIError:
                logger.info(
                    "Retrying callback ACK through normal request path: callback_id=%s",
                    method.callback_query_id,
                )

    return await make_request(bot, method)


def install_early_callback_ack_session_middleware(bot: Bot) -> None:
    """Install duplicate-ACK reuse before general request telemetry."""

    session = bot.session
    marker = "_happyfox_early_callback_ack_installed"
    if getattr(session, marker, False):
        return
    session.middleware.register(early_callback_ack_session_middleware)
    setattr(session, marker, True)
