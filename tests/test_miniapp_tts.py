from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_tts_parity_layer_is_loaded_and_uses_backend_model_identity() -> None:
    html = (MINIAPP / "index.html").read_text(encoding="utf-8")
    script = (MINIAPP / "tts-parity.js").read_text(encoding="utf-8")

    assert "/mini-app/tts-parity.js" in html
    assert "elevenlabs-turbo-2-5" in script
    assert "ElevenLabs Turbo 2.5" in script
    assert "data-model" in script
    assert "Аудио" in script


def test_voice_launcher_becomes_real_but_studio_remains_schema_driven() -> None:
    script = (MINIAPP / "tts-parity.js").read_text(encoding="utf-8")

    assert '[data-complete-tool="voice"]' in script
    assert "button.disabled = false" in script
    assert "data-submit" in script
    assert "Цена не опубликована" in script
    assert "schema-card label" in script
    assert "Voice ID" in script
    assert "Скорость" in script


def test_tts_browser_layer_has_no_provider_secret_or_direct_kie_request() -> None:
    script = (MINIAPP / "tts-parity.js").read_text(encoding="utf-8")
    lowered = script.lower()

    assert "api.kie.ai" not in lowered
    assert "authorization" not in lowered
    assert "kie_api_key" not in lowered
    assert "bearer " not in lowered
    assert "createtask" not in lowered
