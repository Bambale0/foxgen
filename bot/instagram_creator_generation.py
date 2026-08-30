from __future__ import annotations

import contextlib

from bot.channel_identity import ChannelIdentity
from bot.instagram_api import InstagramEvent
from bot.instagram_creation_mode import (
    get_instagram_creation_kind,
    set_instagram_creation_kind,
)
from bot.instagram_generation import get_instagram_draft, update_instagram_draft
from bot.instagram_model_contract import normalize_instagram_creation_kind
from bot.instagram_seedream_generation import InstagramSeedream5ProService
from bot.instagram_video_generation import (
    InstagramVideoGenerationService,
    video_state_parts,
)


class InstagramCreatorGenerationService(InstagramVideoGenerationService):
    """Choose photo/video first, then delegate to the matching durable flow."""

    async def _ask_creation_kind(self, event: InstagramEvent) -> None:
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            "Что хочешь создать?\n\n"
            "📸 Фото — Seedream 5 Pro\n"
            "🎬 Видео — Seedance 2.5\n\n"
            "Ответь «Фото» или «Видео».",
        )

    async def _confirm_kind(self, event: InstagramEvent, kind: str) -> None:
        if kind == "photo":
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "📸 Фото выбрано. Пришли исходное фото, затем одним сообщением "
                "напиши, что хочешь получить.",
            )
            return
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            "🎬 Видео выбрано. Пришли фото или видео-референс, затем напиши, "
            "что должно происходить в ролике.",
        )

    async def _select_creation_kind(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
        selected_kind: str,
    ) -> bool:
        draft = await get_instagram_draft(identity.id)
        if draft is not None:
            video_stage, _media_type = video_state_parts(draft.state)
            if draft.state == "generating" or video_stage == "generating":
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

    async def handle_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        text = str(event.text or "").strip()
        selected_kind = normalize_instagram_creation_kind(text)
        if selected_kind:
            return await self._select_creation_kind(identity, event, selected_kind)

        current_kind = await get_instagram_creation_kind(identity.id)
        if not current_kind:
            await self._ask_creation_kind(event)
            return True

        if current_kind == "photo":
            return await InstagramSeedream5ProService.handle_message(
                self,
                identity,
                event,
            )
        return await self.handle_video_message(identity, event)
