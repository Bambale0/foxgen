"""Manually inspect and reconcile pending FreeKassa transactions.

Usage:
    python3 scripts/poll_freekassa_pending.py

The merchant API key is required for status lookup. The script does not credit
orders by itself because production completion also applies promo/referral side
effects; it prints provider states for operational diagnostics.
"""

import asyncio
import json
import logging

from bot.services.freekassa_service import freekassa_service

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    if not freekassa_service.api_enabled:
        raise SystemExit(
            "FreeKassa API lookup is disabled. Set FREEKASSA_MERCHANT_ID, "
            "FREEKASSA_SECRET_WORD, FREEKASSA_SECRET_WORD_2 and FREEKASSA_API_KEY."
        )

    results = await freekassa_service.poll_pending_transactions(
        providers=("freekassa", "yookassa"),
        complete_order=None,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    await freekassa_service.close()


if __name__ == "__main__":
    asyncio.run(main())
