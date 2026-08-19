from foxgen.providers.kie.registry import ModelRegistry


def test_suno_extend_is_production_ready_but_uses_dedicated_api_family() -> None:
    registry = ModelRegistry()
    extend = registry.get("suno-v5-extend")

    assert extend.production_ready is True
    assert extend.api_family == "suno_extend"
    assert "suno-v5-extend" in {item.slug for item in registry.submission_models()}
