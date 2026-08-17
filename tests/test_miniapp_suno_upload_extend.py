from pathlib import Path

MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_upload_extend_module_is_loaded_by_happy_fox_shell() -> None:
    html = (MINIAPP / "index.html").read_text(encoding="utf-8")
    script = (MINIAPP / "suno-upload-extend.js").read_text(encoding="utf-8")

    assert "/mini-app/suno-upload-extend.js" in html
    assert "Продолжить своё аудио" in script
    assert "data-suno-upload-extend-action" in script


def test_upload_extend_uses_owner_private_input_and_owner_endpoint() -> None:
    script = (MINIAPP / "suno-upload-extend.js").read_text(encoding="utf-8")

    assert "'/input-media'" in script
    assert "'/music/suno/upload-extend'" in script
    assert "input_storage_key: uploadedKey" in script
    assert "Idempotency-Key" in script
    assert "sessionStorage" in script
    assert "audio/*" in script


def test_upload_extend_hides_low_level_model_and_never_calls_kie() -> None:
    script = (MINIAPP / "suno-upload-extend.js").read_text(encoding="utf-8")
    lowered = script.lower()

    assert '[data-model="suno-v5-upload-extend"]' in script
    assert ".remove()" in script
    assert "api.kie.ai" not in lowered
    assert "/api/v1/generate/upload-extend" not in lowered
    assert "kie_api_key" not in lowered
    assert "uploadurl" not in lowered


def test_upload_extend_simple_mode_does_not_send_advanced_fields() -> None:
    script = (MINIAPP / "suno-upload-extend.js").read_text(encoding="utf-8")

    assert "default_param_flag: custom" in script
    assert "instrumental: custom ? instrumental : false" in script
    assert "style: custom ? style : ''" in script
    assert "title: custom ? title : ''" in script
    assert "if (custom)" in script
    assert "body.continue_at = continueAt" in script


def test_upload_extend_exposes_custom_advanced_bounds_without_making_them_required() -> None:
    script = (MINIAPP / "suno-upload-extend.js").read_text(encoding="utf-8")

    assert "suno-upload-extend-continue-at" in script
    assert "suno-upload-extend-vocal-gender" in script
    assert "suno-upload-extend-style-weight" in script
    assert "suno-upload-extend-weirdness" in script
    assert "suno-upload-extend-audio-weight" in script
    assert "suno-upload-extend-persona" in script
    assert "value < 0 || value > 1" in script


def test_upload_extend_price_and_balance_are_server_owned() -> None:
    script = (MINIAPP / "suno-upload-extend.js").read_text(encoding="utf-8")

    assert "api('/bootstrap')" in script
    assert "Цена Suno V5 Upload & Extend не опубликована" in script
    assert "Недостаточно средств" in script
    assert "price.amount_units" in script
    assert "available_units" in script


def test_unsubmitted_upload_extend_input_is_cleaned_on_replace_or_close() -> None:
    script = (MINIAPP / "suno-upload-extend.js").read_text(encoding="utf-8")

    assert "cleanupUploaded" in script
    assert "method: 'DELETE'" in script
    assert "uploadedKey === submittedKey" in script
