from __future__ import annotations

import asyncio
import time

from foxgen.admin.worker import AdminDeliverySender


class RateLimitedAdminSender:
    """Serialize admin-originated Telegram sends at a configured global rate."""

    def __init__(self, sender: AdminDeliverySender, *, rate_per_second: float) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._sender = sender
        self._interval = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._next_send_at = 0.0

    async def send_text(self, recipient_id: int, text: str) -> int:
        async with self._lock:
            now = time.monotonic()
            delay = self._next_send_at - now
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                return await self._sender.send_text(recipient_id, text)
            finally:
                self._next_send_at = time.monotonic() + self._interval
