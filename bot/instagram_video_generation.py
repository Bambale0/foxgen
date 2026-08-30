from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from bot.channel_identity import ChannelIdentity
from bot.channel_promotions import (
    consume_instagram_first_image,
    ensure_instagram_first_image_promotion,
    release_instagram_first_image,
    reserve_instagram_first_image,
)
from bot.database import add_credits, add_generation_history, deduct_credits
from bot.instagram_api import InstagramEvent
from bot.instagram_generation import (
    InstagramDraft,
    InstagramGenerationJob,
    InstagramGenerationRetry,
    _activate_job,
    _CANCEL_WORDS,
    _CONFIRM_WORDS,
    _insert_job,
    _linked_billing_user,
    _mark_job_delivered,
    _mark_job_failed,
    _mark_job_provider_task,
    _mark_job_result,
    _mark_job_succeeded,
    _normalized_reply,
    _retry_job,
    get_instagram_draft,
    save_instagram_image_draft,
    update_instagram_draft,
)
from bot.instagram_model_contract import INSTAGRAM_VIDEO_MODEL, instagram_video_cost
from bot.instagram_seedream_generation import InstagramSeedream5ProService
from bot.services.preset_manager import preset_manager
from bot.services.seedance_25_service import seedance_25_service

logger = logging.getLogger(__name__)
VIDEO_DURATION_SECONDS = 5
_PROVIDER_POLL_SECONDS = 5.0
_PROVIDER_POLL_ATTEMPTS = 120
_SUCCESS_STATES = {"success", "succeeded", "completed", "done"}
_FAILURE_STATES = {"fail", "failed", "error", "cancelled", "canceled"}


def message_media(event: InstagramEvent) -> tuple[str, str]:
    message = event.payload.get("message")
    if not isinstance(message, dict):
        return "", ""
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return "", ""
    for item in attachments:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("type") or "").strip().lower()
        if media_type not in {"image", "video"}:
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        media_url = str(payload.get("url") or "").strip()
        if media_url:
            return media_type, media_url
    return "", ""


def video_state(stage: str, media_type: str) -> str:
    return f"video:{stage}:{media_type}"


def video_state_parts(state: str) -> tuple[str, str]:
    parts = str(state or "").split(":", 2)
    if len(parts) == 3 and parts[0] == "video":
        return parts[1], parts[2]
    return "", ""


def _status_output_url(status: dict) -> str:
    data = status.get("data") if isinstance(status.get("data"), dict) else {}
    output = data.get("output")
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, list):
        for value in output:
            candidate = str(value or "").strip()
            if candidate:
                return candidate
    return ""


class InstagramVideoGenerationService(InstagramSeedream5ProService):
    """Seedance 2.5 generation path sharing the durable Instagram job queue."""

    async def handle_video_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        media_type, media_url = message_media(event)
        if media_url:
            draft = await get_instagram_draft(identity.id)
            stage, _ = video_state_parts(draft.state if draft else "")
            if stage == "generating":
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Предыдущее видео ещё создаётся. Сначала пришлю результат.",
                )
                return True
            await save_instagram_image_draft(identity.id, media_url)
            await update_instagram_draft(
                identity.id,
                state=video_state("waiting_prompt", media_type),
            )
            promotion = await ensure_instagram_first_image_promotion(identity.id)
            free_line = (
                " Первая генерация будет бесплатно 🎁"
                if promotion.status != "consumed"
                else ""
            )
            media_label = "Фото" if media_type == "image" else "Видео"
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                f"{media_label} получил 🎬.{free_line} "
                "Теперь напиши, что должно происходить в ролике.",
            )
            return True

        text = str(event.text or "").strip()
        if not text:
            return False
        draft = await get_instagram_draft(identity.id)
        if draft is None or not draft.image_url:
            message = (
                "Продолжаем 🎬 Пришли фото или видео-референс для Seedance 2.5."
                if _normalized_reply(text) in _CONFIRM_WORDS
                else "Сначала пришли фото или видео-референс 🎬."
            )
            await self.client.send_text(event.account_id, event.sender_id, message)
            return True

        stage, media_type = video_state_parts(draft.state)
        normalized = _normalized_reply(text)
        if stage == "generating":
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Seedance 2.5 уже создаёт ролик. Результат пришлю сюда автоматически.",
            )
            return True

        if stage == "awaiting_confirmation":
            return await self._handle_video_confirmation(
                identity,
                event,
                draft,
                media_type,
                normalized,
            )

        if stage == "awaiting_link":
            if identity.user_id is None:
                await self._send_account_link(identity, event.account_id, event.sender_id)
                return True
            await self._offer_paid_video(
                identity,
                draft,
                draft.prompt or text,
                media_type,
                event.account_id,
                event.sender_id,
            )
            return True

        promotion = await ensure_instagram_first_image_promotion(identity.id)
        if promotion.status != "consumed":
            if await self._enqueue_free_video(
                identity,
                draft,
                text,
                media_type,
                event.account_id,
                event.sender_id,
            ):
                return True
            promotion = await ensure_instagram_first_image_promotion(identity.id)
            if promotion.status != "consumed":
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Бесплатная генерация уже запускается. Результат пришлю сюда.",
                )
                return True

        await self._offer_paid_video(
            identity,
            draft,
            text,
            media_type,
            event.account_id,
            event.sender_id,
        )
        return True

    async def _handle_video_confirmation(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
        draft: InstagramDraft,
        media_type: str,
        normalized: str,
    ) -> bool:
        if normalized in _CANCEL_WORDS:
            await update_instagram_draft(
                identity.id,
                prompt="",
                state=video_state("waiting_prompt", media_type),
            )
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Отменил. Референс сохранил — можешь написать новый запрос.",
            )
            return True
        if normalized not in _CONFIRM_WORDS:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Ответь ДА для запуска или НЕТ для отмены.",
            )
            return True
        await self._enqueue_paid_video(
            identity,
            draft,
            media_type,
            event.account_id,
            event.sender_id,
        )
        return True

    async def _offer_paid_video(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        prompt: str,
        media_type: str,
        account_id: str,
        recipient_id: str,
    ) -> None:
        billing = await _linked_billing_user(identity.id)
        if billing is None:
            await update_instagram_draft(
                identity.id,
                prompt=prompt,
                state=video_state("awaiting_link", media_type),
            )
            await self._send_account_link(identity, account_id, recipient_id)
            return

        _user_id, _telegram_id, credits = billing
        cost = instagram_video_cost(duration=VIDEO_DURATION_SECONDS)
        await update_instagram_draft(
            identity.id,
            prompt=prompt,
            state=video_state("awaiting_confirmation", media_type),
        )
        price_rub = round(cost * float(preset_manager.get_credit_rub_value()), 2)
        action = (
            " Ответь ДА для запуска или НЕТ для отмены."
            if credits >= cost
            else " Баланса не хватает — пополни его в Telegram и вернись с «Продолжить»."
        )
        await self.client.send_text(
            account_id,
            recipient_id,
            f"Seedance 2.5 • {VIDEO_DURATION_SECONDS} сек • {cost:g} 🐾 "
            f"({price_rub:g} ₽). Баланс: {credits:g} 🐾.{action}",
        )

    async def _enqueue_free_video(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        prompt: str,
        media_type: str,
        account_id: str,
        recipient_id: str,
    ) -> bool:
        job_id = uuid.uuid4().hex
        if not await reserve_instagram_first_image(identity.id, job_id):
            return False
        job = self._video_job(
            job_id=job_id,
            identity=identity,
            draft=draft,
            media_type=media_type,
            account_id=account_id,
            recipient_id=recipient_id,
            prompt=prompt,
            cost=0,
            billing_mode="free",
            telegram_id=None,
            promotion_reservation_key=job_id,
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
            state=video_state("generating", media_type),
        )
        await self.client.send_text(
            account_id,
            recipient_id,
            "Запускаю Seedance 2.5 🎬 Первая генерация бесплатная 🎁",
        )
        return True

    async def _enqueue_paid_video(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        media_type: str,
        account_id: str,
        recipient_id: str,
    ) -> None:
        billing = await _linked_billing_user(identity.id)
        if billing is None:
            await update_instagram_draft(
                identity.id,
                state=video_state("awaiting_link", media_type),
            )
            await self._send_account_link(identity, account_id, recipient_id)
            return

        user_id, telegram_id, _credits = billing
        cost = instagram_video_cost(duration=VIDEO_DURATION_SECONDS)
        job = self._video_job(
            job_id=uuid.uuid4().hex,
            identity=identity,
            draft=draft,
            media_type=media_type,
            account_id=account_id,
            recipient_id=recipient_id,
            prompt=draft.prompt,
            cost=cost,
            billing_mode="credits",
            telegram_id=telegram_id,
            promotion_reservation_key=None,
        )
        await _insert_job(job, status="prepared")
        if not await deduct_credits(telegram_id, cost):
            await _mark_job_failed(job.id, "insufficient_balance")
            await self.client.send_text(
                account_id,
                recipient_id,
                f"Не хватает баланса. Для Seedance 2.5 нужно {cost:g} 🐾.",
            )
            return
        try:
            await _activate_job(job.id)
        except Exception:
            await add_credits(telegram_id, cost)
            await _mark_job_failed(job.id, "activation_failed")
            raise
        await update_instagram_draft(
            identity.id,
            state=video_state("generating", media_type),
        )
        await self.client.send_text(
            account_id,
            recipient_id,
            f"{cost:g} 🐾 списано ✅ Запускаю Seedance 2.5.",
        )
        logger.info("Instagram Seedance 2.5 job queued: job=%s user=%s", job.id, user_id)

    @staticmethod
    def _video_job(
        *,
        job_id: str,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        media_type: str,
        account_id: str,
        recipient_id: str,
        prompt: str,
        cost: float,
        billing_mode: str,
        telegram_id: int | None,
        promotion_reservation_key: str | None,
    ) -> InstagramGenerationJob:
        return InstagramGenerationJob(
            id=job_id,
            identity_id=identity.id,
            account_id=account_id,
            recipient_id=recipient_id,
            image_url=draft.image_url,
            prompt=prompt,
            model=f"{INSTAGRAM_VIDEO_MODEL.product_key}:{media_type}",
            cost=cost,
            billing_mode=billing_mode,
            telegram_id=telegram_id,
            promotion_reservation_key=promotion_reservation_key,
            status="prepared",
            provider_task_id=None,
            result_url=None,
            delivered_at_epoch=None,
            attempt_count=0,
        )

    async def _generate_result(self, job: InstagramGenerationJob) -> str:
        if not self._is_video_job(job):
            return await super()._generate_result(job)

        media_type = job.model.rsplit(":", 1)[-1]
        task_id = str(job.provider_task_id or "").strip()
        if not task_id:
            response = await seedance_25_service.generate_video(
                prompt=job.prompt,
                duration=VIDEO_DURATION_SECONDS,
                aspect_ratio=INSTAGRAM_VIDEO_MODEL.aspect_ratio,
                resolution=INSTAGRAM_VIDEO_MODEL.resolution,
                first_frame_url=job.image_url if media_type == "image" else None,
                reference_video_urls=[job.image_url] if media_type == "video" else None,
                generate_audio=True,
                output_format="mp4",
                callBackUrl=None,
            )
            if not isinstance(response, dict):
                raise InstagramGenerationRetry("Seedance 2.5 did not accept the generation")
            task_id = str(response.get("task_id") or "").strip()
            if not task_id:
                message = str(
                    response.get("error")
                    or response.get("message")
                    or "Seedance 2.5 returned no task"
                )
                if response.get("error") in {"network_error", "invalid_json"}:
                    raise InstagramGenerationRetry(message)
                raise RuntimeError(message)
            await _mark_job_provider_task(job.id, task_id)
        return await self._wait_seedance_result(task_id)

    async def _wait_seedance_result(self, task_id: str) -> str:
        consecutive_errors = 0
        for _ in range(_PROVIDER_POLL_ATTEMPTS):
            status = await seedance_25_service.get_task_status(task_id)
            if not isinstance(status, dict):
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    raise InstagramGenerationRetry(
                        "Seedance 2.5 status is temporarily unavailable"
                    )
                await asyncio.sleep(_PROVIDER_POLL_SECONDS)
                continue
            consecutive_errors = 0
            data = status.get("data") if isinstance(status.get("data"), dict) else {}
            state = str(data.get("status") or "").strip().lower()
            if state in _SUCCESS_STATES:
                result_url = _status_output_url(status)
                if not result_url:
                    raise RuntimeError("Seedance 2.5 completed without a video URL")
                return result_url
            if state in _FAILURE_STATES:
                raise RuntimeError("Seedance 2.5 generation failed")
            await asyncio.sleep(_PROVIDER_POLL_SECONDS)
        raise InstagramGenerationRetry("Seedance 2.5 is still processing")

    async def _process_job(self, job: InstagramGenerationJob) -> None:
        if not self._is_video_job(job):
            await super()._process_job(job)
            return

        result_url = str(job.result_url or "").strip()
        if not result_url:
            try:
                result_url = await self._generate_result(job)
                if not result_url:
                    raise RuntimeError("Seedance 2.5 returned an empty URL")
                await _mark_job_result(job.id, result_url, job.provider_task_id)
            except InstagramGenerationRetry as error:
                if job.provider_task_id is None and job.attempt_count >= 5:
                    await self._finalize_failure(job, error)
                else:
                    await _retry_job(job.id, str(error))
                return
            except Exception as error:
                logger.exception("Instagram video generation failed: job=%s", job.id)
                await self._finalize_failure(job, error)
                return

        delivered_at = job.delivered_at_epoch
        if delivered_at is None:
            try:
                await self.client.send_media(
                    job.account_id,
                    job.recipient_id,
                    "video",
                    result_url,
                )
                delivered_at = await _mark_job_delivered(job.id)
            except Exception as error:
                logger.exception("Instagram video delivery failed: job=%s", job.id)
                await _retry_job(job.id, str(error))
                return

        try:
            await self._finalize_success(job)
        except Exception as error:
            logger.exception(
                "Instagram video finalization failed: job=%s delivered_at=%s",
                job.id,
                delivered_at,
            )
            await _retry_job(job.id, str(error))

    async def _finalize_failure(
        self,
        job: InstagramGenerationJob,
        error: Exception,
    ) -> None:
        await super()._finalize_failure(job, error)
        if self._is_video_job(job):
            media_type = job.model.rsplit(":", 1)[-1]
            with contextlib.suppress(Exception):
                await update_instagram_draft(
                    job.identity_id,
                    state=video_state("waiting_prompt", media_type),
                )

    async def _finalize_success(self, job: InstagramGenerationJob) -> None:
        if not self._is_video_job(job):
            await super()._finalize_success(job)
            return

        if job.billing_mode == "free" and job.promotion_reservation_key:
            consumed = await consume_instagram_first_image(job.promotion_reservation_key)
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
            await self._finish_paid_video(job)
            return
        await self._finish_free_video(job)

    async def _finish_paid_video(self, job: InstagramGenerationJob) -> None:
        billing = await _linked_billing_user(job.identity_id)
        if billing is not None:
            user_id, _telegram_id, _credits = billing
            with contextlib.suppress(Exception):
                await add_generation_history(
                    user_id,
                    "instagram_seedance_2_5",
                    job.prompt,
                    job.cost,
                )
        with contextlib.suppress(Exception):
            await self.client.send_text(
                job.account_id,
                job.recipient_id,
                "Готово 🎬 Хочешь ещё — пришли новый референс или напиши «Фото».",
            )

    async def _finish_free_video(self, job: InstagramGenerationJob) -> None:
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
                "Чтобы продолжить, пополни баланс тем же способом, что в Telegram. "
                "После оплаты вернись сюда и напиши «Продолжить»."
                + suffix,
            )

    @staticmethod
    def _is_video_job(job: InstagramGenerationJob) -> bool:
        return job.model.startswith(f"{INSTAGRAM_VIDEO_MODEL.product_key}:")
