from foxgen.domain.models import Capability, MediaKind
from foxgen.providers.kie.catalog import ModelRegistry


def test_registry_filters_by_capability() -> None:
    registry = ModelRegistry()

    models = registry.list(
        media_kind=MediaKind.IMAGE,
        capability=Capability.TEXT_TO_IMAGE,
    )

    assert {model.slug for model in models} >= {"gpt-image-2", "qwen-image"}
    assert all(model.verified for model in models)
