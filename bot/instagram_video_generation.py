from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from bot import instagram_generation as generation
from bot.channel_identity import ChannelIdentity
from bot.database import add_credits, add_generation_history, deduct_credits
from bot.instagram_api import InstagramEvent
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
_VIDEO_PAYWALL_STAGE = "awaiting_topup"
_VIDEO_WAIT_SOURCE_STAGE = "waiting_source"
_VIDEO_WAIT_PROMPT_STAGE = "waiting_prompt"
_VIDEO_CONFIRM_STAGE = "awaiting_confirmation"
_VIDEO_GENERATING_STAGE = "generating"


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


def video_state(stage: str, media_type: str = "") -> str:
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
    """Paid-only Seedance 2.5 flow sharing the durable Instagram job queue."""

    async def _account_link_url(self, identity: ChannelIdentity) -> str:
        if self.account_link_factory is None:
            return ""
        try:
            return str(await self.account_link_factory(identity)).strip()
        except Exception:
            logger.exception(
                "Failed to build Instagram video top-up link: identity=%s",
                identity.id,
            )
            return ""

    async def enter_video_paywall(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> None:
        await generation.update_instagram_draft(
            identity.id,
            prompt="",
            state=video_state(_VIDEO_PAYWALL_STAGE),
            clear_image=True,
        )
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=VIDEO_DURATION_SECONDS)
        price_rub = round(cost * float(preset_manager.get_credit_rub_value()), 2)
        link = await self._account_link_url(identity)

        balance_note = ""
        if billing is not None:
            _user_id, _telegram_id, credits = billing
            balance_note = f"\nТекущий баланс: {credits:g} 🐾."
            if credits >= cost:
                balance_note += " Уже хватает — можешь сразу написать «Продолжить»."

        link_note = f"\n\nПополнить и продолжить: {link}" if link else ""
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            "🎬 Видео в Instagram — платное.\n\n"
            f"Seedance 2.5 • {VIDEO_DURATION_SECONDS} сек • {cost:g} 🐾 "
            f"({price_rub:g} ₽)."
            f"{balance_note}\n\n"
            "Сначала пополни баланс в Telegram. После оплаты вернись сюда и "
            "напиши «Продолжить». Только после этого попрошу фото или видео-референс."
            f"{link_note}",
        )

    async def _resume_after_topup(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=VIDEO_DURATION_SECONDS)
        if billing is None:
            await self.enter_video_paywall(identity, event)
            return True

        _user_id, _telegram_id, credits = billing
        if credits < cost:
            await self.enter_video_paywall(identity, event)
            return True

        await generation.update_instagram_draft(
            identity.id,
            prompt="",
            state=video_state(_VIDEO_WAIT_SOURCE_STAGE),
            clear_image=True,
        )
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            f"Баланс готов ✅ Для Seedance 2.5 нужно {cost:g} 🐾.\n\n"
            "Теперь пришли фото или видео-референс.",
        )
        return True

    async def handle_video_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        draft = await generation.get_instagram_draft(identity.id)
        stage, media_type = video_state_parts(draft.state if draft else "")
        normalized = generation._normalized_reply(str(event.text or ""))
        incoming_media_type, media_url = message_media(event)

        if not stage or stage == _VIDEO_PAYWALL_STAGE:
            if normalized == "продолжить":
                return await self._resume_after_topup(identity, event)
            if stage == _VIDEO_PAYWALL_STAGE:
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Для видео сначала пополни баланс по ссылке выше, затем напиши "
                    "«Продолжить». Референс пока не нужен.",
                )
                return True
            await self.enter_video_paywall(identity, event)
            return True

        if stage == _VIDEO_GENERATING_STAGE:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Seedance 2.5 уже создаёт ролик. Результат пришлю сюда автоматически.",
            )
            return True

        if stage == _VIDEO_WAIT_SOURCE_STAGE:
            if not media_url:
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Пришли фото или видео-референс для Seedance 2.5.",
                )
                return True
            await generation.save_instagram_image_draft(identity.id, media_url)
            await generation.update_instagram_draft(
                identity.id,
                state=video_state(_VIDEO_WAIT_PROMPT_STAGE, incoming_media_type),
            )
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Референс получил 🎬 Теперь одним сообщением напиши, "
                "что должно происходить в ролике.",
            )
            return True

        if stage == _VIDEO_WAIT_PROMPT_STAGE:
            if media_url:
                await generation.save_instagram_image_draft(identity.id, media_url)
                await generation.update_instagram_draft(
                    identity.id,
                    state=video_state(_VIDEO_WAIT_PROMPT_STAGE, incoming_media_type),
                )
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Новый референс сохранил. Теперь напиши, что должно происходить в видео.",
                )
                return True
            text = str(event.text or "").strip()
            if not text:
                return False
            draft = await generation.get_instagram_draft(identity.id)
            if draft is None or not draft.image_url:
                await generation.update_instagram_draft(
                    identity.id,
                    state=video_state(_VIDEO_WAIT_SOURCE_STAGE),
                )
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Референс потерялся. Пришли фото или видео ещё раз.",
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

        if stage == _VIDEO_CONFIRM_STAGE:
            text = str(event.text or "").strip()
            if not text:
                return False
            draft = await generation.get_instagram_draft(identity.id)
            if draft is None:
                await self.enter_video_paywall(identity, event)
                return True
            return await self._handle_video_confirmation(
                identity,
                event,
                draft,
                media_type,
                generation._normalized_reply(text),
            )

        await self.enter_video_paywall(identity, event)
        return True

    async def _handle_video_confirmation(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
        draft: generation.InstagramDraft,
        media_type: str,
        normalized: str,
    ) -> bool:
        if normalized in generation._CANCEL_WORDS:
            await generation.update_instagram_draft(
                identity.id,
                prompt="",
                state=video_state(_VIDEO_WAIT_PROMPT_STAGE, media_type),
            )
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Отменил. Референс сохранил — можешь написать новый запрос.",
            )
            return True
        if normalized not in generation._CONFIRM_WORDS:
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
        draft: generation.InstagramDraft,
        prompt: str,
        media_type: str,
        account_id: str,
        recipient_id: str,
    ) -> None:
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=VIDEO_DURATION_SECONDS)
        if billing is None:
            await generation.update_instagram_draft(
                identity.id,
                prompt="",
                state=video_state(_VIDEO_PAYWALL_STAGE),
                clear_image=True,
            )
            event = InstagramEvent(
                event_id="video-paywall",
                kind="message",
                account_id=account_id,
                sender_id=recipient_id,
            )
            await self.enter_video_paywall(identity, event)
            return

        _user_id, _telegram_id, credits = billing
        if credits < cost:
            await generation.update_instagram_draft(
                identity.id,
                prompt="",
                state=video_state(_VIDEO_PAYWALL_STAGE),
                clear_image=True,
            )
            event = InstagramEvent(
                event_id="video-paywall",
                kind="message",
                account_id=account_id,
                sender_id=recipient_id,
            )
            await self.enter_video_paywall(identity, event)
            return

        await generation.update_instagram_draft(
            identity.id,
            prompt=prompt,
            state=video_state(_VIDEO_CONFIRM_STAGE, media_type),
        )
        price_rub = round(cost * float(preset_manager.get_credit_rub_value()), 2)
        await self.client.send_text(
            account_id,
            recipient_id,
            f"Seedance 2.5 • {VIDEO_DURATION_SECONDS} сек • {cost:g} 🐾 "
            f"({price_rub:g} ₽). Баланс: {credits:g} 🐾.\n\n"
            "Ответь ДА для запуска или НЕТ для отмены.",
        )

    async def _enqueue_paid_video(
        self,
        identity: ChannelIdentity,
        draft: generation.InstagramDraft,
        media_type: str,
        account_id: str,
        recipient_id: str,
    ) -> None:
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=VIDEO_DURATION_SECONDS)
        if billing is None:
            event = InstagramEvent(
                event_id="video-paywall",
                kind="message",
                account_id=account_id,
                sender_id=recipient_id,
            )
            await self.enter_video_paywall(identity, event)
            return

        user_id, telegram_id, _credits = billing
        job = generation.InstagramGenerationJob(
            id=uuid.uuid4().hex,
            identity_id=identity.id,
            account_id=account_id,
            recipient_id=recipient_id,
            image_url=draft.image_url,
            prompt=draft.prompt,
            model=f"{INSTAGRAM_VIDEO_MODEL.product_key}:{media_type}",
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
        await generation._insert_job(job, status="prepared")
        if not await deduct_credits(telegram_id, cost):
            await generation._mark_job_failed(job.id, "insufficient_balance")
            event = InstagramEvent(
                event_id="video-paywall",
                kind="message",
                account_id=account_id,
                sender_id=recipient_id,
            )
            await self.enter_video_paywall(identity, event)
            return
        try:
            await generation._activate_job(job.id)
        except Exception:
            await add_credits(telegram_id, cost)
            await generation._mark_job_failed(job.id, "activation_failed")
            raise

        await generation.update_instagram_draft(
            identity.id,
            state=video_state(_VIDEO_GENERATING_STAGE, media_type),
        )
        await self.client.send_text(
            account_id,
            recipient_id,
            f"{cost:g} 🐾 списано ✅ Запускаю Seedance 2.5.",
        )
        logger.info("Instagram Seedance 2.5 job queued: job=%s user=%s", job.id, user_id)

    async def _generate_result(self, job: generation.InstagramGenerationJob) -> str:
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
                callBackUrl=None,
            )
            if not isinstance(response, dict):
                raise generation.InstagramGenerationRetry(
                    "Seedance 2.5 did not accept the generation"
                )
            task_id = str(response.get("task_id") or "").strip()
            if not task_id:
                message = str(
                    response.get("error")
                    or response.get("message")
                    or "Seedance 2.5 returned no task"
                )
                if response.get("error") in {"network_error", "invalid_json"}:
                    raise generation.InstagramGenerationRetry(message)
                raise RuntimeError(message)
            await generation._mark_job_provider_task(job.id, task_id)
        return await self._wait_seedance_result(task_id)

    async def _wait_seedance_result(self, task_id: str) -> str:
        consecutive_errors = 0
        for _ in range(_PROVIDER_POLL_ATTEMPTS):
            status = await seedance_25_service.get_task_status(task_id)
            if not isinstance(status, dict):
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    raise generation.InstagramGenerationRetry(
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
        raise generation.InstagramGenerationRetry("Seedance 2.5 is still processing")

    async def _process_job(self, job: generation.InstagramGenerationJob) -> None:
        if not self._is_video_job(job):
            await super()._process_job(job)
            return

        result_url = str(job.result_url or "").strip()
        if not result_url:
            try:
                result_url = await self._generate_result(job)
                if not result_url:
                    raise RuntimeError("Seedance 2.5 returned an empty URL")
                await generation._mark_job_result(job.id, result_url, job.provider_task_id)
            except generation.InstagramGenerationRetry as error:
                if job.provider_task_id is None and job.attempt_count >= 5:
                    await self._finalize_failure(job, error)
                else:
                    await generation._retry_job(job.id, str(error))
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
                delivered_at = await generation._mark_job_delivered(job.id)
            except Exception as error:
                logger.exception("Instagram video delivery failed: job=%s", job.id)
                await generation._retry_job(job.id, str(error))
                return

        try:
            await self._finalize_success(job)
        except Exception as error:
            logger.exception(
                "Instagram video finalization failed: job=%s delivered_at=%s",
                job.id,
                delivered_at,
            )
            await generation._retry_job(job.id, str(error))

    async def _finalize_failure(
        self,
        job: generation.InstagramGenerationJob,
        error: Exception,
    ) -> None:
        await super()._finalize_failure(job, error)
        if self._is_video_job(job):
            media_type = job.model.rsplit(":", 1)[-1]
            with contextlib.suppress(Exception):
                await generation.update_instagram_draft(
                    job.identity_id,
                    state=video_state(_VIDEO_WAIT_PROMPT_STAGE, media_type),
                )

    async def _finalize_success(self, job: generation.InstagramGenerationJob) -> None:
        if not self._is_video_job(job):
            await super()._finalize_success(job)
            return

        await generation._mark_job_succeeded(job.id)
        with contextlib.suppress(Exception):
            await generation.update_instagram_draft(
                job.identity_id,
                prompt="",
                state="idle",
                clear_image=True,
            )

        billing = await generation._linked_billing_user(job.identity_id)
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
                "Готово 🎬 Чтобы сделать ещё видео, снова выбери «Видео». "
                "Перед загрузкой нового референса предложу пополнить баланс.",
            )

    @staticmethod
    def _is_video_job(job: generation.InstagramGenerationJob) -> bool:
        return job.model.startswith(f"{INSTAGRAM_VIDEO_MODEL.product_key}:")
