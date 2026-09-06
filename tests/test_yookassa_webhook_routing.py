import asyncio
from types import SimpleNamespace

from aiohttp import web

from bot.internal_api import internal_auth_middleware


def _call_middleware(path: str) -> web.Response:
    async def handler(_request):
        return web.Response(status=204)

    request = SimpleNamespace(path=path)
    return asyncio.run(internal_auth_middleware(request, handler))


def test_yookassa_webhook_paths_are_not_retired_by_internal_middleware() -> None:
    for path in ("/yookassa/webhook", "/webhook/yookassa"):
        response = _call_middleware(path)
        assert response.status == 204
