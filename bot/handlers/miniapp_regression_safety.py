from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from functools import wraps
from typing import Any

from aiohttp import web

from bot import db as db_backend
from bot.config import config
from bot.services.lava_service import lava_service, normalize_lava_customer_email

RequestHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]

_TREND_TAGS = {"trend", "trend-video"}
_TREND_SUBMIT_PATHS = {
    "/api/v1/prompts",
}
_REQUEST_LAVA_EMAIL: ContextVar[str | None] = ContextVar(
    "miniapp_lava_customer_email",
    default=None,
)

_INSTALLED = False
_ORIGINAL_ADD_GET: Callable[..., Any] | None = None
_ORIGINAL_ADD_POST: Callable[..., Any] | None = None
_ORIGINAL_LAVA_CREATE_INVOICE: Callable[..., Awaitable[dict[str, Any]]] | None = None
_PAYMENT_EMAIL_SCHEMA_READY = False
_PAYMENT_EMAIL_SCHEMA_LOCK: asyncio.Lock | None = None


def _get_payment_email_schema_lock() -> asyncio.Lock:
    global _PAYMENT_EMAIL_SCHEMA_LOCK
    if _PAYMENT_EMAIL_SCHEMA_LOCK is None:
        _PAYMENT_EMAIL_SCHEMA_LOCK = asyncio.Lock()
    return _PAYMENT_EMAIL_SCHEMA_LOCK


async def _ensure_payment_email_schema() -> None:
    """Add the account-level payment email column on old and clean databases."""

    global _PAYMENT_EMAIL_SCHEMA_READY
    if _PAYMENT_EMAIL_SCHEMA_READY:
        return

    async with _get_payment_email_schema_lock():
        if _PAYMENT_EMAIL_SCHEMA_READY:
            return
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                # The project's PostgreSQL compatibility adapter intentionally
                # skips top-level ALTER TABLE statements. Wrap the migration in
                # a DO block so it executes on existing production databases.
                await db.execute(
                    """
                    DO $$
                    BEGIN
                        ALTER TABLE users ADD COLUMN payment_email TEXT;
                    EXCEPTION
                        WHEN duplicate_column THEN NULL;
                    END
                    $$;
                    """
                )
            else:
                try:
                    await db.execute("ALTER TABLE users ADD COLUMN payment_email TEXT")
                except db_backend.OperationalError:
                    # SQLite reports a duplicate-column error after the first run.
                    pass
            await db.commit()
        _PAYMENT_EMAIL_SCHEMA_READY = True


async def _get_saved_payment_email(telegram_id: int) -> str | None:
    await _ensure_payment_email_schema()
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT payment_email FROM users WHERE telegram_id = ? LIMIT 1",
            (int(telegram_id),),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return normalize_lava_customer_email(row["payment_email"])


async def _save_payment_email(telegram_id: int, email: str) -> str:
    normalized = normalize_lava_customer_email(email)
    if not normalized:
        raise ValueError("Invalid Lava customer email")

    await _ensure_payment_email_schema()
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE users
            SET payment_email = ?, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
            """,
            (normalized, int(telegram_id)),
        )
        await db.commit()
    return normalized


def _normalized_tags(raw_tags: Any) -> set[str]:
    if not isinstance(raw_tags, (list, tuple, set)):
        return set()
    return {
        str(tag).strip().lower()
        for tag in raw_tags
        if str(tag).strip()
    }


def _requests_trend_publication(body: dict[str, Any]) -> bool:
    return bool(_normalized_tags(body.get("tags")) & _TREND_TAGS)


def _is_lava_payment(body: dict[str, Any]) -> bool:
    return str(body.get("provider") or "").strip().lower() == "lava"


def _get_miniapp_module() -> Any:
    """Import lazily after bot.miniapp has completed initialization."""

    return importlib.import_module("bot.miniapp")


async def _secure_prompt_submit(
    original_handler: RequestHandler,
    request: web.Request,
) -> web.StreamResponse:
    miniapp_module = _get_miniapp_module()
    body = await miniapp_module._miniapp_payload(request)
    if _requests_trend_publication(body):
        try:
            telegram_id, _ctx = await miniapp_module._get_user_context(
                request.app,
                body.get("init_data", ""),
                body.get("start_param_fallback"),
            )
        except ValueError as error:
            return web.json_response(
                {"ok": False, "error": str(error) or "Telegram auth failed"},
                status=401,
            )
        if not config.is_admin(telegram_id):
            return web.json_response(
                {"ok": False, "error": "Добавлять тренды может только администратор"},
                status=403,
            )

    return await original_handler(request)


async def _secure_bootstrap(
    original_handler: RequestHandler,
    request: web.Request,
) -> web.StreamResponse:
    """Expose only the authenticated account's saved payment email."""

    response = await original_handler(request)
    if not isinstance(response, web.Response) or response.status >= 400:
        return response

    try:
        payload = json.loads(response.text)
    except (TypeError, ValueError):
        return response
    if not isinstance(payload, dict):
        return response

    try:
        telegram_id = int(payload.get("telegram_id") or 0)
    except (TypeError, ValueError):
        telegram_id = 0
    if not telegram_id:
        return response

    payload["payment_email"] = await _get_saved_payment_email(telegram_id) or ""
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
    return web.json_response(payload, status=response.status, headers=headers)


async def _secure_create_payment(
    original_handler: RequestHandler,
    request: web.Request,
) -> web.StreamResponse:
    body = await request.json()
    if not _is_lava_payment(body):
        return await original_handler(request)

    raw_customer_email = str(body.get("customer_email") or "").strip()
    submitted_email = None
    if raw_customer_email:
        submitted_email = normalize_lava_customer_email(raw_customer_email)
        if not submitted_email:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Укажите действующую почту для оплаты картой или через СБП",
                },
                status=400,
            )

    miniapp_module = _get_miniapp_module()
    payload = miniapp_module._validate_init_data(
        body.get("init_data", ""),
        config.BOT_TOKEN,
    )
    telegram_id = int(payload["user"]["id"])

    customer_email = submitted_email or await _get_saved_payment_email(telegram_id)
    if not customer_email:
        return web.json_response(
            {
                "ok": False,
                "error": "Укажите действующую почту для оплаты картой или через СБП",
            },
            status=400,
        )

    if submitted_email:
        customer_email = await _save_payment_email(telegram_id, submitted_email)

    token = _REQUEST_LAVA_EMAIL.set(customer_email)
    try:
        return await original_handler(request)
    finally:
        _REQUEST_LAVA_EMAIL.reset(token)


async def _create_invoice_with_request_email(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if _ORIGINAL_LAVA_CREATE_INVOICE is None:
        raise RuntimeError("Mini App regression safety is not installed")

    customer_email = _REQUEST_LAVA_EMAIL.get()
    if customer_email:
        if args:
            args = (customer_email, *args[1:])
        else:
            kwargs["email"] = customer_email

    return await _ORIGINAL_LAVA_CREATE_INVOICE(*args, **kwargs)


def _miniapp_api_root() -> str:
    value = str(getattr(config, "MINI_APP_PATH", "") or "/mini-app").strip()
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/") or "/mini-app"


def _is_miniapp_api_path(path: Any) -> bool:
    normalized = str(path or "")
    return normalized.startswith(f"{_miniapp_api_root()}/api/") or normalized.startswith(
        "/api/v1/"
    )


async def _banned_miniapp_response(request: web.Request) -> web.Response | None:
    """Return 403 for an authenticated banned Mini App user.

    Missing or invalid initData is deliberately left to the original route so
    existing authentication/error semantics do not change.
    """

    miniapp_module = _get_miniapp_module()
    try:
        body = await miniapp_module._miniapp_payload(request)
        init_data = str(body.get("init_data") or "")
        if not init_data:
            return None
        auth_payload = miniapp_module._validate_init_data(init_data, config.BOT_TOKEN)
        telegram_id = int(auth_payload["user"]["id"])
    except (KeyError, TypeError, ValueError):
        return None

    if config.is_admin(telegram_id):
        return None

    from bot.database import is_user_banned

    if not await is_user_banned(telegram_id):
        return None

    return web.json_response(
        {
            "ok": False,
            "error": "⛔ Доступ к сервису ограничен.",
            "code": "user_banned",
        },
        status=403,
    )


def _wrap_ban_guard(handler: RequestHandler) -> RequestHandler:
    @wraps(handler)
    async def guarded(request: web.Request) -> web.StreamResponse:
        blocked = await _banned_miniapp_response(request)
        if blocked is not None:
            return blocked
        return await handler(request)

    return guarded


def _is_trend_submit_path(path: Any) -> bool:
    normalized = str(path or "").rstrip("/")
    return normalized.endswith("/api/prompts/submit") or normalized in _TREND_SUBMIT_PATHS


def _is_bootstrap_path(path: Any) -> bool:
    return str(path or "").rstrip("/").endswith("/api/bootstrap")


def _is_payment_path(path: Any) -> bool:
    return str(path or "").rstrip("/").endswith("/api/create-payment")


def _is_partner_overview_path(path: Any) -> bool:
    return str(path or "").rstrip("/").endswith("/api/partner-overview")


def _is_action_path(path: Any) -> bool:
    return str(path or "").rstrip("/").endswith("/api/action")


async def _partner_overview_with_approval(
    original_handler: RequestHandler,
    request: web.Request,
) -> web.StreamResponse:
    response = await original_handler(request)
    if not isinstance(response, web.Response) or response.status >= 400:
        return response

    try:
        payload = json.loads(response.text)
    except (TypeError, ValueError):
        return response
    if not isinstance(payload, dict):
        return response

    miniapp_module = _get_miniapp_module()
    try:
        body = await miniapp_module._miniapp_payload(request)
        auth_payload = miniapp_module._validate_init_data(
            str(body.get("init_data") or ""),
            config.BOT_TOKEN,
        )
        telegram_id = int(auth_payload["user"]["id"])
    except (KeyError, TypeError, ValueError):
        return response

    from bot.services.partner_approval_service import get_partner_application_state

    approval = await get_partner_application_state(telegram_id)
    approval_status = str(approval.get("status") or "available")
    is_approved = bool(approval.get("is_partner"))

    payload["application_status"] = approval_status
    payload["application_id"] = approval.get("application_id")
    payload["can_apply"] = bool(approval.get("can_apply"))
    payload["is_partner"] = is_approved
    payload["status"] = "partner" if is_approved else approval_status
    if not is_approved:
        # The user's profile code still exists for profile/feed addressing, but
        # it must not be exposed as an active partner link before approval.
        payload["referral_link"] = ""
        payload["referral_bot_link"] = ""

    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
    return web.json_response(payload, status=response.status, headers=headers)


async def _partner_action_with_approval(
    original_handler: RequestHandler,
    request: web.Request,
) -> web.StreamResponse:
    miniapp_module = _get_miniapp_module()
    body = await miniapp_module._miniapp_payload(request)
    if str(body.get("action") or "").strip() != "partner_apply":
        return await original_handler(request)

    try:
        telegram_id, _ctx = await miniapp_module._get_user_context(
            request.app,
            str(body.get("init_data") or ""),
            body.get("start_param_fallback"),
        )
    except ValueError as error:
        return web.json_response(
            {"ok": False, "error": str(error) or "Telegram auth failed"},
            status=401,
        )

    from bot.services.partner_approval_service import (
        notify_admins_about_partner_application,
        submit_partner_application,
    )

    result = await submit_partner_application(
        telegram_id,
        source="miniapp",
    )
    application_id = result.get("application_id")
    if result.get("created") and application_id:
        await notify_admins_about_partner_application(
            request.app.get("bot"),
            int(application_id),
        )

    return web.json_response(
        {
            "ok": True,
            "status": result.get("status"),
            "application_id": application_id,
            "created": bool(result.get("created")),
        }
    )


def _wrap_post_handler(path: Any, handler: RequestHandler) -> RequestHandler:
    wrapped = handler

    if _is_trend_submit_path(path):
        original = wrapped

        @wraps(original)
        async def guarded_trend_submit(request: web.Request) -> web.StreamResponse:
            return await _secure_prompt_submit(original, request)

        wrapped = guarded_trend_submit

    if _is_bootstrap_path(path):
        original = wrapped

        @wraps(original)
        async def guarded_bootstrap(request: web.Request) -> web.StreamResponse:
            return await _secure_bootstrap(original, request)

        wrapped = guarded_bootstrap

    if _is_payment_path(path):
        original = wrapped

        @wraps(original)
        async def guarded_create_payment(request: web.Request) -> web.StreamResponse:
            return await _secure_create_payment(original, request)

        wrapped = guarded_create_payment

    if _is_partner_overview_path(path):
        original = wrapped

        @wraps(original)
        async def guarded_partner_overview(request: web.Request) -> web.StreamResponse:
            return await _partner_overview_with_approval(original, request)

        wrapped = guarded_partner_overview

    if _is_action_path(path):
        original = wrapped

        @wraps(original)
        async def guarded_action(request: web.Request) -> web.StreamResponse:
            return await _partner_action_with_approval(original, request)

        wrapped = guarded_action

    if _is_miniapp_api_path(path):
        wrapped = _wrap_ban_guard(wrapped)

    return wrapped


def _wrap_get_handler(path: Any, handler: RequestHandler) -> RequestHandler:
    return _wrap_ban_guard(handler) if _is_miniapp_api_path(path) else handler


def _guarded_add_get(
    dispatcher: web.UrlDispatcher,
    path: Any,
    handler: RequestHandler,
    **kwargs: Any,
) -> Any:
    if _ORIGINAL_ADD_GET is None:
        raise RuntimeError("Mini App route safety is not installed")
    return _ORIGINAL_ADD_GET(
        dispatcher,
        path,
        _wrap_get_handler(path, handler),
        **kwargs,
    )


def _guarded_add_post(
    dispatcher: web.UrlDispatcher,
    path: Any,
    handler: RequestHandler,
    **kwargs: Any,
) -> Any:
    if _ORIGINAL_ADD_POST is None:
        raise RuntimeError("Mini App route safety is not installed")
    return _ORIGINAL_ADD_POST(
        dispatcher,
        path,
        _wrap_post_handler(path, handler),
        **kwargs,
    )


def install_miniapp_regression_safety() -> None:
    """Install import-safe route guards before Mini App routes are registered."""

    global _INSTALLED
    global _ORIGINAL_ADD_GET
    global _ORIGINAL_ADD_POST
    global _ORIGINAL_LAVA_CREATE_INVOICE

    if _INSTALLED:
        return

    _ORIGINAL_ADD_GET = web.UrlDispatcher.add_get
    _ORIGINAL_ADD_POST = web.UrlDispatcher.add_post
    _ORIGINAL_LAVA_CREATE_INVOICE = lava_service.create_invoice

    web.UrlDispatcher.add_get = _guarded_add_get
    web.UrlDispatcher.add_post = _guarded_add_post
    lava_service.create_invoice = _create_invoice_with_request_email

    _INSTALLED = True
