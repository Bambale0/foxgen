from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"
SPECIAL = FRONTEND / "components" / "special-model-form.tsx"
API = FRONTEND / "lib" / "api.ts"


def test_upload_extend_uses_private_input_and_owner_endpoint() -> None:
    special = SPECIAL.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")

    assert "suno-v5-upload-extend" in special
    assert "miniAppApi.uploadInput(file)" in special
    assert "'/music/suno/upload-extend'" in special
    assert "input_storage_key: upload.storage_key" in special
    assert "Idempotency-Key" in special
    assert "'/input-media'" in api


def test_upload_extend_never_calls_kie_directly() -> None:
    source = SPECIAL.read_text(encoding="utf-8").lower()

    assert "api.kie.ai" not in source
    assert "/api/v1/generate/upload-extend" not in source
    assert "kie_api_key" not in source
    assert "uploadurl" not in source


def test_upload_extend_has_continue_at_and_backend_owned_submission() -> None:
    source = SPECIAL.read_text(encoding="utf-8")

    assert "kind === 'extend'" in source
    assert "body.continue_at = continueAt ? Number(continueAt) : null" in source
    assert "body.default_param_flag = false" in source
    assert "instrumental" in source
    assert "style" in source
    assert "title" in source
    assert "MutationObserver" not in source
