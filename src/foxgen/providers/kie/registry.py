from dataclasses import replace
from typing import Iterable

from foxgen.domain.models import Capability, MediaKind, ModelSpec
from foxgen.providers.kie.catalog import MODEL_SPECS, ModelRegistry as BaseModelRegistry, model
from foxgen.providers.kie.contracts import InputContract


SEEDREAM_45_MODELS: tuple[ModelSpec, ...] = (
    model(
        slug="seedream-4-5",
        provider_model="seedream/4.5-text-to-image",
        title="Seedream 4.5",
        family="Seedream",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset({Capability.TEXT_TO_IMAGE}),
        contract=InputContract.SEEDREAM_45_TEXT,
        docs_path="/market/seedream/4-5-text-to-image",
        rank=2,
        defaults={"aspect_ratio": "1:1", "quality": "basic", "nsfw_checker": False},
        recommended_for=("photorealism", "commercial visuals", "stable production"),
    ),
    model(
        slug="seedream-4-5-edit",
        provider_model="seedream/4.5-edit",
        title="Seedream 4.5 Edit",
        family="Seedream",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset({Capability.IMAGE_TO_IMAGE, Capability.IMAGE_EDIT}),
        contract=InputContract.SEEDREAM_45_EDIT,
        docs_path="/market/seedream/4-5-edit",
        rank=3,
        defaults={"aspect_ratio": "1:1", "quality": "basic", "nsfw_checker": False},
        recommended_for=("image editing", "material replacement", "product retouching"),
    ),
)


def _active_models() -> tuple[ModelSpec, ...]:
    """Build the exact active priority set without the unwanted Seedance Fast tier."""

    models: list[ModelSpec] = list(SEEDREAM_45_MODELS)
    for item in MODEL_SPECS:
        if item.slug == "seedance-2-fast":
            continue
        if item.slug == "seedance-2-mini":
            item = replace(item, rank=2)
        models.append(item)
    return tuple(models)


ACTIVE_MODEL_SPECS = _active_models()


class ModelRegistry(BaseModelRegistry):
    """FoxGen registry with exact project priorities applied."""

    def __init__(self, models: Iterable[ModelSpec] = ACTIVE_MODEL_SPECS) -> None:
        super().__init__(models)
