import asyncio
from dataclasses import dataclass
from pathlib import Path

from bot.channel_identity import ChannelIdentity
from bot.handlers import instagram_account_link


@dataclass
class _User:
    id: int
    credits: float = 12.5


class _FromUser:
    id = 700010


class _Message:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = _FromUser()
        self.answers: list[tuple[str, dict]] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append((text, kwargs))


class _State:
    def __init__(self) -> None:
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True


def test_instagram_start_token_parser_is_narrow() -> None:
    assert instagram_account_link.extract_link_token("/start iglink_abc-123_X") == "abc-123_X"
    assert (
        instagram_account_link.extract_link_token(
            "/start@HappyFoxBot iglink_token123"
        )
        == "token123"
    )
    assert instagram_account_link.extract_link_token("/start ref_TEST") == ""
    assert instagram_account_link.extract_link_token("/start") == ""


def test_successful_instagram_link_opens_normal_telegram_topup(monkeypatch) -> None:
    message = _Message("/start iglink_token-123")
    state = _State()
    calls: list[tuple[str, int]] = []

    async def fake_get_or_create_user(_telegram_id: int):
        return _User(id=55, credits=12.5)

    async def fake_consume(token: str, user_id: int):
        calls.append((token, user_id))
        return ChannelIdentity(
            id=2,
            user_id=user_id,
            channel="instagram",
            account_id="ig-business-1",
            external_user_id="igsid-1",
        )

    monkeypatch.setattr(
        instagram_account_link,
        "get_or_create_user",
        fake_get_or_create_user,
    )
    monkeypatch.setattr(
        instagram_account_link,
        "consume_channel_link_token",
        fake_consume,
    )

    asyncio.run(instagram_account_link.confirm_instagram_account_link(message, state))

    assert state.cleared is True
    assert calls == [("token-123", 55)]
    assert len(message.answers) == 1
    text, kwargs = message.answers[0]
    assert "instagram привязан" in text.lower()
    assert "пополн" in text.lower()
    assert "продолжить" in text.lower()
    keyboard = kwargs.get("reply_markup")
    assert keyboard is not None
    callback_values = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "menu_topup" in callback_values


def test_account_link_router_is_before_legacy_start_handler() -> None:
    source = Path("bot/handlers/__init__.py").read_text(encoding="utf-8")

    account_link_position = source.index("instagram_account_link_router")
    legacy_position = source.index("common_router.include_router(legacy_common_router)")
    assert account_link_position < legacy_position
