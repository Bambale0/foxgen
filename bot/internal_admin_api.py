from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import os
import time
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from typing import Any, Awaitable, Callable

from aiohttp import web

from bot import db as db_backend

logger = logging.getLogger(__name__)

API_VERSION = "1"
CHANNEL = "telegram"
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "").strip()
INTERNAL_API_SERVICE_VERSION = os.getenv("INTERNAL_API_SERVICE_VERSION", "1.0.0").strip()
INTERNAL_API_MAX_CLOCK_SKEW_SECONDS = int(
    os.getenv("INTERNAL_API_MAX_CLOCK_SKEW_SECONDS", "60")
)
INTERNAL_API_ALLOWED_NETWORKS = os.getenv(
    "INTERNAL_API_ALLOWED_NETWORKS",
    "127.0.0.1/32,::1/128",
)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class InvalidCursorError(ValueError):
    """Raised when a pagination cursor cannot be decoded safely."""


def _service_envelope() -> dict[str, Any]:
    return {
        "channel": CHANNEL,
        "api_version": API_VERSION,
        "service_version": INTERNAL_API_SERVICE_VERSION,
    }


def _body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def build_internal_signature(
    *,
    secret: str,
    timestamp: str,
    method: str,
    request_path: str,
    body: bytes = b"",
) -> str:
    canonical = "\n".join(
        [
            timestamp,
            method.upper(),
            request_path,
            _body_hash(body),
        ]
    )
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_internal_signature(
    *,
    secret: str,
    timestamp: str,
    method: str,
    request_path: str,
    signature: str,
    body: bytes = b"",
    now: int | None = None,
    max_clock_skew_seconds: int | None = None,
) -> bool:
    if not secret or not timestamp or not signature:
        return False

    try:
        signed_at = int(timestamp)
    except (TypeError, ValueError):
        return False

    current_time = int(time.time()) if now is None else now
    max_skew = (
        INTERNAL_API_MAX_CLOCK_SKEW_SECONDS
        if max_clock_skew_seconds is None
        else max_clock_skew_seconds
    )
    if abs(current_time - signed_at) > max_skew:
        return False

    expected = build_internal_signature(
        secret=secret,
        timestamp=timestamp,
        method=method,
        request_path=request_path,
        body=body,
    )
    return hmac.compare_digest(expected, signature)


def _allowed_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw_value in INTERNAL_API_ALLOWED_NETWORKS.split(","):
        value = raw_value.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            logger.error("Ignoring invalid INTERNAL_API_ALLOWED_NETWORKS entry: %s", value)
    return tuple(networks)


def is_allowed_internal_peer(
    peer_ip: str | None,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] | None = None,
) -> bool:
    if not peer_ip:
        return False
    try:
        address = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    allowed = _allowed_networks() if networks is None else networks
    return any(address in network for network in allowed)


def encode_cursor(last_id: int) -> str:
    if last_id <= 0:
        raise InvalidCursorError("Cursor id must be positive")
    encoded = base64.urlsafe_b64encode(str(last_id).encode("ascii")).decode("ascii")
    return encoded.rstrip("=")


def decode_cursor(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    if len(value) > 128:
        raise InvalidCursorError("Cursor is too long")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("ascii")
        cursor_id = int(decoded)
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursorError("Invalid cursor") from exc
    if cursor_id <= 0:
        raise InvalidCursorError("Invalid cursor")
    return cursor_id


def _parse_page_limit(request: web.Request) -> int:
    raw_limit = request.query.get("limit", str(DEFAULT_PAGE_LIMIT))
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise web.HTTPBadRequest(text="limit must be an integer") from exc
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise web.HTTPBadRequest(text=f"limit must be between 1 and {MAX_PAGE_LIMIT}")
    return limit


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _row_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(row[key]) for key in row.keys()}


async def _fetch_one(sql: str, parameters: tuple[Any, ...] = ()) -> Mapping[str, Any]:
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(sql, parameters)
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("PostgreSQL query returned no row")
    return row


async def _fetch_all(
    sql: str,
    parameters: tuple[Any, ...] = (),
) -> list[Mapping[str, Any]]:
    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(sql, parameters)
        rows = await cursor.fetchall()
    return list(rows)


def _request_peer_ip(request: web.Request) -> str | None:
    if request.transport is not None:
        peer = request.transport.get_extra_info("peername")
        if peer:
            return str(peer[0])
    return request.remote


async def _authorize_internal_request(request: web.Request) -> web.Response | None:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)

    if not INTERNAL_API_SECRET:
        logger.error("Internal admin API rejected request: INTERNAL_API_SECRET is not configured")
        return web.json_response({"error": "service_unavailable"}, status=503)

    peer_ip = _request_peer_ip(request)
    if not is_allowed_internal_peer(peer_ip):
        logger.warning("Internal admin API rejected peer: %s", peer_ip or "unknown")
        return web.json_response({"error": "forbidden"}, status=403)

    timestamp = request.headers.get("X-Internal-Timestamp", "")
    signature = request.headers.get("X-Internal-Signature", "")
    body = await request.read()
    if not verify_internal_signature(
        secret=INTERNAL_API_SECRET,
        timestamp=timestamp,
        method=request.method,
        request_path=request.raw_path,
        signature=signature,
        body=body,
    ):
        logger.warning("Internal admin API rejected invalid HMAC from %s", peer_ip)
        return web.json_response({"error": "unauthorized"}, status=401)
    return None


def internal_endpoint(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapped(request: web.Request) -> web.StreamResponse:
        authorization_error = await _authorize_internal_request(request)
        if authorization_error is not None:
            return authorization_error
        try:
            return await handler(request)
        except InvalidCursorError:
            return web.json_response({"error": "invalid_cursor"}, status=400)
        except web.HTTPException:
            raise
        except Exception:
            logger.exception("Internal admin endpoint failed: %s", request.path)
            return web.json_response({"error": "internal_error"}, status=500)

    return wrapped


@internal_endpoint
async def health_handler(_request: web.Request) -> web.Response:
    await _fetch_one("SELECT 1 AS ok")
    return web.json_response(
        {
            "status": "ok",
            **_service_envelope(),
        }
    )


@internal_endpoint
async def summary_handler(_request: web.Request) -> web.Response:
    row = await _fetch_one(
        """
        SELECT
            (SELECT COUNT(*) FROM users) AS users_total,
            (SELECT COUNT(*) FROM users WHERE has_paid IS TRUE) AS users_paid,
            (SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE) AS users_today,
            (SELECT COALESCE(SUM(credits), 0) FROM users) AS credits_balance_total,
            (SELECT COUNT(*) FROM generation_tasks) AS generations_total,
            (SELECT COUNT(*) FROM generation_tasks WHERE created_at >= CURRENT_DATE) AS generations_today,
            (SELECT COUNT(*) FROM generation_tasks WHERE status = 'completed') AS generations_completed,
            (SELECT COUNT(*) FROM generation_tasks WHERE status = 'failed') AS generations_failed,
            (SELECT COUNT(*) FROM generation_tasks WHERE status IN ('pending', 'processing', 'submitting')) AS generations_active
        """
    )
    return web.json_response({**_service_envelope(), "data": _row_dict(row)})


async def _paginated_rows(
    *,
    request: web.Request,
    select_sql: str,
) -> tuple[list[dict[str, Any]], str | None]:
    limit = _parse_page_limit(request)
    cursor_id = decode_cursor(request.query.get("cursor"))
    parameters: tuple[Any, ...]
    if cursor_id is None:
        sql = f"{select_sql} ORDER BY id DESC LIMIT ?"
        parameters = (limit + 1,)
    else:
        sql = f"{select_sql} WHERE id < ? ORDER BY id DESC LIMIT ?"
        parameters = (cursor_id, limit + 1)

    rows = await _fetch_all(sql, parameters)
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [_row_dict(row) for row in page_rows]
    next_cursor = None
    if has_more and page_rows:
        next_cursor = encode_cursor(int(page_rows[-1]["id"]))
    return items, next_cursor


@internal_endpoint
async def users_handler(request: web.Request) -> web.Response:
    items, next_cursor = await _paginated_rows(
        request=request,
        select_sql="""
            SELECT
                id,
                telegram_id,
                username,
                first_name,
                last_name,
                credits,
                has_paid,
                is_banned,
                created_at,
                updated_at
            FROM users
        """,
    )
    for item in items:
        item["has_paid"] = bool(item.get("has_paid"))
        item["is_banned"] = bool(item.get("is_banned"))
    return web.json_response(
        {
            **_service_envelope(),
            "items": items,
            "next_cursor": next_cursor,
        }
    )


@internal_endpoint
async def generations_handler(request: web.Request) -> web.Response:
    items, next_cursor = await _paginated_rows(
        request=request,
        select_sql="""
            SELECT
                id,
                task_id,
                user_id,
                telegram_id,
                type,
                model,
                status,
                cost,
                duration,
                aspect_ratio,
                created_at,
                completed_at
            FROM generation_tasks
        """,
    )
    return web.json_response(
        {
            **_service_envelope(),
            "items": items,
            "next_cursor": next_cursor,
        }
    )


@internal_endpoint
async def finance_handler(_request: web.Request) -> web.Response:
    row = await _fetch_one(
        """
        SELECT
            COUNT(*) AS payments_total,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS payments_completed,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS payments_pending,
            SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS payments_processing,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS payments_failed,
            COALESCE(SUM(CASE WHEN status = 'completed' THEN amount_rub ELSE 0 END), 0) AS revenue_total_rub,
            COALESCE(SUM(CASE WHEN status = 'completed' AND created_at >= CURRENT_DATE THEN amount_rub ELSE 0 END), 0) AS revenue_today_rub,
            COALESCE(SUM(CASE WHEN status = 'completed' THEN credits ELSE 0 END), 0) AS credits_sold_total
        FROM transactions
        """
    )
    return web.json_response({**_service_envelope(), "data": _row_dict(row)})


def setup_internal_admin_routes(app: web.Application) -> None:
    app.router.add_get("/internal/admin/health", health_handler)
    app.router.add_get("/internal/admin/summary", summary_handler)
    app.router.add_get("/internal/admin/users", users_handler)
    app.router.add_get("/internal/admin/generations", generations_handler)
    app.router.add_get("/internal/admin/finance", finance_handler)
