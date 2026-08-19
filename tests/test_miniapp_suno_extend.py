from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"
SPECIAL = FRONTEND / "components" / "special-model-form.tsx"


def test_suno_extend_uses_owner_sources_and_dedicated_endpoint() -> None:
    source = SPECIAL.read_text(encoding="utf-8")

    assert "suno-v5-extend" in source
    assert "'/music/suno/sources?limit=100'" in source
    assert "'/music/suno/extend'" in source
    assert "source_generation_id:selected.generation_id" in source
    assert "audio_id:selected.audio_id" in source
    assert "continue_at:continueAt ? Number(continueAt) : null" in source


def test_suno_extend_never_calls_kie_or_supplies_client_price() -> None:
    source = SPECIAL.read_text(encoding="utf-8").lower()

    assert "api.kie.ai" not in source
    assert "/api/v1/generate/extend" not in source
    assert "kie_api_key" not in source
    assert "amount_units:" not in source
    assert "idempotency-key" in source


def test_suno_extend_is_selected_by_model_slug_not_dom_recovery() -> None:
    source = SPECIAL.read_text(encoding="utf-8")

    assert "if (model.slug === 'suno-v5-extend')" in source
    assert "<SunoExtendForm model={model} />" in source
    assert "MutationObserver" not in source
    assert "document.createElement" not in source
