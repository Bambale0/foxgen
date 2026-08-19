import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CANONICAL_IMAGE_ALIASES = {
    "banana_pro": "nano-banana-pro",
    "nano_banana_pro": "nano-banana-pro",
    "nano-banana-pro": "nano-banana-pro",
    "gemini_3_pro": "gemini_3_pro",
    "gemini-3-pro": "gemini_3_pro",
    "gemini-3-pro-image-preview": "gemini_3_pro",
    "banana_2": "banana_2",
    "nanobanana": "banana_2",
    "gemini_2_5_flash": "gemini_2_5_flash",
    "gemini-2.5-flash": "gemini_2_5_flash",
    "gemini-2.5-flash-image": "gemini_2_5_flash",
    "gemini-3.1-flash-image-preview": "banana_2",
    "nano-banana-2-lite": "nano-banana-2-lite",
    "nano_banana_2_lite": "nano-banana-2-lite",
    "banana_2_lite": "nano-banana-2-lite",
    "seedream": "seedream",
    "seedream_45": "seedream_45",
    "seedream_edit": "seedream_edit",
    "seedream_5_pro": "seedream_edit",
    "flux_pro": "flux_pro",
    "grok_imagine_i2i": "grok_imagine_i2i",
    "wan_27": "wan_27",
    "wan27": "wan_27",
    "wan-2.7": "wan_27",
    "z_image_turbo": "z_image_turbo",
    "z-image-turbo": "z_image_turbo",
}

CANONICAL_VIDEO_ALIASES = {
    "v3_std": "v3_std",
    "kling_v3_std": "v3_std",
    "kling-v3-std": "v3_std",
    "v3_pro": "v3_pro",
    "kling_v3_pro": "v3_pro",
    "kling-v3-pro": "v3_pro",
    "v26_pro": "v26_pro",
    "grok_imagine": "grok_imagine",
    "grok_imagine_v15": "grok_imagine_v15",
    "grok-imagine-video-1-5-preview": "grok_imagine_v15",
    "seedance_2": "seedance_2",
    "bytedance/seedance-2": "seedance_2",
    "seedance_2_5": "seedance_2_5",
    "seedance_2.5": "seedance_2_5",
    "seedance-2.5": "seedance_2_5",
    "bytedance/seedance-2-5": "seedance_2_5",
    "glow": "glow",
    "motion_control_v26": "motion_control_v26",
    "motion_control_v30": "motion_control_v30",
    "veo3": "veo3",
    "veo3_fast": "veo3_fast",
    "veo3_lite": "veo3_lite",
    "gemini_omni": "gemini_omni_video",
    "gemini-omni": "gemini_omni_video",
    "gemini_omni_video": "gemini_omni_video",
    "gemini-omni-video": "gemini_omni_video",
    "gemini_omni_audio": "gemini_omni_audio",
    "gemini-omni-audio": "gemini_omni_audio",
    "gemini_omni_character": "gemini_omni_character",
    "gemini-omni-character": "gemini_omni_character",
    "avatar_std": "avatar_std",
    "avatar_pro": "avatar_pro",
    "v26_motion_std": "v26_motion_std",
    "v26_motion_pro": "v26_motion_pro",
    # legacy aliases kept only for safe DB/config compatibility
    "v3_omni_std": "v3_std",
    "v3_omni_pro": "v3_pro",
    "v3_omni_std_r2v": "v3_std",
    "v3_omni_pro_r2v": "v3_pro",
}

DEFAULT_IMAGE_COST = 3
DEFAULT_VIDEO_COST = 8
DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT = 10
DEFAULT_CREDIT_RUB_VALUE = 10
DEFAULT_PHOTO_PROMPT_PRICE_RUB = 1
DEFAULT_VIDEO_PROMPT_COST = 3


@dataclass
class Preset:
    id: str
    name: str
    prompt: str
    cost: int
    model: str
    requires_input: bool
    requires_upload: bool = False
    input_prompt: Optional[str] = None
    placeholders: List[str] = field(default_factory=list)
    aspect_ratio: Optional[str] = None
    duration: Optional[int] = None
    category: str = ""

    def format_prompt(self, **kwargs) -> str:
        """Заполняет плейсхолдеры в промпте."""
        try:
            return self.prompt.format(**kwargs)
        except KeyError:
            return self.prompt


class PresetManager:
    def __init__(
        self,
        presets_path: str = "data/presets.json",
        price_path: str = "data/price.json",
    ):
        self.presets_path = Path(presets_path)
        self.price_path = Path(price_path)
        self._presets: Dict[str, Preset] = {}
        self._categories: Dict[str, Dict] = {}
        self._price_config: Dict = {}
        self._admin_ids: List[int] = []
        self._default_values: Dict[str, List[str]] = {}
        self.load_all()

    def load_all(self):
        """Загружает конфигурацию пресетов и прайса."""
        self._load_presets()
        self._load_price()

    def _load_presets(self):
        """Загружает пресеты из JSON, если файл существует."""
        if not self.presets_path.exists():
            self._categories = {}
            self._presets = {}
            self._default_values = {}
            return

        try:
            with open(self.presets_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._categories = data.get("categories", {})
            self._presets = {}

            for cat_key, cat_data in self._categories.items():
                for preset_data in cat_data.get("presets", []):
                    preset = Preset(
                        id=preset_data["id"],
                        name=preset_data["name"],
                        prompt=preset_data["prompt"],
                        cost=preset_data["cost"],
                        model=preset_data.get("model", "banana_2"),
                        requires_input=preset_data.get("requires_input", False),
                        requires_upload=preset_data.get("requires_upload", False),
                        input_prompt=preset_data.get("input_prompt"),
                        placeholders=preset_data.get("placeholders", []),
                        aspect_ratio=preset_data.get("aspect_ratio"),
                        duration=preset_data.get("duration"),
                        category=cat_key,
                    )
                    self._presets[preset.id] = preset

            self._default_values = data.get("default_values", {})
        except Exception as e:
            print(f"Error loading presets: {e}")
            self._categories = {}
            self._presets = {}
            self._default_values = {}

    def _load_price(self):
        """Загружает прайс-лист."""
        if not self.price_path.exists():
            raise FileNotFoundError(f"Price file not found: {self.price_path}")

        with open(self.price_path, "r", encoding="utf-8") as f:
            self._price_config = json.load(f)
        self._admin_ids = self._price_config.get("admin_ids", [])

    def reload(self) -> bool:
        """Перезагружает конфигурацию без перезапуска бота."""
        try:
            self.load_all()
            return True
        except Exception as e:
            print(f"Error reloading presets: {e}")
            return False

    def get_preset(self, preset_id: str) -> Optional[Preset]:
        return self._presets.get(preset_id)

    def get_category_presets(self, category: str) -> List[Preset]:
        cat_data = self._categories.get(category, {})
        preset_ids = [p["id"] for p in cat_data.get("presets", [])]
        return [self._presets[pid] for pid in preset_ids if pid in self._presets]

    def get_categories(self) -> Dict[str, Dict]:
        return {
            key: {"name": data["name"], "description": data.get("description", "")}
            for key, data in self._categories.items()
        }

    def get_packages(self) -> List[Dict]:
        return self._price_config.get("packages", [])

    def get_price_config(self) -> Dict:
        return deepcopy(self._price_config)

    def get_partner_exchange_rub_per_credit(self) -> float:
        exchange_cfg = self._price_config.get("partner_exchange", {}) or {}
        value = exchange_cfg.get("rub_per_credit", DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT)
        return float(value or DEFAULT_PARTNER_EXCHANGE_RUB_PER_CREDIT)

    def get_credit_rub_value(self) -> float:
        value = self._price_config.get("credit_rub_value", DEFAULT_CREDIT_RUB_VALUE)
        normalized = float(value or DEFAULT_CREDIT_RUB_VALUE)
        return normalized if normalized > 0 else float(DEFAULT_CREDIT_RUB_VALUE)

    def get_photo_prompt_price_rub(self) -> float:
        service_prices = self._price_config.get("service_prices", {}) or {}
        value = service_prices.get("photo_prompt_rub", DEFAULT_PHOTO_PROMPT_PRICE_RUB)
        return round(float(value or DEFAULT_PHOTO_PROMPT_PRICE_RUB), 2)

    def get_photo_prompt_cost(self) -> float:
        return round(self.get_photo_prompt_price_rub() / self.get_credit_rub_value(), 4)

    def get_video_prompt_cost(self) -> float:
        service_prices = self._price_config.get("service_prices", {}) or {}
        value = service_prices.get("video_prompt", DEFAULT_VIDEO_PROMPT_COST)
        return float(value or DEFAULT_VIDEO_PROMPT_COST)

    def get_package(self, package_id: str) -> Optional[Dict]:
        for pkg in self.get_packages():
            if pkg["id"] == package_id:
                return pkg
        return None

    def is_admin(self, user_id: int) -> bool:
        return user_id in self._admin_ids

    def get_default_values(self, key: str) -> List[str]:
        return self._default_values.get(key, [])

    def get_all_presets(self) -> Dict[str, Preset]:
        return self._presets.copy()

    def _costs_reference(self) -> Dict:
        return self._price_config.get("costs_reference", {})

    def _image_costs(self) -> Dict:
        return self._costs_reference().get("image_models", {})

    def _video_costs(self) -> Dict:
        return self._costs_reference().get("video_models", {})

    def _legacy_costs(self) -> Dict:
        return self._costs_reference().get("legacy_keys", {})

    def normalize_image_model_key(self, model: str) -> str:
        if not model:
            return ""
        return CANONICAL_IMAGE_ALIASES.get(model.lower(), model.lower())

    def normalize_video_model_key(self, model: str) -> str:
        if not model:
            return ""
        return CANONICAL_VIDEO_ALIASES.get(model.lower(), model.lower())

    def _clamp_video_duration(
        self, duration: int, model_config: Dict | None = None
    ) -> int:
        """Clamp duration using model-specific bounds when the price config has them."""
        model_config = model_config or {}
        min_duration = int(model_config.get("duration_min", 3) or 3)
        max_duration = int(model_config.get("duration_max", 30) or 30)
        if min_duration > max_duration:
            min_duration, max_duration = max_duration, min_duration
        return max(min_duration, min(max_duration, int(duration)))

    def _format_cost(self, value):
        """Округляем до ближайшего 0.5 для поддержки дробных кредитов."""
        v = float(value)
        rounded = round(v * 2) / 2
        return int(rounded) if rounded == int(rounded) else rounded

    def get_generation_cost(self, model: str, options: dict = None) -> float:
        """Вернуть стоимость генерации изображения по каноническому ключу модели."""
        image_models = self._image_costs()
        legacy_keys = self._legacy_costs()
        key = self.normalize_image_model_key(model)

        if key in image_models:
            return self._format_cost(image_models[key])
        if key in legacy_keys:
            return self._format_cost(legacy_keys[key])
        return DEFAULT_IMAGE_COST

    def get_video_cost(self, model: str, duration: int = 5) -> float:
        """Вернуть стоимость генерации видео по каноническому ключу модели."""
        video_models = self._video_costs()
        legacy_keys = self._legacy_costs()
        duration_costs = self._costs_reference().get("video_duration_costs", {})

        key = self.normalize_video_model_key(model)
        model_config = video_models.get(key) or {}
        duration = self._clamp_video_duration(duration, model_config)

        if key in video_models:
            specific = model_config.get("duration_costs", {})
            if str(duration) in specific:
                return self._format_cost(specific[str(duration)])
            base = model_config.get("base") or model_config.get("cost")
            if base is not None:
                default_dur = int(
                    model_config.get("default_duration")
                    or (
                        6
                        if key.startswith("veo3") or key.startswith("gemini_omni")
                        else 5
                    )
                )
                per_sec = base / default_dur
                raw = duration * per_sec
                return self._format_cost(raw)

        if key in legacy_keys:
            return int(legacy_keys[key])

        if str(duration) in duration_costs:
            return self._format_cost(duration_costs[str(duration)])

        return DEFAULT_VIDEO_COST

    def get_video_cost_with_quality(
        self, model: str, duration: int = 5, quality: str | None = None
    ) -> float:
        """Вернуть стоимость видео с учётом качества (например, 720p/1080p для Motion Control).

        quality_costs хранят стоимость за 1 секунду; реальная цена
        считается пропорционально длительности.
        """
        if quality:
            video_models = self._video_costs()
            key = self.normalize_video_model_key(model)
            if key in video_models:
                model_config = video_models[key] or {}
                quality_costs = model_config.get("quality_costs", {})
                quality_key = str(quality).strip().lower()
                quality_lookup = {
                    str(item_key).strip().lower(): item_value
                    for item_key, item_value in quality_costs.items()
                }
                if quality_key in quality_lookup:
                    per_sec = quality_lookup[quality_key]
                    duration = self._clamp_video_duration(duration, model_config)
                    raw = per_sec * duration
                    return self._format_cost(raw)
        return self.get_video_cost(model, duration)

    def get_video_quality_costs(self, model: str) -> Dict[str, float]:
        """Вернуть цены качества за 1 секунду для видео-модели."""
        video_models = self._video_costs()
        key = self.normalize_video_model_key(model)
        model_config = video_models.get(key) or {}
        return deepcopy(model_config.get("quality_costs", {}))

    def get_video_cost_per_second(
        self, model: str, duration: int = 5, quality: str | None = None
    ):
        """Вернуть стоимость генерации видео за одну секунду."""
        duration = max(1, int(duration))
        if quality:
            total_cost = self.get_video_cost_with_quality(model, duration, quality)
        else:
            total_cost = self.get_video_cost(model, duration)
        return self._format_cost(total_cost / duration)

    def get_image_cost(self, model: str) -> int:
        return self.get_generation_cost(model)

    def update_price_config(self, price_config: Dict) -> bool:
        """Сохраняет обновлённый прайс и перезагружает конфиг."""
        with open(self.price_path, "w", encoding="utf-8") as f:
            json.dump(price_config, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return self.reload()


preset_manager = PresetManager()
