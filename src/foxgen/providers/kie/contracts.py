from enum import StrEnum
from typing import Any, Literal

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
    SEEDREAM_45_TEXT = "seedream_45_text"
    SEEDREAM_45_EDIT = "seedream_45_edit"
    SEEDREAM_5_TEXT = "seedream_5_text"
    SEEDREAM_5_IMAGE = "seedream_5_image"
    NANO_BANANA = "nano_banana"
    SEEDANCE_2 = "seedance_2"
    KLING_3 = "kling_3"


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


class DialogueLine(StrictInput):
    text: str = Field(min_length=1)
    voice: str = Field(min_length=1)


class DialogueInput(OpenInput):
    dialogue: list[DialogueLine] = Field(min_length=1)


class Seedream45TextInput(StrictInput):
    """Exact KIE Market contract for Seedream 4.5 text-to-image."""

    prompt: str = Field(min_length=1, max_length=10_000)
    aspect_ratio: str = "1:1"
    quality: str = "basic"
    nsfw_checker: bool = False


class Seedream45EditInput(Seedream45TextInput):
    """Exact KIE Market contract for Seedream 4.5 image editing."""

    image_urls: list[AnyHttpUrl] = Field(min_length=1)


class Seedream5TextInput(StrictInput):
    prompt: str = Field(min_length=1, max_length=10_000)
    aspect_ratio: str = "1:1"
    quality: str = "basic"
    output_format: Literal["png", "jpg", "jpeg"] = "png"
    nsfw_checker: bool = False


class Seedream5ImageInput(Seedream5TextInput):
    image_urls: list[AnyHttpUrl] = Field(min_length=1)


class NanoBananaInput(StrictInput):
    prompt: str = Field(min_length=1, max_length=10_000)
    image_input: list[AnyHttpUrl] = Field(default_factory=list)
    aspect_ratio: str = "auto"
    resolution: str = "1K"
    output_format: Literal["png", "jpg", "jpeg"] = "png"


class Seedance2Input(StrictInput):
    prompt: str = Field(min_length=1, max_length=10_000)
    first_frame_url: AnyHttpUrl | None = None
    last_frame_url: AnyHttpUrl | None = None
    reference_image_urls: list[AnyHttpUrl] = Field(default_factory=list)
    reference_video_urls: list[AnyHttpUrl] = Field(default_factory=list)
    reference_audio_urls: list[AnyHttpUrl] = Field(default_factory=list)
    return_last_frame: bool = False
    generate_audio: bool = False
    resolution: str = "720p"
    aspect_ratio: str = "16:9"
    duration: int = Field(default=5, gt=0)
    web_search: bool = False

    @model_validator(mode="after")
    def validate_generation_mode(self) -> "Seedance2Input":
        if self.last_frame_url is not None and self.first_frame_url is None:
            raise ValueError("last_frame_url requires first_frame_url")

        frame_mode = self.first_frame_url is not None or self.last_frame_url is not None
        reference_mode = bool(
            self.reference_image_urls
            or self.reference_video_urls
            or self.reference_audio_urls
        )
        if frame_mode and reference_mode:
            raise ValueError(
                "first/last frame mode and multimodal reference mode are mutually exclusive"
            )
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
    InputContract.SEEDREAM_45_TEXT: Seedream45TextInput,
    InputContract.SEEDREAM_45_EDIT: Seedream45EditInput,
    InputContract.SEEDREAM_5_TEXT: Seedream5TextInput,
    InputContract.SEEDREAM_5_IMAGE: Seedream5ImageInput,
    InputContract.NANO_BANANA: NanoBananaInput,
    InputContract.SEEDANCE_2: Seedance2Input,
    InputContract.KLING_3: Kling3Input,
}


def get_contract(name: str) -> type[BaseModel]:
    try:
        contract = InputContract(name)
        return CONTRACT_MODELS[contract]
    except (ValueError, KeyError) as exc:
        raise KeyError(f"Unknown input contract: {name}") from exc


def validate_input(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    validated = get_contract(name).model_validate(payload)
    return validated.model_dump(mode="json", exclude_none=True)


def contract_schema(name: str) -> dict[str, Any]:
    return get_contract(name).model_json_schema()
