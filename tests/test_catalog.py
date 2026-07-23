from foxgen.domain.models import Capability, MediaKind
from foxgen.providers.kie.registry import ModelRegistry


def test_registry_filters_by_capability() -> None:
    registry = ModelRegistry()

    models = registry.list(
        media_kind=MediaKind.IMAGE,
        capability=Capability.TEXT_TO_IMAGE,
    )

    assert {model.slug for model in models} >= {
        "seedream-4-5",
        "seedream-5-pro",
        "nano-banana-2",
        "nano-banana-pro",
        "gpt-image-2",
    }
    assert all(model.verified for model in models)


def test_registry_recommends_exact_project_priorities_first() -> None:
    registry = ModelRegistry()

    image_models = registry.recommend(
        media_kind=MediaKind.IMAGE,
        capability=Capability.TEXT_TO_IMAGE,
        limit=5,
    )
    video_models = registry.recommend(
        media_kind=MediaKind.VIDEO,
        capability=Capability.TEXT_TO_VIDEO,
        limit=2,
    )

    assert [item.slug for item in image_models] == [
        "seedream-5-pro",
        "seedream-4-5",
        "nano-banana-2",
        "nano-banana-pro",
        "gpt-image-2",
    ]
    assert [item.slug for item in video_models] == [
        "seedance-2",
        "seedance-2-mini",
    ]


def test_seedance_fast_is_not_in_active_project_registry() -> None:
    registry = ModelRegistry()

    assert "seedance-2-fast" not in {item.slug for item in registry.list()}
