#!/usr/bin/env python3
"""Backfill missing attached referral_events from bot logs.

Reads rotated log files, extracts successful
`Referral attached: visitor=... code=... referrer_id=...` lines, and inserts
missing `referral_events` rows only when they do not already exist.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.env import load_project_env

load_project_env()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("backfill_referral_events")

LOG_PATTERN = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} - "
    r"bot\.services\.referral_service - INFO - "
    r"Referral attached: visitor=(?P<visitor>\d+) code=(?P<code>[A-Z0-9]+) referrer_id=(?P<referrer>\d+)$"
)


@dataclass(frozen=True)
class AttachedEvent:
    created_at: str
    visitor_telegram_id: int
    clicked_code: str
    clicked_referrer_id: int
    source_log: str


def _iter_log_files(log_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in log_dir.iterdir()
            if path.is_file() and path.name.startswith("bot.log")
        ]
    )


def _parse_attached_events(log_dir: Path, clicked_code: str | None = None) -> list[AttachedEvent]:
    code_filter = str(clicked_code or "").strip().upper()
    events: list[AttachedEvent] = []

    for log_path in _iter_log_files(log_dir):
        with log_path.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw_line in fh:
                line = raw_line.rstrip("\n")
                match = LOG_PATTERN.match(line)
                if not match:
                    continue
                code = match.group("code").strip().upper()
                if code_filter and code != code_filter:
                    continue
                timestamp = datetime.strptime(
                    match.group("ts"),
                    "%Y-%m-%d %H:%M:%S",
                ).strftime("%Y-%m-%d %H:%M:%S")
                events.append(
                    AttachedEvent(
                        created_at=timestamp,
                        visitor_telegram_id=int(match.group("visitor")),
                        clicked_code=code,
                        clicked_referrer_id=int(match.group("referrer")),
                        source_log=log_path.name,
                    )
                )

    deduped: dict[tuple[int, str], AttachedEvent] = {}
    for event in events:
        deduped[(event.visitor_telegram_id, event.clicked_code)] = event
    return sorted(deduped.values(), key=lambda item: item.created_at)


async def _backfill(events: list[AttachedEvent], apply: bool) -> tuple[int, int]:
    from bot import db as db_backend

    inserted = 0
    skipped = 0

    async with db_backend.connect(None, timeout=15) as db:
        db.row_factory = db_backend.Row
        for event in events:
            exists_cursor = await db.execute(
                """
                SELECT 1
                FROM referral_events
                WHERE visitor_telegram_id = ?
                  AND clicked_code = ?
                  AND reason = 'attached'
                LIMIT 1
                """,
                (event.visitor_telegram_id, event.clicked_code),
            )
            if await exists_cursor.fetchone():
                skipped += 1
                continue

            user_cursor = await db.execute(
                """
                SELECT u.id AS visitor_user_id, u.referred_by, r.telegram_id AS referrer_telegram_id
                FROM users u
                LEFT JOIN users r ON r.id = u.referred_by
                WHERE u.telegram_id = ?
                """,
                (event.visitor_telegram_id,),
            )
            user_row = await user_cursor.fetchone()
            if not user_row:
                logger.warning(
                    "Skip event without user row: visitor=%s code=%s",
                    event.visitor_telegram_id,
                    event.clicked_code,
                )
                skipped += 1
                continue

            if int(user_row["referred_by"] or 0) != event.clicked_referrer_id:
                logger.warning(
                    "Skip mismatched event: visitor=%s code=%s db_referred_by=%s log_referrer_id=%s",
                    event.visitor_telegram_id,
                    event.clicked_code,
                    user_row["referred_by"],
                    event.clicked_referrer_id,
                )
                skipped += 1
                continue

            if not apply:
                inserted += 1
                continue

            metadata = json.dumps(
                {
                    "backfilled_from_log": event.source_log,
                    "backfill_reason": "missing_referral_event_after_successful_attach",
                },
                ensure_ascii=False,
            )
            await db.execute(
                """
                INSERT INTO referral_events (
                    created_at,
                    visitor_user_id,
                    visitor_telegram_id,
                    clicked_code,
                    clicked_referrer_id,
                    existing_referrer_id,
                    attached,
                    reason,
                    source,
                    start_param,
                    is_self_click,
                    is_repeat_click,
                    metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.created_at,
                    user_row["visitor_user_id"],
                    event.visitor_telegram_id,
                    event.clicked_code,
                    event.clicked_referrer_id,
                    None,
                    True,
                    "attached",
                    "log_backfill",
                    event.clicked_code,
                    False,
                    False,
                    metadata,
                ),
            )
            inserted += 1

        if apply and inserted:
            await db.commit()

    return inserted, skipped


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing referral_events from logs")
    parser.add_argument("--apply", action="store_true", help="Write rows to the database")
    parser.add_argument("--code", help="Only process one referral code, e.g. JXZWPGFA")
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="Directory with bot.log files (default: logs)",
    )
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    if not log_dir.exists():
        raise SystemExit(f"Log directory not found: {log_dir}")

    events = _parse_attached_events(log_dir, clicked_code=args.code)
    logger.info("Parsed %s unique attached events from logs", len(events))
    inserted, skipped = await _backfill(events, apply=args.apply)
    logger.info(
        "%s complete: inserted=%s skipped=%s mode=%s",
        "Backfill",
        inserted,
        skipped,
        "apply" if args.apply else "dry-run",
    )


if __name__ == "__main__":
    asyncio.run(main())
