#!/usr/bin/env python3
"""Detect and optionally repair cycles in users.referred_by."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from bot.env import load_project_env

load_project_env()

from bot import db as db_backend


async def _load_parent_map() -> dict[int, int | None]:
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute("SELECT id, referred_by FROM users")
        rows = await cursor.fetchall()
    return {
        int(row["id"]): (int(row["referred_by"]) if row["referred_by"] else None)
        for row in rows
    }


def _find_cycle_repairs(parents: dict[int, int | None]) -> list[tuple[int, int, tuple[int, ...]]]:
    repairs: dict[frozenset[int], tuple[int, int, tuple[int, ...]]] = {}

    for start_id in parents:
        path: list[int] = []
        seen_at: dict[int, int] = {}
        current_id: int | None = start_id

        while current_id is not None and current_id in parents:
            if current_id in seen_at:
                cycle = tuple(path[seen_at[current_id] :])
                if not cycle:
                    break
                break_user_id = max(cycle)
                old_referrer_id = parents.get(break_user_id)
                if old_referrer_id is not None:
                    repairs[frozenset(cycle)] = (
                        break_user_id,
                        int(old_referrer_id),
                        cycle,
                    )
                break
            seen_at[current_id] = len(path)
            path.append(current_id)
            current_id = parents.get(current_id)

    return list(repairs.values())


async def _apply_repairs(
    repairs: list[tuple[int, int, tuple[int, ...]]],
) -> tuple[int, int]:
    updated = 0
    deleted_referrals = 0
    async with db_backend.connect() as db:
        for break_user_id, old_referrer_id, _cycle in repairs:
            update_cursor = await db.execute(
                """
                UPDATE users
                SET referred_by = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND referred_by = ?
                """,
                (break_user_id, old_referrer_id),
            )
            updated += max(int(update_cursor.rowcount or 0), 0)
            delete_cursor = await db.execute(
                """
                DELETE FROM referrals
                WHERE referrer_id = ? AND referred_id = ?
                """,
                (old_referrer_id, break_user_id),
            )
            deleted_referrals += max(int(delete_cursor.rowcount or 0), 0)
        await db.commit()
    return updated, deleted_referrals


async def _load_integrity_repairs() -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        missing_rows = await (
            await db.execute(
                """
                SELECT u.referred_by AS referrer_id, u.id AS referred_id
                FROM users u
                LEFT JOIN referrals r
                  ON r.referrer_id = u.referred_by
                 AND r.referred_id = u.id
                WHERE u.referred_by IS NOT NULL
                  AND r.id IS NULL
                """
            )
        ).fetchall()
        orphan_rows = await (
            await db.execute(
                """
                SELECT r.referrer_id, r.referred_id
                FROM referrals r
                LEFT JOIN users u
                  ON u.id = r.referred_id
                 AND u.referred_by = r.referrer_id
                WHERE u.id IS NULL
                """
            )
        ).fetchall()
    missing = [(int(row["referrer_id"]), int(row["referred_id"])) for row in missing_rows]
    orphan = [(int(row["referrer_id"]), int(row["referred_id"])) for row in orphan_rows]
    return missing, orphan


async def _apply_integrity_repairs(
    missing: list[tuple[int, int]],
    orphan: list[tuple[int, int]],
) -> tuple[int, int]:
    inserted_missing = 0
    deleted_orphan = 0
    async with db_backend.connect() as db:
        for referrer_id, referred_id in missing:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits)
                VALUES (?, ?, 0)
                """,
                (referrer_id, referred_id),
            )
            inserted_missing += max(int(cursor.rowcount or 0), 0)
        for referrer_id, referred_id in orphan:
            cursor = await db.execute(
                """
                DELETE FROM referrals
                WHERE referrer_id = ? AND referred_id = ?
                """,
                (referrer_id, referred_id),
            )
            deleted_orphan += max(int(cursor.rowcount or 0), 0)
        await db.commit()
    return inserted_missing, deleted_orphan


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply repairs")
    args = parser.parse_args()

    parents = await _load_parent_map()
    repairs = _find_cycle_repairs(parents)
    missing, orphan = await _load_integrity_repairs()
    print(f"backend={db_backend.backend_name()} users={len(parents)} cycles={len(repairs)}")
    print(f"missing_referral_rows={len(missing)} orphan_referral_rows={len(orphan)}")

    for break_user_id, old_referrer_id, cycle in repairs[:20]:
        print(
            "cycle repair candidate: "
            f"break_user_id={break_user_id} old_referrer_id={old_referrer_id} "
            f"cycle_size={len(cycle)}"
        )
    if len(repairs) > 20:
        print(f"... {len(repairs) - 20} more cycle(s)")

    if not args.apply:
        print("dry_run=1")
        return 0

    updated, deleted_referrals = await _apply_repairs(repairs)
    inserted_missing, deleted_orphan = await _apply_integrity_repairs(missing, orphan)
    print(
        "applied=1 "
        f"updated_users={updated} "
        f"deleted_cycle_referrals={deleted_referrals} "
        f"inserted_missing_referrals={inserted_missing} "
        f"deleted_orphan_referrals={deleted_orphan}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
