import asyncio
from types import SimpleNamespace

from bot.services.bot_identity_cache import (
    clear_bot_identity_cache,
    get_bot_me_cached,
)


class _FakeBot:
    id = 123456

    def __init__(self) -> None:
        self.calls = 0

    async def get_me(self):
        self.calls += 1
        await asyncio.sleep(0)
        return SimpleNamespace(username="happyfox_test_bot")


def test_bot_identity_cache_coalesces_concurrent_requests() -> None:
    async def run() -> None:
        clear_bot_identity_cache()
        bot = _FakeBot()
        results = await asyncio.gather(*(get_bot_me_cached(bot) for _ in range(8)))
        assert bot.calls == 1
        assert {item.username for item in results} == {"happyfox_test_bot"}

        again = await get_bot_me_cached(bot)
        assert again.username == "happyfox_test_bot"
        assert bot.calls == 1

        clear_bot_identity_cache(bot)
        await get_bot_me_cached(bot)
        assert bot.calls == 2

    asyncio.run(run())
