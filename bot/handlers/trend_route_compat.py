"""Register the curated trend runner before Mini App's API catch-all route."""

from __future__ import annotations

from functools import wraps

from aiohttp import web

from bot.config import config
from bot.trend_api import setup_trend_routes


def _miniapp_root() -> str:
    value = str(getattr(config, "MINI_APP_PATH", "") or "/mini-app").strip()
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/") or "/mini-app"


def install_trend_route_compat() -> None:
    """Patch Mini App route setup so the exact trend route cannot be swallowed.

    ``bot.trend_api`` owns ``POST /mini-app/api/trends/run`` but historically its
    setup function was never called from the production app. The generic Mini App
    API catch-all is registered by ``setup_miniapp_routes`` and therefore must come
    after this exact route.
    """

    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_trend_route_compat_installed", False):
        return

    current_setup = miniapp_module.setup_miniapp_routes

    @wraps(current_setup)
    def setup_with_trend_route(app: web.Application) -> None:
        setup_trend_routes(app, _miniapp_root())
        current_setup(app)

    miniapp_module.setup_miniapp_routes = setup_with_trend_route
    miniapp_module._trend_route_compat_installed = True
