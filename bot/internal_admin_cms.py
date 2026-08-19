from __future__ import annotations

import json
import re
from collections.abc import Mapping
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

_ALLOWED_KINDS = {"announcement", "help", "faq", "banner", "legal"}
_ALLOWED_CONTENT_KEYS = {
    "text",
    "caption",
    "button_label",
    "button_url",
    "media_file_id",
    "locale",
    "metadata",
}
_DOCUMENT_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def _service_envelope() -> dict[str, Any]:
    return base_api._service_envelope()


def _json_value(value: Any) -> Any:
    return base_api._json_value(value)


def _signed_payload(request: web.Request) -> dict[str, Any]:
    body = bytes(request.get("internal_body", b""))
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandValidationError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise CommandValidationError("request body must be an object")
    return payload


def _reason(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("reason") or "").strip()
    if not 5 <= len(value) <= 500:
        raise CommandValidationError("reason must contain between 5 and 500 characters")
    return value


def _document_id(request: web.Request) -> int:
    raw = request.match_info.get("document_id", "")
    try:
        value = int(raw)
    except ValueError as exc:
        raise CommandValidationError("document id must be an integer") from exc
    if value <= 0:
        raise CommandValidationError("document id must be positive")
    return value


def _validate_content(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        raise CommandValidationError("content nesting is too deep")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 8000:
            raise CommandValidationError("content string is too long")
        return value
    if isinstance(value, list):
        if len(value) > 50:
            raise CommandValidationError("content list is too long")
        return [_validate_content(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 50:
            raise CommandValidationError("content object is too large")
        return {
            str(key)[:80]: _validate_content(item, depth=depth + 1)
            for key, item in value.items()
        }
    raise CommandValidationError("content contains an unsupported value")


def _normalize_content(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CommandValidationError("content must be an object")
    unknown = sorted(set(value) - _ALLOWED_CONTENT_KEYS)
    if unknown:
        raise CommandValidationError(f"unsupported content keys: {', '.join(unknown)}")
    normalized = _validate_content(value)
    if not isinstance(normalized, dict):
        raise CommandValidationError("content must be an object")
    if not str(normalized.get("text") or normalized.get("caption") or "").strip():
        raise CommandValidationError("content must contain text or caption")
    button_url = normalized.get("button_url")
    if button_url and not str(button_url).startswith(("https://", "tg://")):
        raise CommandValidationError("button_url must use https:// or tg://")
    return normalized


def _document_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    content = row["published_content"] if "published_content" in row.keys() else None
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = None
    return {
        "id": int(row["id"]),
        "document_key": row["document_key"],
        "title": row["title"],
        "kind": row["kind"],
        "status": row["status"],
        "published_version_id": row["published_version_id"],
        "published_version_number": row["published_version_number"],
        "published_content": content,
        "versions_count": int(row["versions_count"] or 0),
        "created_at": _json_value(row["created_at"]),
        "updated_at": _json_value(row["updated_at"]),
    }


_DOCUMENT_SELECT = """
    SELECT
        d.id, d.document_key, d.title, d.kind, d.status,
        d.published_version_id, d.created_at, d.updated_at,
        pv.version_number AS published_version_number,
        pv.content AS published_content,
        (SELECT COUNT(*) FROM cms_document_versions v WHERE v.document_id = d.id) AS versions_count
    FROM cms_documents d
    LEFT JOIN cms_document_versions pv ON pv.id = d.published_version_id
"""


async def _fetch_document(document_id: int, *, connection: db_backend.Connection | None = None, for_update: bool = False) -> Mapping[str, Any] | None:
    suffix = " FOR UPDATE OF d" if for_update else ""
    if connection is not None:
        connection.row_factory = db_backend.Row
        cursor = await connection.execute(
            f"{_DOCUMENT_SELECT} WHERE d.id = ?{suffix}",
            (document_id,),
        )
        return await cursor.fetchone()
    rows = await base_api._fetch_all(
        f"{_DOCUMENT_SELECT} WHERE d.id = ?{suffix}",
        (document_id,),
    )
    return rows[0] if rows else None


async def _document_detail(document_id: int) -> dict[str, Any]:
    document = await _fetch_document(document_id)
    if document is None:
        raise web.HTTPNotFound(text="cms_document_not_found")
    versions = await base_api._fetch_all(
        """
        SELECT id, version_number, content, reason, created_by, created_at
        FROM cms_document_versions
        WHERE document_id = ?
        ORDER BY version_number DESC
        """,
        (document_id,),
    )
    normalized_versions = []
    for version in versions:
        content = version["content"]
        if isinstance(content, str):
            content = json.loads(content)
        normalized_versions.append(
            {
                "id": int(version["id"]),
                "version_number": int(version["version_number"]),
                "content": content,
                "reason": version["reason"],
                "created_by": version["created_by"],
                "created_at": _json_value(version["created_at"]),
            }
        )
    return {"document": _document_from_row(document), "versions": normalized_versions}


@internal_user_endpoint
async def cms_documents_handler(request: web.Request) -> web.Response:
    if request.method != "GET":
        return web.json_response({"error": "method_not_allowed"}, status=405)
    limit = base_api._parse_page_limit(request)
    cursor_id = base_api.decode_cursor(request.query.get("cursor"))
    query = (request.query.get("query") or "").strip()
    kind = (request.query.get("kind") or "").strip().lower()
    status = (request.query.get("status") or "").strip().lower()
    if kind and kind not in _ALLOWED_KINDS:
        raise CommandValidationError("unsupported CMS kind")
    if status and status not in {"draft", "published", "archived"}:
        raise CommandValidationError("unsupported CMS status")
    clauses: list[str] = []
    parameters: list[Any] = []
    if cursor_id is not None:
        clauses.append("d.id < ?")
        parameters.append(cursor_id)
    if query:
        pattern = f"%{query.lower()}%"
        clauses.append("(LOWER(d.document_key) LIKE ? OR LOWER(d.title) LIKE ?)")
        parameters.extend([pattern, pattern])
    if kind:
        clauses.append("d.kind = ?")
        parameters.append(kind)
    if status:
        clauses.append("d.status = ?")
        parameters.append(status)
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(limit + 1)
    rows = await base_api._fetch_all(
        f"{_DOCUMENT_SELECT}{where_sql} ORDER BY d.id DESC LIMIT ?",
        tuple(parameters),
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        base_api.encode_cursor(int(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return web.json_response(
        {
            **_service_envelope(),
            "items": [_document_from_row(row) for row in page_rows],
            "next_cursor": next_cursor,
        }
    )


@internal_user_endpoint
async def cms_document_detail_handler(request: web.Request) -> web.Response:
    return web.json_response(
        {**_service_envelope(), "data": await _document_detail(_document_id(request))}
    )


@internal_user_endpoint
async def save_cms_document_handler(request: web.Request) -> web.Response:
    payload = _signed_payload(request)
    document_key = str(payload.get("document_key") or "").strip().lower()
    if not _DOCUMENT_KEY.fullmatch(document_key):
        raise CommandValidationError("document_key is invalid")
    title = str(payload.get("title") or "").strip()
    if not 3 <= len(title) <= 160:
        raise CommandValidationError("title must contain between 3 and 160 characters")
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in _ALLOWED_KINDS:
        raise CommandValidationError("unsupported CMS kind")
    content = _normalize_content(payload.get("content"))
    reason = _reason(payload)
    if str(payload.get("confirmation") or "") != f"SAVE {document_key}":
        raise CommandConflictError(f"confirmation must equal SAVE {document_key}")
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="cms.save",
            user_id=1,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload={"document_key": document_key, "reason": reason},
        )
        if existing is not None:
            await connection.rollback()
            return web.json_response(existing)

        document_cursor = await connection.execute(
            """
            INSERT INTO cms_documents (document_key, title, kind, status)
            VALUES (?, ?, ?, 'draft')
            ON CONFLICT (document_key) DO UPDATE SET
                title = EXCLUDED.title,
                kind = EXCLUDED.kind,
                status = CASE
                    WHEN cms_documents.status = 'archived' THEN 'draft'
                    ELSE cms_documents.status
                END,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (document_key, title, kind),
        )
        document = await document_cursor.fetchone()
        if not document:
            raise RuntimeError("CMS document was not created")
        document_id = int(document["id"])
        version_cursor = await connection.execute(
            """
            INSERT INTO cms_document_versions (
                document_id, version_number, content, reason, created_by
            )
            SELECT ?, COALESCE(MAX(version_number), 0) + 1, CAST(? AS JSONB), ?, ?
            FROM cms_document_versions
            WHERE document_id = ?
            RETURNING id, version_number
            """,
            (
                document_id,
                json.dumps(content, ensure_ascii=False),
                reason,
                admin_user_id,
                document_id,
            ),
        )
        version = await version_cursor.fetchone()
        if not version:
            raise RuntimeError("CMS version was not created")
        response_payload = {
            **_service_envelope(),
            "data": {
                "document_id": document_id,
                "version_id": int(version["id"]),
                "version_number": int(version["version_number"]),
                "document_key": document_key,
                "status": "draft",
            },
        }
        await _complete_command(
            connection,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )
        await connection.commit()
    return web.json_response(response_payload)


@internal_user_endpoint
async def publish_cms_document_handler(request: web.Request) -> web.Response:
    document_id = _document_id(request)
    payload = _signed_payload(request)
    reason = _reason(payload)
    try:
        version_id = int(payload.get("version_id"))
    except (TypeError, ValueError) as exc:
        raise CommandValidationError("version_id must be an integer") from exc
    if str(payload.get("confirmation") or "") != f"PUBLISH {document_id}:{version_id}":
        raise CommandConflictError(
            f"confirmation must equal PUBLISH {document_id}:{version_id}"
        )
    idempotency_key, admin_user_id, request_id = _command_headers(request)

    async with db_backend.connect() as connection:
        connection.row_factory = db_backend.Row
        existing = await _reserve_command(
            connection,
            idempotency_key=idempotency_key,
            action="cms.publish",
            user_id=document_id,
            admin_user_id=admin_user_id,
            request_id=request_id,
            payload={"version_id": version_id, "reason": reason},
        )
        if existing is not None:
            await connection.rollback()
            return web.json_response(existing)
        cursor = await connection.execute(
            """
            SELECT id
            FROM cms_document_versions
            WHERE id = ? AND document_id = ?
            """,
            (version_id, document_id),
        )
        if not await cursor.fetchone():
            raise CommandValidationError("CMS version does not belong to the document")
        await connection.execute(
            """
            UPDATE cms_documents
            SET published_version_id = ?, status = 'published', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (version_id, document_id),
        )
        response_payload = {
            **_service_envelope(),
            "data": {
                "document_id": document_id,
                "published_version_id": version_id,
                "status": "published",
            },
        }
        await _complete_command(
            connection,
            idempotency_key=idempotency_key,
            response_payload=response_payload,
        )
        await connection.commit()
    return web.json_response(response_payload)


async def get_published_cms_content(document_key: str) -> dict[str, Any] | None:
    rows = await base_api._fetch_all(
        """
        SELECT v.content
        FROM cms_documents d
        JOIN cms_document_versions v ON v.id = d.published_version_id
        WHERE d.document_key = ? AND d.status = 'published'
        LIMIT 1
        """,
        (document_key,),
    )
    if not rows:
        return None
    content = rows[0]["content"]
    if isinstance(content, str):
        content = json.loads(content)
    return content if isinstance(content, dict) else None
