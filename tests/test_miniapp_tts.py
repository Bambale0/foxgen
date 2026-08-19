from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"


def test_tts_is_rendered_from_backend_model_registry() -> None:
    models = (FRONTEND / "components" / "tabs" / "models-tab.tsx").read_text(encoding="utf-8")
    create = (FRONTEND / "components" / "tabs" / "create-tab.tsx").read_text(encoding="utf-8")

    assert "bootstrap?.models" in models
    assert "item.media_kind === 'audio'" in create
    assert "selectModel(model)" in models
    assert "selectModel(model)" in create


def test_voice_studio_remains_schema_driven() -> None:
    form = (FRONTEND / "components" / "model-form.tsx").read_text(encoding="utf-8")
    context = (FRONTEND / "lib" / "app-context.tsx").read_text(encoding="utf-8")

    assert "model.input_schema?.properties" in form
    assert "model.input_schema?.required" in form
    assert "enumValues" in form
    assert "normalizedType" in form
    assert "submitModel" in form
    assert "miniAppApi.validateModel(model.slug, input)" in context
    assert "miniAppApi.createTask(model.slug, validated.input, sourcePublicationId)" in context


def test_tts_browser_layer_has_no_provider_secret_or_direct_kie_request() -> None:
    source = "\n".join(
        (
            (FRONTEND / "components" / "model-form.tsx").read_text(encoding="utf-8"),
            (FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8"),
        )
    ).lower()

    assert "api.kie.ai" not in source
    assert "kie_api_key" not in source
    assert "/api/v1/generate" not in source
