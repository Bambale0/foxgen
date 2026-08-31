from bot.max_api import (
    MAX_DEFAULT_API_BASE,
    MaxSettings,
    callback_button,
    inline_keyboard,
    token_attachment,
)


def test_max_settings_are_dark_by_default(monkeypatch) -> None:
    for key in (
        "MAX_ENABLED",
        "MAX_ACCESS_TOKEN",
        "MAX_WEBHOOK_SECRET",
        "MAX_API_BASE",
        "MAX_WEBHOOK_PATH",
        "MAX_MINI_APP_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = MaxSettings.from_env()
    assert settings.enabled is False
    assert settings.api_base == MAX_DEFAULT_API_BASE
    assert settings.webhook_path == "/max/webhook"


def test_enabled_max_requires_official_secret_contract(monkeypatch) -> None:
    monkeypatch.setenv("MAX_ENABLED", "1")
    monkeypatch.setenv("MAX_ACCESS_TOKEN", "token")
    monkeypatch.setenv("MAX_WEBHOOK_SECRET", "valid_secret-42")
    settings = MaxSettings.from_env()
    settings.validate_enabled()

    monkeypatch.setenv("MAX_WEBHOOK_SECRET", "bad secret")
    invalid = MaxSettings.from_env()
    try:
        invalid.validate_enabled()
    except RuntimeError as exc:
        assert "MAX_WEBHOOK_SECRET" in str(exc)
    else:
        raise AssertionError("invalid MAX webhook secret was accepted")


def test_max_inline_keyboard_enforces_platform_limits() -> None:
    markup = inline_keyboard(
        [[callback_button("Фото", "max:create_image"), callback_button("Видео", "max:create_video")]]
    )
    assert markup["type"] == "inline_keyboard"
    assert markup["payload"]["buttons"][0][0]["payload"] == "max:create_image"

    too_wide = [[callback_button(str(index), f"max:{index}") for index in range(8)]]
    try:
        inline_keyboard(too_wide)
    except ValueError as exc:
        assert "limits" in str(exc)
    else:
        raise AssertionError("MAX keyboard accepted more than seven buttons per row")


def test_non_image_media_uses_token_attachment_contract() -> None:
    attachment = token_attachment("video", "upload-token")
    assert attachment == {"type": "video", "payload": {"token": "upload-token"}}
