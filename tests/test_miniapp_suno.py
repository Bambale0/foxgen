from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"


def test_suno_is_exposed_from_backend_model_catalog() -> None:
    models = (FRONTEND / "components" / "tabs" / "models-tab.tsx").read_text(encoding="utf-8")
    create = (FRONTEND / "components" / "tabs" / "create-tab.tsx").read_text(encoding="utf-8")

    assert "bootstrap?.models" in models
    assert "slug.startsWith('suno-')" in models
    assert "Музыка" in create
    assert "item.slug.startsWith('suno-')" in create


def test_standard_suno_studio_is_backend_schema_driven() -> None:
    form = (FRONTEND / "components" / "model-form.tsx").read_text(encoding="utf-8")
    context = (FRONTEND / "lib" / "app-context.tsx").read_text(encoding="utf-8")

    assert "model.input_schema?.properties" in form
    assert "model.input_schema?.required" in form
    assert "model.defaults" in form
    assert "enumValues" in form
    assert "normalizedType" in form
    assert "submitModel" in form
    assert "miniAppApi.validateModel(model.slug, input)" in context
    assert "miniAppApi.createTask(model.slug, validated.input)" in context


def test_suno_browser_layer_has_no_direct_provider_credentials_or_request() -> None:
    source = "\n".join(
        (
            (FRONTEND / "components" / "model-form.tsx").read_text(encoding="utf-8"),
            (FRONTEND / "components" / "special-model-form.tsx").read_text(encoding="utf-8"),
        )
    ).lower()

    assert "api.kie.ai" not in source
    assert "kie_api_key" not in source
    assert "/api/v1/generate" not in source
