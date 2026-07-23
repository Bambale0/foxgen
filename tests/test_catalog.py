from foxgen.domain.models import Capability, MediaKind
from foxgen.providers.kie.catalog import ModelRegistry


def test_registry_filters_by_capability() -> None:
    registry = ModelRegistry()

    models = registry.list(
        media_kind=MediaKind.IMAGE,
        capability=Capability.TEXT_TO_IMAGE,
    )

    assert {model.slug for model in models} >= {
        "seedream-5-pro",
        "nano-banana-2",
        "nano-banana-pro",
        "gpt-image-2",
    }
    assert all(model.verified for model in models)


def test_registry_recommends_current_flagships_first() -> None:
    registry = ModelRegistry()

    image_models = registry.recommend(
        media_kind=MediaKind.IMAGE,
        capability=Capability.TEXT_TO_IMAGE,
        limit=4,
    )
    video_models = registry.recommend(
        media_kind=MediaKind.VIDEO,
        capability=Capability.TEXT_TO_VIDEO,
        limit=3,
    )

    assert [item.slug for item in image_models] == [
        "seedream-5-pro",
        "nano-banana-2",
        "nano-banana-pro",
        "gpt-image-2",
    ]
    assert [item.slug for item in video_models] == [
        "seedance-2",
        "seedance-2-fast",
        "seedance-2-mini",
    ]
