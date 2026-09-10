from pathlib import Path

from bot.services.support_ai_service import (
    SUPPORT_ESCALATION_MARKER,
    SupportAIService,
    parse_support_ai_text,
)
from bot.support_service import _normalize_source


def test_support_ai_defaults_to_kie_gpt55(monkeypatch) -> None:
    monkeypatch.setenv("SUPPORT_KIE_API_KEY", "test-key")
    monkeypatch.delenv("KIE_AI_API_KEY", raising=False)
    monkeypatch.delenv("SUPPORT_AI_MODEL", raising=False)
    service = SupportAIService()
    assert service.api_key == "test-key"
    assert service.model == "gpt-5-5"
    assert service.base_url == "https://api.kie.ai"


def test_support_ai_escalation_marker_is_not_user_visible() -> None:
    answer = parse_support_ai_text(
        f"Нужна ручная проверка платежа. {SUPPORT_ESCALATION_MARKER}"
    )
    assert answer.escalate is True
    assert SUPPORT_ESCALATION_MARKER not in answer.text
    assert "ручная проверка" in answer.text


def test_support_source_is_explicit_and_bounded() -> None:
    assert _normalize_source("telegram_support_bot") == "telegram_support_bot"


def test_support_compose_service_is_opt_in_and_separate() -> None:
    compose = Path("compose.backend.yml").read_text(encoding="utf-8")
    assert "support_bot:" in compose
    assert "- support" in compose
    assert "bot.support_bot_runtime" in compose
    assert ".env.happyfox.support" in compose
    assert "SUPPORT_BOT_TOKEN" not in compose


def test_support_example_contains_no_real_secret() -> None:
    content = Path(".env.happyfox.support.example").read_text(encoding="utf-8")
    assert "SUPPORT_BOT_TOKEN=" in content
    assert "SUPPORT_KIE_API_KEY=" in content
    assert "SUPPORT_AI_MODEL=gpt-5-5" in content
