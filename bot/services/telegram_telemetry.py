"""Structured Telegram update and Bot API telemetry.

The update middleware establishes one correlation context per Telegram update.
The Bot API request middleware reads that context through contextvars so
outbound Telegram methods can be attributed to the exact update/route/handler
that caused them, including calls made by child tasks spawned by the handler.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypeVar

from aiogram import BaseMiddleware, Bot
from aiogram.methods.base import TelegramMethod
from aiogram.types import Update
from aiogram.types.update import UpdateTypeLookupError

logger = logging.getLogger("bot.telemetry.telegram")

TelegramResult = TypeVar("TelegramResult")
RequestHandler = Callable[[Bot, TelegramMethod[Any]], Awaitable[TelegramResult]]

SLOW_UPDATE_MS = max(
    1.0,
    float(os.getenv("TELEGRAM_TELEMETRY_SLOW_UPDATE_MS", "750")),
)
SLOW_BOT_API_MS = max(
    1.0,
    float(os.getenv("TELEGRAM_TELEMETRY_SLOW_BOT_API_MS", "500")),
)
_MAX_ROUTE_CHARS = 160
_MAX_METHOD_SAMPLES = 12
RELEASE = str(os.getenv("HAPPYFOX_RELEASE", "unknown")).strip() or "unknown"


@dataclass
class TelegramTelemetryContext:
    update_id: int
    event_type: str
    route: str
    user_id: int | None = None
    chat_id: int | None = None
    handler_name: str = "-"
    bot_api_calls: int = 0
    bot_api_total_ms: float = 0.0
    bot_api_slowest_ms: float = 0.0
    bot_api_slowest_method: str = "-"
    bot_api_methods: list[str] = field(default_factory=list)

    def record_bot_api(self, method: str, duration_ms: float) -> None:
        self.bot_api_calls += 1
        self.bot_api_total_ms += duration_ms
        if duration_ms >= self.bot_api_slowest_ms:
            self.bot_api_slowest_ms = duration_ms
            self.bot_api_slowest_method = method
        if len(self.bot_api_methods) < _MAX_METHOD_SAMPLES:
            self.bot_api_methods.append(f"{method}:{duration_ms:.1f}")


_CURRENT_TELEGRAM_CONTEXT: ContextVar[TelegramTelemetryContext | None] = ContextVar(
    "current_telegram_telemetry_context",
    default=None,
)


def current_telegram_context() -> TelegramTelemetryContext | None:
    """Return the current update telemetry context, if called inside one."""
    return _CURRENT_TELEGRAM_CONTEXT.get()


def _clean_route(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "-"
    return text[:_MAX_ROUTE_CHARS]


def _message_route(event: Any) -> str:
    text = str(getattr(event, "text", "") or "").strip()
    if text.startswith("/"):
        command = text.split(maxsplit=1)[0]
        command = command.split("@", 1)[0].lower()
        return _clean_route(command)

    content_type = getattr(event, "content_type", None)
    raw_content_type = getattr(content_type, "value", content_type)
    return f"message:{_clean_route(raw_content_type or 'unknown')}"


def describe_update(update: Update) -> tuple[str, str, int | None, int | None]:
    """Return event type, route, user ID and chat ID without logging payloads."""
    try:
        event_type = str(update.event_type)
        event = update.event
    except UpdateTypeLookupError:
        return "unknown", "-", None, None

    route = event_type
    if event_type in {
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "business_message",
        "edited_business_message",
        "guest_message",
    }:
        route = _message_route(event)
    elif event_type == "callback_query":
        route = f"callback:{_clean_route(getattr(event, 'data', None))}"
    elif event_type == "inline_query":
        route = "inline_query"
    elif event_type == "pre_checkout_query":
        route = "pre_checkout"
    elif event_type == "shipping_query":
        route = "shipping_query"

    from_user = getattr(event, "from_user", None)
    user_id = getattr(from_user, "id", None)

    chat_id = None
    chat = getattr(event, "chat", None)
    if chat is not None:
        chat_id = getattr(chat, "id", None)
    if chat_id is None:
        message = getattr(event, "message", None)
        chat_id = getattr(getattr(message, "chat", None), "id", None)

    return (
        event_type,
        route,
        int(user_id) if user_id is not None else None,
        int(chat_id) if chat_id is not None else None,
    )


def _handler_name(data: dict[str, Any]) -> str:
    handler_object = data.get("handler")
    callback = getattr(handler_object, "callback", None)
    if callback is None:
        return "-"
    module = getattr(callback, "__module__", "")
    qualname = getattr(callback, "__qualname__", getattr(callback, "__name__", "handler"))
    return f"{module}.{qualname}" if module else str(qualname)


class TelegramUpdateTelemetryMiddleware(BaseMiddleware):
    """Measure a complete Telegram update and establish correlation context."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        event_type, route, user_id, chat_id = describe_update(event)
        context = TelegramTelemetryContext(
            update_id=int(event.update_id),
            event_type=event_type,
            route=route,
            user_id=user_id,
            chat_id=chat_id,
        )
        token = _CURRENT_TELEGRAM_CONTEXT.set(context)
        started = time.perf_counter()
        outcome = "success"
        error_type = "-"

        try:
            return await handler(event, data)
        except Exception as exc:
            outcome = "error"
            error_type = type(exc).__name__
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            sampled_methods = ",".join(context.bot_api_methods) or "-"
            if context.bot_api_calls > len(context.bot_api_methods):
                sampled_methods = (
                    f"{sampled_methods},+{context.bot_api_calls - len(context.bot_api_methods)}"
                )

            log_method = logger.warning if duration_ms >= SLOW_UPDATE_MS else logger.info
            log_method(
                "telegram_update update_id=%s event_type=%s route=%s handler=%s "
                "user_id=%s chat_id=%s duration_ms=%.1f outcome=%s error_type=%s "
                "bot_api_calls=%s bot_api_total_ms=%.1f bot_api_slowest_method=%s "
                "bot_api_slowest_ms=%.1f bot_api_methods=%s release=%s",
                context.update_id,
                context.event_type,
                context.route,
                context.handler_name,
                context.user_id if context.user_id is not None else "-",
                context.chat_id if context.chat_id is not None else "-",
                duration_ms,
                outcome,
                error_type,
                context.bot_api_calls,
                context.bot_api_total_ms,
                context.bot_api_slowest_method,
                context.bot_api_slowest_ms,
                sampled_methods,
                RELEASE,
            )
            _CURRENT_TELEGRAM_CONTEXT.reset(token)


class TelegramResolvedHandlerTelemetryMiddleware(BaseMiddleware):
    """Capture the concrete aiogram handler once routing/filtering is resolved."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        context = _CURRENT_TELEGRAM_CONTEXT.get()
        if context is not None:
            context.handler_name = _handler_name(data)
        return await handler(event, data)


async def telegram_bot_api_telemetry_middleware(
    make_request: RequestHandler[TelegramResult],
    bot: Bot,
    method: TelegramMethod[Any],
) -> TelegramResult:
    """Measure one outbound Telegram Bot API method."""
    context = _CURRENT_TELEGRAM_CONTEXT.get()
    api_method = str(getattr(method, "__api_method__", type(method).__name__))
    started = time.perf_counter()
    outcome = "success"
    error_type = "-"

    try:
        return await make_request(bot, method)
    except Exception as exc:
        outcome = "error"
        error_type = type(exc).__name__
        raise
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        if context is not None:
            context.record_bot_api(api_method, duration_ms)

        log_method = logger.warning if duration_ms >= SLOW_BOT_API_MS else logger.info
        log_method(
            "telegram_bot_api method=%s update_id=%s event_type=%s route=%s handler=%s "
            "duration_ms=%.1f outcome=%s error_type=%s release=%s",
            api_method,
            context.update_id if context is not None else "-",
            context.event_type if context is not None else "-",
            context.route if context is not None else "-",
            context.handler_name if context is not None else "-",
            duration_ms,
            outcome,
            error_type,
            RELEASE,
        )


def log_telegram_webhook_ack(
    *,
    update_id: int,
    mode: str,
    started_at: float,
) -> None:
    """Log webhook acknowledgement mode and latency for one update."""
    duration_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "telegram_webhook_ack update_id=%s mode=%s duration_ms=%.1f release=%s",
        update_id,
        mode,
        duration_ms,
        RELEASE,
    )


def install_telegram_bot_api_telemetry(bot: Bot) -> None:
    """Install the request middleware once on a Bot session."""
    session = bot.session
    marker = "_happyfox_telegram_telemetry_installed"
    if getattr(session, marker, False):
        return
    session.middleware.register(telegram_bot_api_telemetry_middleware)
    setattr(session, marker, True)
