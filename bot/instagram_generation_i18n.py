from __future__ import annotations

import contextlib

from bot import instagram_generation as generation
from bot.channel_identity import ChannelIdentity
from bot.channel_promotions import ensure_instagram_first_image_promotion
from bot.instagram_api import InstagramEvent
from bot.instagram_i18n import resolve_instagram_language, tr


class InstagramLocalizedGenerationMixin:
    """RU/EN user-facing behavior layered over the durable generation core."""

    async def _send_account_link(
        self,
        identity: ChannelIdentity,
        account_id: str,
        recipient_id: str,
    ) -> None:
        language = await resolve_instagram_language(identity.id)
        link = ""
        if self.account_link_factory is not None:
            link = str(await self.account_link_factory(identity)).strip()
        suffix = f"\n\n{link}" if link else ""
        await self.client.send_text(
            account_id,
            recipient_id,
            tr(language, "account_link", suffix=suffix),
        )

    async def handle_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        language = await resolve_instagram_language(identity.id, event.text)
        image_url = generation._attachment_image_url(event)
        if image_url:
            draft = await generation.get_instagram_draft(identity.id)
            if draft and draft.state == "generating":
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "photo_generation_running"),
                )
                return True
            await generation.save_instagram_image_draft(identity.id, image_url)
            promotion = await ensure_instagram_first_image_promotion(identity.id)
            key = (
                "photo_received_free"
                if promotion.status != "consumed"
                else "photo_received_paid"
            )
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, key),
            )
            return True

        text = str(event.text or "").strip()
        if not text:
            return False
        draft = await generation.get_instagram_draft(identity.id)
        if draft is None or not draft.image_url:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, "send_photo_first"),
            )
            return True

        normalized = generation._normalized_reply(text)
        if draft.state == "generating":
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, "generation_running"),
            )
            return True

        if draft.state == "awaiting_confirmation":
            if normalized in generation._CANCEL_WORDS:
                await generation.update_instagram_draft(
                    identity.id,
                    prompt="",
                    state="waiting_prompt",
                )
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "cancelled_keep_photo"),
                )
                return True
            if normalized not in generation._CONFIRM_WORDS:
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "confirm_yes_no"),
                )
                return True
            await self._enqueue_paid(
                identity,
                draft,
                event.account_id,
                event.sender_id,
            )
            return True

        if draft.state == "awaiting_link":
            if identity.user_id is None:
                await self._send_account_link(
                    identity,
                    event.account_id,
                    event.sender_id,
                )
                return True
            await self._offer_paid_generation(
                identity,
                draft,
                draft.prompt or text,
                event.account_id,
                event.sender_id,
            )
            return True

        promotion = await ensure_instagram_first_image_promotion(identity.id)
        if promotion.status != "consumed":
            if await self._enqueue_free(
                identity,
                draft,
                text,
                event.account_id,
                event.sender_id,
            ):
                return True
            promotion = await ensure_instagram_first_image_promotion(identity.id)
            if promotion.status != "consumed":
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "free_already_starting"),
                )
                return True

        await self._offer_paid_generation(
            identity,
            draft,
            text,
            event.account_id,
            event.sender_id,
        )
        return True

    async def _finalize_failure(
        self,
        job: generation.InstagramGenerationJob,
        error: Exception,
    ) -> None:
        if job.billing_mode == "free" and job.promotion_reservation_key:
            await generation.release_instagram_first_image(job.promotion_reservation_key)
        elif job.billing_mode == "credits" and job.telegram_id and job.cost > 0:
            await generation.add_credits(job.telegram_id, job.cost)
        await generation._mark_job_failed(job.id, str(error))
        with contextlib.suppress(Exception):
            await generation.update_instagram_draft(job.identity_id, state="waiting_prompt")
        language = await resolve_instagram_language(job.identity_id)
        key = (
            "generation_failed_free"
            if job.billing_mode == "free"
            else "generation_failed_paid"
        )
        with contextlib.suppress(Exception):
            await self.client.send_text(
                job.account_id,
                job.recipient_id,
                tr(language, key),
            )
