import asyncio
from types import SimpleNamespace

from bot.services.bot_identity_cache import (
    clear_bot_identity_cache,
    install_bot_identity_cache,
)


class _FakeBot:
    def __init__(self) -> None:
        self.calls = 0

    async def get_me(self):
        self.calls += 1
        await asyncio.sleep(0)
        return SimpleNamespace(username="happyfox_test_bot")


def test_bot_identity_cache_coalesces_concurrent_requests() -> None:
    async def run() -> None:
        bot = _FakeBot()
        install_bot_identity_cache(bot)

        results = await asyncio.gather(*(bot.get_me() for _ in range(8)))
        assert bot.calls == 1
        assert {item.username for item in results} == {"happyfox_test_bot"}

        again = await bot.get_me()
        assert again.username == "happyfox_test_bot"
        assert bot.calls == 1

        clear_bot_identity_cache(bot)
        await bot.get_me()
        assert bot.calls == 2

    asyncio.run(run())


def test_bot_identity_cache_install_is_idempotent() -> None:
    async def run() -> None:
        bot = _FakeBot()
        install_bot_identity_cache(bot)
        first_wrapper = bot.get_me
        install_bot_identity_cache(bot)
        assert bot.get_me is first_wrapper

        await bot.get_me()
        await bot.get_me()
        assert bot.calls == 1

    asyncio.run(run())
