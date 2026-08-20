"""Apply the HappyFox product delta to the proven tanyapi runtime.

The migration deliberately keeps stable provider/database identifiers intact. This
script patches only product presentation and product-owned configuration hooks and
fails closed if an expected upstream anchor changes.
"""

from pathlib import Path

COMMON_PATH = Path("bot/handlers/common.py")
PAYMENTS_PATH = Path("bot/handlers/payments.py")
PRESET_MANAGER_PATH = Path("bot/services/preset_manager.py")

PRODUCT_IMPORT = "from bot.product import product\n"
PRODUCT_IMPORT_ANCHOR = "from bot.config import config\n"
OLD_MAIN_MENU_BRAND = '        "🏠 <b>NEUROMIX</b>\\n"\n'
NEW_MAIN_MENU_BRAND = '        f"🏠 <b>{html.escape(product.brand_name)}</b>\\n"\n'


def _ensure_import(text: str, *, anchor: str, import_line: str, context: str) -> str:
    if import_line in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{context} import anchor was not found")
    return text.replace(anchor, anchor + import_line, 1)


def _patch_common() -> None:
    text = COMMON_PATH.read_text(encoding="utf-8")
    text = _ensure_import(
        text,
        anchor=PRODUCT_IMPORT_ANCHOR,
        import_line=PRODUCT_IMPORT,
        context="HappyFox common",
    )

    if OLD_MAIN_MENU_BRAND in text:
        text = text.replace(OLD_MAIN_MENU_BRAND, NEW_MAIN_MENU_BRAND, 1)
    elif NEW_MAIN_MENU_BRAND not in text:
        raise RuntimeError("HappyFox main-menu brand anchor was not found")

    if '🏠 <b>NEUROMIX</b>' in text:
        raise RuntimeError("Stale NEUROMIX main-menu brand remains")

    COMMON_PATH.write_text(text, encoding="utf-8")


def _patch_preset_manager() -> None:
    text = PRESET_MANAGER_PATH.read_text(encoding="utf-8")
    text = _ensure_import(
        text,
        anchor="from typing import Dict, List, Optional\n",
        import_line="\nfrom bot.config import config\nfrom bot.product import product\n",
        context="HappyFox preset manager",
    )

    old = """        with open(self.price_path, \"r\", encoding=\"utf-8\") as f:\n            self._price_config = json.load(f)\n        self._admin_ids = self._price_config.get(\"admin_ids\", [])\n"""
    new = """        with open(self.price_path, \"r\", encoding=\"utf-8\") as f:\n            self._price_config = json.load(f)\n\n        if product.product_id == \"happyfox\":\n            # Keep the proven numeric pricing/model table, but never expose or\n            # trust imported NEUROMIX/Tanya product-owned presentation/config.\n            self._price_config[\"credit_name\"] = product.credit_name\n            self._price_config[\"credit_name_plural\"] = product.credit_name_plural\n            self._price_config[\"credit_emoji\"] = product.credit_emoji\n            self._price_config[\"credit_value\"] = \"1 кредит = 10 ₽\"\n            self._price_config[\"support_contact\"] = product.support_contact\n            self._price_config[\"admin_ids\"] = list(config.admin_ids)\n\n            package_names = {\n                \"mini\": \"Мини\",\n                \"start\": \"Старт\",\n                \"optimal\": \"Оптимальный\",\n                \"pro\": \"Про\",\n                \"studio\": \"Студия\",\n                \"business\": \"Бизнес\",\n            }\n            for package in self._price_config.get(\"packages\", []):\n                package_id = str(package.get(\"id\") or \"\")\n                if package_id in package_names:\n                    package[\"name\"] = package_names[package_id]\n                # Imported Tanya offer IDs are product credentials. HappyFox\n                # resolves its Lava offers exclusively from environment config.\n                package.pop(\"lava_offer_id\", None)\n                package.pop(\"lava_currency\", None)\n\n        self._admin_ids = self._price_config.get(\"admin_ids\", [])\n"""
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("HappyFox price-config anchor was not found")

    PRESET_MANAGER_PATH.write_text(text, encoding="utf-8")


def _patch_payments() -> None:
    text = PAYMENTS_PATH.read_text(encoding="utf-8")
    text = _ensure_import(
        text,
        anchor="from bot.config import config\n",
        import_line="from bot.product import product\n",
        context="HappyFox payments",
    )

    old_offer = """def _package_lava_offer_config(package: dict) -> tuple[str, str]:\n    package_id = str(package.get(\"id\") or \"\")\n    offer_id = str(package.get(\"lava_offer_id\") or \"\").strip()\n    if offer_id:\n        currency = str(package.get(\"lava_currency\") or \"RUB\").strip().upper() or \"RUB\"\n        return offer_id, currency\n    return config.lava_offer_id_for_package(package_id), \"RUB\"\n"""
    new_offer = """def _package_lava_offer_config(package: dict) -> tuple[str, str]:\n    package_id = str(package.get(\"id\") or \"\")\n    if product.product_id == \"happyfox\":\n        # Product credentials must come from the HappyFox environment only.\n        return config.lava_offer_id_for_package(package_id), \"RUB\"\n\n    offer_id = str(package.get(\"lava_offer_id\") or \"\").strip()\n    if offer_id:\n        currency = str(package.get(\"lava_currency\") or \"RUB\").strip().upper() or \"RUB\"\n        return offer_id, currency\n    return config.lava_offer_id_for_package(package_id), \"RUB\"\n"""
    if old_offer in text:
        text = text.replace(old_offer, new_offer, 1)
    elif new_offer not in text:
        raise RuntimeError("HappyFox Lava offer anchor was not found")

    replacements = {
        "return f\"\\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов\"":
            "return f\"\\n🎁 Реферальный бонус: <code>{product.format_credits(referral_bonus['value'])}</code>\"",
        "f\"Покупка: <code>{credits}</code>🍌 на <code>{amount_rub}</code> ₽\\n\"":
            "f\"Покупка: <code>{product.format_credits(credits)}</code> на <code>{amount_rub}</code> ₽\\n\"",
        "f\"• {credits}🍌 → +<code>{bonus}</code>🍌\"":
            "f\"• {product.format_credits(credits)} → +<code>{product.format_credits(bonus)}</code>\"",
        "f\"\\n🎟 Промокод{code_part}: +<code>{promo_bonus['bonus_credits']}</code> бананов\"":
            "f\"\\n🎟 Промокод{code_part}: +<code>{product.format_credits(promo_bonus['bonus_credits'])}</code>\"",
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)

    PAYMENTS_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    _patch_common()
    _patch_preset_manager()
    _patch_payments()


if __name__ == "__main__":
    main()
