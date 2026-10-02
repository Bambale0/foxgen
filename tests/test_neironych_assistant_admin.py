from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_shared_ai_assistant_uses_selected_neironych_model_without_kie(monkeypatch):
    from bot.services import ai_assistant_service as assistant_module

    captured = {}

    async def selected(_requested=None):
        return "gpt-5.6-luna"

    class FakeClient:
        async def submit(self, request):
            captured["request"] = request
            return type("Outcome", (), {"text": "native answer"})()

    monkeypatch.setattr(assistant_module.neironych_routing, "text_model", selected)
    monkeypatch.setattr(assistant_module.neironych_routing, "client", FakeClient())
    monkeypatch.setattr(assistant_module.config, "KIE_AI_API_KEY", "must-not-be-used")

    service = assistant_module.AIAssistantService()
    result = await service.get_assistant_response(
        "Что выбрать?",
        {"user_credits": 10, "provider_request_key": "telegram-42-777"},
    )

    assert result == "native answer"
    request = captured["request"]
    assert request.model.id == "gpt-5.6-luna"
    assert request.key == "telegram-42-777"
    assert "Что выбрать?" in request.payload["input"]


@pytest.mark.asyncio
async def test_unknown_native_text_outcome_never_falls_back_to_kie(monkeypatch):
    from bot.services import ai_assistant_service as assistant_module
    from happyfox_neironych import ProviderError

    async def selected(_requested=None):
        return "grok-4.5"

    class FakeClient:
        async def submit(self, request):
            raise ProviderError("submission_outcome_unknown", uncertain=True)

    monkeypatch.setattr(assistant_module.neironych_routing, "text_model", selected)
    monkeypatch.setattr(assistant_module.neironych_routing, "client", FakeClient())
    monkeypatch.setattr(assistant_module.config, "KIE_AI_API_KEY", "configured")

    service = assistant_module.AIAssistantService()
    assert (
        await service.get_assistant_response(
            "test",
            {"provider_request_key": "telegram-42-778"},
        )
        is None
    )


def test_admin_handler_exposes_neironych_control_plane():
    source = Path("bot/handlers/admin.py").read_text(encoding="utf-8")
    assert '@router.message(Command("neironych"))' in source
    assert "neironych_routing.configure" in source
    assert "config.is_admin(message.from_user.id)" in source
