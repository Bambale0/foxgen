from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class InputContract(StrEnum):
    PASSTHROUGH = "passthrough"
    PROMPT = "prompt"
    PROMPT_IMAGES = "prompt_images"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    TEXT_TO_SPEECH = "text_to_speech"
    DIALOGUE = "dialogue"
    ELEVENLABS_TTS_TURBO_2_5 = "elevenlabs_tts_turbo_2_5"
    SUNO_V5_GENERATE = "suno_v5_generate"
    SUNO_V5_EXTEND = "suno_v5_extend"
    SUNO_V5_UPLOAD_COVER = "suno_v5_upload_cover"
    SUNO_V5_UPLOAD_EXTEND = "suno_v5_upload_extend"
    SEEDREAM_45_TEXT = "seedream_45_text"
    SEEDREAM_45_EDIT = "seedream_45_edit"
    SEEDREAM_5_TEXT = "seedream_5_text"
    SEEDREAM_5_IMAGE = "seedream_5_image"
    NANO_BANANA = "nano_banana"
    SEEDANCE_2 = "seedance_2"
    KLING_3 = "kling_3"


SeedreamAspectRatio = Literal[
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "21:9",
]
SeedreamQuality = Literal["basic", "high"]
ImageOutputFormat = Literal["png", "jpg"]
NanoBananaAspectRatio = Literal[
    "auto",
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "21:9",
]
NanoBananaResolution = Literal["1K", "2K", "4K"]
SeedanceResolution = Literal["720p"]
SeedanceAspectRatio = Literal["16:9", "9:16", "1:1"]
SeedanceDuration = Literal[5, 10, 15]


class OpenInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PassthroughInput(OpenInput):
    @model_validator(mode="before")
    @classmethod
    def require_non_empty_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not value:
            raise ValueError("input payload must not be empty")
        return value


class PromptInput(OpenInput):
    prompt: str = Field(min_length=1, max_length=10_000)


class PromptImagesInput(PromptInput):
    image_urls: list[AnyHttpUrl] = Field(default_factory=list)
    input_urls: list[AnyHttpUrl] = Field(default_factory=list)
    image_input: list[AnyHttpUrl] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_images(self) -> "PromptImagesInput":
        if not (self.image_urls or self.input_urls or self.image_input):
            raise ValueError("at least one image URL is required")
        return self


class ImageInput(OpenInput):
    image_url: AnyHttpUrl | None = None
    image_urls: list[AnyHttpUrl] = Field(default_factory=list)
    input_urls: list[AnyHttpUrl] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_image(self) -> "ImageInput":
        if self.image_url is None and not (self.image_urls or self.input_urls):
            raise ValueError("an image URL is required")
        return self


class VideoInput(OpenInput):
    video_url: AnyHttpUrl | None = None
    video_urls: list[AnyHttpUrl] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_video(self) -> "VideoInput":
        if self.video_url is None and not self.video_urls:
            raise ValueError("a video URL is required")
        return self


class AudioInput(OpenInput):
    audio_url: AnyHttpUrl


class TextToSpeechInput(OpenInput):
    text: str = Field(min_length=1, max_length=50_000)
    voice: str = Field(min_length=1)


class ElevenLabsTurbo25Input(StrictInput):
    """Reviewed safe KIE request subset for ElevenLabs Turbo 2.5 TTS."""

    text: str = Field(min_length=1, max_length=50_000)
    voice: str = Field(min_length=1, max_length=128)
    stability: float = Field(default=0.5, ge=0.0, le=1.0)
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0)
    style: float = Field(default=0.0, ge=0.0, le=1.0)
    speed: float = Field(default=1.0, ge=0.7, le=1.2)
    timestamps: bool = False
    previous_text: str = Field(default="", max_length=50_000)
    next_text: str = Field(default="", max_length=50_000)
    language_code: str = Field(default="", max_length=16, pattern=r"^[A-Za-z0-9_-]*$")


class SunoV5GenerateInput(StrictInput):
    """Reviewed KIE Suno V5 core text-to-song request contract."""

    custom_mode: bool = False
    instrumental: bool = False
    prompt: str = Field(default="", max_length=5_000)
    style: str = Field(default="", max_length=1_000)
    title: str = Field(default="", max_length=80)
    negative_tags: str = Field(default="", max_length=1_000)
    vocal_gender: Literal["m", "f"] | None = None
    style_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    weirdness_constraint: float | None = Field(default=None, ge=0.0, le=1.0)
    audio_weight: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_mode_contract(self) -> "SunoV5GenerateInput":
        prompt = self.prompt.strip()
        style = self.style.strip()
        title = self.title.strip()
        advanced_present = bool(
            style
            or title
            or self.negative_tags.strip()
            or self.vocal_gender is not None
            or self.style_weight is not None
            or self.weirdness_constraint is not None
            or self.audio_weight is not None
        )

        if not self.custom_mode:
            if not prompt:
                raise ValueError("prompt is required in simple mode")
            if len(prompt) > 500:
                raise ValueError("simple-mode prompt must be at most 500 characters")
            if advanced_present:
                raise ValueError("advanced Suno fields require custom_mode=true")
            return self

        if not style:
            raise ValueError("style is required in custom mode")
        if not title:
            raise ValueError("title is required in custom mode")
        if not self.instrumental and not prompt:
            raise ValueError("prompt is required for custom vocal music")
        return self


class SunoV5ExtendInput(StrictInput):
    """Reviewed KIE V5 music-extension request plus owner-audit source identity."""

    source_generation_id: UUID
    audio_id: str = Field(min_length=1, max_length=128)
    default_param_flag: bool = False
    prompt: str = Field(default="", max_length=5_000)
    style: str = Field(default="", max_length=1_000)
    title: str = Field(default="", max_length=100)
    continue_at: float | None = Field(default=None, gt=0)
    negative_tags: str = Field(default="", max_length=1_000)
    vocal_gender: Literal["m", "f"] | None = None
    style_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    weirdness_constraint: float | None = Field(default=None, ge=0.0, le=1.0)
    audio_weight: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_extend_mode(self) -> "SunoV5ExtendInput":
        advanced_present = bool(
            self.prompt.strip()
            or self.style.strip()
            or self.title.strip()
            or self.continue_at is not None
            or self.negative_tags.strip()
            or self.vocal_gender is not None
            or self.style_weight is not None
            or self.weirdness_constraint is not None
            or self.audio_weight is not None
        )
        if not self.default_param_flag:
            if advanced_present:
                raise ValueError("custom extend fields require default_param_flag=true")
            return self

        if not self.prompt.strip():
            raise ValueError("prompt is required for custom V5 extension")
        if not self.style.strip():
            raise ValueError("style is required for custom V5 extension")
        if not self.title.strip():
            raise ValueError("title is required for custom V5 extension")
        if self.continue_at is None:
            raise ValueError("continue_at is required for custom V5 extension")
        return self


class SunoV5UploadCoverInput(StrictInput):
    """Reviewed V5 upload-cover contract with FoxGen-owned input identity."""

    input_storage_key: str = Field(min_length=8, max_length=512, pattern=r"^inputs/")
    custom_mode: bool = False
    instrumental: bool = False
    prompt: str = Field(default="", max_length=5_000)
    style: str = Field(default="", max_length=1_000)
    title: str = Field(default="", max_length=100)
    negative_tags: str = Field(default="", max_length=1_000)
    vocal_gender: Literal["m", "f"] | None = None
    style_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    weirdness_constraint: float | None = Field(default=None, ge=0.0, le=1.0)
    audio_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    persona_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_upload_cover_mode(self) -> "SunoV5UploadCoverInput":
        prompt = self.prompt.strip()
        style = self.style.strip()
        title = self.title.strip()
        advanced_present = bool(
            style
            or title
            or self.negative_tags.strip()
            or self.vocal_gender is not None
            or self.style_weight is not None
            or self.weirdness_constraint is not None
            or self.audio_weight is not None
            or (self.persona_id is not None and self.persona_id.strip())
        )
        if not self.custom_mode:
            if not prompt:
                raise ValueError("prompt is required in simple upload-cover mode")
            if len(prompt) > 500:
                raise ValueError("simple upload-cover prompt must be at most 500 characters")
            if advanced_present:
                raise ValueError("advanced upload-cover fields require custom_mode=true")
            return self

        if not style:
            raise ValueError("style is required in custom upload-cover mode")
        if not title:
            raise ValueError("title is required in custom upload-cover mode")
        if not self.instrumental and not prompt:
            raise ValueError("prompt is required for custom vocal upload-cover")
        return self


class SunoV5UploadExtendInput(StrictInput):
    """Reviewed V5 upload-extend contract with FoxGen-owned input identity."""

    input_storage_key: str = Field(min_length=8, max_length=512, pattern=r"^inputs/")
    default_param_flag: bool = False
    instrumental: bool = False
    prompt: str = Field(default="", max_length=5_000)
    style: str = Field(default="", max_length=1_000)
    title: str = Field(default="", max_length=100)
    continue_at: float | None = Field(default=None, gt=0)
    negative_tags: str = Field(default="", max_length=1_000)
    vocal_gender: Literal["m", "f"] | None = None
    style_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    weirdness_constraint: float | None = Field(default=None, ge=0.0, le=1.0)
    audio_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    persona_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_upload_extend_mode(self) -> "SunoV5UploadExtendInput":
        prompt = self.prompt.strip()
        style = self.style.strip()
        title = self.title.strip()
        advanced_present = bool(
            style
            or title
            or self.continue_at is not None
            or self.negative_tags.strip()
            or self.vocal_gender is not None
            or self.style_weight is not None
            or self.weirdness_constraint is not None
            or self.audio_weight is not None
            or (self.persona_id is not None and self.persona_id.strip())
        )
        if not self.default_param_flag:
            if not prompt:
                raise ValueError("prompt is required in default upload-extend mode")
            if advanced_present:
                raise ValueError("custom upload-extend fields require default_param_flag=true")
            return self

        if not style:
            raise ValueError("style is required in custom upload-extend mode")
        if not title:
            raise ValueError("title is required in custom upload-extend mode")
        if self.continue_at is None:
            raise ValueError("continue_at is required in custom upload-extend mode")
        if not self.instrumental and not prompt:
            raise ValueError("prompt is required for custom vocal upload-extend")
        return self


class DialogueLine(StrictInput):
    text: str = Field(min_length=1)
    voice: str = Field(min_length=1)


class DialogueInput(OpenInput):
    dialogue: list[DialogueLine] = Field(min_length=1)


class Seedream45TextInput(StrictInput):
    prompt: str = Field(min_length=1, max_length=10_000)
    aspect_ratio: SeedreamAspectRatio = "1:1"
    quality: SeedreamQuality = "basic"
    nsfw_checker: bool = False


class Seedream45EditInput(Seedream45TextInput):
    image_urls: list[AnyHttpUrl] = Field(min_length=1, max_length=10)


class Seedream5TextInput(StrictInput):
    """Reviewed KIE Market request contract for Seedream 5 Pro text-to-image."""

    prompt: str = Field(min_length=1, max_length=10_000)
    aspect_ratio: SeedreamAspectRatio = "1:1"
    quality: SeedreamQuality = "basic"
    output_format: ImageOutputFormat = "png"
    nsfw_checker: bool = False


class Seedream5ImageInput(Seedream5TextInput):
    """Reviewed KIE Market request contract for Seedream 5 Pro image-to-image."""

    image_urls: list[AnyHttpUrl] = Field(min_length=1, max_length=10)


class NanoBananaInput(StrictInput):
    """Shared reviewed KIE contract for Nano Banana 2 and Nano Banana Pro."""

    prompt: str = Field(min_length=1, max_length=10_000)
    image_input: list[AnyHttpUrl] = Field(default_factory=list, max_length=14)
    aspect_ratio: NanoBananaAspectRatio = "auto"
    resolution: NanoBananaResolution = "1K"
    output_format: ImageOutputFormat = "png"


class Seedance2Input(StrictInput):
    """Reviewed safe request subset for Seedance 2 and Mini."""

    prompt: str = Field(min_length=1, max_length=10_000)
    first_frame_url: AnyHttpUrl | None = None
    last_frame_url: AnyHttpUrl | None = None
    reference_image_urls: list[AnyHttpUrl] = Field(default_factory=list, max_length=6)
    reference_video_urls: list[AnyHttpUrl] = Field(default_factory=list, max_length=3)
    reference_audio_urls: list[AnyHttpUrl] = Field(default_factory=list, max_length=3)
    return_last_frame: bool = False
    generate_audio: bool = False
    resolution: SeedanceResolution = "720p"
    aspect_ratio: SeedanceAspectRatio = "16:9"
    duration: SeedanceDuration = 5
    web_search: bool = False

    @model_validator(mode="after")
    def validate_generation_mode(self) -> "Seedance2Input":
        if self.last_frame_url is not None and self.first_frame_url is None:
            raise ValueError("last_frame_url requires first_frame_url")

        frame_mode = self.first_frame_url is not None or self.last_frame_url is not None
        reference_count = (
            len(self.reference_image_urls)
            + len(self.reference_video_urls)
            + len(self.reference_audio_urls)
        )
        if frame_mode and reference_count:
            raise ValueError(
                "first/last frame mode and multimodal reference mode are mutually exclusive"
            )
        if reference_count > 6:
            raise ValueError("multimodal reference mode accepts at most six references")
        return self


class KlingShot(StrictInput):
    prompt: str = Field(min_length=1, max_length=500)
    duration: int = Field(gt=0, le=12)


class KlingElement(StrictInput):
    name: str = Field(min_length=1)
    description: str = ""
    element_input_urls: list[AnyHttpUrl] = Field(min_length=2, max_length=4)


class Kling3Input(OpenInput):
    prompt: str | None = Field(default=None, max_length=10_000)
    image_urls: list[AnyHttpUrl] = Field(default_factory=list, max_length=2)
    sound: bool = False
    duration: str = "5"
    aspect_ratio: Literal["16:9", "9:16", "1:1"] | None = "16:9"
    mode: Literal["std", "pro", "4K"] = "pro"
    multi_shots: bool = False
    multi_prompt: list[KlingShot] = Field(default_factory=list)
    kling_elements: list[KlingElement] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_shot_mode(self) -> "Kling3Input":
        if self.multi_shots:
            if not self.multi_prompt:
                raise ValueError("multi_prompt is required when multi_shots is true")
        elif not self.prompt:
            raise ValueError("prompt is required for single-shot mode")
        return self


CONTRACT_MODELS: dict[InputContract, type[BaseModel]] = {
    InputContract.PASSTHROUGH: PassthroughInput,
    InputContract.PROMPT: PromptInput,
    InputContract.PROMPT_IMAGES: PromptImagesInput,
    InputContract.IMAGE: ImageInput,
    InputContract.VIDEO: VideoInput,
    InputContract.AUDIO: AudioInput,
    InputContract.TEXT_TO_SPEECH: TextToSpeechInput,
    InputContract.DIALOGUE: DialogueInput,
    InputContract.ELEVENLABS_TTS_TURBO_2_5: ElevenLabsTurbo25Input,
    InputContract.SUNO_V5_GENERATE: SunoV5GenerateInput,
    InputContract.SUNO_V5_EXTEND: SunoV5ExtendInput,
    InputContract.SUNO_V5_UPLOAD_COVER: SunoV5UploadCoverInput,
    InputContract.SUNO_V5_UPLOAD_EXTEND: SunoV5UploadExtendInput,
    InputContract.SEEDREAM_45_TEXT: Seedream45TextInput,
    InputContract.SEEDREAM_45_EDIT: Seedream45EditInput,
    InputContract.SEEDREAM_5_TEXT: Seedream5TextInput,
    InputContract.SEEDREAM_5_IMAGE: Seedream5ImageInput,
    InputContract.NANO_BANANA: NanoBananaInput,
    InputContract.SEEDANCE_2: Seedance2Input,
    InputContract.KLING_3: Kling3Input,
}


SCHEMA_VERIFIED_CONTRACTS: frozenset[InputContract] = frozenset(
    {
        InputContract.ELEVENLABS_TTS_TURBO_2_5,
        InputContract.SUNO_V5_GENERATE,
        InputContract.SUNO_V5_EXTEND,
        InputContract.SUNO_V5_UPLOAD_COVER,
        InputContract.SUNO_V5_UPLOAD_EXTEND,
        InputContract.SEEDREAM_5_TEXT,
        InputContract.SEEDREAM_5_IMAGE,
        InputContract.NANO_BANANA,
        InputContract.SEEDANCE_2,
    }
)


def get_contract(name: str) -> type[BaseModel]:
    try:
        contract = InputContract(name)
        return CONTRACT_MODELS[contract]
    except (ValueError, KeyError) as exc:
        raise KeyError(f"Unknown input contract: {name}") from exc


def is_schema_verified_contract(name: str) -> bool:
    try:
        return InputContract(name) in SCHEMA_VERIFIED_CONTRACTS
    except ValueError:
        return False


def validate_input(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    validated = get_contract(name).model_validate(payload)
    return validated.model_dump(mode="json", exclude_none=True)


def contract_schema(name: str) -> dict[str, Any]:
    return get_contract(name).model_json_schema()
