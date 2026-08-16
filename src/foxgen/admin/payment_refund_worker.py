from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy import or_, select

from foxgen.infra.admin_models import PaymentEvent
from foxgen.infra.database import Database
from foxgen.infra.payment_models import UserPaymentOrder
from foxgen.infra.payment_refund_models import PaymentRefundAttempt
from foxgen.infra.payment_refunds import restore_refund_hold


@dataclass(frozen=True, slots=True)
class RefundProviderResult:
    already_refunded: bool
    raw_payload: dict[str, object]


class PaymentRefundSender(Protocol):
    async def refund(
        self,
        *,
        user_id: int,
        telegram_payment_charge_id: str,
    ) -> RefundProviderResult: ...


class RetriablePaymentRefundError(Exception):
    def __init__(self, message: str, *, delay_seconds: float | None = None) -> None:
        super().__init__(message)
        self.delay_seconds = delay_seconds


class PermanentPaymentRefundError(Exception):
    pass


class TelegramStarsRefundSender:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def refund(
        self,
        *,
        user_id: int,
        telegram_payment_charge_id: str,
    ) -> RefundProviderResult:
        try:
            accepted = await self._bot.refund_star_payment(
                user_id=user_id,
                telegram_payment_charge_id=telegram_payment_charge_id,
            )
        except TelegramBadRequest as exc:
            normalized = str(exc).upper().replace(" ", "_").replace("-", "_")
            if "CHARGE_ALREADY_REFUNDED" in normalized:
                return RefundProviderResult(
                    already_refunded=True,
                    raw_payload={"telegram_status": "already_refunded"},
                )
            raise PermanentPaymentRefundError(f"Telegram rejected Stars refund: {exc}") from exc
        except TelegramRetryAfter as exc:
            raise RetriablePaymentRefundError(
                "Telegram rate limited Stars refund",
                delay_seconds=float(exc.retry_after),
            ) from exc
        except (TelegramNetworkError, TelegramServerError) as exc:
            raise RetriablePaymentRefundError(
                "Telegram Stars refund outcome is not confirmed"
            ) from exc
        except TelegramAPIError as exc:
            raise PermanentPaymentRefundError(
                f"Telegram refund API rejected request: {exc}"
            ) from exc
        if accepted is not True:
            raise RetriablePaymentRefundError("Telegram did not confirm Stars refund")
        return RefundProviderResult(
            already_refunded=False,
            raw_payload={"telegram_status": "refunded"},
        )


class PaymentRefundWorker:
    def __init__(
        self,
        *,
        database: Database,
        sender: PaymentRefundSender,
        worker_id: str,
        batch_size: int = 50,
        lease_seconds: int = 120,
        max_attempts: int = 4,
    ) -> None:
        self._database = database
        self._sender = sender
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    async def run_once(self) -> int:
        claimed = await self._claim()
        for attempt_id in claimed:
            await self._process(attempt_id)
        return len(claimed)

    async def _claim(self) -> tuple[UUID, ...]:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=self._lease_seconds)
        async with self._database.session() as session:
            async with session.begin():
                rows = tuple(
                    (
                        await session.scalars(
                            select(PaymentRefundAttempt)
                            .where(
                                or_(
                                    (
                                        (PaymentRefundAttempt.status == "pending")
                                        & (PaymentRefundAttempt.available_at <= now)
                                    ),
                                    (
                                        (PaymentRefundAttempt.status == "processing")
                                        & (PaymentRefundAttempt.locked_at <= stale_before)
                                    ),
                                )
                            )
                            .order_by(
                                PaymentRefundAttempt.available_at,
                                PaymentRefundAttempt.created_at,
                            )
                            .with_for_update(skip_locked=True)
                            .limit(self._batch_size)
                        )
                    ).all()
                )
                for attempt in rows:
                    attempt.status = "processing"
                    attempt.locked_at = now
                    attempt.attempts += 1
                    attempt.attempted_at = now
                    attempt.provider_payload = {
                        **attempt.provider_payload,
                        "worker_id": self._worker_id,
                    }
                return tuple(attempt.id for attempt in rows)

    async def _process(self, attempt_id: UUID) -> None:
        async with self._database.session() as session:
            attempt = await session.get(PaymentRefundAttempt, attempt_id)
            if attempt is None or attempt.status != "processing":
                return
            user_id = attempt.user_id
            charge_id = attempt.external_charge_id

        try:
            result = await self._sender.refund(
                user_id=user_id,
                telegram_payment_charge_id=charge_id,
            )
        except PermanentPaymentRefundError as exc:
            await self._fail(attempt_id, exc, permanent=True)
            return
        except RetriablePaymentRefundError as exc:
            await self._fail(attempt_id, exc, permanent=False)
            return
        except Exception as exc:
            # Unknown sender exceptions are treated as ambiguous external outcomes.
            # The CREDIT hold remains in place until bounded retries or manual evidence resolution.
            await self._fail(
                attempt_id,
                RetriablePaymentRefundError(
                    f"Unexpected refund transport failure: {type(exc).__name__}: {exc}"
                ),
                permanent=False,
            )
            return

        async with self._database.session() as session:
            async with session.begin():
                attempt = await session.get(PaymentRefundAttempt, attempt_id, with_for_update=True)
                if attempt is None or attempt.status != "processing":
                    return
                payment = await session.get(PaymentEvent, attempt.payment_id, with_for_update=True)
                order = await session.get(UserPaymentOrder, attempt.order_id, with_for_update=True)
                if payment is None or order is None:
                    raise RuntimeError(
                        "Refund payment/order disappeared after provider confirmation"
                    )
                now = datetime.now(timezone.utc)
                attempt.status = "succeeded"
                attempt.provider_payload = {**attempt.provider_payload, **result.raw_payload}
                attempt.provider_payload["already_refunded"] = result.already_refunded
                attempt.last_error = None
                attempt.locked_at = None
                attempt.resolved_at = now
                order.status = "refunded"
                payment.status = "refunded"
                payment.raw_payload = {
                    **payment.raw_payload,
                    "refund_attempt_id": str(attempt.id),
                    "refund_status": "refunded",
                }

    async def _fail(
        self,
        attempt_id: UUID,
        exc: Exception,
        *,
        permanent: bool,
    ) -> None:
        async with self._database.session() as session:
            async with session.begin():
                attempt = await session.get(PaymentRefundAttempt, attempt_id, with_for_update=True)
                if attempt is None or attempt.status != "processing":
                    return
                payment = await session.get(PaymentEvent, attempt.payment_id, with_for_update=True)
                order = await session.get(UserPaymentOrder, attempt.order_id, with_for_update=True)
                if payment is None or order is None:
                    raise RuntimeError("Refund payment/order disappeared during failure handling")

                now = datetime.now(timezone.utc)
                attempt.last_error = f"{type(exc).__name__}: {exc}"[:4000]
                attempt.locked_at = None
                if permanent:
                    restore_key = await restore_refund_hold(
                        session,
                        attempt=attempt,
                        actor="system:telegram-stars-refund-worker",
                        reason=f"Restore CREDIT after rejected Stars refund: {exc}",
                    )
                    attempt.status = "failed"
                    attempt.resolved_at = now
                    attempt.provider_payload = {
                        **attempt.provider_payload,
                        "restore_ledger_key": restore_key,
                    }
                    order.status = "credited"
                    payment.status = "completed"
                    return

                if attempt.attempts >= self._max_attempts:
                    attempt.status = "unknown"
                    order.status = "refund_unknown"
                    payment.status = "refund_unknown"
                    payment.raw_payload = {
                        **payment.raw_payload,
                        "refund_attempt_id": str(attempt.id),
                        "refund_status": "unknown",
                    }
                    return

                attempt.status = "pending"
                attempt.available_at = now + _retry_delay(attempt.attempts, exc)


def _retry_delay(attempts: int, exc: Exception) -> timedelta:
    if isinstance(exc, RetriablePaymentRefundError) and exc.delay_seconds is not None:
        seconds = max(1.0, min(exc.delay_seconds, 3600.0))
        return timedelta(seconds=seconds)
    return timedelta(seconds=min(600, max(2, 2 ** min(attempts, 9))))
