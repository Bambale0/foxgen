from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_upload_cover_module_is_loaded_by_happy_fox_shell() -> None:
    html = (MINIAPP / "index.html").read_text(encoding="utf-8")
    script = (MINIAPP / "suno-upload-cover.js").read_text(encoding="utf-8")

    assert "/mini-app/suno-upload-cover.js" in html
    assert "Suno Cover из аудио" in script
    assert "data-suno-cover-action" in script


def test_upload_cover_uses_owner_private_input_and_owner_endpoint() -> None:
    script = (MINIAPP / "suno-upload-cover.js").read_text(encoding="utf-8")

    assert "'/input-media'" in script
    assert "'/music/suno/upload-cover'" in script
    assert "input_storage_key: uploadedKey" in script
    assert "Idempotency-Key" in script
    assert "sessionStorage" in script
    assert "audio/*" in script


def test_upload_cover_hides_low_level_model_and_never_calls_kie() -> None:
    script = (MINIAPP / "suno-upload-cover.js").read_text(encoding="utf-8")
    lowered = script.lower()

    assert '[data-model="suno-v5-upload-cover"]' in script
    assert ".remove()" in script
    assert "api.kie.ai" not in lowered
    assert "/api/v1/generate/upload-cover" not in lowered
    assert "kie_api_key" not in lowered
    assert "uploadurl" not in lowered


def test_upload_cover_price_and_balance_are_server_owned() -> None:
    script = (MINIAPP / "suno-upload-cover.js").read_text(encoding="utf-8")

    assert "api('/bootstrap')" in script
    assert "Цена Suno V5 Cover не опубликована" in script
    assert "Недостаточно средств" in script
    assert "price.amount_units" in script
    assert "available_units" in script


def test_unsubmitted_cover_input_is_cleaned_on_replace_or_close() -> None:
    script = (MINIAPP / "suno-upload-cover.js").read_text(encoding="utf-8")

    assert "cleanupUploaded" in script
    assert "method: 'DELETE'" in script
    assert "uploadedKey === submittedKey" in script
