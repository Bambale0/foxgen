from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from foxgen.application.payments import (
    PreCheckoutDecision,
    StarInvoice,
    StarPackage,
    StarPaymentResult,
)
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.domain.models import LedgerEntryType
from foxgen.infra.admin_models import PaymentEvent, TariffVersion
from foxgen.infra.billing import ensure_wallet_locked
from foxgen.infra.billing_models import LedgerEntry
from foxgen.infra.database import Database, User
from foxgen.infra.payment_models import UserPaymentOrder


TELEGRAM_STARS_PROVIDER = "telegram_stars"
TELEGRAM_STARS_CURRENCY = "XTR"


class TelegramStarsInvoiceClient:
    def __init__(self, *, bot_token: str, timeout_seconds: float = 15.0) -> None:
        if not bot_token:
            raise ValueError("Telegram bot token is required for Stars invoices")
        self._url = f"https://api.telegram.org/bot{bot_token}/createInvoiceLink"
        self._timeout = timeout_seconds

    async def create_invoice_link(
        self,
        *,
        title: str,
        description: str,
        payload: str,
        stars_amount: int,
    ) -> str:
        request = {
            "title": title,
            "description": description or title,
            "payload": payload,
            "currency": TELEGRAM_STARS_CURRENCY,
            "prices": [{"label": title, "amount": stars_amount}],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=request)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SubmissionError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Telegram временно не создаёт ссылку оплаты. Попробуйте ещё раз.",
                retryable=True,
            ) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Telegram вернул повреждённый ответ при создании оплаты.",
            ) from exc
        if response.is_error or not isinstance(body, dict) or body.get("ok") is not True:
            raise SubmissionError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Не удалось создать оплату Telegram Stars. Попробуйте ещё раз.",
                retryable=response.status_code >= 500,
            )
        result = body.get("result")
        if not isinstance(result, str) or not result.startswith("https://"):
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Telegram не вернул корректную ссылку оплаты.",
            )
        return result


class SqlAlchemyTelegramStarsPaymentService:
    def __init__(
        self,
        database: Database,
        *,
        bot_token: str,
        invoice_client: TelegramStarsInvoiceClient | None = None,
    ) -> None:
        self._database = database
        self._invoice_client = invoice_client or TelegramStarsInvoiceClient(bot_token=bot_token)

    async def list_packages(self) -> tuple[StarPackage, ...]:
        async with self._database.session() as session:
            return await self._packages(session)

    async def create_invoice(
        self,
        *,
        user_id: int,
        username: str | None,
        package_code: str,
        idempotency_key: str,
    ) -> StarInvoice:
        request_hash = hashlib.sha256(package_code.strip().encode("utf-8")).hexdigest()
        replayed = False

        async with self._database.session() as session:
            async with session.begin():
                order = await session.scalar(
                    select(UserPaymentOrder)
                    .where(
                        UserPaymentOrder.user_id == user_id,
                        UserPaymentOrder.idempotency_key == idempotency_key,
                    )
                    .with_for_update()
                )
                if order is not None:
                    replayed = True
                    if order.request_hash != request_hash:
                        raise SubmissionError(
                            ErrorCode.IDEMPOTENCY_CONFLICT,
                            "Этот ключ оплаты уже использован для другого пакета.",
                        )
                    package = self._package_from_order(order)
                    if order.invoice_url:
                        return StarInvoice(
                            order_id=order.id,
                            package=package,
                            invoice_payload=order.invoice_payload,
                            invoice_url=order.invoice_url,
                            replayed=True,
                        )
                else:
                    packages = {item.code: item for item in await self._packages(session)}
                    package = packages.get(package_code)
                    if package is None:
                        raise SubmissionError(
                            ErrorCode.PRICING_UNAVAILABLE,
                            "Этот пакет пополнения сейчас недоступен.",
                        )
                    await session.execute(
                        pg_insert(User)
                        .values(id=user_id, username=username)
                        .on_conflict_do_nothing(index_elements=[User.id])
                    )
                    if username:
                        await session.execute(
                            update(User).where(User.id == user_id).values(username=username)
                        )
                    order_id = uuid4()
                    order = UserPaymentOrder(
                        id=order_id,
                        user_id=user_id,
                        provider=TELEGRAM_STARS_PROVIDER,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        package_code=package.code,
                        package_title=package.title,
                        package_description=package.description,
                        credits_units=package.credits_units,
                        provider_amount=package.stars_amount,
                        provider_currency=TELEGRAM_STARS_CURRENCY,
                        invoice_payload=f"foxgen-stars:{order_id}",
                        status="created",
                    )
                    session.add(order)
                    await session.flush()

                order_id = order.id
                invoice_payload = order.invoice_payload
                package = self._package_from_order(order)

        invoice_url = await self._invoice_client.create_invoice_link(
            title=package.title,
            description=package.description,
            payload=invoice_payload,
            stars_amount=package.stars_amount,
        )

        async with self._database.session() as session:
            async with session.begin():
                order = await session.scalar(
                    select(UserPaymentOrder)
                    .where(UserPaymentOrder.id == order_id)
                    .with_for_update()
                )
                if order is None:
                    raise SubmissionError(
                        ErrorCode.PROVIDER_PROTOCOL,
                        "Локальный заказ оплаты исчез до сохранения ссылки.",
                    )
                if order.invoice_url is None:
                    order.invoice_url = invoice_url
                    order.status = "invoice_ready"
                stored_url = order.invoice_url

        if stored_url is None:
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Не удалось сохранить ссылку оплаты.",
            )
        return StarInvoice(
            order_id=order_id,
            package=package,
            invoice_payload=invoice_payload,
            invoice_url=stored_url,
            replayed=replayed,
        )

    async def validate_pre_checkout(
        self,
        *,
        user_id: int,
        invoice_payload: str,
        currency: str,
        total_amount: int,
    ) -> PreCheckoutDecision:
        async with self._database.session() as session:
            order = await session.scalar(
                select(UserPaymentOrder).where(UserPaymentOrder.invoice_payload == invoice_payload)
            )
        if order is None or order.user_id != user_id:
            return PreCheckoutDecision(False, "Заказ оплаты не найден. Создайте новую оплату.")
        if order.status in {"credited", "refunded", "failed"}:
            return PreCheckoutDecision(False, "Этот заказ уже завершён. Создайте новую оплату.")
        if currency != TELEGRAM_STARS_CURRENCY or order.provider_currency != currency:
            return PreCheckoutDecision(False, "Валюта оплаты не совпадает с заказом.")
        if total_amount != order.provider_amount:
            return PreCheckoutDecision(False, "Сумма оплаты изменилась. Создайте новую оплату.")
        return PreCheckoutDecision(True)

    async def credit_successful_payment(
        self,
        *,
        user_id: int,
        username: str | None,
        invoice_payload: str,
        currency: str,
        total_amount: int,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str,
        raw_payload: dict[str, object],
    ) -> StarPaymentResult:
        if not telegram_payment_charge_id:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Telegram не передал идентификатор платежа.",
            )
        ledger_key = f"payment-credit:{TELEGRAM_STARS_PROVIDER}:{telegram_payment_charge_id}"
        replayed = False

        async with self._database.session() as session:
            async with session.begin():
                order = await session.scalar(
                    select(UserPaymentOrder)
                    .where(UserPaymentOrder.invoice_payload == invoice_payload)
                    .with_for_update()
                )
                if order is None or order.user_id != user_id:
                    raise SubmissionError(
                        ErrorCode.AUTHORIZATION,
                        "Оплата не относится к этому пользователю.",
                    )
                if currency != TELEGRAM_STARS_CURRENCY or order.provider_currency != currency:
                    raise SubmissionError(ErrorCode.VALIDATION, "Валюта оплаты не совпадает.")
                if total_amount != order.provider_amount:
                    raise SubmissionError(ErrorCode.VALIDATION, "Сумма оплаты не совпадает.")

                charge_owner = await session.scalar(
                    select(UserPaymentOrder)
                    .where(
                        UserPaymentOrder.telegram_payment_charge_id
                        == telegram_payment_charge_id
                    )
                    .with_for_update()
                )
                if charge_owner is not None and charge_owner.id != order.id:
                    raise SubmissionError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Этот Telegram-платёж уже связан с другим заказом.",
                    )

                if order.status == "credited":
                    if order.telegram_payment_charge_id != telegram_payment_charge_id:
                        raise SubmissionError(
                            ErrorCode.IDEMPOTENCY_CONFLICT,
                            "Заказ уже оплачен другим Telegram-платежом.",
                        )
                    replayed = True
                    account = await ensure_wallet_locked(
                        session,
                        user_id=user_id,
                        currency="CREDIT",
                    )
                    return StarPaymentResult(
                        order_id=order.id,
                        available_units=account.available_units,
                        credited_units=order.credits_units,
                        replayed=True,
                    )

                await session.execute(
                    pg_insert(User)
                    .values(id=user_id, username=username)
                    .on_conflict_do_nothing(index_elements=[User.id])
                )
                if username:
                    await session.execute(
                        update(User).where(User.id == user_id).values(username=username)
                    )

                payment = await session.scalar(
                    select(PaymentEvent)
                    .where(
                        PaymentEvent.provider == TELEGRAM_STARS_PROVIDER,
                        PaymentEvent.external_id == telegram_payment_charge_id,
                    )
                    .with_for_update()
                )
                if payment is None:
                    payment = PaymentEvent(
                        provider=TELEGRAM_STARS_PROVIDER,
                        external_id=telegram_payment_charge_id,
                        user_id=user_id,
                        status="completed",
                        amount_units=order.credits_units,
                        currency="CREDIT",
                        raw_payload=raw_payload,
                    )
                    session.add(payment)
                elif payment.user_id != user_id or payment.amount_units != order.credits_units:
                    raise SubmissionError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Telegram-платёж уже обработан с другими параметрами.",
                    )
                else:
                    payment.status = "completed"
                    payment.raw_payload = raw_payload

                account = await ensure_wallet_locked(
                    session,
                    user_id=user_id,
                    currency="CREDIT",
                )
                ledger = await session.scalar(
                    select(LedgerEntry).where(LedgerEntry.idempotency_key == ledger_key)
                )
                if ledger is None:
                    account.available_units += order.credits_units
                    account.version += 1
                    session.add(
                        LedgerEntry(
                            user_id=user_id,
                            generation_id=None,
                            reservation_id=None,
                            entry_type=LedgerEntryType.CREDIT,
                            currency="CREDIT",
                            available_delta=order.credits_units,
                            reserved_delta=0,
                            idempotency_key=ledger_key,
                            actor="system:telegram_stars",
                            reason=f"Telegram Stars top-up package {order.package_code}",
                            metadata_json={
                                "payment_order_id": str(order.id),
                                "package_code": order.package_code,
                                "stars_amount": order.provider_amount,
                            },
                        )
                    )
                elif ledger.user_id != user_id or ledger.available_delta != order.credits_units:
                    raise SubmissionError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "Ключ зачисления Telegram-платежа уже использован иначе.",
                    )
                else:
                    replayed = True

                now = datetime.now(timezone.utc)
                order.status = "credited"
                order.telegram_payment_charge_id = telegram_payment_charge_id
                order.provider_payment_charge_id = provider_payment_charge_id
                order.raw_payment = raw_payload
                order.paid_at = now
                order.credited_at = now
                payment.credited_ledger_key = ledger_key
                payment.processed_at = now
                await session.flush()

                return StarPaymentResult(
                    order_id=order.id,
                    available_units=account.available_units,
                    credited_units=order.credits_units,
                    replayed=replayed,
                )

    async def _packages(self, session: object) -> tuple[StarPackage, ...]:
        latest = await session.scalar(select(TariffVersion).order_by(TariffVersion.version.desc()).limit(1))
        if latest is None:
            return ()
        raw_packages = latest.payload.get("packages") if isinstance(latest.payload, dict) else None
        if not isinstance(raw_packages, dict):
            return ()
        packages: list[StarPackage] = []
        for raw_code, raw in raw_packages.items():
            if not isinstance(raw_code, str) or not raw_code.strip() or not isinstance(raw, dict):
                continue
            credits = raw.get("credits_units", raw.get("credits"))
            stars = raw.get("stars_amount", raw.get("stars"))
            if (
                not isinstance(credits, int)
                or isinstance(credits, bool)
                or credits <= 0
                or not isinstance(stars, int)
                or isinstance(stars, bool)
                or stars <= 0
            ):
                continue
            title_value = raw.get("title")
            description_value = raw.get("description")
            title = title_value.strip() if isinstance(title_value, str) and title_value.strip() else raw_code
            description = (
                description_value.strip()
                if isinstance(description_value, str) and description_value.strip()
                else f"Пополнение FoxGen на {credits} CREDIT"
            )
            packages.append(
                StarPackage(
                    code=raw_code,
                    title=title[:255],
                    description=description[:512],
                    credits_units=credits,
                    stars_amount=stars,
                )
            )
        packages.sort(key=lambda item: (item.stars_amount, item.credits_units, item.code))
        return tuple(packages)

    @staticmethod
    def _package_from_order(order: UserPaymentOrder) -> StarPackage:
        return StarPackage(
            code=order.package_code,
            title=order.package_title,
            description=order.package_description,
            credits_units=order.credits_units,
            stars_amount=order.provider_amount,
        )
