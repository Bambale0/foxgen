from pathlib import Path


def test_instagram_channel_is_wired_through_runtime_composition() -> None:
    internal_api = Path("bot/internal_api.py").read_text(encoding="utf-8")

    assert "InstagramSettings" in internal_api
    assert "setup_instagram_routes" in internal_api
    assert "build_instagram_event_handler" in internal_api


def test_happyfox_instagram_env_is_safe_by_default() -> None:
    env_example = Path(".env.happyfox.example").read_text(encoding="utf-8")

    assert "INSTAGRAM_ENABLED=0" in env_example
    assert "INSTAGRAM_APP_ID=" in env_example
    assert "INSTAGRAM_APP_SECRET=" in env_example
    assert "INSTAGRAM_VERIFY_TOKEN=" in env_example
    assert "INSTAGRAM_ACCESS_TOKEN=" in env_example
    assert "INSTAGRAM_IG_USER_ID=" in env_example
    assert "INSTAGRAM_API_VERSION=v24.0" in env_example
    assert "INSTAGRAM_WEBHOOK_PATH=/instagram/webhook" in env_example
    assert "INSTAGRAM_SUBSCRIBED_FIELDS=messages,messaging_postbacks,comments" in env_example
