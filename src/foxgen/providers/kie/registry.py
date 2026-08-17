from dataclasses import replace
from typing import Iterable

from foxgen.domain.models import Capability, MediaKind, ModelSpec
from foxgen.providers.kie.catalog import MODEL_SPECS, model
from foxgen.providers.kie.catalog import ModelRegistry as BaseModelRegistry
from foxgen.providers.kie.contracts import InputContract

SUBMISSION_MODEL_SLUGS: frozenset[str] = frozenset(
    {
        "seedream-5-pro",
        "seedream-5-pro-edit",
        "nano-banana-2",
        "nano-banana-pro",
        "seedance-2",
        "seedance-2-mini",
        "elevenlabs-turbo-2-5",
        "suno-v5",
        "suno-v5-extend",
        "suno-v5-upload-cover",
        "suno-v5-upload-extend",
    }
)


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


ELEVENLABS_TTS_MODEL = replace(
    model(
        slug="elevenlabs-turbo-2-5",
        provider_model="elevenlabs/text-to-speech-turbo-2-5",
        title="ElevenLabs Turbo 2.5",
        family="ElevenLabs",
        media_kind=MediaKind.AUDIO,
        capabilities=frozenset({Capability.TEXT_TO_SPEECH}),
        contract=InputContract.ELEVENLABS_TTS_TURBO_2_5,
        docs_path="/market/elevenlabs/text-to-speech-turbo-2-5",
        tier="standard",
        rank=1,
        defaults={
            "voice": "Rachel",
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "speed": 1.0,
            "timestamps": False,
            "previous_text": "",
            "next_text": "",
            "language_code": "",
        },
        recommended_for=("voiceovers", "short narration", "fast multilingual TTS"),
    ),
    contract_reviewed_at="2026-08-16",
)


SUNO_V5_MODEL = ModelSpec(
    slug="suno-v5",
    provider_model="V5",
    title="Suno V5",
    family="Suno",
    media_kind=MediaKind.AUDIO,
    capabilities=frozenset({Capability.MUSIC_GENERATION}),
    verified=True,
    defaults={
        "custom_mode": False,
        "instrumental": False,
        "prompt": "",
        "style": "",
        "title": "",
        "negative_tags": "",
    },
    contract=InputContract.SUNO_V5_GENERATE,
    tier="standard",
    rank=1,
    docs_url="https://docs.kie.ai/suno-api/generate-music/",
    recommended_for=("full songs", "instrumentals", "lyrics-driven music"),
    api_family="suno",
    provider_id_verified=True,
    schema_verified=True,
    enabled_for_submission=True,
    tested_live=False,
    contract_reviewed_at="2026-08-16",
)


SUNO_V5_EXTEND_MODEL = ModelSpec(
    slug="suno-v5-extend",
    provider_model="V5",
    title="Suno V5 Extend",
    family="Suno",
    media_kind=MediaKind.AUDIO,
    capabilities=frozenset({Capability.MUSIC_EDIT}),
    verified=True,
    defaults={
        "default_param_flag": False,
        "prompt": "",
        "style": "",
        "title": "",
        "negative_tags": "",
    },
    contract=InputContract.SUNO_V5_EXTEND,
    tier="standard",
    rank=2,
    docs_url="https://docs.kie.ai/suno-api/extend-music/",
    recommended_for=("continue generated songs", "longer arrangements", "custom continuation"),
    api_family="suno_extend",
    provider_id_verified=True,
    schema_verified=True,
    enabled_for_submission=True,
    tested_live=False,
    contract_reviewed_at="2026-08-16",
)


SUNO_V5_UPLOAD_COVER_MODEL = ModelSpec(
    slug="suno-v5-upload-cover",
    provider_model="V5",
    title="Suno V5 Cover",
    family="Suno",
    media_kind=MediaKind.AUDIO,
    capabilities=frozenset({Capability.MUSIC_EDIT}),
    verified=True,
    defaults={
        "custom_mode": False,
        "instrumental": False,
        "prompt": "",
        "style": "",
        "title": "",
        "negative_tags": "",
    },
    contract=InputContract.SUNO_V5_UPLOAD_COVER,
    tier="standard",
    rank=3,
    docs_url="https://docs.kie.ai/suno-api/upload-and-cover-audio/",
    recommended_for=("restyle uploaded audio", "genre covers", "instrumental remakes"),
    api_family="suno_upload_cover",
    provider_id_verified=True,
    schema_verified=True,
    enabled_for_submission=True,
    tested_live=False,
    contract_reviewed_at="2026-08-17",
)


SUNO_V5_UPLOAD_EXTEND_MODEL = ModelSpec(
    slug="suno-v5-upload-extend",
    provider_model="V5",
    title="Suno V5 Upload & Extend",
    family="Suno",
    media_kind=MediaKind.AUDIO,
    capabilities=frozenset({Capability.MUSIC_EDIT}),
    verified=True,
    defaults={
        "default_param_flag": False,
        "instrumental": False,
        "prompt": "",
        "style": "",
        "title": "",
        "negative_tags": "",
    },
    contract=InputContract.SUNO_V5_UPLOAD_EXTEND,
    tier="standard",
    rank=4,
    docs_url="https://docs.kie.ai/suno-api/upload-and-extend-audio",
    recommended_for=(
        "continue uploaded audio",
        "longer arrangements",
        "custom uploaded continuation",
    ),
    api_family="suno_upload_extend",
    provider_id_verified=True,
    schema_verified=True,
    enabled_for_submission=True,
    tested_live=False,
    contract_reviewed_at="2026-08-17",
)


def _active_models() -> tuple[ModelSpec, ...]:
    """Build the reviewed catalog and apply the explicit paid-submission allowlist."""

    models: list[ModelSpec] = list(SEEDREAM_45_MODELS)
    models.extend(
        (
            ELEVENLABS_TTS_MODEL,
            SUNO_V5_MODEL,
            SUNO_V5_EXTEND_MODEL,
            SUNO_V5_UPLOAD_COVER_MODEL,
            SUNO_V5_UPLOAD_EXTEND_MODEL,
        )
    )
    for item in MODEL_SPECS:
        if item.slug in {"seedance-2-fast", "elevenlabs-turbo-2-5"}:
            continue
        values: dict[str, object] = {
            "enabled_for_submission": item.slug in SUBMISSION_MODEL_SLUGS,
        }
        if item.slug == "seedance-2-mini":
            values["rank"] = 2
        item = replace(item, **values)
        models.append(item)
    models = [
        replace(item, enabled_for_submission=item.slug in SUBMISSION_MODEL_SLUGS) for item in models
    ]
    return tuple(models)


ACTIVE_MODEL_SPECS = _active_models()


class ModelRegistry(BaseModelRegistry):
    """FoxGen catalog with explicit separation between discovery and paid submission."""

    def __init__(self, models: Iterable[ModelSpec] = ACTIVE_MODEL_SPECS) -> None:
        items = tuple(models)
        for item in items:
            if item.enabled_for_submission and not item.provider_id_verified:
                raise ValueError(
                    f"Submission model {item.slug} has an unverified provider identifier"
                )
            if item.enabled_for_submission and not item.schema_verified:
                raise ValueError(f"Submission model {item.slug} has no verified schema")
            if item.enabled_for_submission and item.contract == InputContract.PASSTHROUGH:
                raise ValueError(f"Submission model {item.slug} cannot use passthrough validation")
        super().__init__(items)

    def submission_models(self) -> tuple[ModelSpec, ...]:
        return tuple(item for item in self.list() if item.production_ready)
