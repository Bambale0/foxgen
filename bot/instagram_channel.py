from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from bot.channel_identity import ChannelIdentity, ensure_channel_identity
from bot.channel_promotions import (
    ChannelPromotionStatus,
    ensure_instagram_first_image_promotion,
)
from bot.instagram_api import InstagramClient, InstagramEvent, InstagramSettings

logger = logging.getLogger(__name__)

IdentityResolver = Callable[..., Awaitable[ChannelIdentity]]
AccountLinkFactory = Callable[[ChannelIdentity], Awaitable[str]]
PromotionResolver = Callable[[int], Awaitable[ChannelPromotionStatus]]
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
        promotion_resolver: PromotionResolver = ensure_instagram_first_image_promotion,
        account_link_factory: AccountLinkFactory | None = None,
        comment_keywords: set[str] | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or InstagramClient.from_settings(settings)
        self.identity_resolver = identity_resolver
        self.promotion_resolver = promotion_resolver
        self.account_link_factory = account_link_factory
        self.comment_keywords = {
            item.casefold().strip()
            for item in (comment_keywords or _DEFAULT_COMMENT_KEYWORDS)
            if item.strip()
        }

    @classmethod
    def from_env(cls) -> InstagramChannelAdapter:
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
            logger.warning(
                "Instagram comment event without comment id: %s",
                event.event_id,
            )
            return
        await self.client.private_reply(
            event.account_id,
            comment_id,
            "Привет! 👋 Напиши мне в Direct и пришли фото — первая AI-генерация будет бесплатно 🎁",
        )

    async def _send_account_link(
        self,
        event: InstagramEvent,
        identity: ChannelIdentity,
    ) -> None:
        link = ""
        if self.account_link_factory is not None:
            link = (await self.account_link_factory(identity)).strip()
        if link:
            text = (
                "Бесплатная первая генерация уже использована ✅\n\n"
                "Чтобы делать следующие фото и оплачивать их по обычным ценам HappyFox, привяжи Instagram к своему аккаунту.\n\n"
                f"Открой ссылку: {link}\n\n"
                "После подтверждения вернись сюда — продолжим в Direct."
            )
        else:
            text = (
                "Бесплатная первая генерация уже использована ✅\n\n"
                "Для следующих генераций нужна привязка к HappyFox, но ссылка сейчас недоступна. "
                "Попробуй ещё раз чуть позже."
            )
        await self.client.send_text(event.account_id, event.sender_id, text)

    async def _handle_message(self, event: InstagramEvent, *, first_image_free: bool) -> None:
        attachments = _message_attachments(event)
        attachment_types = {
            str(item.get("type") or "").strip().lower() for item in attachments
        }
        if "image" in attachment_types:
            free_line = " Первая генерация будет бесплатно 🎁" if first_image_free else ""
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Фото получил 📸" + free_line + " Теперь напиши, что хочешь с ним сделать — например: «сделай стильную аватарку».",
            )
            return
        if "video" in attachment_types:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Видео получил 🎬 Напиши, какой результат хочешь получить, и я подберу подходящий сценарий.",
            )
            return

        free_line = " Первая генерация фото — бесплатно 🎁" if first_image_free else ""
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            "Привет! Здесь можно делать AI-фото и видео прямо из Direct." + free_line + " Пришли фото и одним сообщением напиши, что хочешь получить.",
        )

    async def _handle_postback(self, event: InstagramEvent, *, first_image_free: bool) -> None:
        postback = event.payload.get("postback")
        payload = (
            str(postback.get("payload") or "") if isinstance(postback, dict) else ""
        )
        if payload == "CREATE_IMAGE":
            free_line = " Первая генерация будет бесплатно 🎁" if first_image_free else ""
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Пришли фото и коротко опиши результат." + free_line,
            )

    async def handle_event(self, event: InstagramEvent) -> None:
        if not event.sender_id:
            logger.info("Instagram event has no sender; skipped: %s", event.event_id)
            return

        identity = await self._ensure_identity(event)
        if identity is None:
            return

        if event.kind == "comments":
            await self._handle_comment(event)
            return

        promotion = await self.promotion_resolver(identity.id)
        first_image_free = promotion.status != "consumed"

        if identity.user_id is None and not first_image_free:
            await self._send_account_link(event, identity)
            return

        if event.kind == "message":
            await self._handle_message(event, first_image_free=first_image_free)
            return
        if event.kind == "postback":
            await self._handle_postback(event, first_image_free=first_image_free)


def build_instagram_event_handler(
    settings: InstagramSettings | None = None,
    *,
    account_link_factory: AccountLinkFactory | None = None,
) -> Callable[[InstagramEvent], Awaitable[None]]:
    adapter = InstagramChannelAdapter(
        settings=settings or InstagramSettings.from_env(),
        account_link_factory=account_link_factory,
    )
    return adapter.handle_event
