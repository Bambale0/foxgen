import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode

from aiohttp import web

from bot.config import config
from bot.trend_api import setup_trend_routes
from bot.trend_task_privacy import sanitize_task_api_payload
from bot.trend_visibility import (
    sanitize_prompt_api_payload,
    verified_telegram_id_from_init_data,
)

_LOGIN_MAX_AGE_SECONDS = 10 * 60
_BROWSER_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60
_ALLOWED_LOGIN_FIELDS = {
    "id",
    "first_name",
    "last_name",
    "username",
    "photo_url",
    "auth_date",
}


def _normalized_login_payload(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise TypeError("Invalid Telegram login payload")

    payload: dict[str, str] = {}
    for key in _ALLOWED_LOGIN_FIELDS | {"hash"}:
        value = raw.get(key)
        if value is not None:
            payload[key] = str(value)
    return payload


def _verify_telegram_login(raw: Any, bot_token: str) -> dict[str, Any]:
    payload = _normalized_login_payload(raw)
    received_hash = payload.pop("hash", "")
    if not received_hash:
        raise ValueError("Missing Telegram login hash")

    try:
        auth_date = int(payload.get("auth_date", "0"))
        telegram_id = int(payload.get("id", "0"))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid Telegram login payload") from error

    now = int(time.time())
    if telegram_id <= 0 or auth_date <= 0:
        raise ValueError("Invalid Telegram login payload")
    if auth_date > now + 60 or now - auth_date > _LOGIN_MAX_AGE_SECONDS:
        raise ValueError("Expired Telegram login")

    data_check_string = "\n".join(
        f"{key}={payload[key]}" for key in sorted(payload) if key in _ALLOWED_LOGIN_FIELDS
    )
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Invalid Telegram login signature")

    return {
        "id": telegram_id,
        "first_name": payload.get("first_name", ""),
        "last_name": payload.get("last_name", ""),
        "username": payload.get("username", ""),
        "photo_url": payload.get("photo_url", ""),
        "language_code": "ru",
    }


def _build_browser_init_data(user: dict[str, Any], bot_token: str) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": f"browser_{secrets.token_urlsafe(18)}",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    fields["hash"] = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(fields)


async def browser_telegram_auth_config(request: web.Request) -> web.Response:
    try:
        bot = request.app["bot"]
        me = await bot.get_me()
        response = web.json_response(
            {
                "ok": True,
                "bot_username": str(me.username or "").lstrip("@"),
            }
        )
        response.headers["Cache-Control"] = "public, max-age=300"
        return response
    except Exception:  # noqa: BLE001 - transport failures must become a stable 503 response
        return web.json_response(
            {"ok": False, "error": "Telegram login is unavailable"},
            status=503,
            headers={"Cache-Control": "no-store"},
        )


async def browser_telegram_auth(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        telegram_auth = body.get("telegram_auth", body)
        user = _verify_telegram_login(telegram_auth, config.BOT_TOKEN)
        init_data = _build_browser_init_data(user, config.BOT_TOKEN)
        response = web.json_response(
            {
                "ok": True,
                "init_data": init_data,
                "expires_in": _BROWSER_SESSION_MAX_AGE_SECONDS,
            }
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        return web.json_response(
            {"ok": False, "error": str(error)},
            status=401,
            headers={"Cache-Control": "no-store"},
        )
    except Exception:  # noqa: BLE001 - unexpected auth failures must not leak internals
        return web.json_response(
            {"ok": False, "error": "Telegram login failed"},
            status=500,
            headers={"Cache-Control": "no-store"},
        )


@web.middleware
async def trend_prompt_privacy_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    """Keep curated trend recipes out of shared links, task details and history.

    The handler consumes and validates Mini App initData first. Privacy filtering
    happens only after a successful endpoint response, so request-body parsing
    cannot interfere with the catch-all Mini App handler.
    """

    miniapp_root = str(request.app.get("trend_prompt_privacy_root") or "")
    prompt_api_root = f"{miniapp_root}/api/prompts"
    task_detail_path = f"{miniapp_root}/api/task-detail"
    bootstrap_path = f"{miniapp_root}/api/bootstrap"
    is_prompt_api = bool(miniapp_root) and (
        request.path == prompt_api_root or request.path.startswith(prompt_api_root + "/")
    )
    is_task_api = bool(miniapp_root) and request.path in {
        task_detail_path,
        bootstrap_path,
    }
    if not is_prompt_api and not is_task_api:
        return await handler(request)

    response = await handler(request)
    response.headers["Cache-Control"] = "no-store"

    if response.status >= 400 or not isinstance(response, web.Response):
        return response
    if response.content_type != "application/json" or not response.body:
        return response

    request_body: dict[str, Any] = {}
    viewer_is_admin = False
    signed_start_param = ""
    try:
        raw_body = await request.json()
        request_body = raw_body if isinstance(raw_body, dict) else {}
        init_data = str(request_body.get("init_data") or "")
        telegram_id = verified_telegram_id_from_init_data(init_data, config.BOT_TOKEN)
        viewer_is_admin = bool(telegram_id and config.is_admin(telegram_id))
        if telegram_id:
            signed_start_param = str(
                dict(parse_qsl(init_data, keep_blank_values=True)).get("start_param") or ""
            ).strip()
    except Exception:  # noqa: BLE001 - privacy middleware must fail closed
        viewer_is_admin = False
        signed_start_param = ""

    try:
        payload = json.loads(response.body.decode(response.charset or "utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return response

    if is_prompt_api:
        start_param = str(
            request_body.get("start_param_fallback") or signed_start_param or ""
        ).strip()
        shared_prompt_detail = (
            request.path == f"{prompt_api_root}/detail"
            and start_param.startswith("prompt_")
        )
        if not viewer_is_admin or shared_prompt_detail:
            payload = sanitize_prompt_api_payload(payload)

    if is_task_api:
        payload = await sanitize_task_api_payload(payload)

    response.body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return response


def setup_browser_auth_routes(app: web.Application) -> None:
    miniapp_path = config.MINI_APP_PATH or "/mini-app"
    if not miniapp_path.startswith("/"):
        miniapp_path = f"/{miniapp_path}"
    miniapp_root = miniapp_path.rstrip("/")

    # Install before setup_miniapp_routes freezes the application. The prompt
    # endpoints themselves still perform the authoritative initData checks.
    app["trend_prompt_privacy_root"] = miniapp_root
    if not app.get("trend_prompt_privacy_middleware_installed"):
        app.middlewares.append(trend_prompt_privacy_middleware)
        app["trend_prompt_privacy_middleware_installed"] = True

    # Exact routes must be registered before setup_miniapp_routes adds its
    # catch-all /mini-app/api/{tail:.*} handler.
    setup_trend_routes(app, miniapp_root)
    app.router.add_get(
        miniapp_root + "/api/browser-auth/config",
        browser_telegram_auth_config,
    )
    app.router.add_post(miniapp_root + "/api/browser-auth", browser_telegram_auth)
