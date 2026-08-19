import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


class CryptoBotService:
    """Minimal Crypto Pay API client for invoices and webhook validation."""

    def __init__(self, api_token: str, use_testnet: bool = False):
        self.api_token = api_token
        self.base_url = (
            "https://testnet-pay.crypt.bot" if use_testnet else "https://pay.crypt.bot"
        )
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_token)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def _api_call(self, method: str, payload: Optional[Dict[str, Any]] = None):
        if not self.enabled:
            return {"ok": False, "error": "CRYPTOBOT_API_TOKEN is not configured"}

        session = await self._get_session()
        headers = {
            "Crypto-Pay-API-Token": self.api_token,
            "Content-Type": "application/json",
        }
        async with session.post(
            f"{self.base_url}/api/{method}",
            headers=headers,
            json=payload or {},
        ) as resp:
            try:
                return await resp.json()
            except Exception:
                text = await resp.text()
                return {"ok": False, "error": text}

    async def create_invoice(
        self,
        amount_rub: float,
        description: str,
        order_id: str,
        paid_btn_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "currency_type": "fiat",
            "fiat": "RUB",
            "amount": f"{amount_rub:.2f}",
            "description": description[:1024],
            "payload": order_id,
            "allow_comments": True,
            "allow_anonymous": True,
        }
        if paid_btn_url:
            payload["paid_btn_name"] = "openBot"
            payload["paid_btn_url"] = paid_btn_url
        return await self._api_call("createInvoice", payload)

    async def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        payload = {"invoice_ids": str(invoice_id)}
        resp = await self._api_call("getInvoices", payload)
        if not resp.get("ok"):
            return None
        items = (resp.get("result") or {}).get("items") or []
        return items[0] if items else None

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """Verify crypto-pay-api-signature header."""
        if not signature or not self.api_token:
            return False
        secret = hashlib.sha256(self.api_token.encode("utf-8")).digest()
        calculated = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(calculated, signature)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


cryptobot_service = CryptoBotService(
    api_token=config.CRYPTOBOT_API_TOKEN,
    use_testnet=config.CRYPTOBOT_USE_TESTNET,
)
