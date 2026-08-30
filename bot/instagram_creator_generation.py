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
from bot.instagram_creation_mode import (
    get_instagram_creation_kind,
    set_instagram_creation_kind,
)
from bot.instagram_generation import (
    InstagramDraft,
    InstagramGenerationJob,
    InstagramGenerationRetry,
    _CANCEL_WORDS,
    _CONFIRM_WORDS,
    _activate_job,
    _claim_next_job,
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
from bot.instagram_model_contract import (
    INSTAGRAM_VIDEO_MODEL,
    instagram_video_cost,
    normalize_instagram_creation_kind,
)
from bot.instagram_seedream_generation import InstagramSeedream5ProService
from bot.services.preset_manager import preset_manager
from bot.services.seedance_25_service import seedance_25_service

logger = logging.getLogger(__name__)
_VIDEO_DURATION = 5
_VIDEO_SUCCESS_STATES = {"success", "succeeded", "completed", "done"}
_VIDEO_FAILURE_STATES = {"fail", "failed", "error", "cancelled", "canceled"}
_PROVIDER_POLL_SECONDS = 5.0
_PROVIDER_POLL_ATTEMPTS = 120


def _message_media(event: InstagramEvent) -> tuple[str, str]:
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
        url = str(payload.get("url") or "").strip()
        if url:
            return media_type, url
    return "", ""


def _video_state(stage: str, media_type: str) -> str:
    return f"video:{stage}:{media_type}"


def _video_state_parts(state: str) -> tuple[str, str]:
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


class InstagramCreatorGenerationService(InstagramSeedream5ProService):
    """One durable Instagram creator flow for Seedream 5 Pro and Seedance 2.5."""

    async def _ask_creation_kind(self, event: InstagramEvent) -> None:
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            "Что хочешь создать?\n\n📸 Фото — Seedream 5 Pro\n🎬 Видео — Seedance 2.5\n\nОтветь «Фото» или «Видео».",
        )

    async def _confirm_kind(self, event: InstagramEvent, kind: str) -> None:
        if kind == "photo":
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "📸 Фото выбрано. Пришли исходное фото, затем одним сообщением напиши, что хочешь получить.",
            )
            return
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            "🎬 Видео выбрано. Пришли фото или видео-референс, затем напиши, что должно происходить в ролике.",
        )

    async def handle_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        text = str(event.text or "").strip()
        selected_kind = normalize_instagram_creation_kind(text)
        current_kind = await get_instagram_creation_kind(identity.id)

        if selected_kind:
            draft = await get_instagram_draft(identity.id)
            if draft is not None:
                stage, _media_type = _video_state_parts(draft.state)
                if draft.state == "generating" or stage == "generating":
                    await self.client.send_text(
                        event.account_id,
                        event.sender_id,
                        "Сначала закончу текущую генерацию, потом можно переключить тип.",
                    )
                    return True
                with contextlib.suppress(Exception):
                    await update_instagram_draft(
                        identity.id,
                        prompt="",
                        state="idle",
                        clear_image=True,
                    )
            await set_instagram_creation_kind(identity.id, selected_kind)
            await self._confirm_kind(event, selected_kind)
            return True

        if not current_kind:
            await self._ask_creation_kind(event)
            return True

        if current_kind == "photo":
            return await super().handle_message(identity, event)
        return await self._handle_video_message(identity, event)

    async def _handle_video_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        media_type, media_url = _message_media(event)
        if media_url:
            draft = await get_instagram_draft(identity.id)
            if draft is not None:
                stage, _ = _video_state_parts(draft.state)
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
                state=_video_state("waiting_prompt", media_type),
            )
            promotion = await ensure_instagram_first_image_promotion(identity.id)
            free_line = (
                " Первая генерация будет бесплатно 🎁"
                if promotion.status != "consumed"
                else ""
            )
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                ("Фото" if media_type == "image" else "Видео")
                + " получил 🎬."
                + free_line
                + " Теперь напиши, что должно происходить в ролике.",
            )
            return True

        text = str(event.text or "").strip()
        if not text:
            return False
        draft = await get_instagram_draft(identity.id)
        if draft is None or not draft.image_url:
            if _normalized_reply(text) in _CONFIRM_WORDS:
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Продолжаем 🎬 Пришли фото или видео-референс для Seedance 2.5.",
                )
            else:
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Сначала пришли фото или видео-референс 🎬.",
                )
            return True

        stage, media_type = _video_state_parts(draft.state)
        normalized = _normalized_reply(text)
        if stage == "generating":
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Seedance 2.5 уже создаёт ролик. Результат пришлю сюда автоматически.",
            )
            return True

        if stage == "awaiting_confirmation":
            if normalized in _CANCEL_WORDS:
                await update_instagram_draft(
                    identity.id,
                    prompt="",
                    state=_video_state("waiting_prompt", media_type),
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
                state=_video_state("awaiting_link", media_type),
            )
            await self._send_account_link(identity, account_id, recipient_id)
            return

        _user_id, _telegram_id, credits = billing
        cost = instagram_video_cost(duration=_VIDEO_DURATION)
        await update_instagram_draft(
            identity.id,
            prompt=prompt,
            state=_video_state("awaiting_confirmation", media_type),
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
            f"Seedance 2.5 • {_VIDEO_DURATION} сек • {cost:g} 🐾 ({price_rub:g} ₽). "
            f"Баланс: {credits:g} 🐾.{action}",
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
        job = InstagramGenerationJob(
            id=job_id,
            identity_id=identity.id,
            account_id=account_id,
            recipient_id=recipient_id,
            image_url=draft.image_url,
            prompt=prompt,
            model=f"{INSTAGRAM_VIDEO_MODEL.product_key}:{media_type}",
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
            state=_video_state("generating", media_type),
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
                state=_video_state("awaiting_link", media_type),
            )
            await self._send_account_link(identity, account_id, recipient_id)
            return
        user_id, telegram_id, _credits = billing
        cost = instagram_video_cost(duration=_VIDEO_DURATION)
        job = InstagramGenerationJob(
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
            state=_video_state("generating", media_type),
        )
        await self.client.send_text(
            account_id,
            recipient_id,
            f"{cost:g} 🐾 списано ✅ Запускаю Seedance 2.5.",
        )
        logger.info("Instagram Seedance 2.5 job queued: job=%s user=%s", job.id, user_id)

    async def _generate_result(self, job: InstagramGenerationJob) -> str:
        if not job.model.startswith(f"{INSTAGRAM_VIDEO_MODEL.product_key}:"):
            return await super()._generate_result(job)

        media_type = job.model.rsplit(":", 1)[-1]
        task_id = str(job.provider_task_id or "").strip()
        if not task_id:
            response = await seedance_25_service.generate_video(
                prompt=job.prompt,
                duration=_VIDEO_DURATION,
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
                message = str(response.get("error") or response.get("message") or "Seedance 2.5 returned no task")
                if response.get("error") in {"network_error", "invalid_json"}:
                    raise InstagramGenerationRetry(message)
                raise RuntimeError(message)
            await _mark_job_provider_task(job.id, task_id)

        consecutive_errors = 0
        for _ in range(_PROVIDER_POLL_ATTEMPTS):
            status = await seedance_25_service.get_task_status(task_id)
            if not isinstance(status, dict):
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    raise InstagramGenerationRetry("Seedance 2.5 status is temporarily unavailable")
                await asyncio.sleep(_PROVIDER_POLL_SECONDS)
                continue
            consecutive_errors = 0
            data = status.get("data") if isinstance(status.get("data"), dict) else {}
            state = str(data.get("status") or "").strip().lower()
            if state in _VIDEO_SUCCESS_STATES:
                url = _status_output_url(status)
                if not url:
                    raise RuntimeError("Seedance 2.5 completed without a video URL")
                return url
            if state in _VIDEO_FAILURE_STATES:
                raise RuntimeError("Seedance 2.5 generation failed")
            await asyncio.sleep(_PROVIDER_POLL_SECONDS)
        raise InstagramGenerationRetry("Seedance 2.5 is still processing")

    async def _process_job(self, job: InstagramGenerationJob) -> None:
        is_video = job.model.startswith(f"{INSTAGRAM_VIDEO_MODEL.product_key}:")
        result_url = str(job.result_url or "").strip()
        if not result_url:
            try:
                result_url = await self._generate_result(job)
                if not result_url:
                    raise RuntimeError("Generator returned an empty URL")
                await _mark_job_result(job.id, result_url, job.provider_task_id)
            except InstagramGenerationRetry as error:
                if job.provider_task_id is None and job.attempt_count >= 5:
                    await self._finalize_failure(job, error)
                else:
                    await _retry_job(job.id, str(error))
                return
            except Exception as error:
                logger.exception("Instagram creator generation failed: job=%s", job.id)
                await self._finalize_failure(job, error)
                return

        delivered_at = job.delivered_at_epoch
        if delivered_at is None:
            try:
                await self.client.send_media(
                    job.account_id,
                    job.recipient_id,
                    "video" if is_video else "image",
                    result_url,
                )
                delivered_at = await _mark_job_delivered(job.id)
            except Exception as error:
                logger.exception("Instagram creator delivery failed: job=%s", job.id)
                await _retry_job(job.id, str(error))
                return

        try:
            await self._finalize_success(job)
        except Exception as error:
            logger.exception(
                "Instagram creator finalization failed: job=%s delivered_at=%s",
                job.id,
                delivered_at,
            )
            await _retry_job(job.id, str(error))

    async def _finalize_failure(self, job: InstagramGenerationJob, error: Exception) -> None:
        await super()._finalize_failure(job, error)
        if job.model.startswith(f"{INSTAGRAM_VIDEO_MODEL.product_key}:"):
            media_type = job.model.rsplit(":", 1)[-1]
            with contextlib.suppress(Exception):
                await update_instagram_draft(
                    job.identity_id,
                    state=_video_state("waiting_prompt", media_type),
                )

    async def _finalize_success(self, job: InstagramGenerationJob) -> None:
        if not job.model.startswith(f"{INSTAGRAM_VIDEO_MODEL.product_key}:"):
            await super()._finalize_success(job)
            return

        if job.billing_mode == "free" and job.promotion_reservation_key:
            if not await consume_instagram_first_image(job.promotion_reservation_key):
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
                        "instagram_seedance_2_5",
                        job.prompt,
                        job.cost,
                    )
            with contextlib.suppress(Exception):
                await self.client.send_text(
                    job.account_id,
                    job.recipient_id,
                    "Готово 🎬 Хочешь ещё — пришли новый референс или напиши «Фото», чтобы переключиться.",
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
                "Чтобы продолжить, пополни баланс тем же способом, что в Telegram. "
                "После оплаты вернись сюда и напиши «Продолжить»."
                + suffix,
            )
