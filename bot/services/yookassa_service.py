from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import aiohttp

from bot import db as db_backend
from bot.config import config

logger = logging.getLogger(__name__)

FINAL_SUCCESS_STATUSES = {"succeeded"}
FINAL_FAILED_STATUSES = {"canceled"}


def normalize_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid YooKassa payment amount") from exc
    if amount <= 0:
        raise ValueError("YooKassa payment amount must be positive")
    return format(amount, ".2f")


def _idempotence_key(order_id: str) -> str:
    """Stable per local order so a network retry cannot create a second charge."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"happyfox:yookassa:{order_id}"))


class YooKassaService:
    """Async YooKassa HTTP Basic Auth client integrated with HappyFox ledger.

    Incoming notifications are never trusted on their own. Existing webhook and
    reconciliation paths call :meth:`get_payment`, which fetches the current
    object from YooKassa and then cross-checks amount/order/provider against the
    local transaction before reporting a successful status.
    """

    def __init__(self) -> None:
        self.shop_id = config.YOOKASSA_SHOP_ID.strip()
        self.secret_key = config.YOOKASSA_SECRET_KEY.strip()
        self.api_base_url = config.YOOKASSA_API_BASE_URL.rstrip("/")
        self.timeout_seconds = max(5, int(config.YOOKASSA_REQUEST_TIMEOUT_SECONDS))
        self.enabled = bool(self.shop_id and self.secret_key)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(self.shop_id, self.secret_key),
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                headers={"Accept": "application/json"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_payload: dict[str, Any] | None = None,
        idempotence_key: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if idempotence_key:
            headers["Idempotence-Key"] = idempotence_key

        session = await self._get_session()
        url = f"{self.api_base_url}/{endpoint.lstrip('/')}"
        try:
            async with session.request(
                method,
                url,
                json=json_payload,
                headers=headers,
            ) as response:
                text = await response.text()
                if response.status < 200 or response.status >= 300:
                    logger.warning(
                        "YooKassa API request failed: method=%s endpoint=%s status=%s body=%s",
                        method,
                        endpoint,
                        response.status,
                        text[:800],
                    )
                    return None
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, UnicodeError):
                    logger.warning(
                        "YooKassa API returned invalid JSON: endpoint=%s body=%s",
                        endpoint,
                        text[:500],
                    )
                    return None
                return payload if isinstance(payload, dict) else None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.exception("YooKassa API request error: endpoint=%s", endpoint)
            return None

    async def create_payment(
        self,
        amount_rub: float,
        order_id: str,
        description: str,
        return_url: str | None = None,
        notification_url: str | None = None,
    ) -> dict[str, Any] | None:
        _ = notification_url  # Basic Auth webhooks are configured in YooKassa cabinet.
        if not self.enabled:
            return {
                "Success": False,
                "Message": "YooKassa is not configured",
                "Provider": "yookassa",
            }

        order = str(order_id or "").strip()
        if not order:
            raise ValueError("order_id is required")

        effective_return_url = str(
            return_url or config.YOOKASSA_RETURN_URL or config.mini_app_url
        ).strip()
        if not effective_return_url:
            raise ValueError("YooKassa return_url is required")

        amount = normalize_amount(amount_rub)
        payload = {
            "amount": {"value": amount, "currency": "RUB"},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": effective_return_url,
            },
            "description": str(description or f"HappyFox order {order}")[:128],
            "metadata": {
                "order_id": order,
                "product": "happyfox",
            },
        }
        payment = await self._request(
            "POST",
            "payments",
            json_payload=payload,
            idempotence_key=_idempotence_key(order),
        )
        if not payment:
            return {
                "Success": False,
                "Message": "YooKassa payment creation failed",
                "Provider": "yookassa",
            }

        payment_id = str(payment.get("id") or "").strip()
        confirmation = payment.get("confirmation") or {}
        payment_url = str(
            confirmation.get("confirmation_url")
            or confirmation.get("url")
            or ""
        ).strip()
        if not payment_id or not payment_url:
            logger.warning(
                "YooKassa payment response is missing checkout data: order_id=%s",
                order,
            )
            return {
                "Success": False,
                "Message": "YooKassa did not return a payment URL",
                "Provider": "yookassa",
            }

        return {
            "Success": True,
            "PaymentId": payment_id,
            "PaymentURL": payment_url,
            "Provider": "yookassa",
            "Status": str(payment.get("status") or "pending"),
            "Raw": payment,
        }

    @staticmethod
    def extract_order_id(payment: Any) -> str | None:
        if not isinstance(payment, dict):
            return None
        metadata = payment.get("metadata") or {}
        order_id = metadata.get("order_id") if isinstance(metadata, dict) else None
        return str(order_id).strip() if order_id else None

    async def _local_transaction_for_payment(
        self,
        *,
        payment_id: str,
        order_id: str | None,
    ) -> db_backend.Row | None:
        async with db_backend.connect() as connection:
            connection.row_factory = db_backend.Row
            if order_id:
                cursor = await connection.execute(
                    "SELECT order_id, payment_id, provider, amount_rub, status "
                    "FROM transactions WHERE order_id = ? LIMIT 1",
                    (order_id,),
                )
                row = await cursor.fetchone()
                if row:
                    return row
            cursor = await connection.execute(
                "SELECT order_id, payment_id, provider, amount_rub, status "
                "FROM transactions WHERE payment_id = ? LIMIT 1",
                (payment_id,),
            )
            return await cursor.fetchone()

    async def _verify_success_against_local_ledger(
        self,
        payment: dict[str, Any],
    ) -> tuple[bool, str | None]:
        payment_id = str(payment.get("id") or "").strip()
        order_id = self.extract_order_id(payment)
        row = await self._local_transaction_for_payment(
            payment_id=payment_id,
            order_id=order_id,
        )
        if not row:
            return False, "local_transaction_not_found"
        if str(row["provider"] or "").lower() != "yookassa":
            return False, "provider_mismatch"
        local_payment_id = str(row["payment_id"] or "").strip()
        if local_payment_id and local_payment_id != payment_id:
            return False, "payment_id_mismatch"
        if order_id and str(row["order_id"]) != order_id:
            return False, "order_id_mismatch"

        remote_amount = normalize_amount(
            (payment.get("amount") or {}).get("value")
        )
        local_amount = normalize_amount(row["amount_rub"])
        if remote_amount != local_amount:
            return False, "amount_mismatch"
        if str((payment.get("amount") or {}).get("currency") or "").upper() != "RUB":
            return False, "currency_mismatch"
        return True, None

    async def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        lookup_id = str(payment_id or "").strip()
        if not lookup_id or not self.enabled:
            return None
        payment = await self._request("GET", f"payments/{lookup_id}")
        if not payment:
            return None

        status = str(payment.get("status") or "").lower()
        paid = bool(payment.get("paid")) or status in FINAL_SUCCESS_STATUSES
        verification_error: str | None = None
        if paid:
            verified, verification_error = await self._verify_success_against_local_ledger(
                payment
            )
            if not verified:
                logger.error(
                    "Refusing unverified YooKassa success: payment_id=%s reason=%s",
                    lookup_id,
                    verification_error,
                )
                status = "verification_failed"
                paid = False

        return {
            "id": str(payment.get("id") or lookup_id),
            "status": status,
            "paid": paid,
            "failed": status in FINAL_FAILED_STATUSES,
            "metadata": payment.get("metadata") or {},
            "amount": payment.get("amount") or {},
            "verification_error": verification_error,
            "Raw": payment,
        }

    async def poll_pending_transactions(
        self,
        limit: int = 100,
        complete_order: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        async with db_backend.connect() as connection:
            connection.row_factory = db_backend.Row
            cursor = await connection.execute(
                "SELECT order_id, payment_id FROM transactions "
                "WHERE provider = 'yookassa' AND status = 'pending' "
                "ORDER BY created_at ASC LIMIT ?",
                (int(limit),),
            )
            rows = await cursor.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            order_id = str(row["order_id"])
            payment_id = str(row["payment_id"] or "")
            item: dict[str, Any] = {
                "order_id": order_id,
                "payment_id": payment_id,
            }
            if not payment_id:
                item["action"] = "missing_payment_id"
                results.append(item)
                continue

            payment = await self.get_payment(payment_id)
            if not payment:
                item["action"] = "not_found"
                results.append(item)
                continue

            item["status"] = payment.get("status")
            if payment.get("paid"):
                completion = await complete_order(order_id) if complete_order else None
                item["action"] = (
                    "already_completed"
                    if completion and completion.get("already_completed")
                    else "completed"
                    if completion and completion.get("ok")
                    else "completion_failed"
                )
            elif payment.get("failed"):
                from bot.database import update_transaction_status

                await update_transaction_status(order_id, "failed")
                item["action"] = "failed"
            else:
                item["action"] = "still_pending"
            results.append(item)
        return results


yookassa_service = YooKassaService()
