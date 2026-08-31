from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from bot.channel_identity import ChannelIdentity, ensure_channel_identity
from bot.channel_promotions import (
    ChannelPromotionStatus,
    ensure_instagram_first_image_promotion,
)
from bot.instagram_api import InstagramClient, InstagramEvent, InstagramSettings
from bot.instagram_generation import InstagramGenerationService
from bot.instagram_i18n import (
    detect_instagram_language,
    resolve_instagram_language,
    tr,
)

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


async def _resolve_language_safe(identity_id: int, text: str | None) -> str:
    try:
        return await resolve_instagram_language(identity_id, text)
    except sqlite3.IntegrityError as error:
        logger.warning(
            "Instagram language preference could not be persisted: identity=%s error=%s",
            identity_id,
            error,
        )
        return detect_instagram_language(text)


def _choice_text(language: str) -> str:
    key = "ask_kind" if language else "ask_kind_bilingual"
    text = tr(language, key)
    if language == "en":
        return text + "\n\nYour first photo is free 🎁; video is paid."
    if language == "ru":
        return text + "\n\nПервое фото бесплатно 🎁, видео — платно."
    return text + "\n\n📸 Seedream 5 Pro\n🎬 Seedance 2.5"


def _account_link_text(language: str, suffix: str) -> str:
    if language == "en":
        return tr(language, "account_link", suffix=suffix)
    return (
        "Бесплатная первая фото-генерация уже использована ✅ "
        "Следующие генерации оплачиваются по обычным ценам HappyFox. "
        "Привяжи Instagram к HappyFox, чтобы использовать общий баланс и историю."
        + suffix
    )


class InstagramChannelAdapter:
    """Instagram UX adapter; billing/generation are delegated to durable services."""

    def __init__(
        self,
        *,
        settings: InstagramSettings,
        client: InstagramClient | Any | None = None,
        identity_resolver: IdentityResolver = ensure_channel_identity,
        promotion_resolver: PromotionResolver = ensure_instagram_first_image_promotion,
        account_link_factory: AccountLinkFactory | None = None,
        generation_service: InstagramGenerationService | Any | None = None,
        comment_keywords: set[str] | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or InstagramClient.from_settings(settings)
        self.identity_resolver = identity_resolver
        self.promotion_resolver = promotion_resolver
        self.account_link_factory = account_link_factory
        self.generation_service = generation_service
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

    async def _handle_comment(
        self,
        event: InstagramEvent,
        identity: ChannelIdentity,
    ) -> None:
        if not self._is_acquisition_comment(event.text):
            return
        comment_id = str(event.payload.get("id") or "").strip()
        if not comment_id:
            logger.warning(
                "Instagram comment event without comment id: %s",
                event.event_id,
            )
            return
        language = await _resolve_language_safe(identity.id, event.text)
        await self.client.private_reply(
            event.account_id,
            comment_id,
            tr(language, "comment_invite"),
        )

    async def _send_account_link(
        self,
        event: InstagramEvent,
        identity: ChannelIdentity,
    ) -> None:
        language = await _resolve_language_safe(identity.id, event.text)
        link = ""
        if self.account_link_factory is not None:
            link = (await self.account_link_factory(identity)).strip()
        suffix = f"\n\n{link}" if link else ""
        await self.client.send_text(
            event.account_id,
            event.sender_id,
            _account_link_text(language, suffix),
        )

    async def _handle_message(
        self,
        event: InstagramEvent,
        identity: ChannelIdentity,
        *,
        first_image_free: bool,
    ) -> None:
        language = await _resolve_language_safe(identity.id, event.text)
        attachments = _message_attachments(event)
        attachment_types = {
            str(item.get("type") or "").strip().lower() for item in attachments
        }
        if "image" in attachment_types:
            key = "photo_received_free" if first_image_free else "photo_received_paid"
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, key),
            )
            return
        if "video" in attachment_types:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                _choice_text(language),
            )
            return

        await self.client.send_text(
            event.account_id,
            event.sender_id,
            _choice_text(language),
        )

    async def _handle_postback(
        self,
        event: InstagramEvent,
        identity: ChannelIdentity,
        *,
        first_image_free: bool,
    ) -> None:
        language = await _resolve_language_safe(identity.id, event.text)
        postback = event.payload.get("postback")
        payload = (
            str(postback.get("payload") or "") if isinstance(postback, dict) else ""
        )
        if payload in {"CREATE_IMAGE", "CREATE_PHOTO"}:
            key = "photo_selected" if first_image_free else "send_photo_first"
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                tr(language, key),
            )
        elif payload in {"CREATE_VIDEO", "CREATE_REEL"}:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                _choice_text(language),
            )

    async def handle_event(self, event: InstagramEvent) -> None:
        if not event.sender_id:
            logger.info("Instagram event has no sender; skipped: %s", event.event_id)
            return

        identity = await self._ensure_identity(event)
        if identity is None:
            return

        await _resolve_language_safe(identity.id, event.text)
        if event.kind == "comments":
            await self._handle_comment(event, identity)
            return

        if (
            event.kind == "message"
            and self.generation_service is not None
            and await self.generation_service.handle_message(identity, event)
        ):
            return

        promotion = await self.promotion_resolver(identity.id)
        first_image_free = promotion.status != "consumed"

        if identity.user_id is None and not first_image_free:
            await self._send_account_link(event, identity)
            return

        if event.kind == "message":
            await self._handle_message(
                event,
                identity,
                first_image_free=first_image_free,
            )
            return
        if event.kind == "postback":
            await self._handle_postback(
                event,
                identity,
                first_image_free=first_image_free,
            )


def build_instagram_event_handler(
    settings: InstagramSettings | None = None,
    *,
    client: InstagramClient | Any | None = None,
    account_link_factory: AccountLinkFactory | None = None,
    generation_service: InstagramGenerationService | Any | None = None,
) -> Callable[[InstagramEvent], Awaitable[None]]:
    adapter = InstagramChannelAdapter(
        settings=settings or InstagramSettings.from_env(),
        client=client,
        account_link_factory=account_link_factory,
        generation_service=generation_service,
    )
    return adapter.handle_event
