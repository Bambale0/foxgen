from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"
SPECIAL = FRONTEND / "components" / "special-model-form.tsx"
API = FRONTEND / "lib" / "api.ts"


def test_upload_cover_uses_private_input_and_owner_endpoint() -> None:
    special = SPECIAL.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")

    assert "suno-v5-upload-cover" in special
    assert "miniAppApi.uploadInput(file)" in special
    assert "'/music/suno/upload-cover'" in special
    assert "input_storage_key: upload.storage_key" in special
    assert "Idempotency-Key" in special
    assert "'/input-media'" in api


def test_upload_cover_never_calls_kie_directly() -> None:
    source = SPECIAL.read_text(encoding="utf-8").lower()

    assert "api.kie.ai" not in source
    assert "/api/v1/generate/upload-cover" not in source
    assert "kie_api_key" not in source
    assert "uploadurl" not in source


def test_upload_cover_simple_and_custom_fields_are_react_owned() -> None:
    source = SPECIAL.read_text(encoding="utf-8")

    assert "kind: 'cover' | 'extend'" in source
    assert "body.custom_mode = Boolean(prompt || style || title)" in source
    assert "instrumental" in source
    assert "style" in source
    assert "title" in source
    assert "MutationObserver" not in source
