import asyncio

from bot import database
from bot.max_api import MaxSettings
from bot.max_assistant import MaxAIAssistantService
from bot.max_product_channel import MaxProductChannelService
from bot.max_store import get_max_session
from bot.max_ui import main_menu


class FakeMaxClient:
    def __init__(self) -> None:
        self.sent = []
        self.answers = []

    async def send_message(self, user_id, text, *, attachments=None, format="html", notify=True):
        self.sent.append(
            {
                "user_id": user_id,
                "text": text,
                "attachments": attachments,
                "format": format,
                "notify": notify,
            }
        )
        return {"ok": True}

    async def answer_callback(self, callback_id, *, message=None):
        self.answers.append({"callback_id": callback_id, "message": message})
        return {"success": True}


class FakePayments:
    enabled = True


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def _service() -> tuple[MaxProductChannelService, FakeMaxClient]:
    client = FakeMaxClient()
    service = MaxProductChannelService(
        settings=MaxSettings(
            enabled=True,
            access_token="token",
            webhook_secret="valid_secret",
            mini_app_url="https://example.invalid/mini-app/",
        ),
        client=client,
        payments=FakePayments(),
        bot_name="happyfox_bot",
        support_contact="https://max.ru/happyfox-support",
    )
    return service, client


def _callback(user_id: int, callback_id: str, payload: str) -> dict:
    return {
        "update_type": "message_callback",
        "callback": {
            "callback_id": callback_id,
            "payload": payload,
            "user": {"user_id": user_id, "name": "Creator"},
        },
    }


def _message(user_id: int, text: str) -> dict:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "name": "Creator"},
            "body": {"text": text, "attachments": []},
        },
    }


def _callback_payloads() -> list[str]:
    rows = main_menu(42, mini_app_url="https://example.invalid/mini-app/")[0]["payload"]["buttons"]
    return [
        button["payload"]
        for row in rows
        for button in row
        if button.get("type") == "callback"
    ]


def _sample_prompt() -> dict:
    return {
        "id": 17,
        "title": "Кинематографичный портрет",
        "description": "Портрет с мягким светом и выразительной глубиной кадра.",
        "category": "portrait",
        "model": "banana_2",
        "tags": ["portrait", "cinematic"],
        "likes": 11,
        "uses_count": 23,
        "prompt_text": "cinematic portrait, soft key light, 85mm lens, realistic skin texture",
    }


def test_every_max_main_menu_screen_is_actionable(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-product-screens.db", monkeypatch)
    service, client = _service()

    async def fake_load_prompts(mode: str):
        assert mode in {"top", "popular", "new"}
        return [_sample_prompt()]

    monkeypatch.setattr("bot.max_product_channel._load_prompts", fake_load_prompts)

    payloads = _callback_payloads()
    expected = {
        "max:create_image",
        "max:omni_audio",
        "max:create_video",
        "max:music",
        "max:motion_control",
        "max:prompts",
        "max:gemini_omni",
        "max:assistant",
        "max:history",
        "max:support",
        "max:balance",
        "max:partners",
        "max:topup",
    }
    assert set(payloads) == expected

    for index, payload in enumerate(payloads, start=1):
        asyncio.run(service.handle_update(_callback(700, f"cb-{index}", payload)))

    assert len(client.answers) == len(payloads)
    rendered = "\n".join(str(item["message"]["text"]) for item in client.answers if item.get("message"))
    assert "ещё переносится" not in rendered
    assert "AI-помощник HappyFox" in rendered
    assert "Промпты · Лучшие" in rendered
    assert "Поддержка HappyFox" in rendered
    assert "Gemini Omni" in rendered


def test_max_assistant_uses_its_own_session_and_max_context(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-assistant.db", monkeypatch)
    service, client = _service()
    captured = {}

    async def fake_answer(*, user_message: str, context: dict):
        captured["user_message"] = user_message
        captured["context"] = context
        return "Для product-фото начните с Nano Banana 2."

    monkeypatch.setattr(
        "bot.max_product_channel.max_ai_assistant_service.get_assistant_response",
        fake_answer,
    )

    asyncio.run(service.handle_update(_callback(701, "assistant-open", "max:assistant")))
    assert asyncio.run(get_max_session(701)).state == "assistant:waiting_message"

    asyncio.run(service.handle_update(_message(701, "Что выбрать для product-фото?")))

    assert captured["user_message"] == "Что выбрать для product-фото?"
    assert captured["context"]["menu_location"] == "AI-помощник"
    assert "banana_2" in captured["context"]["available_models"]
    assert asyncio.run(get_max_session(701)).state == "assistant:waiting_message"
    assert "Nano Banana 2" in client.sent[-1]["text"]


def test_max_assistant_pricing_context_never_falls_back_to_telegram_copy() -> None:
    service = MaxAIAssistantService()

    context = service._format_context(
        {
            "user_credits": 12.5,
            "menu_location": "AI-помощник",
            "available_models": "banana_2, seedance_2_5",
        }
    )
    pricing = service.get_pricing_info()
    system = service._get_system_prompt()

    assert "Баланс MAX: 12.5 🐾" in context
    assert "бананов" not in context
    assert "Авторитетные цены MAX" in pricing
    assert '"nano-banana-2-lite":1.0' in pricing
    assert '"seedance_2_5"' in pricing
    assert '"price_rub":150' in pricing
    assert "не Telegram" in system
    assert "🐾" in system


def test_max_prompt_library_has_native_navigation_and_full_prompt(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-prompts.db", monkeypatch)
    service, client = _service()

    async def fake_load_prompts(mode: str):
        return [_sample_prompt()]

    async def fake_get_prompt(prompt_id: int, *, approved_public_only: bool = False):
        assert prompt_id == 17
        assert approved_public_only is True
        return _sample_prompt()

    monkeypatch.setattr("bot.max_product_channel._load_prompts", fake_load_prompts)
    monkeypatch.setattr("bot.max_product_channel.get_prompt_by_id", fake_get_prompt)

    asyncio.run(service.handle_update(_callback(702, "prompts-open", "max:prompts")))
    screen = client.answers[-1]["message"]
    assert "Промпты · Лучшие" in screen["text"]
    buttons = screen["attachments"][0]["payload"]["buttons"]
    callbacks = {
        button.get("payload")
        for row in buttons
        for button in row
        if button.get("type") == "callback"
    }
    assert "max:prompt:nav:popular:0" in callbacks
    assert "max:prompt:nav:new:0" in callbacks
    assert "max:prompt:full:17" in callbacks

    asyncio.run(service.handle_update(_callback(702, "prompt-full", "max:prompt:full:17")))
    assert "cinematic portrait" in client.answers[-1]["message"]["text"]
