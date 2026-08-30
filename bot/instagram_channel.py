from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from bot.channel_identity import ChannelIdentity, ensure_channel_identity
from bot.instagram_api import InstagramClient, InstagramEvent, InstagramSettings

logger = logging.getLogger(__name__)

IdentityResolver = Callable[..., Awaitable[ChannelIdentity]]
_DEFAULT_COMMENT_KEYWORDS = {"хочу", "want", "try", "попробовать"}


def _normalized_words(value: str) -> set[str]:
    return {
        part
        for part in re.split(r"[^0-9a-zа-яё]+", str(value or "").casefold())
        if part
    }


def _profile_from_event(event: InstagramEvent) -> tuple[str, str]:
    source = event.payload.get("from")
    if not isinstance(source, dict):
        return "", ""
    username = str(source.get("username") or "").strip()
    display_name = str(source.get("name") or "").strip()
    return username, display_name


def _message_attachments(event: InstagramEvent) -> list[dict[str, Any]]:
    message = event.payload.get("message")
    if not isinstance(message, dict):
        return []
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return []
    return [item for item in attachments if isinstance(item, dict)]


class InstagramChannelAdapter:
    """Thin Instagram UX adapter; generation and billing stay outside this module."""

    def __init__(
        self,
        *,
        settings: InstagramSettings,
        client: InstagramClient | Any | None = None,
        identity_resolver: IdentityResolver = ensure_channel_identity,
        comment_keywords: set[str] | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or InstagramClient.from_settings(settings)
        self.identity_resolver = identity_resolver
        self.comment_keywords = {
            item.casefold().strip()
            for item in (comment_keywords or _DEFAULT_COMMENT_KEYWORDS)
            if item.strip()
        }

    @classmethod
    def from_env(cls) -> "InstagramChannelAdapter":
        return cls(settings=InstagramSettings.from_env())

    async def _ensure_identity(self, event: InstagramEvent) -> ChannelIdentity | None:
        if not event.sender_id:
            return None
        username, display_name = _profile_from_event(event)
        return await self.identity_resolver(
            channel="instagram",
            account_id=event.account_id,
            external_user_id=event.sender_id,
            username=username,
            display_name=display_name,
        )

    def _is_acquisition_comment(self, text: str) -> bool:
        return bool(_normalized_words(text) & self.comment_keywords)

    async def _handle_comment(self, event: InstagramEvent) -> None:
        if not self._is_acquisition_comment(event.text):
            return
        comment_id = str(event.payload.get("id") or "").strip()
        if not comment_id:
            logger.warning("Instagram comment event without comment id: %s", event.event_id)
            return
        await self.client.private_reply(
            event.account_id,
            comment_id,
            "Привет! 👋 Напиши мне в Direct и пришли фото — помогу сделать AI-версию в HappyFox.",
        )

    async def _handle_message(self, event: InstagramEvent) -> None:
        attachments = _message_attachments(event)
        attachment_types = {
            str(item.get("type") or "").strip().lower() for item in attachments
        }
        if "image" in attachment_types:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Фото получил 📸 Теперь напиши, что хочешь с ним сделать — например: «сделай стильную аватарку».",
            )
            return
        if "video" in attachment_types:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Видео получил 🎬 Напиши, какой результат хочешь получить, и я подберу подходящий сценарий.",
            )
            return

        await self.client.send_text(
            event.account_id,
            event.sender_id,
            "Привет! Здесь можно делать AI-фото и видео прямо из Direct. Пришли фото и одним сообщением напиши, что хочешь получить.",
        )

    async def _handle_postback(self, event: InstagramEvent) -> None:
        postback = event.payload.get("postback")
        payload = str(postback.get("payload") or "") if isinstance(postback, dict) else ""
        if payload == "CREATE_IMAGE":
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Пришли фото и коротко опиши результат. Я подхвачу их как один запрос.",
            )

    async def handle_event(self, event: InstagramEvent) -> None:
        if not event.sender_id:
            logger.info("Instagram event has no sender; skipped: %s", event.event_id)
            return

        await self._ensure_identity(event)

        if event.kind == "comments":
            await self._handle_comment(event)
            return
        if event.kind == "message":
            await self._handle_message(event)
            return
        if event.kind == "postback":
            await self._handle_postback(event)


def build_instagram_event_handler(
    settings: InstagramSettings | None = None,
) -> Callable[[InstagramEvent], Awaitable[None]]:
    adapter = InstagramChannelAdapter(settings=settings or InstagramSettings.from_env())
    return adapter.handle_event
