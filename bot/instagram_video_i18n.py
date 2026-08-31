from __future__ import annotations

import contextlib
import uuid

from bot import instagram_generation as generation
from bot import instagram_video_generation as video
from bot.channel_identity import ChannelIdentity
from bot.database import add_credits, add_generation_history, deduct_credits
from bot.instagram_api import InstagramEvent
from bot.instagram_i18n import resolve_instagram_language, tr
from bot.instagram_model_contract import INSTAGRAM_VIDEO_MODEL, instagram_video_cost
from bot.services.preset_manager import preset_manager

_CONTINUE_WORDS = {"продолжить", "continue"}


class LocalizedInstagramVideoGenerationService(video.InstagramVideoGenerationService):
    """RU/EN UX wrapper over the durable paid-only Seedance 2.5 service."""

    async def enter_video_paywall(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> None:
        await generation.update_instagram_draft(
            identity.id,
            prompt="",
            state=video.video_state(video._VIDEO_PAYWALL_STAGE),
            clear_image=True,
        )
        language = await resolve_instagram_language(identity.id, event.text)
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=video.VIDEO_DURATION_SECONDS)
        price_rub = round(cost * float(preset_manager.get_credit_rub_value()), 2)
        link = await self._account_link_url(identity)

        balance_note = ""
        if billing is not None:
            _user_id, _telegram_id, credits = billing
            balance_note = tr(language, "video_balance", credits=credits)
            if credits >= cost:
                balance_note += tr(language, "video_balance_enough")

        label = "Пополнить и продолжить" if language != "en" else "Top up and continue"
        link_note = f"\n\n{label}: {link}" if link else ""
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            tr(
                language,
                "video_paywall",
                duration=video.VIDEO_DURATION_SECONDS,
                cost=cost,
                price=price_rub,
                balance=balance_note,
                link=link_note,
            ),
        )

    async def _resume_after_topup(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        language = await resolve_instagram_language(identity.id, event.text)
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=video.VIDEO_DURATION_SECONDS)
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
            state=video.video_state(video._VIDEO_WAIT_SOURCE_STAGE),
            clear_image=True,
        )
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            tr(language, "video_balance_ready", cost=cost),
        )
        return True

    async def handle_video_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        language = await resolve_instagram_language(identity.id, event.text)
        draft = await generation.get_instagram_draft(identity.id)
        stage, media_type = video.video_state_parts(draft.state if draft else "")
        normalized = generation._normalized_reply(str(event.text or ""))
        incoming_media_type, media_url = video.message_media(event)

        if not stage or stage == video._VIDEO_PAYWALL_STAGE:
            if normalized in _CONTINUE_WORDS:
                return await self._resume_after_topup(identity, event)
            if stage == video._VIDEO_PAYWALL_STAGE:
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "video_topup_required"),
                )
                return True
            await self.enter_video_paywall(identity, event)
            return True

        if stage == video._VIDEO_GENERATING_STAGE:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, "video_running"),
            )
            return True

        if stage == video._VIDEO_WAIT_SOURCE_STAGE:
            if not media_url:
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "video_send_reference"),
                )
                return True
            await generation.save_instagram_image_draft(identity.id, media_url)
            await generation.update_instagram_draft(
                identity.id,
                state=video.video_state(
                    video._VIDEO_WAIT_PROMPT_STAGE,
                    incoming_media_type,
                ),
            )
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, "video_reference_received"),
            )
            return True

        if stage == video._VIDEO_WAIT_PROMPT_STAGE:
            if media_url:
                await generation.save_instagram_image_draft(identity.id, media_url)
                await generation.update_instagram_draft(
                    identity.id,
                    state=video.video_state(
                        video._VIDEO_WAIT_PROMPT_STAGE,
                        incoming_media_type,
                    ),
                )
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "video_reference_replaced"),
                )
                return True
            text = str(event.text or "").strip()
            if not text:
                return False
            draft = await generation.get_instagram_draft(identity.id)
            if draft is None or not draft.image_url:
                await generation.update_instagram_draft(
                    identity.id,
                    state=video.video_state(video._VIDEO_WAIT_SOURCE_STAGE),
                )
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "video_reference_lost"),
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

        if stage == video._VIDEO_CONFIRM_STAGE:
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
        language = await resolve_instagram_language(identity.id, event.text)
        if normalized in generation._CANCEL_WORDS:
            await generation.update_instagram_draft(
                identity.id,
                prompt="",
                state=video.video_state(video._VIDEO_WAIT_PROMPT_STAGE, media_type),
            )
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, "video_cancelled"),
            )
            return True
        if normalized not in generation._CONFIRM_WORDS:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, "confirm_yes_no"),
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
        language = await resolve_instagram_language(identity.id)
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=video.VIDEO_DURATION_SECONDS)
        if billing is None:
            await generation.update_instagram_draft(
                identity.id,
                prompt="",
                state=video.video_state(video._VIDEO_PAYWALL_STAGE),
                clear_image=True,
            )
            await self.enter_video_paywall(
                identity,
                InstagramEvent(
                    event_id="video-paywall",
                    kind="message",
                    account_id=account_id,
                    sender_id=recipient_id,
                ),
            )
            return

        _user_id, _telegram_id, credits = billing
        if credits < cost:
            await generation.update_instagram_draft(
                identity.id,
                prompt="",
                state=video.video_state(video._VIDEO_PAYWALL_STAGE),
                clear_image=True,
            )
            await self.enter_video_paywall(
                identity,
                InstagramEvent(
                    event_id="video-paywall",
                    kind="message",
                    account_id=account_id,
                    sender_id=recipient_id,
                ),
            )
            return

        await generation.update_instagram_draft(
            identity.id,
            prompt=prompt,
            state=video.video_state(video._VIDEO_CONFIRM_STAGE, media_type),
        )
        price_rub = round(cost * float(preset_manager.get_credit_rub_value()), 2)
        await self.client.send_text(
            account_id,
            recipient_id,
            tr(
                language,
                "video_offer",
                duration=video.VIDEO_DURATION_SECONDS,
                cost=cost,
                price=price_rub,
                credits=credits,
            ),
        )

    async def _enqueue_paid_video(
        self,
        identity: ChannelIdentity,
        draft: generation.InstagramDraft,
        media_type: str,
        account_id: str,
        recipient_id: str,
    ) -> None:
        language = await resolve_instagram_language(identity.id)
        billing = await generation._linked_billing_user(identity.id)
        cost = instagram_video_cost(duration=video.VIDEO_DURATION_SECONDS)
        if billing is None:
            await self.enter_video_paywall(
                identity,
                InstagramEvent(
                    event_id="video-paywall",
                    kind="message",
                    account_id=account_id,
                    sender_id=recipient_id,
                ),
            )
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
            await self.enter_video_paywall(
                identity,
                InstagramEvent(
                    event_id="video-paywall",
                    kind="message",
                    account_id=account_id,
                    sender_id=recipient_id,
                ),
            )
            return
        try:
            await generation._activate_job(job.id)
        except Exception:
            await add_credits(telegram_id, cost)
            await generation._mark_job_failed(job.id, "activation_failed")
            raise

        await generation.update_instagram_draft(
            identity.id,
            state=video.video_state(video._VIDEO_GENERATING_STAGE, media_type),
        )
        await self.client.send_text(
            account_id,
            recipient_id,
            tr(language, "video_started", cost=cost),
        )
        video.logger.info(
            "Instagram Seedance 2.5 job queued: job=%s user=%s",
            job.id,
            user_id,
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
        language = await resolve_instagram_language(job.identity_id)
        with contextlib.suppress(Exception):
            await self.client.send_text(
                job.account_id,
                job.recipient_id,
                tr(language, "video_done"),
            )
