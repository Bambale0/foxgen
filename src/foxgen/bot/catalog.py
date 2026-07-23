from dataclasses import dataclass
from enum import StrEnum


class Product(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class GenerationMode(StrEnum):
    IMAGE_TEXT = "image_text"
    IMAGE_EDIT = "image_edit"
    VIDEO_TEXT = "video_text"
    VIDEO_IMAGE = "video_image"
    VIDEO_REFERENCE = "video_reference"


@dataclass(frozen=True, slots=True)
class ModelChoice:
    slug: str
    title: str
    summary: str


MODE_TITLES: dict[GenerationMode, str] = {
    GenerationMode.IMAGE_TEXT: "Изображение по описанию",
    GenerationMode.IMAGE_EDIT: "Редактирование изображения",
    GenerationMode.VIDEO_TEXT: "Видео по описанию",
    GenerationMode.VIDEO_IMAGE: "Оживить изображение",
    GenerationMode.VIDEO_REFERENCE: "Видео по референсам",
}


MODELS_BY_MODE: dict[GenerationMode, tuple[ModelChoice, ...]] = {
    GenerationMode.IMAGE_TEXT: (
        ModelChoice("seedream-5-pro", "Seedream 5 Pro", "максимальное качество и текст"),
        ModelChoice("nano-banana-2", "Nano Banana 2", "быстро и универсально"),
        ModelChoice("nano-banana-pro", "Nano Banana Pro", "сложные композиции"),
    ),
    GenerationMode.IMAGE_EDIT: (
        ModelChoice("seedream-5-pro-edit", "Seedream 5 Pro Edit", "точное премиальное редактирование"),
        ModelChoice("nano-banana-2", "Nano Banana 2", "быстрые правки по фото"),
        ModelChoice("nano-banana-pro", "Nano Banana Pro", "сложные изменения и консистентность"),
    ),
    GenerationMode.VIDEO_TEXT: (
        ModelChoice("seedance-2", "Seedance 2", "лучшее качество и звук"),
        ModelChoice("seedance-2-mini", "Seedance 2 Mini", "быстрее и дешевле"),
    ),
    GenerationMode.VIDEO_IMAGE: (
        ModelChoice("seedance-2", "Seedance 2", "кинематографичное оживление"),
        ModelChoice("seedance-2-mini", "Seedance 2 Mini", "быстрые ролики из фото"),
    ),
    GenerationMode.VIDEO_REFERENCE: (
        ModelChoice("seedance-2", "Seedance 2", "мультимодальные референсы"),
        ModelChoice("seedance-2-mini", "Seedance 2 Mini", "референсы с меньшей стоимостью"),
    ),
}


IMAGE_ASPECT_RATIOS: tuple[tuple[str, str], ...] = (
    ("1:1", "1 × 1"),
    ("16:9", "16 × 9"),
    ("9:16", "9 × 16"),
    ("4:3", "4 × 3"),
    ("3:4", "3 × 4"),
)

VIDEO_ASPECT_RATIOS: tuple[tuple[str, str], ...] = (
    ("16:9", "16 × 9"),
    ("9:16", "9 × 16"),
    ("1:1", "1 × 1"),
)


MODE_CALLBACKS: dict[str, GenerationMode] = {
    "mode:image:text": GenerationMode.IMAGE_TEXT,
    "mode:image:edit": GenerationMode.IMAGE_EDIT,
    "mode:video:text": GenerationMode.VIDEO_TEXT,
    "mode:video:image": GenerationMode.VIDEO_IMAGE,
    "mode:video:reference": GenerationMode.VIDEO_REFERENCE,
}


def product_for_mode(mode: GenerationMode) -> Product:
    return Product.IMAGE if mode.value.startswith("image_") else Product.VIDEO


def mode_requires_media(mode: GenerationMode) -> bool:
    return mode in {
        GenerationMode.IMAGE_EDIT,
        GenerationMode.VIDEO_IMAGE,
        GenerationMode.VIDEO_REFERENCE,
    }


def mode_supports_multiple_media(mode: GenerationMode) -> bool:
    return mode == GenerationMode.VIDEO_REFERENCE


def model_uses_seedream_quality(slug: str) -> bool:
    return slug.startswith("seedream-5-pro")


def model_choice(mode: GenerationMode, slug: str) -> ModelChoice:
    for choice in MODELS_BY_MODE[mode]:
        if choice.slug == slug:
            return choice
    raise KeyError(f"Model {slug} is unavailable for mode {mode}")
