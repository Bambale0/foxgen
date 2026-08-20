from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from aiohttp import web

from bot.internal_admin_api import (
    InvalidCursorError,
    finance_handler,
    generations_handler,
    health_handler,
    summary_handler,
)
from bot.internal_admin_cms import (
    cms_document_detail_handler,
    cms_documents_handler,
    publish_cms_document_handler,
    save_cms_document_handler,
)
from bot.internal_admin_command_schema import ensure_internal_admin_command_schema
from bot.internal_admin_notification_actions import test_campaign_handler
from bot.internal_admin_notification_schema import ensure_internal_admin_notification_schema
from bot.internal_admin_notifications import (
    campaign_detail_handler,
    campaign_preview_handler,
    campaigns_handler,
    cancel_campaign_handler,
    start_campaign_handler,
)
from bot.internal_admin_operation_actions import replay_operation_handler
from bot.internal_admin_operation_schema import ensure_internal_admin_operation_schema
from bot.internal_admin_operations import (
    operation_detail_handler,
    operation_timeline_handler,
    operations_handler,
    refund_operation_handler,
)
from bot.internal_admin_payment_actions import (
    publish_tariffs_handler,
    recheck_payment_handler,
    reprocess_payment_handler,
)
from bot.internal_admin_payment_schema import ensure_internal_admin_payment_schema
from bot.internal_admin_payments import payment_detail_handler, payments_handler
from bot.internal_admin_support import (
    assign_ticket_handler,
    reply_ticket_handler,
    ticket_detail_handler,
    tickets_handler,
    update_ticket_handler,
)
from bot.internal_admin_support_schema import ensure_internal_admin_support_schema
from bot.internal_admin_tariffs import (
    current_tariffs_handler,
    tariff_version_detail_handler,
    tariff_versions_handler,
)
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _authorize_request,
    adjust_user_balance_handler,
    block_user_handler,
    search_users_handler,
    unblock_user_handler,
)

logger = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class _AuthenticatedBody(bytes):
    """Signed request body that is usable as bytes and JSON text."""

    def __str__(self) -> str:
        return self.decode("utf-8")


_INTERNAL_HANDLERS = {
    "/internal/admin/health": health_handler,
    "/internal/admin/summary": summary_handler,
    "/internal/admin/users": search_users_handler,
    "/internal/admin/generations": generations_handler,
    "/internal/admin/finance": finance_handler,
}
_USER_COMMAND_PATH = re.compile(
    r"^/internal/admin/users/(?P<user_id>[1-9][0-9]*)/(?P<action>block|unblock|balance-adjustments)$"
)
_USER_COMMAND_HANDLERS = {
    "block": block_user_handler,
    "unblock": unblock_user_handler,
    "balance-adjustments": adjust_user_balance_handler,
}
_OPERATION_PATH = re.compile(
    r"^/internal/admin/operations/(?P<operation_id>[1-9][0-9]*)(?:/(?P<action>timeline|replay|refund))?$"
)
_OPERATION_HANDLERS: dict[str, Handler] = {
    "list": operations_handler,
    "detail": operation_detail_handler,
    "timeline": operation_timeline_handler,
    "replay": replay_operation_handler,
    "refund": refund_operation_handler,
}
_PAYMENT_PATH = re.compile(
    r"^/internal/admin/payments/(?P<payment_id>[1-9][0-9]*)(?:/(?P<action>recheck|reprocess))?$"
)
_PAYMENT_HANDLERS: dict[str, Handler] = {
    "list": payments_handler,
    "detail": payment_detail_handler,
    "recheck": recheck_payment_handler,
    "reprocess": reprocess_payment_handler,
}
_TARIFF_VERSION_PATH = re.compile(
    r"^/internal/admin/tariffs/versions/(?P<version_id>[1-9][0-9]*)$"
)
_TICKET_PATH = re.compile(
    r"^/internal/admin/tickets/(?P<ticket_id>[1-9][0-9]*)(?:/(?P<action>assign|update|reply))?$"
)
_TICKET_HANDLERS: dict[str, Handler] = {
    "detail": ticket_detail_handler,
    "assign": assign_ticket_handler,
    "update": update_ticket_handler,
    "reply": reply_ticket_handler,
}
_CMS_DOCUMENT_PATH = re.compile(
    r"^/internal/admin/cms/documents/(?P<document_id>[1-9][0-9]*)(?:/(?P<action>publish))?$"
)
_NOTIFICATION_CAMPAIGN_PATH = re.compile(
    r"^/internal/admin/notifications/campaigns/(?P<campaign_id>[1-9][0-9]*)(?:/(?P<action>test|start|cancel))?$"
)
_NOTIFICATION_HANDLERS: dict[str, Handler] = {
    "detail": campaign_detail_handler,
    "test": test_campaign_handler,
    "start": start_campaign_handler,
    "cancel": cancel_campaign_handler,
}


async def _authenticate_and_prepare(
    request: web.Request,
    *,
    operation_schema: bool = False,
    payment_schema: bool = False,
    support_schema: bool = False,
    notification_schema: bool = False,
) -> web.Response | None:
    body, authorization_error = await _authorize_request(request)
    if authorization_error is not None:
        return authorization_error
    request["internal_body"] = _AuthenticatedBody(body)

    try:
        await ensure_internal_admin_command_schema()
        if operation_schema:
            await ensure_internal_admin_operation_schema()
        if payment_schema:
            await ensure_internal_admin_payment_schema()
        if support_schema:
            await ensure_internal_admin_support_schema()
        if notification_schema:
            await ensure_internal_admin_notification_schema()
    except Exception:
        logger.exception("Internal admin schema is unavailable")
        return web.json_response({"error": "service_unavailable"}, status=503)
    return None


async def _dispatch_authenticated(
    request: web.Request,
    handler: Handler,
    *,
    operation_schema: bool = False,
    payment_schema: bool = False,
    support_schema: bool = False,
    notification_schema: bool = False,
) -> web.StreamResponse:
    preparation_error = await _authenticate_and_prepare(
        request,
        operation_schema=operation_schema,
        payment_schema=payment_schema,
        support_schema=support_schema,
        notification_schema=notification_schema,
    )
    if preparation_error is not None:
        return preparation_error

    undecorated = getattr(handler, "__wrapped__", handler)
    try:
        return await undecorated(request)
    except InvalidCursorError:
        return web.json_response({"error": "invalid_cursor"}, status=400)
    except CommandValidationError as exc:
        return web.json_response(
            {"error": "invalid_command", "detail": str(exc)},
            status=400,
        )
    except CommandConflictError as exc:
        return web.json_response(
            {"error": "command_conflict", "detail": str(exc)},
            status=409,
        )
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Internal admin endpoint failed: %s", request.path)
        return web.json_response({"error": "internal_error"}, status=500)


async def dispatch_internal_admin_request(request: web.Request) -> web.StreamResponse:
    if request.path == "/internal/admin/operations":
        return await _dispatch_authenticated(
            request,
            _OPERATION_HANDLERS["list"],
            operation_schema=True,
        )
    if request.path == "/internal/admin/payments":
        return await _dispatch_authenticated(
            request,
            _PAYMENT_HANDLERS["list"],
            payment_schema=True,
        )
    if request.path == "/internal/admin/tariffs":
        return await _dispatch_authenticated(
            request,
            current_tariffs_handler,
            payment_schema=True,
        )
    if request.path == "/internal/admin/tariffs/versions":
        return await _dispatch_authenticated(
            request,
            tariff_versions_handler,
            payment_schema=True,
        )
    if request.path == "/internal/admin/tariffs/publish":
        return await _dispatch_authenticated(
            request,
            publish_tariffs_handler,
            payment_schema=True,
        )
    if request.path == "/internal/admin/tickets":
        return await _dispatch_authenticated(
            request,
            tickets_handler,
            support_schema=True,
        )
    if request.path == "/internal/admin/cms/documents":
        handler = save_cms_document_handler if request.method == "POST" else cms_documents_handler
        return await _dispatch_authenticated(
            request,
            handler,
            support_schema=True,
        )
    if request.path == "/internal/admin/notifications/preview":
        return await _dispatch_authenticated(
            request,
            campaign_preview_handler,
            notification_schema=True,
        )
    if request.path == "/internal/admin/notifications/campaigns":
        return await _dispatch_authenticated(
            request,
            campaigns_handler,
            notification_schema=True,
        )

    handler = _INTERNAL_HANDLERS.get(request.path)
    if handler is not None:
        return await handler(request)

    user_match = _USER_COMMAND_PATH.fullmatch(request.path)
    if user_match is not None:
        request.match_info["user_id"] = user_match.group("user_id")
        return await _dispatch_authenticated(
            request,
            _USER_COMMAND_HANDLERS[user_match.group("action")],
        )

    operation_match = _OPERATION_PATH.fullmatch(request.path)
    if operation_match is not None:
        request.match_info["operation_id"] = operation_match.group("operation_id")
        return await _dispatch_authenticated(
            request,
            _OPERATION_HANDLERS[operation_match.group("action") or "detail"],
            operation_schema=True,
        )

    payment_match = _PAYMENT_PATH.fullmatch(request.path)
    if payment_match is not None:
        request.match_info["payment_id"] = payment_match.group("payment_id")
        return await _dispatch_authenticated(
            request,
            _PAYMENT_HANDLERS[payment_match.group("action") or "detail"],
            payment_schema=True,
        )

    version_match = _TARIFF_VERSION_PATH.fullmatch(request.path)
    if version_match is not None:
        request.match_info["version_id"] = version_match.group("version_id")
        return await _dispatch_authenticated(
            request,
            tariff_version_detail_handler,
            payment_schema=True,
        )

    ticket_match = _TICKET_PATH.fullmatch(request.path)
    if ticket_match is not None:
        request.match_info["ticket_id"] = ticket_match.group("ticket_id")
        return await _dispatch_authenticated(
            request,
            _TICKET_HANDLERS[ticket_match.group("action") or "detail"],
            support_schema=True,
        )

    document_match = _CMS_DOCUMENT_PATH.fullmatch(request.path)
    if document_match is not None:
        request.match_info["document_id"] = document_match.group("document_id")
        handler = (
            publish_cms_document_handler
            if document_match.group("action") == "publish"
            else cms_document_detail_handler
        )
        return await _dispatch_authenticated(
            request,
            handler,
            support_schema=True,
        )

    notification_match = _NOTIFICATION_CAMPAIGN_PATH.fullmatch(request.path)
    if notification_match is not None:
        request.match_info["campaign_id"] = notification_match.group("campaign_id")
        return await _dispatch_authenticated(
            request,
            _NOTIFICATION_HANDLERS[notification_match.group("action") or "detail"],
            notification_schema=True,
        )

    return web.json_response({"error": "not_found"}, status=404)
