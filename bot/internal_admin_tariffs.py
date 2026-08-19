from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from aiohttp import web

from bot import db as db_backend
from bot import internal_admin_api as base_api
from bot.internal_admin_user_commands import (
    CommandConflictError,
    CommandValidationError,
    _command_headers,
    _complete_command,
    _reserve_command,
    internal_user_endpoint,
)
from bot.services.preset_manager import preset_manager

_TARIFF_KEYS = (
    "currency",
    "credit_name",
    "credit_name_plural",
    "credit_emoji",
    "credit_value",
    "packages",
    "costs_reference",
    "batch_pricing",
    "partner_exchange",
    "service_prices",
)
_PUBLISH_LOCK: asyncio.Lock | None = None
_BASELINE_LOCK: asyncio.Lock | None = None


def _publish_lock() -> asyncio.Lock:
    global _PUBLISH_LOCK
    if _PUBLISH_LOCK is None:
        _PUBLISH_LOCK = asyncio.Lock()
    return _PUBLISH_LOCK


def _baseline_lock() -> asyncio.Lock:
    global _BASELINE_LOCK
    if _BASELINE_LOCK is None:
        _BASELINE_LOCK = asyncio.Lock()
    return _BASELINE_LOCK


def _service_envelope() -> dict[str, Any]:
    return base_api._service_envelope()


def _tariff_view(config: dict[str, Any]) -> dict[str, Any]:
    return {key: config[key] for key in _TARIFF_KEYS if key in config}


def _canonical_bytes(config: dict[str, Any]) -> bytes:
    return json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _checksum(config: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(config)).hexdigest()


def _read_price_config() -> dict[str, Any]:
    path = Path(preset_manager.price_path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise CommandValidationError("price.json root must be an object")
    return payload


def _require_number(value: Any, *, field: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandValidationError(f"{field} must be a number")
    number = float(value)
    if positive and number <= 0:
        raise CommandValidationError(f"{field} must be greater than zero")
    if not positive and number < 0:
        raise CommandValidationError(f"{field} cannot be negative")
    return number


def _validate_tariff_config(config: dict[str, Any]) -> None:
    currency = config.get("currency")
    if not isinstance(currency, str) or not 2 <= len(currency.strip()) <= 8:
        raise CommandValidationError("currency must be a short string")

    packages = config.get("packages")
    if not isinstance(packages, list) or not packages:
        raise CommandValidationError("packages must be a non-empty list")
    package_ids: set[str] = set()
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise CommandValidationError(f"packages[{index}] must be an object")
        package_id = str(package.get("id") or "").strip()
        if not package_id or len(package_id) > 64:
            raise CommandValidationError(f"packages[{index}].id is invalid")
        if package_id in package_ids:
            raise CommandValidationError(f"duplicate package id: {package_id}")
        package_ids.add(package_id)
        name = str(package.get("name") or "").strip()
        if not name or len(name) > 160:
            raise CommandValidationError(f"packages[{index}].name is invalid")
        _require_number(package.get("credits"), field=f"packages[{index}].credits", positive=True)
        _require_number(package.get("price_rub"), field=f"packages[{index}].price_rub", positive=True)
        _require_number(
            package.get("bonus_credits", 0),
            field=f"packages[{index}].bonus_credits",
        )
        if "price_usd" in package:
            _require_number(
                package["price_usd"],
                field=f"packages[{index}].price_usd",
                positive=True,
            )
        if "lava_offer_id" in package:
            lava_offer_id = str(package.get("lava_offer_id") or "").strip()
            if not lava_offer_id or len(lava_offer_id) > 128:
                raise CommandValidationError(
                    f"packages[{index}].lava_offer_id is invalid"
                )
        if "lava_currency" in package:
            lava_currency = str(package.get("lava_currency") or "").strip()
            if not 2 <= len(lava_currency) <= 8:
                raise CommandValidationError(
                    f"packages[{index}].lava_currency is invalid"
                )

    costs_reference = config.get("costs_reference")
    if not isinstance(costs_reference, dict):
        raise CommandValidationError("costs_reference must be an object")
    image_models = costs_reference.get("image_models")
    video_models = costs_reference.get("video_models")
    if not isinstance(image_models, dict) or not image_models:
        raise CommandValidationError("costs_reference.image_models must be non-empty")
    if not isinstance(video_models, dict) or not video_models:
        raise CommandValidationError("costs_reference.video_models must be non-empty")
    for model, cost in image_models.items():
        _require_number(cost, field=f"image_models.{model}", positive=True)
    for model, model_config in video_models.items():
        if isinstance(model_config, (int, float)) and not isinstance(model_config, bool):
            _require_number(model_config, field=f"video_models.{model}", positive=True)
            continue
        if not isinstance(model_config, dict):
            raise CommandValidationError(f"video_models.{model} must be an object")
        if "base" in model_config:
            _require_number(
                model_config["base"],
                field=f"video_models.{model}.base",
                positive=True,
            )
        for map_name in ("duration_costs", "quality_costs"):
            values = model_config.get(map_name, {})
            if not isinstance(values, dict):
                raise CommandValidationError(
                    f"video_models.{model}.{map_name} must be an object"
                )
            for option, cost in values.items():
                _require_number(
                    cost,
                    field=f"video_models.{model}.{map_name}.{option}",
                    positive=True,
                )


def _merge_tariff_view(current: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(view) - set(_TARIFF_KEYS))
    if unknown:
        raise CommandValidationError(f"unsupported tariff keys: {', '.join(unknown)}")
    merged = dict(current)
    for key in _TARIFF_KEYS:
        if key in view:
            merged[key] = view[key]
    _validate_tariff_config(merged)
    return merged


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode = path.stat().st_mode if path.exists() else None
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if original_mode is not None:
            os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


async def _insert_version(
    connection: db_backend.Connection,
    *,
    snapshot: dict[str, Any],
    reason: str,
    published_by: str | None,
    request_id: str | None,
    idempotency_key: str | None,
) -> int:
    cursor = await connection.execute(
        """
        INSERT INTO internal_admin_tariff_versions (
            checksum, snapshot, reason, published_by, request_id, idempotency_key
        ) VALUES (?, CAST(? AS JSONB), ?, ?, ?, ?)
        RETURNING id
        """,
        (
            _checksum(snapshot),
            json.dumps(snapshot, ensure_ascii=False),
            reason,
            published_by,
            request_id,
            idempotency_key,
        ),
    )
    row = await cursor.fetchone()
    if not row:
        raise RuntimeError("tariff version was not created")
    return int(row["id"])


async def _ensure_baseline_version() -> None:
    async with _baseline_lock():
        async with db_backend.connect() as connection:
            cursor = await connection.execute(
                "SELECT id FROM internal_admin_tariff_versions ORDER BY id DESC LIMIT 1"
            )
            if await cursor.fetchone():
                return
            current = _read_price_config()
            _validate_tariff_config(current)
            await _insert_version(
                connection,
                snapshot=current,
                reason="Initial data/price.json baseline",
                published_by=None,
                request_id=None,
                idempotency_key=None,
            )
            await connection.commit()


@internal_user_endpoint
async def current_tariffs_handler(request: web.Request) -> web.Response:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)
    await _ensure_baseline_version()
    current = _read_price_config()
    _validate_tariff_config(current)
    return web.json_response(
        {
            **_service_envelope(),
            "data": {
                "checksum": _checksum(current),
                "config": _tariff_view(current),
            },
        }
    )


@internal_user_endpoint
async def tariff_versions_handler(request: web.Request) -> web.Response:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)
    await _ensure_baseline_version()
    limit = base_api._parse_page_limit(request)
    cursor_id = base_api.decode_cursor(request.query.get("cursor"))
    params: list[Any] = []
    where_sql = ""
    if cursor_id is not None:
        where_sql = " WHERE id < ?"
        params.append(cursor_id)
    params.append(limit + 1)
    rows = await base_api._fetch_all(
        f"""
        SELECT id, checksum, reason, published_by, request_id, created_at,
               jsonb_array_length(COALESCE(snapshot->'packages', '[]'::jsonb)) AS package_count
        FROM internal_admin_tariff_versions
        {where_sql}
        ORDER BY id DESC
        LIMIT ?
        """,
        tuple(params),
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [
        {
            "id": int(row["id"]),
            "checksum": row["checksum"],
            "reason": row["reason"],
            "published_by": row["published_by"],
            "request_id": row["request_id"],
            "package_count": int(row["package_count"] or 0),
            "created_at": base_api._json_value(row["created_at"]),
        }
        for row in page_rows
    ]
    next_cursor = (
        base_api.encode_cursor(int(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return web.json_response(
        {**_service_envelope(), "items": items, "next_cursor": next_cursor}
    )


@internal_user_endpoint
async def tariff_version_detail_handler(request: web.Request) -> web.Response:
    raw_version_id = request.match_info.get("version_id", "")
    try:
        version_id = int(raw_version_id)
    except ValueError as exc:
        raise CommandValidationError("version id must be an integer") from exc
    rows = await base_api._fetch_all(
        """
        SELECT id, checksum, snapshot, reason, published_by, request_id, created_at
        FROM internal_admin_tariff_versions
        WHERE id = ?
        LIMIT 1
        """,
        (version_id,),
    )
    if not rows:
        raise web.HTTPNotFound(text="tariff_version_not_found")
    row = rows[0]
    snapshot = row["snapshot"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    return web.json_response(
        {
            **_service_envelope(),
            "data": {
                "id": int(row["id"]),
                "checksum": row["checksum"],
                "reason": row["reason"],
                "published_by": row["published_by"],
                "request_id": row["request_id"],
                "created_at": base_api._json_value(row["created_at"]),
                "config": _tariff_view(snapshot if isinstance(snapshot, dict) else {}),
            },
        }
    )


@internal_user_endpoint
async def publish_tariffs_handler(request: web.Request) -> web.Response:
    body = bytes(request.get("internal_body", b""))
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandValidationError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise CommandValidationError("request body must be an object")
    reason = str(payload.get("reason") or "").strip()
    if not 5 <= len(reason) <= 500:
        raise CommandValidationError("reason must contain between 5 and 500 characters")
    if payload.get("confirmation") != "PUBLISH TARIFFS":
        raise CommandConflictError("confirmation must equal PUBLISH TARIFFS")
    config_view = payload.get("config")
    if not isinstance(config_view, dict):
        raise CommandValidationError("config must be an object")
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    async with db_backend.connect() as connection:
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="tariffs.publish",
            user_id=1,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload={"reason": reason, "checksum": _checksum(config_view)},
        )
        if existing is not None:
            await connection.rollback()
            return web.json_response(existing)
        await connection.commit()

    path = Path(preset_manager.price_path)
    async with _publish_lock():
        current = _read_price_config()
        merged = _merge_tariff_view(current, config_view)
        current_checksum = _checksum(current)
        next_checksum = _checksum(merged)
        if next_checksum == current_checksum:
            response_payload = {
                **_service_envelope(),
                "data": {
                    "action": "no_change",
                    "checksum": current_checksum,
                    "config": _tariff_view(current),
                },
            }
            async with db_backend.connect() as connection:
                await _complete_command(
                    connection,
                    idempotency_key=idempotency_key,
                    response_payload=response_payload,
                )
                await connection.commit()
            return web.json_response(response_payload)

        old_bytes = path.read_bytes()
        new_bytes = json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        try:
            _atomic_write(path, new_bytes)
            if not preset_manager.reload():
                raise RuntimeError("preset manager rejected the published price file")
            async with db_backend.connect() as connection:
                version_id = await _insert_version(
                    connection,
                    snapshot=merged,
                    reason=reason,
                    published_by=admin_user_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )
                response_payload = {
                    **_service_envelope(),
                    "data": {
                        "action": "published",
                        "version_id": version_id,
                        "checksum": next_checksum,
                        "previous_checksum": current_checksum,
                        "config": _tariff_view(merged),
                    },
                }
                await _complete_command(
                    connection,
                    idempotency_key=idempotency_key,
                    response_payload=response_payload,
                )
                await connection.commit()
            return web.json_response(response_payload)
        except Exception as exc:
            _atomic_write(path, old_bytes)
            preset_manager.reload()
            failure_payload = {
                **_service_envelope(),
                "error": "tariff_publish_failed",
                "detail": str(exc)[:500],
                "_http_status": 502,
            }
            async with db_backend.connect() as connection:
                await _complete_command(
                    connection,
                    idempotency_key=idempotency_key,
                    response_payload=failure_payload,
                )
                await connection.commit()
            return web.json_response(
                {key: value for key, value in failure_payload.items() if key != "_http_status"},
                status=502,
            )
