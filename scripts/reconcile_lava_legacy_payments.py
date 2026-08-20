from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot import db as db_backend  # noqa: E402
from bot.database import complete_payment_atomic  # noqa: E402
from bot.services.lava_service import lava_service  # noqa: E402

logger = logging.getLogger("reconcile_lava_legacy_payments")

SUCCESS_STATUSES = {"completed", "paid", "success", "succeeded"}
FAILED_STATUSES = {"cancelled", "canceled", "failed", "expired"}
DEFAULT_LOCAL_STATUSES = ("pending", "failed")


@dataclass(slots=True)
class Candidate:
    order_id: str
    payment_id: str
    local_status: str
    created_at: str | None
    amount_rub: float
    credits: int


@dataclass(slots=True)
class ReconcileResult:
    order_id: str
    old_payment_id: str
    contract_id: str | None
    local_status: str
    provider_status: str
    action: str
    details: str = ""


def normalize_statuses(values: Iterable[str]) -> tuple[str, ...]:
    statuses = tuple(
        dict.fromkeys(
            str(value or "").strip().lower()
            for value in values
            if str(value or "").strip()
        )
    )
    if not statuses:
        raise ValueError("At least one local status is required")
    allowed = {"pending", "failed", "processing", "completed"}
    unknown = set(statuses) - allowed
    if unknown:
        raise ValueError(f"Unsupported local statuses: {', '.join(sorted(unknown))}")
    return statuses


def provider_status(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    return lava_service.webhook_status(payload)


def provider_reference(payload: dict[str, Any] | None) -> str | None:
    """Resolve the identifier returned by Lava's GET invoice endpoint.

    Create-invoice responses may contain a distinct ``contractId`` and must keep
    using :meth:`extract_contract_id`. GET ``/api/v2/invoices/{id}``, however,
    returns the contract identifier as the top-level ``id`` and often omits a
    separate ``contractId`` field. The fallback is therefore intentionally
    local to this reconciliation script.
    """

    if not payload:
        return None
    return (
        lava_service.extract_contract_id(payload)
        or lava_service.extract_invoice_id(payload)
    )


async def load_candidates(
    *,
    limit: int,
    statuses: tuple[str, ...],
    order_id: str | None,
) -> list[Candidate]:
    safe_limit = max(1, min(int(limit), 5000))
    placeholders = ", ".join("?" for _ in statuses)
    conditions = ["provider = 'lava'", f"status IN ({placeholders})"]
    params: list[Any] = list(statuses)

    if order_id:
        conditions.append("order_id = ?")
        params.append(order_id)

    params.append(safe_limit)
    query = f"""
        SELECT order_id, payment_id, status, created_at, amount_rub, credits
        FROM transactions
        WHERE {' AND '.join(conditions)}
          AND payment_id IS NOT NULL
          AND TRIM(payment_id) != ''
        ORDER BY datetime(created_at) ASC, id ASC
        LIMIT ?
    """

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        rows = await (await db.execute(query, params)).fetchall()

    return [
        Candidate(
            order_id=str(row["order_id"]),
            payment_id=str(row["payment_id"]),
            local_status=str(row["status"] or "").lower(),
            created_at=str(row["created_at"]) if row["created_at"] else None,
            amount_rub=float(row["amount_rub"] or 0),
            credits=int(row["credits"] or 0),
        )
        for row in rows
    ]


async def replace_payment_reference(candidate: Candidate, contract_id: str) -> bool:
    """Compare-and-set old invoice id to webhook contractId."""
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE transactions
            SET payment_id = ?
            WHERE order_id = ?
              AND provider = 'lava'
              AND payment_id = ?
              AND status != 'completed'
            """,
            (contract_id, candidate.order_id, candidate.payment_id),
        )
        await db.commit()
        return cursor.rowcount == 1


async def restore_failed_to_pending(candidate: Candidate) -> bool:
    """Restore only a provider-confirmed paid transaction before atomic completion."""
    if candidate.local_status != "failed":
        return True

    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE transactions
            SET status = 'pending'
            WHERE order_id = ?
              AND provider = 'lava'
              AND status = 'failed'
            """,
            (candidate.order_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def reconcile_candidate(
    candidate: Candidate,
    *,
    apply: bool,
    complete_paid: bool,
) -> ReconcileResult:
    invoice = await lava_service.get_invoice(candidate.payment_id)
    if not invoice:
        return ReconcileResult(
            order_id=candidate.order_id,
            old_payment_id=candidate.payment_id,
            contract_id=None,
            local_status=candidate.local_status,
            provider_status="lookup_failed",
            action="unresolved",
            details="Lava API did not return the invoice",
        )

    contract_id = provider_reference(invoice)
    remote_status = provider_status(invoice) or "unknown"
    needs_reference_update = bool(contract_id and contract_id != candidate.payment_id)
    is_paid = remote_status in SUCCESS_STATUSES

    if not apply:
        actions: list[str] = []
        if needs_reference_update:
            actions.append("update_payment_id")
        if complete_paid and is_paid:
            actions.append("complete_paid")
        return ReconcileResult(
            order_id=candidate.order_id,
            old_payment_id=candidate.payment_id,
            contract_id=contract_id,
            local_status=candidate.local_status,
            provider_status=remote_status,
            action="dry_run:" + ("+".join(actions) or "no_change"),
        )

    if needs_reference_update:
        updated = await replace_payment_reference(candidate, str(contract_id))
        if not updated:
            return ReconcileResult(
                order_id=candidate.order_id,
                old_payment_id=candidate.payment_id,
                contract_id=contract_id,
                local_status=candidate.local_status,
                provider_status=remote_status,
                action="skipped_race",
                details="Transaction changed concurrently or was already completed",
            )

    if complete_paid and is_paid:
        restored = await restore_failed_to_pending(candidate)
        if not restored:
            return ReconcileResult(
                order_id=candidate.order_id,
                old_payment_id=candidate.payment_id,
                contract_id=contract_id,
                local_status=candidate.local_status,
                provider_status=remote_status,
                action="skipped_status_race",
                details="Local transaction status changed concurrently",
            )

        completion = await complete_payment_atomic(candidate.order_id)
        if completion.get("already_completed"):
            action = "already_completed"
        elif completion.get("ok"):
            action = "completed"
        else:
            action = "complete_failed"
        return ReconcileResult(
            order_id=candidate.order_id,
            old_payment_id=candidate.payment_id,
            contract_id=contract_id,
            local_status=candidate.local_status,
            provider_status=remote_status,
            action=action,
            details=str(completion.get("reason") or ""),
        )

    if needs_reference_update:
        action = "payment_id_updated"
    elif remote_status in FAILED_STATUSES:
        action = "provider_failed_no_change"
    else:
        action = "no_change"

    return ReconcileResult(
        order_id=candidate.order_id,
        old_payment_id=candidate.payment_id,
        contract_id=contract_id,
        local_status=candidate.local_status,
        provider_status=remote_status,
        action=action,
    )


async def run(args: argparse.Namespace) -> int:
    if not lava_service.enabled:
        print("ERROR: LAVA_API_KEY is not configured", file=sys.stderr)
        return 2

    statuses = normalize_statuses(args.status)
    candidates = await load_candidates(
        limit=args.limit,
        statuses=statuses,
        order_id=args.order_id,
    )

    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "complete_paid": bool(args.complete_paid),
                "statuses": statuses,
                "candidates": len(candidates),
            },
            ensure_ascii=False,
        )
    )

    summary: dict[str, int] = {}
    try:
        for index, candidate in enumerate(candidates, start=1):
            result = await reconcile_candidate(
                candidate,
                apply=args.apply,
                complete_paid=args.complete_paid,
            )
            summary[result.action] = summary.get(result.action, 0) + 1
            print(json.dumps(asdict(result), ensure_ascii=False))
            if args.delay > 0 and index < len(candidates):
                await asyncio.sleep(args.delay)
    finally:
        await lava_service.close()

    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 0 if not any(key in summary for key in ("unresolved", "complete_failed")) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recover legacy Lava transactions whose local payment_id contains an "
            "invoice id instead of the contractId sent in webhooks."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write resolved contractId values to the database. Default is dry-run.",
    )
    parser.add_argument(
        "--complete-paid",
        action="store_true",
        help=(
            "After resolving the reference, atomically complete transactions that "
            "Lava reports as paid. Requires --apply."
        ),
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--order-id", help="Process only one local order_id")
    parser.add_argument(
        "--status",
        action="append",
        default=None,
        help=(
            "Local status to scan. Repeat the flag for several statuses. "
            "Default: pending and failed."
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Delay between Lava API requests in seconds.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.complete_paid and not args.apply:
        parser.error("--complete-paid requires --apply")
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    args.status = args.status or list(DEFAULT_LOCAL_STATUSES)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
