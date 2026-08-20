from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_INSTALLED = False


def install_profile_feed_deeplink_compat(common_module) -> None:
    """Open profile-only publications by their ordinary ``feed_*`` bot link.

    Profile publications deliberately do not belong to the discovery feed.  The
    legacy deep-link renderer first searches the discovery feed and can then
    reject a valid profile-only card when the author's profile carousel is
    empty or stale.  Resolve that card directly and render it as a one-item
    profile carousel; subsequent profile navigation continues to use the
    established handlers.
    """

    global _INSTALLED
    if _INSTALLED:
        return

    original_renderer = getattr(common_module, "_render_feed_deeplink", None)
    get_profile_card = getattr(common_module, "get_profile_generation_card", None)
    render_carousel = getattr(common_module, "_render_feed_carousel", None)
    if not all(callable(item) for item in (original_renderer, get_profile_card, render_carousel)):
        logger.warning("Profile publication deep-link compatibility was not installed")
        return

    async def render_feed_deeplink(
        message,
        user,
        gen_id: str,
        *,
        state=None,
        open_repeat: bool = False,
    ) -> bool:
        viewer_user_id = getattr(user, "id", None)
        try:
            card = await get_profile_card(
                gen_id,
                viewer_user_id=viewer_user_id,
                include_unavailable=True,
            )
        except Exception:
            logger.exception(
                "Failed to resolve profile publication deep link: gen_id=%r viewer_user_id=%r",
                gen_id,
                viewer_user_id,
            )
            card = None

        if card:
            scope = str(card.get("publication_scope") or "").strip().lower()
            is_profile_only = scope == "profile" or (
                bool(card.get("is_profile_visible"))
                and not bool(card.get("is_public_feed"))
            )
            if is_profile_only:
                referral_code = str(
                    card.get("author_referral_code") or ""
                ).strip().upper()
                await render_carousel(
                    message,
                    [card],
                    index=0,
                    source_code="m",
                    profile_code=referral_code or None,
                )
                return True

        return await original_renderer(
            message,
            user,
            gen_id,
            state=state,
            open_repeat=open_repeat,
        )

    common_module._render_feed_deeplink = render_feed_deeplink
    _INSTALLED = True


__all__ = ["install_profile_feed_deeplink_compat"]
