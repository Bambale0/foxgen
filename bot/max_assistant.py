from __future__ import annotations

import json
from typing import Any

from bot.max_catalog import MaxPresetManager, max_preset_manager
from bot.services.ai_assistant_service import AIAssistantService


class MaxAIAssistantService(AIAssistantService):
    """AI assistant adapter with MAX-owned balance, models and pricing context."""

    def __init__(
        self,
        catalog: MaxPresetManager = max_preset_manager,
    ) -> None:
        super().__init__()
        self.catalog = catalog

    def _get_system_prompt(self, *, is_admin: bool = False) -> str:
        base = super()._get_system_prompt(is_admin=is_admin)
        return (
            f"{base}\n\n"
            "## КАНАЛ MAX\n"
            "Сейчас пользователь общается с HappyFox внутри мессенджера MAX, не Telegram. "
            "Называй внутреннюю валюту MAX символом 🐾 и не называй её бананами. "
            "Используй только цены из блока «Авторитетные цены MAX» ниже. "
            "Не подменяй их Telegram-ценами и не обещай кнопки, которых нет в MAX. "
            "Если точная стоимость зависит от длительности/качества и её нельзя уверенно "
            "вывести из переданных данных, предложи открыть соответствующий экран модели: "
            "там стоимость считается перед запуском."
        )

    def _format_context(self, context: dict) -> str:
        lines = ["- Канал: MAX"]
        if "user_credits" in context:
            lines.append(f"- Баланс MAX: {context['user_credits']} 🐾")
        if "menu_location" in context:
            lines.append(f"- Раздел MAX: {context['menu_location']}")
        if "available_models" in context:
            lines.append(f"- Доступные модели MAX: {context['available_models']}")
        return "\n".join(lines) if lines else "- Канал: MAX"

    def get_pricing_info(self) -> str:
        config = self.catalog.get_price_config()
        costs = config.get("costs_reference", {}) or {}
        image_costs = {
            key: value
            for key, value in self.catalog.image_models().items()
        }
        video_costs = costs.get("video_models", {}) or {}
        packages = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "credits": item.get("credits"),
                "price_rub": item.get("price_rub"),
            }
            for item in self.catalog.get_packages()
        ]
        payload: dict[str, Any] = {
            "image_models": image_costs,
            "video_models": video_costs,
            "packages": packages,
            "credit_rub_value": config.get("credit_rub_value"),
            "service_prices": config.get("service_prices", {}),
        }
        return (
            "Авторитетные цены MAX (🐾), не использовать цены других каналов:\n"
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n"
            "Suno показывает актуальную стоимость прямо на кнопках своего MAX-экрана."
        )


max_ai_assistant_service = MaxAIAssistantService()
