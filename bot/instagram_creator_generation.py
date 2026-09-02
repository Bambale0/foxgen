from __future__ import annotations

import contextlib

from bot.channel_identity import ChannelIdentity
from bot.instagram_api import InstagramEvent
from bot.instagram_creation_mode import (
    get_instagram_creation_kind,
    set_instagram_creation_kind,
)
from bot.instagram_generation import get_instagram_draft, update_instagram_draft
from bot.instagram_i18n import resolve_instagram_language, tr
from bot.instagram_model_contract import normalize_instagram_creation_kind
from bot.instagram_seedance25_official import InstagramSeedance25OfficialService
from bot.instagram_seedream_generation import InstagramSeedream5ProService
from bot.instagram_video_generation import video_state_parts
from bot.instagram_video_state import ensure_instagram_video_draft


class InstagramCreatorGenerationService(InstagramSeedance25OfficialService):
    """Choose photo/video first, then delegate to the matching durable flow."""

    async def _ask_creation_kind(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> None:
        language = await resolve_instagram_language(identity.id, event.text)
        key = "ask_kind" if language else "ask_kind_bilingual"
        text = tr(language, key)
        if not language:
            text += "\n\n📸 Seedream 5 Pro\n🎬 Seedance 2.5"
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            text,
        )

    async def _confirm_photo_kind(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> None:
        language = await resolve_instagram_language(identity.id, event.text, allow_switch=True)
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            tr(language, "photo_selected"),
        )

    async def enter_video_paywall(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> None:
        await ensure_instagram_video_draft(identity.id)
        await super().enter_video_paywall(identity, event)

    async def _select_creation_kind(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
        selected_kind: str,
    ) -> bool:
        language = await resolve_instagram_language(identity.id, event.text, allow_switch=True)
        draft = await get_instagram_draft(identity.id)
        if draft is not None:
            video_stage, _media_type = video_state_parts(draft.state)
            seedance_stage = str(draft.state or "").split(":", 1)[1] if str(draft.state or "").startswith("s25:") else ""
            if draft.state == "generating" or video_stage == "generating" or seedance_stage == "generating":
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    tr(language, "generation_busy_switch"),
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
        if selected_kind == "video":
            await self.enter_video_paywall(identity, event)
            return True

        await self._confirm_photo_kind(identity, event)
        return True

    async def handle_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        text = str(event.text or "").strip()
        selected_kind = normalize_instagram_creation_kind(text)
        if selected_kind:
            return await self._select_creation_kind(identity, event, selected_kind)

        await resolve_instagram_language(identity.id, text)
        current_kind = await get_instagram_creation_kind(identity.id)
        if not current_kind:
            await self._ask_creation_kind(identity, event)
            return True

        if current_kind == "photo":
            return await InstagramSeedream5ProService.handle_message(
                self,
                identity,
                event,
            )
        return await self.handle_video_message(identity, event)
