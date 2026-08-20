"""YooKassa payment adapter for HappyFox.

The adapter intentionally contains only provider communication. Balance
crediting must be performed by the existing payment lifecycle after a
verified webhook/status transition.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import aiohttp


class YooKassaProvider:
    """Minimal async YooKassa client.

    Required environment:
      YOOKASSA_SHOP_ID
      YOOKASSA_SECRET_KEY
    """

    API_URL = "https://api.yookassa.ru/v3/payments"

    def __init__(self, shop_id: str, secret_key: str):
        self.shop_id = shop_id
        self.secret_key = secret_key

    async def create_payment(
        self,
        amount_rub: Decimal,
        description: str,
        return_url: str,
        metadata: dict[str, str],
    ) -> dict:
        payload = {
            "amount": {
                "value": f"{amount_rub:.2f}",
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url,
            },
            "capture": True,
            "description": description,
            "metadata": metadata,
        }

        headers = {"Idempotence-Key": str(uuid.uuid4())}
        auth = aiohttp.BasicAuth(self.shop_id, self.secret_key)

        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.post(
                self.API_URL,
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                return await response.json()

    async def get_payment(self, payment_id: str) -> dict:
        auth = aiohttp.BasicAuth(self.shop_id, self.secret_key)

        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.get(
                f"{self.API_URL}/{payment_id}",
            ) as response:
                response.raise_for_status()
                return await response.json()
