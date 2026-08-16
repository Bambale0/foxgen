from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from foxgen.application.payments import StarInvoice, StarPackage
from foxgen.core.errors import ErrorCode, SubmissionError
from foxgen.infra.admin_models import TariffVersion
from foxgen.infra.database import User
from foxgen.infra.payment_models import UserPaymentOrder
from foxgen.infra.payments import (
    TELEGRAM_INVOICE_DESCRIPTION_MAX_LENGTH,
    TELEGRAM_INVOICE_TITLE_MAX_LENGTH,
    TELEGRAM_STARS_CURRENCY,
    TELEGRAM_STARS_PROVIDER,
    SqlAlchemyTelegramStarsPaymentService,
)


class BonusAwareTelegramStarsPaymentService(SqlAlchemyTelegramStarsPaymentService):
    """Telegram Stars service with immutable explicit package-bonus snapshots.

    `UserPaymentOrder.credits_units` intentionally stores the total CREDIT grant so
    the existing settlement, payment reprocess, and native refund paths continue to
    operate on exactly the amount originally issued. `bonus_units` stores the
    auditable bonus component; base CREDIT is `credits_units - bonus_units`.
    """

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
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"stars:invoice:{user_id}:{idempotency_key}"},
                )
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
                        credits_units=package.total_credits_units,
                        bonus_units=package.bonus_units,
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

    async def _packages(self, session: AsyncSession) -> tuple[StarPackage, ...]:
        latest = await session.scalar(
            select(TariffVersion).order_by(TariffVersion.version.desc()).limit(1)
        )
        if latest is None:
            return ()
        raw_packages = latest.payload.get("packages") if isinstance(latest.payload, dict) else None
        if not isinstance(raw_packages, dict):
            return ()

        packages: list[StarPackage] = []
        for raw_code, raw in raw_packages.items():
            if not isinstance(raw_code, str) or not raw_code.strip() or not isinstance(raw, dict):
                continue
            base_credits = raw.get("credits_units", raw.get("credits"))
            bonus = raw.get("bonus_units", raw.get("bonus_credits", 0))
            stars = raw.get("stars_amount", raw.get("stars"))
            if (
                not isinstance(base_credits, int)
                or isinstance(base_credits, bool)
                or base_credits <= 0
                or not isinstance(bonus, int)
                or isinstance(bonus, bool)
                or bonus < 0
                or not isinstance(stars, int)
                or isinstance(stars, bool)
                or stars <= 0
            ):
                continue

            title_value = raw.get("title")
            description_value = raw.get("description")
            title = (
                title_value.strip()
                if isinstance(title_value, str) and title_value.strip()
                else raw_code
            )
            if isinstance(description_value, str) and description_value.strip():
                description = description_value.strip()
            elif bonus:
                description = f"{base_credits} CREDIT + {bonus} бонус CREDIT"
            else:
                description = f"Пополнение FoxGen на {base_credits} CREDIT"

            packages.append(
                StarPackage(
                    code=raw_code,
                    title=title[:TELEGRAM_INVOICE_TITLE_MAX_LENGTH],
                    description=description[:TELEGRAM_INVOICE_DESCRIPTION_MAX_LENGTH],
                    credits_units=base_credits + bonus,
                    stars_amount=stars,
                    bonus_units=bonus,
                    base_credits_units=base_credits,
                )
            )
        packages.sort(key=lambda item: (item.stars_amount, item.total_credits_units, item.code))
        return tuple(packages)

    @staticmethod
    def _package_from_order(order: UserPaymentOrder) -> StarPackage:
        base_credits = order.credits_units - order.bonus_units
        if base_credits <= 0:
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Сохранённый заказ содержит некорректный снимок бонуса.",
            )
        return StarPackage(
            code=order.package_code,
            title=order.package_title,
            description=order.package_description,
            credits_units=order.credits_units,
            stars_amount=order.provider_amount,
            bonus_units=order.bonus_units,
            base_credits_units=base_credits,
        )
