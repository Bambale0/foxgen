from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_server_owned_personalized_trend_fields_and_edit_upgrade() -> None:
    trend = read("bot/trend_api.py")
    ui = read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")
    runner = read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")
    client = read("frontend/miniapp-v0/lib/trend-api.ts")
    assert "render_trend_prompt(prompt, settings, user_values)" in trend
    assert 'async def miniapp_save_admin_trend' in trend
    assert 'settings["user_fields"] = normalize_trend_user_fields' in trend
    assert 'UPDATE user_prompts' in trend and 'WHERE id = ?' in trend
    assert 'saveAdminTrend(editingTrend?.id || null' in ui
    assert 'Array.isArray(settings?.user_fields) ? settings.user_fields.slice(0, 6) : []' in ui
    assert 'payload.user_values = userValues' in client
    assert 'Скрытый prompt останется скрытым' in runner

def test_public_prompt_privacy_middleware_still_redacts_trend_recipe() -> None:
    privacy = read("bot/trend_visibility.py")
    assert 'payload["prompt_text"] = ""' in privacy
    assert 'payload["generation_settings"] = public_trend_settings(payload)' in privacy

def test_field_renderer_validates_and_renders_values() -> None:
    from bot.trend_user_fields import TrendUserFieldsError, normalize_trend_user_fields, render_trend_prompt

    settings = {"user_fields": normalize_trend_user_fields([
        {"key": "Возраст", "label": "Возраст", "type": "number", "min": 1, "max": 120}
    ], prompt="Happy birthday {{Возраст}}")}
    assert render_trend_prompt("Happy birthday {{Возраст}}", settings, {"Возраст": "28"}) == "Happy birthday 28"
    try:
        render_trend_prompt("Happy birthday {{Возраст}}", settings, {"Возраст": "121"})
    except TrendUserFieldsError:
        pass
    else:
        raise AssertionError("out-of-range value must be rejected")
