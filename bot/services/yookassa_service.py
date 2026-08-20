"""Compatibility adapter for code paths that still use the old provider name.

Lava is the primary payment provider. This module contains no YooKassa SDK calls
and cannot activate YooKassa; stale ``yookassa`` calls are delegated to
``freekassa_service`` only as a legacy compatibility path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from bot.config import config
from bot.services.freekassa_service import freekassa_service

# Some legacy webhook/Mini App code reads these instance attributes. Map them to
# FreeKassa values so stale code fails safely without restoring YooKassa secrets.
for _name, _value in {
    "YOOKASSA_SHOP_ID": config.FREEKASSA_MERCHANT_ID,
    "YOOKASSA_SECRET_KEY": config.FREEKASSA_SECRET_WORD,
    "YOOKASSA_WEBHOOK_SECRET": config.FREEKASSA_SECRET_WORD_2,
}.items():
    if not hasattr(config, _name):
        setattr(config, _name, _value)


class FreeKassaLegacyAliasService:
    """Expose old method names while executing only FreeKassa operations."""

    @property
    def enabled(self) -> bool:
        return freekassa_service.enabled

    async def create_payment(
        self,
        amount_rub: float,
        order_id: str,
        description: str,
        return_url: str | None = None,
        notification_url: str | None = None,
    ) -> dict[str, Any] | None:
        result = await freekassa_service.create_payment(
            amount_rub=amount_rub,
            order_id=order_id,
            description=description,
            return_url=return_url,
            notification_url=notification_url,
        )
        if not result.get("ok"):
            return {
                "Success": False,
                "Message": result.get("error")
                or "FreeKassa payment creation failed",
                "Provider": "freekassa",
            }
        return {
            "Success": True,
            "PaymentId": result["payment_id"],
            "PaymentURL": result["payment_url"],
            "Provider": "freekassa",
            "Raw": result,
        }

    async def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        result = await freekassa_service.get_payment(
            payment_id,
            merchant_order_id=payment_id,
        )
        if not result:
            return None
        return {
            "id": result.get("id") or payment_id,
            "status": result.get("status") or "",
            "paid": bool(result.get("paid")),
            "failed": bool(result.get("failed")),
            "metadata": {
                "order_id": result.get("merchant_order_id") or payment_id
            },
            "amount": result.get("amount"),
            "currency": result.get("currency"),
            "Raw": result,
        }

    async def poll_pending_transactions(
        self,
        limit: int = 100,
        complete_order: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        return await freekassa_service.poll_pending_transactions(
            limit=limit,
            providers=("yookassa",),
            complete_order=complete_order,
        )

    @staticmethod
    def extract_order_id(payment: Any) -> str | None:
        if isinstance(payment, dict):
            metadata = payment.get("metadata") or {}
            order_id = (
                metadata.get("order_id")
                or payment.get("merchant_order_id")
                or payment.get("payment_id")
            )
            return str(order_id) if order_id else None
        metadata = getattr(payment, "metadata", None) or {}
        order_id = metadata.get("order_id")
        return str(order_id) if order_id else None


# Deliberately retained import symbol; implementation is FreeKassa-only.
yookassa_service = FreeKassaLegacyAliasService()
