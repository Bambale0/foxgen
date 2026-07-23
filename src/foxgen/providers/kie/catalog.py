from collections.abc import Iterable

from foxgen.domain.models import Capability, MediaKind, ModelSpec


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        slug="gpt-image-2",
        provider_model="gpt-image-2-text-to-image",
        title="GPT Image 2",
        family="GPT Image",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset({Capability.TEXT_TO_IMAGE}),
        verified=True,
        defaults={"aspect_ratio": "auto"},
    ),
    ModelSpec(
        slug="gpt-image-2-edit",
        provider_model="gpt-image-2-image-to-image",
        title="GPT Image 2 Edit",
        family="GPT Image",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset({Capability.IMAGE_TO_IMAGE, Capability.IMAGE_EDIT}),
        verified=True,
        defaults={"aspect_ratio": "auto"},
    ),
    ModelSpec(
        slug="grok-imagine-image",
        provider_model="grok-imagine/text-to-image",
        title="Grok Imagine Image",
        family="Grok Imagine",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset({Capability.TEXT_TO_IMAGE}),
        verified=True,
    ),
    ModelSpec(
        slug="qwen-image",
        provider_model="qwen/text-to-image",
        title="Qwen Image",
        family="Qwen",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset({Capability.TEXT_TO_IMAGE}),
        verified=True,
    ),
    ModelSpec(
        slug="recraft-crisp-upscale",
        provider_model="recraft/crisp-upscale",
        title="Recraft Crisp Upscale",
        family="Recraft",
        media_kind=MediaKind.IMAGE,
        capabilities=frozenset({Capability.IMAGE_UPSCALE}),
        verified=True,
    ),
    ModelSpec(
        slug="grok-imagine-video",
        provider_model="grok-imagine/text-to-video",
        title="Grok Imagine Video",
        family="Grok Imagine",
        media_kind=MediaKind.VIDEO,
        capabilities=frozenset({Capability.TEXT_TO_VIDEO}),
        verified=True,
    ),
    ModelSpec(
        slug="gemini-omni-video",
        provider_model="gemini-omni-video",
        title="Gemini Omni Video",
        family="Gemini Omni",
        media_kind=MediaKind.VIDEO,
        capabilities=frozenset(
            {Capability.TEXT_TO_VIDEO, Capability.IMAGE_TO_VIDEO, Capability.REFERENCE_TO_VIDEO}
        ),
        verified=False,
    ),
)


class ModelRegistry:
    def __init__(self, models: Iterable[ModelSpec] = MODEL_SPECS) -> None:
        items = tuple(models)
        self._by_slug = {item.slug: item for item in items}
        if len(self._by_slug) != len(items):
            raise ValueError("Model slugs must be unique")

    def get(self, slug: str) -> ModelSpec:
        try:
            return self._by_slug[slug]
        except KeyError as exc:
            raise KeyError(f"Unknown model: {slug}") from exc

    def list(
        self,
        *,
        media_kind: MediaKind | None = None,
        capability: Capability | None = None,
        verified_only: bool = True,
    ) -> tuple[ModelSpec, ...]:
        result = []
        for model in self._by_slug.values():
            if verified_only and not model.verified:
                continue
            if media_kind is not None and model.media_kind != media_kind:
                continue
            if capability is not None and not model.supports(capability):
                continue
            result.append(model)
        return tuple(result)
