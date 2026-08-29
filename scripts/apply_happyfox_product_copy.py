"""Apply the HappyFox product delta to the proven tanyapi runtime.

The migration deliberately keeps stable provider/database identifiers intact. This
script patches only product presentation and product-owned configuration hooks and
fails closed if an expected upstream anchor changes.
"""

from pathlib import Path

from apply_happyfox_main_menu import apply_happyfox_main_menu

COMMON_PATH = Path("bot/handlers/common.py")
KEYBOARDS_PATH = Path("bot/keyboards.py")
MAIN_PATH = Path("bot/main.py")
MINIAPP_PATH = Path("bot/miniapp.py")
PAYMENTS_PATH = Path("bot/handlers/payments.py")
PRESET_MANAGER_PATH = Path("bot/services/preset_manager.py")

PRODUCT_IMPORT = "from bot.product import product\n"
PRODUCT_IMPORT_ANCHOR = "from bot.config import config\n"
OLD_MAIN_MENU_BRAND = '        "🏠 <b>NEUROMIX</b>\\n"\n'
NEW_MAIN_MENU_BRAND = '        f"🏠 <b>{html.escape(product.brand_name)}</b>\\n"\n'
SUPPORT_CONTACT_EXPRESSION = (
    'f"{html.escape(product.support_contact) if product.support_contact else '
    "'через встроенную поддержку'}\""
)


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

    text = text.replace(
        '"😕 Извини, я временно недоступен. Попробуй ещё раз позже или напиши в поддержку @only_tany"',
        '"😕 Извини, я временно недоступен. Попробуй ещё раз позже или открой раздел поддержки."',
    )
    text = text.replace(
        '"😕 Что-то пошло не так. Попробуй ещё раз или обратись в поддержку @only_tany"',
        '"😕 Что-то пошло не так. Попробуй ещё раз или открой раздел поддержки."',
    )
    text = text.replace(
        '        "@only_tany"\n',
        f"        {SUPPORT_CONTACT_EXPRESSION}\n",
    )

    if '🏠 <b>NEUROMIX</b>' in text:
        raise RuntimeError("Stale NEUROMIX main-menu brand remains")
    if "@only_tany" in text:
        raise RuntimeError("Stale Tanya support contact remains in Telegram runtime")

    COMMON_PATH.write_text(text, encoding="utf-8")


def _patch_telegram_launch() -> None:
    keyboards = KEYBOARDS_PATH.read_text(encoding="utf-8")
    old_query_anchor = """    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if code:
"""
    new_query_anchor = """    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    release = str(os.getenv("HAPPYFOX_RELEASE", "")).strip()
    if release and release.lower() not in {"unknown", "local"}:
        # Telegram WebViews can retain an older document for the same launch URL.
        # Pin every production WebApp launch to the immutable image revision.
        query["release"] = release
    if code:
"""
    if old_query_anchor in keyboards:
        keyboards = keyboards.replace(old_query_anchor, new_query_anchor, 1)
    elif new_query_anchor not in keyboards:
        raise RuntimeError("HappyFox versioned WebApp URL anchor was not found")
    KEYBOARDS_PATH.write_text(keyboards, encoding="utf-8")

    main_text = MAIN_PATH.read_text(encoding="utf-8")
    old_import = """from bot.keyboards import (
    get_main_menu_button_keyboard,
    get_required_subscription_keyboard,
)
"""
    new_import = """from bot.keyboards import (
    _mini_app_url_with_start_param,
    get_main_menu_button_keyboard,
    get_required_subscription_keyboard,
)
"""
    if old_import in main_text:
        main_text = main_text.replace(old_import, new_import, 1)
    elif new_import not in main_text:
        raise RuntimeError("HappyFox main WebApp import anchor was not found")

    old_menu = """async def _set_commands_chat_menu_button() -> None:
    \"\"\"Keep Telegram's system menu button on quick commands.\"\"\"
    url = f\"https://api.telegram.org/bot{config.BOT_TOKEN}/setChatMenuButton\"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            url,
            json={\"menu_button\": {\"type\": \"commands\"}},
        ) as response:
            payload = await response.json(content_type=None)
    if not payload.get(\"ok\"):
        raise RuntimeError(payload.get(\"description\") or \"setChatMenuButton failed\")
"""
    new_menu = """async def _set_commands_chat_menu_button() -> None:
    \"\"\"Keep Telegram's system menu button on the current HappyFox WebApp.\"\"\"
    launch_url = _mini_app_url_with_start_param()
    if not launch_url:
        raise RuntimeError(\"HappyFox Mini App URL is unavailable\")
    url = f\"https://api.telegram.org/bot{config.BOT_TOKEN}/setChatMenuButton\"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            url,
            json={
                \"menu_button\": {
                    \"type\": \"web_app\",
                    \"text\": \"Открыть HappyFox\",
                    \"web_app\": {\"url\": launch_url},
                }
            },
        ) as response:
            payload = await response.json(content_type=None)
    if not payload.get(\"ok\"):
        raise RuntimeError(payload.get(\"description\") or \"setChatMenuButton failed\")
"""
    if old_menu in main_text:
        main_text = main_text.replace(old_menu, new_menu, 1)
    elif new_menu not in main_text:
        raise RuntimeError("HappyFox Telegram menu-button anchor was not found")

    main_text = main_text.replace(
        'logger.info("Configured Telegram chat menu button for bot commands")',
        'logger.info("Configured Telegram chat menu button for current HappyFox WebApp")',
        1,
    )
    if '"type": "commands"' in main_text:
        raise RuntimeError("Stale commands-only Telegram menu button remains")
    MAIN_PATH.write_text(main_text, encoding="utf-8")


def _patch_miniapp() -> None:
    text = MINIAPP_PATH.read_text(encoding="utf-8")
    text = _ensure_import(
        text,
        anchor=PRODUCT_IMPORT_ANCHOR,
        import_line=PRODUCT_IMPORT,
        context="HappyFox miniapp",
    )
    text = text.replace(
        '        "@only_tany"\n',
        f"        {SUPPORT_CONTACT_EXPRESSION}\n",
    )
    if "@only_tany" in text:
        raise RuntimeError("Stale Tanya support contact remains in Mini App backend")
    MINIAPP_PATH.write_text(text, encoding="utf-8")


def _patch_preset_manager() -> None:
    text = PRESET_MANAGER_PATH.read_text(encoding="utf-8")
    text = _ensure_import(
        text,
        anchor="from typing import Dict, List, Optional\n",
        import_line="\nfrom bot.config import config\nfrom bot.product import product\n",
        context="HappyFox preset manager",
    )

    old = """        with open(self.price_path, \"r\", encoding=\"utf-8\") as f:
            self._price_config = json.load(f)
        self._admin_ids = self._price_config.get(\"admin_ids\", [])
"""
    new = """        with open(self.price_path, \"r\", encoding=\"utf-8\") as f:
            self._price_config = json.load(f)

        if product.product_id == \"happyfox\":
            # Keep the proven numeric pricing/model table, but never expose or
            # trust imported source-product presentation/configuration.
            self._price_config[\"credit_name\"] = product.credit_name
            self._price_config[\"credit_name_plural\"] = product.credit_name_plural
            self._price_config[\"credit_emoji\"] = product.credit_emoji
            self._price_config[\"credit_value\"] = \"1 кредит = 10 ₽\"
            self._price_config[\"support_contact\"] = product.support_contact
            self._price_config[\"admin_ids\"] = list(config.admin_ids)

            package_names = {
                \"mini\": \"Мини\",
                \"start\": \"Старт\",
                \"optimal\": \"Оптимальный\",
                \"pro\": \"Про\",
                \"studio\": \"Студия\",
                \"business\": \"Бизнес\",
            }
            for package in self._price_config.get(\"packages\", []):
                package_id = str(package.get(\"id\") or \"\")
                if package_id in package_names:
                    package[\"name\"] = package_names[package_id]
                # Imported payment offer IDs are product credentials. HappyFox
                # resolves its Lava offers exclusively from environment config.
                package.pop(\"lava_offer_id\", None)
                package.pop(\"lava_currency\", None)

        self._admin_ids = self._price_config.get(\"admin_ids\", [])
"""
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

    old_offer = """def _package_lava_offer_config(package: dict) -> tuple[str, str]:
    package_id = str(package.get(\"id\") or \"\")
    offer_id = str(package.get(\"lava_offer_id\") or \"\").strip()
    if offer_id:
        currency = str(package.get(\"lava_currency\") or \"RUB\").strip().upper() or \"RUB\"
        return offer_id, currency
    return config.lava_offer_id_for_package(package_id), \"RUB\"
"""
    new_offer = """def _package_lava_offer_config(package: dict) -> tuple[str, str]:
    package_id = str(package.get(\"id\") or \"\")
    if product.product_id == \"happyfox\":
        # Product credentials must come from the HappyFox environment only.
        return config.lava_offer_id_for_package(package_id), \"RUB\"

    offer_id = str(package.get(\"lava_offer_id\") or \"\").strip()
    if offer_id:
        currency = str(package.get(\"lava_currency\") or \"RUB\").strip().upper() or \"RUB\"
        return offer_id, currency
    return config.lava_offer_id_for_package(package_id), \"RUB\"
"""
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
    _patch_telegram_launch()
    _patch_miniapp()
    _patch_preset_manager()
    _patch_payments()
    apply_happyfox_main_menu()


if __name__ == "__main__":
    main()
