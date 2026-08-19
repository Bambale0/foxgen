from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_BLOCKED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "localhost",
    "invalid",
}
_BLOCKED_EMAILS = {
    "buyer@example.com",
    "client@example.com",
    "test@example.com",
}


def normalize_lava_customer_email(value: Any) -> str | None:
    """Validate a buyer email and reject placeholders shared by many users."""

    email = str(value or "").strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        return None
    if email in _BLOCKED_EMAILS:
        return None
    domain = email.rsplit("@", 1)[-1]
    if domain in _BLOCKED_EMAIL_DOMAINS or domain.endswith(".invalid"):
        return None
    return email


def _preview_lava_error_body(raw_text: str, limit: int = 500) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("<!doctype html", "<html")):
        return f"[html response: {len(text)} chars]"
    if len(text) > limit:
        return text[:limit] + f"... [truncated, {len(text)} chars total]"
    return text


def _lava_error_text(response: dict[str, Any]) -> str:
    error = response.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        for key in ("error", "message"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value
    raw = response.get("raw")
    return raw if isinstance(raw, str) else ""


class LavaService:
    """lava.top Public API client.

    Swagger: lava.top Public API 1.17.0
    Auth: X-Api-Key header.
    Create invoice: POST /api/v3/invoice.
    Get invoice: GET /api/v2/invoices/{id}.
    Webhook payload contains eventType, contractId, amount, currency, status.
    """

    def __init__(self, api_key: str, base_url: str = "https://gate.lava.top"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "LAVA_API_KEY is not configured"}

        session = await self._get_session()
        url = f"{self.base_url}/{path.lstrip('/')}"
        max_attempts = 3 if method.upper() == "GET" else 1

        for attempt in range(1, max_attempts + 1):
            try:
                async with session.request(
                    method.upper(),
                    url,
                    headers=self._headers(),
                    json=payload,
                    params=params,
                ) as resp:
                    raw_text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError, UnicodeError):
                        data = {"raw": raw_text}

                    if resp.status >= 400:
                        if resp.status in {500, 502, 503, 504} and attempt < max_attempts:
                            logger.info(
                                "Lava API transient error %s %s attempt=%s/%s",
                                resp.status,
                                url,
                                attempt,
                                max_attempts,
                            )
                            await asyncio.sleep(0.5 * attempt)
                            continue
                        logger.warning(
                            "Lava API error %s %s: %s",
                            resp.status,
                            url,
                            _preview_lava_error_body(raw_text),
                        )
                        return {
                            "ok": False,
                            "status": resp.status,
                            "error": data,
                            "raw": raw_text,
                        }

                    if isinstance(data, dict):
                        data.setdefault("ok", True)
                        return data
                    return {"ok": True, "result": data}
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt < max_attempts:
                    logger.info(
                        "Lava API request failed %s attempt=%s/%s: %s",
                        url,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    await asyncio.sleep(0.5 * attempt)
                    continue
                logger.warning("Lava API request failed %s: %s", url, exc)
                return {"ok": False, "status": None, "error": str(exc), "raw": ""}

        return {"ok": False, "status": None, "error": "request failed", "raw": ""}

    async def create_invoice(
        self,
        email: str,
        offer_id: str,
        currency: str = "RUB",
        amount: float | None = None,
        payment_provider: str | None = None,
        payment_method: str | None = None,
        buyer_language: str | None = None,
        periodicity: str | None = None,
        client_utm: dict[str, Any] | None = None,
        _allow_product_fallback: bool = True,
    ) -> dict[str, Any]:
        customer_email = normalize_lava_customer_email(email)
        if not customer_email:
            logger.error(
                "Blocked Lava invoice without a real customer email: offer_id=%s currency=%s",
                offer_id,
                currency,
            )
            return {
                "ok": False,
                "status": 400,
                "code": "invalid_customer_email",
                "error": "Для оплаты Lava требуется реальная почта покупателя",
            }

        payload: dict[str, Any] = {
            "email": customer_email,
            "offerId": offer_id,
            "currency": currency,
        }
        if amount is not None:
            payload["amount"] = float(amount)
        if payment_provider:
            payload["paymentProvider"] = payment_provider
        if payment_method:
            payload["paymentMethod"] = payment_method
        if buyer_language:
            payload["buyerLanguage"] = buyer_language
        if periodicity:
            payload["periodicity"] = periodicity
        if client_utm:
            payload["clientUtm"] = client_utm

        response = await self._request("POST", "/api/v3/invoice", payload=payload)
        if response.get("ok") or not _allow_product_fallback:
            return response

        error_text = _lava_error_text(response)
        if "Product with offer id" not in error_text:
            return response

        resolved_offer_id = await self.resolve_offer_id_from_product_id(
            product_id=offer_id,
            currency=currency,
        )
        if not resolved_offer_id or resolved_offer_id == offer_id:
            return response

        logger.info(
            "Resolved Lava productId=%s to offerId=%s for currency=%s",
            offer_id,
            resolved_offer_id,
            currency,
        )
        return await self.create_invoice(
            email=customer_email,
            offer_id=resolved_offer_id,
            currency=currency,
            amount=amount,
            payment_provider=payment_provider,
            payment_method=payment_method,
            buyer_language=buyer_language,
            periodicity=periodicity,
            client_utm=client_utm,
            _allow_product_fallback=False,
        )

    async def resolve_offer_id_from_product_id(
        self,
        product_id: str,
        currency: str,
    ) -> str | None:
        normalized_product_id = str(product_id or "").strip()
        normalized_currency = str(currency or "").strip().upper()
        if not normalized_product_id:
            return None

        next_path = "/api/v2/products"
        max_pages = 20

        for _ in range(max_pages):
            response = await self._request("GET", next_path)
            if not response.get("ok"):
                return None

            items = response.get("items") or []
            if isinstance(items, list):
                resolved = self._find_offer_id_in_products(
                    items=items,
                    product_id=normalized_product_id,
                    currency=normalized_currency,
                )
                if resolved:
                    return resolved

            next_page = response.get("nextPage")
            if not isinstance(next_page, str) or not next_page.strip():
                return None
            next_path = next_page.strip()

        return None

    @staticmethod
    def _find_offer_id_in_products(
        *,
        items: list[Any],
        product_id: str,
        currency: str,
    ) -> str | None:
        fallback_offer_id: str | None = None

        for item in items:
            data = item.get("data") if isinstance(item, dict) else None
            if not isinstance(data, dict) and isinstance(item, dict):
                data = item
            if not isinstance(data, dict):
                continue
            if str(data.get("id") or "").strip() != product_id:
                continue

            offers = data.get("offers") or []
            if not isinstance(offers, list):
                return None

            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                offer_id = str(offer.get("id") or "").strip()
                if not offer_id:
                    continue
                if fallback_offer_id is None:
                    fallback_offer_id = offer_id

                prices = offer.get("prices") or []
                if not isinstance(prices, list):
                    continue
                for price in prices:
                    if not isinstance(price, dict):
                        continue
                    if str(price.get("currency") or "").strip().upper() == currency:
                        return offer_id

            return fallback_offer_id

        return None

    async def get_invoice(self, invoice_id: str) -> dict[str, Any] | None:
        response = await self._request("GET", f"/api/v2/invoices/{invoice_id}")
        if not response.get("ok"):
            return None
        return response

    def extract_invoice_id(self, response: dict[str, Any]) -> str | None:
        value = response.get("id")
        if value:
            return str(value)
        data = response.get("data")
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
        result = response.get("result")
        if isinstance(result, dict) and result.get("id"):
            return str(result["id"])
        return None

    def extract_contract_id(self, response: dict[str, Any]) -> str | None:
        """Извлекает contractId из ответа create_invoice.

        Lava возвращает свой contractId при создании,
        который затем приходит в webhook. Сохраняем его как payment_id."""
        value = self._find_first(response, ("contractId", "contract_id"))
        if value:
            return str(value)
        # Если contractId нет на верхнем уровне, пробуем внутри data / result
        for container_name in ("data", "result"):
            container = response.get(container_name)
            if isinstance(container, dict):
                value = self._find_first(container, ("contractId", "contract_id"))
                if value:
                    return str(value)
        return None

    def extract_payment_url(self, response: dict[str, Any]) -> str | None:
        candidates = [
            response.get("paymentUrl"),
            response.get("payment_url"),
            response.get("url"),
            response.get("link"),
        ]
        for container_name in ("data", "result"):
            container = response.get(container_name)
            if isinstance(container, dict):
                candidates.extend(
                    [
                        container.get("paymentUrl"),
                        container.get("payment_url"),
                        container.get("url"),
                        container.get("link"),
                    ]
                )
        return next((item for item in candidates if item), None)

    @staticmethod
    def _find_first(payload: Any, keys: tuple[str, ...]) -> str | None:
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if value not in (None, ""):
                    return str(value)
            for value in payload.values():
                found = LavaService._find_first(value, keys)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = LavaService._find_first(value, keys)
                if found:
                    return found
        return None

    @staticmethod
    def webhook_event_type(payload: dict[str, Any]) -> str:
        return (
            LavaService._find_first(payload, ("eventType", "event_type"))
            or ""
        ).lower()

    @staticmethod
    def webhook_status(payload: dict[str, Any]) -> str:
        return (
            LavaService._find_first(
                payload,
                ("status", "contractStatus", "contract_status"),
            )
            or ""
        ).lower()

    @classmethod
    def is_success_webhook(cls, payload: dict[str, Any]) -> bool:
        event_type = cls.webhook_event_type(payload)
        status = cls.webhook_status(payload)
        return event_type == "payment.success" or status in {
            "completed",
            "success",
            "succeeded",
            "paid",
        }

    @classmethod
    def is_failed_webhook(cls, payload: dict[str, Any]) -> bool:
        event_type = cls.webhook_event_type(payload)
        status = cls.webhook_status(payload)
        return event_type == "payment.failed" or status in {
            "cancelled",
            "canceled",
            "failed",
            "expired",
        }

    @classmethod
    def webhook_contract_id(cls, payload: dict[str, Any]) -> str | None:
        value = cls._find_first(
            payload,
            ("contractId", "contract_id", "invoiceId", "invoice_id"),
        )
        return str(value) if value else None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


lava_service = LavaService(
    api_key=config.LAVA_API_KEY,
    base_url=config.LAVA_API_BASE_URL,
)
