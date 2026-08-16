from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_suno_parity_layer_is_loaded_and_exposes_music_product() -> None:
    html = (MINIAPP / "index.html").read_text(encoding="utf-8")
    script = (MINIAPP / "suno-parity.js").read_text(encoding="utf-8")

    assert "/mini-app/suno-parity.js" in html
    assert "suno-v5" in script
    assert "Suno V5" in script
    assert "Музыка" in script
    assert 'data-complete-tool="music"' in script
    assert "button.disabled = false" in script


def test_suno_studio_is_backend_schema_driven_and_mode_aware() -> None:
    script = (MINIAPP / "suno-parity.js").read_text(encoding="utf-8")

    assert "data-field" in script
    assert "custom_mode" in script
    assert "instrumental" in script
    assert "style_weight" in script
    assert "weirdness_constraint" in script
    assert "audio_weight" in script
    assert "setVisible('prompt', !custom || !instrumental)" in script
    assert "Цена не опубликована" in script
    assert "data-submit" in script


def test_suno_browser_layer_has_no_direct_provider_credentials_or_request() -> None:
    script = (MINIAPP / "suno-parity.js").read_text(encoding="utf-8").lower()

    assert "api.kie.ai" not in script
    assert "authorization" not in script
    assert "kie_api_key" not in script
    assert "/api/v1/generate" not in script
    assert "bearer " not in script
