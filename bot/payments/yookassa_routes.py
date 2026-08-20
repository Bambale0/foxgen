"""Webhook contract for YooKassa integration.

Framework adapters can mount these handlers into aiohttp/FastAPI.
"""

from __future__ import annotations

from typing import Any

from .yookassa_lifecycle import normalize_yookassa_event


async def handle_yookassa_webhook(
    payload: dict[str, Any],
    payment_processor,
) -> dict[str, Any]:
    event = normalize_yookassa_event(payload)

    # Idempotency belongs to the storage layer.
    already_processed = await payment_processor.has_event(event["event_id"])
    if already_processed:
        return {"ok": True, "duplicate": True}

    result = await payment_processor.process_yookassa_event(event)
    return {"ok": True, "result": result}
