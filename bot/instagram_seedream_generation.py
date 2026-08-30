from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from bot.channel_identity import ChannelIdentity
from bot.channel_promotions import (
    consume_instagram_first_image,
    release_instagram_first_image,
    reserve_instagram_first_image,
)
from bot.database import add_credits, add_generation_history, deduct_credits
from bot.instagram_generation import (
    InstagramDraft,
    InstagramGenerationJob,
    InstagramGenerationRetry,
    InstagramGenerationService,
    _activate_job,
    _insert_job,
    _linked_billing_user,
    _mark_job_failed,
    _mark_job_provider_task,
    _mark_job_succeeded,
    update_instagram_draft,
)
from bot.instagram_model_contract import (
    INSTAGRAM_PHOTO_MODEL,
    instagram_photo_cost,
)
from bot.services.preset_manager import preset_manager
from bot.services.seedream_service import seedream_service

logger = logging.getLogger(__name__)
_PROVIDER_POLL_SECONDS = 5.0
_PROVIDER_POLL_ATTEMPTS = 120
_SUCCESS_STATES = {"success", "succeeded", "completed", "done"}
_FAILURE_STATES = {"fail", "failed", "error", "cancelled", "canceled"}


def _seedream_result_url(status: dict) -> str:
    data = status.get("data") if isinstance(status.get("data"), dict) else {}
    output = data.get("output")
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, list):
        for value in output:
            candidate = str(value or "").strip()
            if candidate:
                return candidate
    raw = status.get("raw") if isinstance(status.get("raw"), dict) else {}
    raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    extracted = seedream_service._extract_output(raw_data)
    if isinstance(extracted, str):
        return extracted.strip()
    if isinstance(extracted, list):
        for value in extracted:
            candidate = str(value or "").strip()
            if candidate:
                return candidate
    return ""


class InstagramSeedream5ProService(InstagramGenerationService):
    """Durable Instagram photo flow backed by Seedream 5 Pro High."""

    async def _offer_paid_generation(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        prompt: str,
        account_id: str,
        recipient_id: str,
    ) -> None:
        billing = await _linked_billing_user(identity.id)
        if billing is None:
            await update_instagram_draft(
                identity.id,
                prompt=prompt,
                state="awaiting_link",
            )
            await self._send_account_link(identity, account_id, recipient_id)
            return

        _user_id, _telegram_id, credits = billing
        cost = instagram_photo_cost()
        await update_instagram_draft(
            identity.id,
            prompt=prompt,
            state="awaiting_confirmation",
        )
        rub_value = float(preset_manager.get_credit_rub_value())
        price_rub = round(cost * rub_value, 2)
        if credits < cost:
            action = (
                " Баланса не хватает — пополни его в Telegram, затем вернись "
                "сюда и напиши «Продолжить»."
            )
        else:
            action = " Ответь ДА для запуска или НЕТ для отмены."
        await self.client.send_text(
            account_id,
            recipient_id,
            f"Seedream 5 Pro • {cost:g} 🐾 ({price_rub:g} ₽). "
            f"Баланс: {credits:g} 🐾.{action}",
        )

    async def _enqueue_free(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        prompt: str,
        account_id: str,
        recipient_id: str,
    ) -> bool:
        job_id = uuid.uuid4().hex
        if not await reserve_instagram_first_image(identity.id, job_id):
            return False
        job = InstagramGenerationJob(
            id=job_id,
            identity_id=identity.id,
            account_id=account_id,
            recipient_id=recipient_id,
            image_url=draft.image_url,
            prompt=prompt,
            model=INSTAGRAM_PHOTO_MODEL.product_key,
            cost=0,
            billing_mode="free",
            telegram_id=None,
            promotion_reservation_key=job_id,
            status="prepared",
            provider_task_id=None,
            result_url=None,
            delivered_at_epoch=None,
            attempt_count=0,
        )
        try:
            await _insert_job(job, status="prepared")
            await _activate_job(job.id)
        except Exception:
            await release_instagram_first_image(job_id)
            raise
        await update_instagram_draft(
            identity.id,
            prompt=prompt,
            state="generating",
        )
        await self.client.send_text(
            account_id,
            recipient_id,
            "Запускаю Seedream 5 Pro ✨ Эта первая генерация бесплатная 🎁",
        )
        return True

    async def _enqueue_paid(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        account_id: str,
        recipient_id: str,
    ) -> None:
        billing = await _linked_billing_user(identity.id)
        if billing is None:
            await update_instagram_draft(identity.id, state="awaiting_link")
            await self._send_account_link(identity, account_id, recipient_id)
            return
        user_id, telegram_id, _credits = billing
        cost = instagram_photo_cost()
        job = InstagramGenerationJob(
            id=uuid.uuid4().hex,
            identity_id=identity.id,
            account_id=account_id,
            recipient_id=recipient_id,
            image_url=draft.image_url,
            prompt=draft.prompt,
            model=INSTAGRAM_PHOTO_MODEL.product_key,
            cost=cost,
            billing_mode="credits",
            telegram_id=telegram_id,
            promotion_reservation_key=None,
            status="prepared",
            provider_task_id=None,
            result_url=None,
            delivered_at_epoch=None,
            attempt_count=0,
        )
        await _insert_job(job, status="prepared")
        deducted = await deduct_credits(telegram_id, cost)
        if not deducted:
            await _mark_job_failed(job.id, "insufficient_balance")
            await self.client.send_text(
                account_id,
                recipient_id,
                f"Не хватает баланса. Для Seedream 5 Pro нужно {cost:g} 🐾. "
                "Пополни баланс в Telegram и вернись с «Продолжить».",
            )
            return
        try:
            await _activate_job(job.id)
        except Exception:
            await add_credits(telegram_id, cost)
            await _mark_job_failed(job.id, "activation_failed")
            raise
        await update_instagram_draft(identity.id, state="generating")
        await self.client.send_text(
            account_id,
            recipient_id,
            f"{cost:g} 🐾 списано ✅ Запускаю Seedream 5 Pro.",
        )
        logger.info(
            "Instagram Seedream 5 Pro job queued: job=%s user=%s",
            job.id,
            user_id,
        )

    async def _generate_result(self, job: InstagramGenerationJob) -> str:
        if self.generator is not None:
            return await self.generator(job.prompt, job.image_url)

        task_id = str(job.provider_task_id or "").strip()
        if not task_id:
            response = await seedream_service.generate_image(
                prompt=job.prompt,
                image_urls=[job.image_url],
                aspect_ratio=INSTAGRAM_PHOTO_MODEL.aspect_ratio,
                quality=INSTAGRAM_PHOTO_MODEL.quality,
                nsfw_checker=False,
                callBackUrl=None,
                model=INSTAGRAM_PHOTO_MODEL.provider_model,
            )
            if not isinstance(response, dict):
                raise InstagramGenerationRetry(
                    "Seedream 5 Pro did not accept the generation"
                )
            task_id = str(response.get("task_id") or "").strip()
            if not task_id:
                message = str(
                    response.get("message")
                    or response.get("error")
                    or "Seedream 5 Pro returned no task"
                )
                if response.get("error") in {"network_error", "invalid_json"}:
                    raise InstagramGenerationRetry(message)
                raise RuntimeError(message)
            await _mark_job_provider_task(job.id, task_id)

        consecutive_errors = 0
        for _ in range(_PROVIDER_POLL_ATTEMPTS):
            status = await seedream_service.get_task_status(task_id)
            if not isinstance(status, dict):
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    raise InstagramGenerationRetry(
                        "Seedream 5 Pro status is temporarily unavailable"
                    )
                await asyncio.sleep(_PROVIDER_POLL_SECONDS)
                continue

            consecutive_errors = 0
            data = status.get("data") if isinstance(status.get("data"), dict) else {}
            state = str(data.get("status") or "").strip().lower()
            if state in _SUCCESS_STATES:
                result_url = _seedream_result_url(status)
                if not result_url:
                    raise RuntimeError(
                        "Seedream 5 Pro completed without a result URL"
                    )
                return result_url
            if state in _FAILURE_STATES:
                raise RuntimeError("Seedream 5 Pro generation failed")
            await asyncio.sleep(_PROVIDER_POLL_SECONDS)

        raise InstagramGenerationRetry("Seedream 5 Pro is still processing")

    async def _finalize_success(self, job: InstagramGenerationJob) -> None:
        if job.billing_mode == "free" and job.promotion_reservation_key:
            consumed = await consume_instagram_first_image(
                job.promotion_reservation_key
            )
            if not consumed:
                raise RuntimeError("Failed to consume Instagram free entitlement")

        await _mark_job_succeeded(job.id)
        with contextlib.suppress(Exception):
            await update_instagram_draft(
                job.identity_id,
                prompt="",
                state="idle",
                clear_image=True,
            )

        if job.billing_mode == "credits":
            billing = await _linked_billing_user(job.identity_id)
            if billing is not None:
                user_id, _telegram_id, _credits = billing
                with contextlib.suppress(Exception):
                    await add_generation_history(
                        user_id,
                        "instagram_seedream_5_pro",
                        job.prompt,
                        job.cost,
                    )
            with contextlib.suppress(Exception):
                await self.client.send_text(
                    job.account_id,
                    job.recipient_id,
                    "Готово ✨ Хочешь ещё — пришли новое фото.",
                )
            return

        identity = ChannelIdentity(
            id=job.identity_id,
            user_id=None,
            channel="instagram",
            account_id=job.account_id,
            external_user_id=job.recipient_id,
        )
        link = ""
        if self.account_link_factory is not None:
            with contextlib.suppress(Exception):
                link = str(await self.account_link_factory(identity)).strip()
        suffix = f"\n\nПополнить и продолжить: {link}" if link else ""
        with contextlib.suppress(Exception):
            await self.client.send_text(
                job.account_id,
                job.recipient_id,
                "Готово 🎁 Первая генерация была бесплатной.\n\n"
                "Хочешь продолжить — пополни баланс тем же способом, что в Telegram. "
                "После оплаты вернись сюда и напиши «Продолжить»."
                + suffix,
            )
