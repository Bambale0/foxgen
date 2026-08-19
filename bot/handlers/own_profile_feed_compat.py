from __future__ import annotations

from typing import Any

_INSTALLED = False


def _normalized_referral_code(value: Any) -> str:
    return str(value or "").strip().upper()


def install_own_profile_feed_compat() -> None:
    """Make the authenticated user authoritative for their own profile feed.

    A direct generation link is resolved by generation id, while the profile grid
    historically resolved the author again through a referral code. If duplicate
    or stale referral data exists, those two paths can point at different user
    rows. For the viewer's own referral code, use the already-authenticated user
    from Mini App init data instead.
    """

    global _INSTALLED
    if _INSTALLED:
        return

    from bot import miniapp as miniapp_module

    async def miniapp_profile_feed(request: Any):
        try:
            body = await miniapp_module._miniapp_payload(request)
            init_data = body.get("init_data", "")
            referral_code = _normalized_referral_code(body.get("referral_code"))
            limit = miniapp_module._bounded_int(
                body.get("limit"),
                default=80,
                maximum=999999,
            )
            offset = miniapp_module._bounded_int(
                body.get("offset"),
                default=0,
                minimum=0,
                maximum=999999,
            )
            if not referral_code:
                return miniapp_module.web.json_response(
                    {"ok": False, "error": "Не указан профиль"},
                    status=400,
                )

            telegram_id, ctx = await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            viewer = ctx["user"]
            viewer_referral_code = _normalized_referral_code(
                getattr(viewer, "referral_code", "")
            )

            if viewer_referral_code and referral_code == viewer_referral_code:
                author = viewer
            else:
                author = await miniapp_module.get_user_by_referral_code(referral_code)

            if not author:
                return miniapp_module.web.json_response(
                    {"ok": False, "error": "Профиль не найден"},
                    status=404,
                )

            feed = await miniapp_module.get_user_feed_generations(
                author.id,
                limit=limit,
                offset=offset,
                profile_visible_only=True,
                include_unavailable=True,
            )
            feed_summary = await miniapp_module.get_user_feed_summary(author.id)
            is_mine = bool(author.id == viewer.id)
            is_admin = miniapp_module.config.is_admin(telegram_id)
            for item in feed:
                item["is_mine"] = is_mine
                if is_admin:
                    item["can_remove"] = True
                if is_admin or is_mine:
                    item["can_blur"] = True

            me = await request.app["bot"].get_me()
            profile = miniapp_module._miniapp_profile_payload(
                author,
                me.username or "",
                viewer_user_id=viewer.id,
                feed_summary=feed_summary,
            )
            response = miniapp_module.web.json_response(
                {"ok": True, "profile": profile, "feed": feed}
            )
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            return response
        except Exception as error:  # noqa: BLE001 - API boundary returns JSON
            return miniapp_module._miniapp_error_response(
                error,
                log_message="Mini App own profile feed failed",
            )

    miniapp_module.miniapp_profile_feed = miniapp_profile_feed
    _INSTALLED = True
