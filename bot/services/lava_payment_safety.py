from __future__ import annotations

import asyncio
import base64
import hmac
import logging
import os
from collections.abc import Iterable
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

from aiogram.exceptions import TelegramAPIError
from aiohttp import web

from bot import db as db_backend
from bot.config import config
from bot.database import (
    create_miniapp_notification,
    get_telegram_id_by_user_id,
    get_transaction_by_order,
)
from bot.services.lava_service import lava_service

logger = logging.getLogger(__name__)

_BINDINGS_TABLE = "lava_payment_bindings"
_FAILED_STATUSES = {"cancelled", "canceled", "failed", "expired"}
_PENDING_STATUSES = {"", "created", "in_progress", "pending", "processing"}
_SUCCESS_STATUSES = {"completed", "success", "succeeded", "paid"}
_DEFAULT_LAVA_WEBHOOK_IP = "158.160.60.174"
_INSTALL_MARKER = "_lava_payment_safety_installed"


async def _ensure_bindings_table() -> None:
    async with db_backend.connect() as db:
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_BINDINGS_TABLE} (
                contract_id TEXT PRIMARY KEY,
                invoice_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        try:
            await db.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{_BINDINGS_TABLE}_invoice "
                f"ON {_BINDINGS_TABLE}(invoice_id)"
            )
        except db_backend.OperationalError:
            logger.warning("Could not create unique Lava invoice binding index")
        await db.commit()


async def _save_binding(contract_id: str | None, invoice_id: str | None) -> None:
    contract = str(contract_id or "").strip()
    invoice = str(invoice_id or "").strip()
    if not contract or not invoice:
        raise ValueError("Both Lava contractId and invoiceId are required")

    await _ensure_bindings_table()
    async with db_backend.connect() as db:
        await db.execute(
            f"""
            INSERT INTO {_BINDINGS_TABLE} (contract_id, invoice_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(contract_id) DO UPDATE SET
                invoice_id = excluded.invoice_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (contract, invoice),
        )
        await db.commit()


async def _invoice_id_for_contract(contract_id: str | None) -> str | None:
    contract = str(contract_id or "").strip()
    if not contract:
        return None

    await _ensure_bindings_table()
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        row = await (
            await db.execute(
                f"SELECT invoice_id FROM {_BINDINGS_TABLE} WHERE contract_id = ? LIMIT 1",
                (contract,),
            )
        ).fetchone()
    return str(row["invoice_id"]) if row and row["invoice_id"] else None


def _extract_invoice_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("items", "content", "invoices", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for key in ("data", "result", "page"):
        value = payload.get(key)
        if isinstance(value, (dict, list)):
            items = _extract_invoice_items(value)
            if items:
                return items
    return []


def _invoice_identity(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    invoice_id = lava_service.extract_invoice_id(payload)
    contract_id = lava_service._find_first(payload, ("contractId", "contract_id"))
    return (
        str(invoice_id).strip() if invoice_id else None,
        str(contract_id).strip() if contract_id else None,
    )


def _next_page_path(response: dict[str, Any]) -> str | None:
    value = response.get("nextPage") or response.get("next_page")
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme and parsed.netloc:
        path = parsed.path or "/api/v2/invoices"
        return f"{path}?{parsed.query}" if parsed.query else path
    return value.strip()


async def _discover_invoice_id_by_contract(contract_id: str) -> str | None:
    """Backfill a legacy contractId→invoiceId mapping from the invoice list API."""

    mapped = await _invoice_id_for_contract(contract_id)
    if mapped:
        return mapped

    path = "/api/v2/invoices"
    params: dict[str, Any] | None = {"page": 0, "size": 100}
    seen_paths: set[str] = set()

    for page_index in range(10):
        response = await lava_service._request("GET", path, params=params)
        if not response.get("ok"):
            if page_index == 0 and params and params.get("page") == 0:
                params = {"page": 1, "size": 100}
                continue
            return None

        items = _extract_invoice_items(response)
        for item in items:
            invoice_id, item_contract_id = _invoice_identity(item)
            if invoice_id and item_contract_id:
                try:
                    await _save_binding(item_contract_id, invoice_id)
                except Exception:
                    logger.exception(
                        "Failed to persist Lava binding discovered from invoice list"
                    )
            if item_contract_id == contract_id and invoice_id:
                return invoice_id

        next_path = _next_page_path(response)
        if next_path:
            if next_path in seen_paths:
                break
            seen_paths.add(next_path)
            path = next_path
            params = None
            continue

        if len(items) < 100:
            break
        current_page = 1
        if params and isinstance(params.get("page"), int):
            current_page = int(params["page"])
        params = {"page": current_page + 1, "size": 100}

    return None


def _decode_basic_authorization(value: str | None) -> str | None:
    header = str(value or "").strip()
    if not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header.split(None, 1)[1], validate=True)
        return raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _configured_basic_credentials() -> str | None:
    explicit = os.getenv("LAVA_WEBHOOK_BASIC_CREDENTIALS", "").strip()
    if explicit:
        return explicit
    username = os.getenv("LAVA_WEBHOOK_BASIC_USERNAME", "").strip()
    password = os.getenv("LAVA_WEBHOOK_BASIC_PASSWORD", "").strip()
    if username and password:
        return f"{username}:{password}"
    return None


def _auth_configuration_present() -> bool:
    return bool(
        str(getattr(config, "LAVA_WEBHOOK_SECRET", "") or "").strip()
        or _configured_basic_credentials()
    )


def _verify_configured_auth(request: web.Request) -> bool:
    secret = str(getattr(config, "LAVA_WEBHOOK_SECRET", "") or "").strip()
    x_api_key = str(request.headers.get("X-Api-Key") or "").strip()
    decoded_basic = _decode_basic_authorization(request.headers.get("Authorization"))
    basic_credentials = _configured_basic_credentials()

    candidates: list[tuple[str, str]] = []
    if secret and x_api_key:
        candidates.append((secret, x_api_key))
    if secret and decoded_basic:
        candidates.append((secret, decoded_basic))
        if ":" in decoded_basic:
            candidates.append((secret, decoded_basic.split(":", 1)[1]))
    if basic_credentials and decoded_basic:
        candidates.append((basic_credentials, decoded_basic))

    return any(hmac.compare_digest(expected, actual) for expected, actual in candidates)


def _request_source_ip(request: web.Request) -> str:
    real_ip = str(request.headers.get("X-Real-IP") or "").strip()
    if real_ip:
        return real_ip
    forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    return str(request.remote or "").strip()


def _allowed_webhook_ips() -> set[str]:
    configured = os.getenv("LAVA_WEBHOOK_ALLOWED_IPS", _DEFAULT_LAVA_WEBHOOK_IP)
    return {item.strip() for item in configured.split(",") if item.strip()}


def _payload_amount_matches(transaction: Any, payload: dict[str, Any]) -> bool:
    try:
        webhook_amount = float(payload.get("amount"))
        expected_amount = float(getattr(transaction, "amount_rub", 0))
    except (TypeError, ValueError):
        return False
    currency = str(payload.get("currency") or "").strip().upper()
    return abs(webhook_amount - expected_amount) < 0.01 and currency == "RUB"


async def _lookup_lava_transaction(
    *,
    contract_id: str,
    order_id: str | None,
) -> Any | None:
    if order_id:
        transaction = await get_transaction_by_order(order_id)
        if transaction and str(getattr(transaction, "provider", "")).lower() == "lava":
            return transaction

    invoice_id = await _invoice_id_for_contract(contract_id)
    candidate_ids = [contract_id]
    if invoice_id and invoice_id not in candidate_ids:
        candidate_ids.append(invoice_id)

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        for payment_id in candidate_ids:
            row = await (
                await db.execute(
                    "SELECT order_id FROM transactions "
                    "WHERE payment_id = ? AND provider = 'lava' LIMIT 1",
                    (payment_id,),
                )
            ).fetchone()
            if row:
                return await get_transaction_by_order(str(row["order_id"]))
    return None


async def _mark_failed_if_pending(order_id: str) -> bool:
    async with db_backend.connect() as db:
        cursor = await db.execute(
            "UPDATE transactions SET status = 'failed' "
            "WHERE order_id = ? AND provider = 'lava' AND status = 'pending'",
            (order_id,),
        )
        await db.commit()
        return bool(cursor.rowcount)


async def _provider_status(
    transaction: Any,
    *,
    contract_id: str | None = None,
    retry_delays: Iterable[float] = (0.0, 0.75, 1.5),
) -> tuple[str, str | None]:
    payment_id = str(getattr(transaction, "payment_id", "") or "").strip()
    contract = str(contract_id or "").strip()

    invoice_id = await _invoice_id_for_contract(contract or payment_id)
    if not invoice_id and contract:
        invoice_id = await _discover_invoice_id_by_contract(contract)

    lookup_id = invoice_id or payment_id or contract
    if not lookup_id:
        return "", None

    last_status = ""
    for delay in retry_delays:
        if delay:
            await asyncio.sleep(delay)
        invoice = await lava_service.get_invoice(lookup_id)
        if not invoice:
            continue
        last_status = (
            lava_service.webhook_status(invoice)
            or str(invoice.get("status") or "").lower()
        )
        if last_status not in _PENDING_STATUSES:
            break
    return last_status, invoice_id


async def _notify_completed_payment(
    payments_module: ModuleType,
    request: web.Request,
    completion: dict[str, Any],
) -> None:
    transaction = completion.get("transaction")
    if not transaction:
        return
    telegram_id = completion.get("telegram_id")
    if not telegram_id:
        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
    if not telegram_id:
        logger.warning(
            "Lava payment completed but Telegram user was not resolved order=%s",
            transaction.order_id,
        )
        return

    referral_bonus = completion.get("referral_bonus") or {}
    promo_bonus = completion.get("promo_bonus") or {}
    bonus_text = payments_module._build_promo_bonus_text(
        promo_bonus
    ) + payments_module._build_bonus_text(referral_bonus)
    bot = request.app.get("bot")

    if bot:
        try:
            await payments_module._notify_user(
                bot,
                telegram_id,
                "✅ <b>Оплата успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramAPIError as exc:
            logger.warning(
                "Lava payment completed but Telegram notification failed order=%s: %s",
                transaction.order_id,
                exc,
            )

    try:
        await create_miniapp_notification(
            transaction.user_id,
            f"✅ Оплата Lava обработана — {transaction.credits} бананов "
            f"за {transaction.amount_rub} ₽",
        )
    except Exception:
        logger.exception(
            "Failed to create Lava miniapp notification order=%s",
            transaction.order_id,
        )


async def safe_handle_lava_webhook(
    request: web.Request,
    *,
    payments_module: ModuleType,
) -> web.Response:
    raw_body = await request.read()
    if not raw_body:
        return web.Response(status=400)

    try:
        import json

        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        logger.warning("Rejected Lava webhook with invalid JSON")
        return web.Response(status=400)

    event_type = lava_service.webhook_event_type(payload)
    status = lava_service.webhook_status(payload)
    if event_type not in {"payment.success", "payment.failed"}:
        logger.info(
            "Ignored Lava webhook event=%s status=%s",
            event_type or "unknown",
            status or "unknown",
        )
        return web.Response(status=200)

    source_ip = _request_source_ip(request)
    auth_configured = _auth_configuration_present()
    auth_verified = _verify_configured_auth(request) if auth_configured else False
    if auth_configured and not auth_verified:
        logger.warning(
            "Rejected Lava webhook authentication event=%s source_ip=%s",
            event_type,
            source_ip,
        )
        return web.Response(status=401)
    if not auth_configured and source_ip not in _allowed_webhook_ips():
        logger.warning(
            "Rejected unauthenticated Lava webhook from source_ip=%s event=%s",
            source_ip,
            event_type,
        )
        return web.Response(status=403)

    contract_id = lava_service.webhook_contract_id(payload)
    order_id = payments_module._extract_first(payload, ("order_id", "orderId"))
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    logger.info(
        "Lava webhook event=%s status=%s contract_id=%s product_id=%s "
        "amount=%s currency=%s source_ip=%s auth=%s",
        event_type,
        status or "unknown",
        contract_id or "",
        product.get("id") or "",
        payload.get("amount"),
        payload.get("currency") or "",
        source_ip,
        "verified" if auth_verified else "provider-verified",
    )

    if not contract_id:
        logger.warning("Rejected Lava webhook without contractId event=%s", event_type)
        return web.Response(status=400)

    transaction = await _lookup_lava_transaction(
        contract_id=contract_id,
        order_id=str(order_id) if order_id else None,
    )
    if not transaction:
        logger.warning(
            "Lava transaction not ready contract_id=%s; requesting webhook retry",
            contract_id,
        )
        return web.Response(status=503)

    if not _payload_amount_matches(transaction, payload):
        logger.error(
            "Rejected Lava webhook amount/currency mismatch order=%s contract_id=%s",
            transaction.order_id,
            contract_id,
        )
        return web.Response(status=409)

    provider_status, invoice_id = await _provider_status(
        transaction,
        contract_id=contract_id,
    )
    logger.info(
        "Lava provider verification order=%s contract_id=%s invoice_id=%s status=%s",
        transaction.order_id,
        contract_id,
        invoice_id or "",
        provider_status or "unknown",
    )

    if event_type == "payment.failed":
        if provider_status in _FAILED_STATUSES:
            changed = await _mark_failed_if_pending(transaction.order_id)
            logger.info(
                "Lava failed payment order=%s action=%s",
                transaction.order_id,
                "marked_failed" if changed else "already_final",
            )
            return web.Response(status=200)
        return web.Response(status=503)

    if provider_status not in _SUCCESS_STATUSES:
        logger.warning(
            "Lava success awaiting provider completion order=%s provider_status=%s",
            transaction.order_id,
            provider_status or "unknown",
        )
        return web.Response(status=503)

    completion = await payments_module._complete_transaction(
        transaction.order_id,
        bot=request.app.get("bot"),
    )
    if completion.get("already_completed"):
        logger.info("Lava payment already completed order=%s", transaction.order_id)
        return web.Response(status=200)
    if not completion.get("ok"):
        logger.error(
            "Lava payment completion failed order=%s reason=%s",
            transaction.order_id,
            completion.get("reason"),
        )
        return web.Response(status=503)

    await _notify_completed_payment(payments_module, request, completion)
    logger.info("Lava payment completed order=%s", transaction.order_id)
    return web.Response(status=200)


async def safe_reconcile_lava_pending_transactions(
    *,
    payments_module: ModuleType,
    limit: int = 200,
    bot: Any | None = None,
) -> list[dict[str, Any]]:
    """Reconcile pending Lava payments without blind TTL failure transitions."""

    if not lava_service.enabled:
        return []

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        rows = await (
            await db.execute(
                "SELECT order_id, payment_id FROM transactions "
                "WHERE provider = 'lava' AND status = 'pending' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        order_id = str(row["order_id"])
        payment_id = str(row["payment_id"] or "")
        item: dict[str, Any] = {
            "order_id": order_id,
            "payment_id": payment_id,
        }
        try:
            transaction = await get_transaction_by_order(order_id)
            if not transaction:
                item.update(action="error", error="transaction_not_found")
                results.append(item)
                continue

            status, invoice_id = await _provider_status(
                transaction,
                contract_id=payment_id,
                retry_delays=(0.0,),
            )
            item["status"] = status or "unknown"
            if invoice_id:
                item["invoice_id"] = invoice_id

            if status in _SUCCESS_STATUSES:
                completion = await payments_module._complete_transaction(
                    order_id,
                    bot=bot,
                )
                if completion.get("already_completed"):
                    item["action"] = "already_completed"
                elif completion.get("ok"):
                    item["action"] = "completed"
                    if bot:
                        request_like = type(
                            "ReconcileRequest",
                            (),
                            {"app": {"bot": bot}},
                        )()
                        await _notify_completed_payment(
                            payments_module,
                            request_like,
                            completion,
                        )
                else:
                    item.update(
                        action="error",
                        error=str(completion.get("reason") or "complete_failed"),
                    )
            elif status in _FAILED_STATUSES:
                changed = await _mark_failed_if_pending(order_id)
                item["action"] = "failed" if changed else "already_final"
            elif status in _PENDING_STATUSES:
                item["action"] = "still_pending"
            else:
                item.update(action="error", error="invoice_lookup_failed")
        except Exception as exc:
            logger.exception(
                "Safe Lava reconcile failed order_id=%s payment_id=%s",
                order_id,
                payment_id,
            )
            item.update(action="error", error=str(exc))
        results.append(item)

    return results


def install_lava_payment_safety(payments_module: ModuleType) -> None:
    """Install corrected callbacks before main.py imports payment functions."""

    if getattr(lava_service, _INSTALL_MARKER, False):
        return

    original_create_invoice = lava_service.create_invoice
    original_get_invoice = lava_service.get_invoice

    async def create_invoice_with_binding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        response = await original_create_invoice(*args, **kwargs)
        if not isinstance(response, dict) or not response.get("ok"):
            return response

        invoice_id = lava_service.extract_invoice_id(response)
        contract_id = lava_service.extract_contract_id(response)
        if not invoice_id or not contract_id:
            logger.error(
                "Rejected Lava invoice response without both identifiers "
                "invoice_id=%s contract_id=%s",
                bool(invoice_id),
                bool(contract_id),
            )
            return {
                **response,
                "ok": False,
                "error": "Lava did not return both invoiceId and contractId",
            }

        try:
            await _save_binding(contract_id, invoice_id)
        except Exception:
            logger.exception("Failed to persist Lava invoice binding")
            return {
                **response,
                "ok": False,
                "error": "Could not persist Lava payment identifiers",
            }
        return response

    async def get_invoice_with_binding(identifier: str) -> dict[str, Any] | None:
        raw_id = str(identifier or "").strip()
        mapped_id = await _invoice_id_for_contract(raw_id)
        if mapped_id:
            return await original_get_invoice(mapped_id)

        direct = await original_get_invoice(raw_id)
        if direct:
            return direct

        discovered_id = await _discover_invoice_id_by_contract(raw_id)
        if discovered_id:
            return await original_get_invoice(discovered_id)
        return None

    lava_service.create_invoice = create_invoice_with_binding  # type: ignore[method-assign]
    lava_service.get_invoice = get_invoice_with_binding  # type: ignore[method-assign]

    async def patched_webhook(request: web.Request) -> web.Response:
        return await safe_handle_lava_webhook(
            request,
            payments_module=payments_module,
        )

    async def patched_reconcile(
        *,
        limit: int = 200,
        bot: Any | None = None,
    ) -> list[dict[str, Any]]:
        return await safe_reconcile_lava_pending_transactions(
            payments_module=payments_module,
            limit=limit,
            bot=bot,
        )

    payments_module.handle_lava_webhook = patched_webhook
    payments_module.reconcile_lava_pending_transactions = patched_reconcile
    setattr(lava_service, _INSTALL_MARKER, True)
    logger.info("Installed reliable Lava payment safety layer")
