from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import aiohttp

from bot import db as db_backend

logger = logging.getLogger(__name__)

FREEKASSA_PAID_STATUS = 1
FREEKASSA_FAILED_STATUSES = {6, 8, 9}
FREEKASSA_CARD_RUB_METHOD_ID = 36
FREEKASSA_SBP_METHOD_ID = 44
FREEKASSA_CHECKOUT_METHOD_IDS = {
    FREEKASSA_CARD_RUB_METHOD_ID,
    FREEKASSA_SBP_METHOD_ID,
}
DEFAULT_ALLOWED_WEBHOOK_IPS = {
    "168.119.157.136",
    "168.119.60.227",
    "178.154.197.79",
    "51.250.54.238",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_amount(value: Any) -> str:
    """Return a stable two-decimal amount used in signatures and DB checks."""
    try:
        amount = Decimal(str(value)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid payment amount") from exc
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    return format(amount, ".2f")


def build_sci_signature(
    merchant_id: str,
    amount: Any,
    secret_word: str,
    currency: str,
    order_id: str,
) -> str:
    amount_text = normalize_amount(amount)
    source = f"{merchant_id}:{amount_text}:{secret_word}:{currency}:{order_id}"
    return hashlib.md5(
        source.encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def build_notification_signature(
    merchant_id: str,
    raw_amount: str,
    secret_word_2: str,
    order_id: str,
) -> str:
    source = f"{merchant_id}:{raw_amount}:{secret_word_2}:{order_id}"
    return hashlib.md5(
        source.encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def build_api_signature(payload: dict[str, Any], api_key: str) -> str:
    values = [str(payload[key]) for key in sorted(payload) if key != "signature"]
    message = "|".join(values).encode("utf-8")
    return hmac.new(api_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def normalize_order_status(value: Any) -> dict[str, Any]:
    try:
        status = int(value)
    except (TypeError, ValueError):
        status = -1
    return {
        "status_code": status,
        "status": {
            0: "new",
            1: "paid",
            6: "refunded",
            8: "error",
            9: "cancelled",
        }.get(status, "unknown"),
        "paid": status == FREEKASSA_PAID_STATUS,
        "failed": status in FREEKASSA_FAILED_STATUSES,
    }


class FreeKassaService:
    """FreeKassa SCI checkout with optional API reconciliation."""

    def __init__(self) -> None:
        self.merchant_id = os.getenv("FREEKASSA_MERCHANT_ID", "").strip()
        self.secret_word = os.getenv("FREEKASSA_SECRET_WORD", "").strip()
        self.secret_word_2 = os.getenv("FREEKASSA_SECRET_WORD_2", "").strip()
        self.api_key = os.getenv("FREEKASSA_API_KEY", "").strip()
        self.currency = (
            os.getenv("FREEKASSA_CURRENCY", "RUB").strip().upper() or "RUB"
        )
        self.language = (
            os.getenv("FREEKASSA_LANGUAGE", "ru").strip().lower() or "ru"
        )
        self.pay_base_url = os.getenv(
            "FREEKASSA_PAY_BASE_URL", "https://pay.fk.money/"
        ).strip()
        self.api_base_url = (
            os.getenv("FREEKASSA_API_BASE_URL", "https://api.fk.life/v1")
            .strip()
            .rstrip("/")
        )
        self.webhook_path = (
            os.getenv("FREEKASSA_WEBHOOK_PATH", "/freekassa/webhook").strip()
            or "/freekassa/webhook"
        )
        if not self.webhook_path.startswith("/"):
            self.webhook_path = f"/{self.webhook_path}"

        self.verify_webhook_ip = _env_bool("FREEKASSA_VERIFY_IP", True)
        configured_ips = {
            item.strip()
            for item in os.getenv("FREEKASSA_ALLOWED_IPS", "").split(",")
            if item.strip()
        }
        self.allowed_webhook_ips = configured_ips or set(
            DEFAULT_ALLOWED_WEBHOOK_IPS
        )
        self.enabled = bool(
            self.merchant_id and self.secret_word and self.secret_word_2
        )
        self.api_enabled = bool(self.enabled and self.api_key)

        self._session: aiohttp.ClientSession | None = None
        self._nonce_lock = asyncio.Lock()
        self._last_nonce = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _next_nonce(self) -> int:
        async with self._nonce_lock:
            current = int(time.time() * 1000)
            self._last_nonce = max(current, self._last_nonce + 1)
            return self._last_nonce

    def create_payment_url(
        self,
        *,
        amount_rub: Any,
        order_id: str,
        email: str | None = None,
        phone: str | None = None,
        payment_system_id: int | None = None,
        custom_params: dict[str, str] | None = None,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("FreeKassa is not configured")

        amount = normalize_amount(amount_rub)
        order = str(order_id or "").strip()
        if not order:
            raise ValueError("order_id is required")

        params: dict[str, str] = {
            "m": self.merchant_id,
            "oa": amount,
            "currency": self.currency,
            "o": order,
            "s": build_sci_signature(
                self.merchant_id,
                amount,
                self.secret_word,
                self.currency,
                order,
            ),
            "lang": self.language,
        }
        if email:
            params["em"] = str(email).strip()
        if phone:
            params["phone"] = str(phone).strip()
        if payment_system_id is not None:
            normalized_method_id = int(payment_system_id)
            if normalized_method_id not in FREEKASSA_CHECKOUT_METHOD_IDS:
                raise ValueError("Unsupported FreeKassa payment method")
            params["i"] = str(normalized_method_id)

        for key, value in (custom_params or {}).items():
            key_text = str(key).strip()
            value_text = str(value).strip()
            if key_text.startswith("us_") and value_text:
                params[key_text] = value_text

        separator = "&" if "?" in self.pay_base_url else "?"
        return f"{self.pay_base_url}{separator}{urlencode(params)}"

    async def create_payment(
        self,
        *,
        amount_rub: Any,
        order_id: str,
        description: str = "",
        return_url: str | None = None,
        notification_url: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        customer_ip: str | None = None,
        payment_system_id: int | None = None,
    ) -> dict[str, Any]:
        """Create an API-only Card RUB or SBP order and return its checkout URL."""
        _ = description
        if not self.api_enabled:
            return {"ok": False, "error": "FreeKassa API is not configured"}

        method_id = int(payment_system_id or 0)
        if method_id not in FREEKASSA_CHECKOUT_METHOD_IDS:
            return {"ok": False, "error": "Unsupported FreeKassa payment method"}
        email_text = str(email or "").strip()
        ip_text = str(customer_ip or "").strip()
        if not email_text or not ip_text:
            return {"ok": False, "error": "Customer email and IP are required"}

        payload: dict[str, Any] = {
            "paymentId": str(order_id),
            "i": method_id,
            "email": email_text,
            "ip": ip_text,
            "amount": normalize_amount(amount_rub),
            "currency": self.currency,
        }
        if phone:
            payload["tel"] = str(phone).strip()
        if return_url:
            payload["success_url"] = return_url
        if notification_url:
            payload["notification_url"] = notification_url

        response = await self._api_post("orders/create", payload)
        payment_url = str((response or {}).get("location") or "").strip()
        provider_order_id = str((response or {}).get("orderId") or "").strip()
        if (response or {}).get("type") != "success" or not payment_url:
            logger.warning("FreeKassa API did not create order: payment_id=%s", order_id)
            return {"ok": False, "error": "FreeKassa rejected payment creation"}

        return {
            "ok": True,
            "payment_id": provider_order_id or str(order_id),
            "payment_url": payment_url,
            "provider": "freekassa",
            "mode": "api",
        }

    def verify_notification(self, payload: dict[str, Any]) -> tuple[bool, str]:
        if not self.enabled:
            return False, "service_disabled"

        merchant_id = str(payload.get("MERCHANT_ID") or "").strip()
        raw_amount = str(payload.get("AMOUNT") or "").strip()
        order_id = str(payload.get("MERCHANT_ORDER_ID") or "").strip()
        received_signature = str(payload.get("SIGN") or "").strip().lower()

        if not merchant_id or not raw_amount or not order_id or not received_signature:
            return False, "missing_required_fields"
        if not hmac.compare_digest(merchant_id, self.merchant_id):
            return False, "merchant_mismatch"

        expected = build_notification_signature(
            merchant_id,
            raw_amount,
            self.secret_word_2,
            order_id,
        )
        if not hmac.compare_digest(received_signature, expected.lower()):
            return False, "invalid_signature"
        return True, "ok"

    def is_allowed_webhook_ip(self, remote_ip: str | None) -> bool:
        if not self.verify_webhook_ip:
            return True
        return bool(remote_ip and remote_ip in self.allowed_webhook_ips)

    async def _api_post(
        self, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not self.api_enabled:
            return None

        body = dict(payload)
        body["shopId"] = int(self.merchant_id)
        body["nonce"] = await self._next_nonce()
        body["signature"] = build_api_signature(body, self.api_key)

        session = await self._get_session()
        url = f"{self.api_base_url}/{endpoint.lstrip('/')}"
        try:
            async with session.post(url, json=body) as response:
                text = await response.text()
                if response.status != 200:
                    logger.warning(
                        "FreeKassa API request failed: endpoint=%s status=%s body=%s",
                        endpoint,
                        response.status,
                        text[:1000],
                    )
                    return None
                try:
                    data = await response.json(content_type=None)
                except (ValueError, UnicodeError):
                    logger.warning(
                        "FreeKassa API returned invalid JSON: endpoint=%s body=%s",
                        endpoint,
                        text[:500],
                    )
                    return None
                return data if isinstance(data, dict) else None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.exception("FreeKassa API request error: endpoint=%s", endpoint)
            return None

    async def get_payment(
        self,
        payment_id: str | None = None,
        *,
        merchant_order_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Look up a payment through the optional merchant API."""
        lookup_id = str(merchant_order_id or payment_id or "").strip()
        if not lookup_id:
            return None
        if not self.api_enabled:
            return {
                "status": "webhook_only",
                "paid": False,
                "failed": False,
                "merchant_order_id": lookup_id,
            }

        response = await self._api_post("orders", {"paymentId": lookup_id})
        orders = (response or {}).get("orders")
        if not isinstance(orders, list) or not orders:
            return None

        selected = None
        for item in orders:
            if not isinstance(item, dict):
                continue
            if str(item.get("merchant_order_id") or "") == lookup_id:
                selected = item
                break
        if selected is None:
            selected = next(
                (item for item in orders if isinstance(item, dict)), None
            )
        if not selected:
            return None

        status = normalize_order_status(selected.get("status"))
        return {
            **status,
            "id": str(selected.get("fk_order_id") or ""),
            "merchant_order_id": str(
                selected.get("merchant_order_id") or lookup_id
            ),
            "amount": selected.get("amount"),
            "currency": selected.get("currency"),
            "raw": selected,
        }

    async def poll_pending_transactions(
        self,
        *,
        limit: int = 100,
        providers: Iterable[str] = ("freekassa",),
        complete_order: Callable[
            [str], Awaitable[dict[str, Any]]
        ]
        | None = None,
    ) -> list[dict[str, Any]]:
        if not self.api_enabled:
            return []

        provider_names = tuple(
            str(provider).strip().lower() for provider in providers if provider
        )
        if not provider_names:
            return []
        placeholders = ",".join("?" for _ in provider_names)
        query = (
            "SELECT order_id, payment_id FROM transactions "
            f"WHERE provider IN ({placeholders}) AND status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?"
        )
        async with db_backend.connect() as connection:
            connection.row_factory = db_backend.Row
            cursor = await connection.execute(
                query, (*provider_names, int(limit))
            )
            rows = await cursor.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            order_id = str(row["order_id"])
            item: dict[str, Any] = {"order_id": order_id}
            payment = await self.get_payment(merchant_order_id=order_id)
            if not payment:
                item["action"] = "not_found"
                results.append(item)
                continue

            item["status"] = payment.get("status")
            if payment.get("paid"):
                completion = (
                    await complete_order(order_id) if complete_order else None
                )
                item["action"] = (
                    "already_completed"
                    if completion and completion.get("already_completed")
                    else "completed"
                    if completion and completion.get("ok")
                    else "paid_unhandled"
                )
                item["completion"] = completion
            elif payment.get("failed"):
                async with db_backend.connect() as connection:
                    cursor = await connection.execute(
                        "UPDATE transactions SET status = 'failed' "
                        "WHERE order_id = ? AND status = 'pending'",
                        (order_id,),
                    )
                    await connection.commit()
                item["action"] = (
                    "failed" if cursor.rowcount else "already_updated"
                )
            else:
                item["action"] = "still_pending"
            results.append(item)

        return results


freekassa_service = FreeKassaService()
