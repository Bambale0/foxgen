from foxgen.providers.kie.registry import ModelRegistry


def test_suno_extend_is_source_bound_not_a_generic_catalog_card() -> None:
    registry = ModelRegistry()
    extend = registry.get("suno-v5-extend")

    assert extend.production_ready is True
    assert extend.api_family == "suno_extend"
    assert "suno-v5-extend" not in {item.slug for item in registry.submission_models()}
