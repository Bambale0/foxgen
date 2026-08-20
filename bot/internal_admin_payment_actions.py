from __future__ import annotations

import json

from aiohttp import web

from bot import internal_admin_payments as payments
from bot import internal_admin_tariffs as tariffs
from bot.internal_admin_user_commands import CommandValidationError, internal_user_endpoint


def _validate_signed_json_object(request: web.Request) -> dict[str, object]:
    body = bytes(request.get("internal_body", b""))
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandValidationError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise CommandValidationError("request body must be an object")
    return payload


@internal_user_endpoint
async def recheck_payment_handler(request: web.Request) -> web.Response:
    _validate_signed_json_object(request)
    return await payments.recheck_payment_handler.__wrapped__(request)


@internal_user_endpoint
async def reprocess_payment_handler(request: web.Request) -> web.Response:
    _validate_signed_json_object(request)
    return await payments.reprocess_payment_handler.__wrapped__(request)


@internal_user_endpoint
async def publish_tariffs_handler(request: web.Request) -> web.Response:
    _validate_signed_json_object(request)
    response = await tariffs.publish_tariffs_handler.__wrapped__(request)
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        return response
    if isinstance(payload, dict) and "_http_status" in payload:
        response_status = int(payload.get("_http_status", 200))
        body = {key: value for key, value in payload.items() if key != "_http_status"}
        return web.json_response(body, status=response_status)
    return response
