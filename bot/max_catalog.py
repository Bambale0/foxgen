from __future__ import annotations

from pathlib import Path

from bot.services.preset_manager import PresetManager

MAX_PRICE_PATH = Path("data/max_price.json")
MAX_IMAGE_MODELS = (
    "nano-banana-2-lite",
    "seedream_5_pro",
    "banana_pro",
    "banana_2",
    "flux_pro",
    "seedream_edit",
    "grok_imagine_i2i",
    "wan_27",
)
MAX_VIDEO_TYPES: dict[str, tuple[str, ...]] = {
    "text": (
        "seedance_2_5",
        "v3_pro",
        "v3_std",
        "v26_pro",
        "seedance_2",
        "gemini_omni",
        "veo3",
        "veo3_fast",
        "veo3_lite",
    ),
    "imgtxt": (
        "seedance_2_5",
        "v3_pro",
        "v3_std",
        "v26_pro",
        "grok_imagine",
        "grok_imagine_v15",
        "seedance_2",
        "gemini_omni",
        "veo3_fast",
    ),
    "video": (
        "seedance_2_5",
        "seedance_2",
        "glow",
        "gemini_omni",
    ),
}


class MaxPresetManager(PresetManager):
    """MAX-owned catalog/pricing snapshot.

    Provider implementations stay shared, but MAX never reads Telegram's live
    price file. Prices and enabled models can diverge safely after the initial
    1:1 snapshot.
    """

    def __init__(self, *, price_path: str | Path = MAX_PRICE_PATH):
        super().__init__(price_path=str(price_path))
        self.price_path = Path(price_path)

    def image_models(self) -> dict[str, float]:
        models: dict[str, float] = {}
        for key in MAX_IMAGE_MODELS:
            if key == "seedream_5_pro":
                models[key] = 2.0
            else:
                models[key] = float(self.get_generation_cost(key))
        return models

    def video_models(self, generation_type: str | None = None) -> dict[str, dict | float]:
        raw = dict(self.get_price_config().get("costs_reference", {}).get("video_models", {}))
        keys = (
            MAX_VIDEO_TYPES.get(str(generation_type), ())
            if generation_type is not None
            else tuple(dict.fromkeys(model for values in MAX_VIDEO_TYPES.values() for model in values))
        )
        result: dict[str, dict | float] = {}
        for key in keys:
            pricing_key = "gemini_omni_video" if key == "gemini_omni" else key
            if pricing_key in raw:
                result[key] = raw[pricing_key]
        return result

    def image_cost(self, model: str) -> float:
        if model == "seedream_5_pro":
            return 2.0
        return float(self.get_generation_cost(model))

    def video_cost(
        self,
        model: str,
        *,
        duration: int = 5,
        quality: str | None = None,
    ) -> float:
        pricing_model = "gemini_omni_video" if model == "gemini_omni" else model
        if quality:
            return float(self.get_video_cost_with_quality(pricing_model, duration, quality))
        return float(self.get_video_cost(pricing_model, duration))


max_preset_manager = MaxPresetManager()
