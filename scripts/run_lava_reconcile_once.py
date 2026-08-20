#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json

from bot.env import load_project_env

load_project_env()

# Importing bot.handlers installs the safe Lava callbacks before we access the
# legacy payments module, matching the production import order in bot.main.
import bot.handlers  # noqa: E402,F401
from bot.handlers import payments as payments_module  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one safe Lava pending-payment reconciliation batch."
    )
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    results = await payments_module.reconcile_lava_pending_transactions(
        limit=max(1, args.limit),
        bot=None,
    )
    summary = {
        "checked": len(results),
        "completed": sum(item.get("action") == "completed" for item in results),
        "already_completed": sum(
            item.get("action") == "already_completed" for item in results
        ),
        "failed": sum(item.get("action") == "failed" for item in results),
        "pending": sum(item.get("action") == "still_pending" for item in results),
        "errors": sum(item.get("action") == "error" for item in results),
    }
    print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
