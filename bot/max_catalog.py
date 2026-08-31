from __future__ import annotations

from pathlib import Path

from bot.services.preset_manager import PresetManager

MAX_PRICE_PATH = Path("data/max_price.json")


class MaxPresetManager(PresetManager):
    """MAX-owned catalog/pricing snapshot.

    Provider implementations stay shared, but MAX never reads Telegram's live
    price file. This allows prices and enabled models to diverge safely later.
    """

    def __init__(self, *, price_path: str | Path = MAX_PRICE_PATH):
        super().__init__(presets_path="data/presets.json", price_path=str(price_path))

    def image_models(self) -> dict:
        return dict(self.get_price_config().get("costs_reference", {}).get("image_models", {}))

    def video_models(self) -> dict:
        return dict(self.get_price_config().get("costs_reference", {}).get("video_models", {}))


max_preset_manager = MaxPresetManager()
