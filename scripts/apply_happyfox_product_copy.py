"""Apply the small HappyFox product-copy delta to the proven tanyapi runtime.

This intentionally avoids rewriting the large production handler. The build fails
closed if the expected source anchor changes, so a future upstream change cannot
silently re-introduce another product's visible brand.
"""

from pathlib import Path

COMMON_PATH = Path("bot/handlers/common.py")
PRODUCT_IMPORT = "from bot.product import product\n"
PRODUCT_IMPORT_ANCHOR = "from bot.config import config\n"
OLD_MAIN_MENU_BRAND = '        "🏠 <b>NEUROMIX</b>\\n"\n'
NEW_MAIN_MENU_BRAND = (
    '        f"🏠 <b>{html.escape(product.brand_name)}</b>\\n"\n'
)


def main() -> None:
    text = COMMON_PATH.read_text(encoding="utf-8")

    if PRODUCT_IMPORT not in text:
        if PRODUCT_IMPORT_ANCHOR not in text:
            raise RuntimeError("HappyFox product import anchor was not found")
        text = text.replace(
            PRODUCT_IMPORT_ANCHOR,
            PRODUCT_IMPORT_ANCHOR + PRODUCT_IMPORT,
            1,
        )

    if OLD_MAIN_MENU_BRAND in text:
        text = text.replace(OLD_MAIN_MENU_BRAND, NEW_MAIN_MENU_BRAND, 1)
    elif NEW_MAIN_MENU_BRAND not in text:
        raise RuntimeError("HappyFox main-menu brand anchor was not found")

    if '🏠 <b>NEUROMIX</b>' in text:
        raise RuntimeError("Stale NEUROMIX main-menu brand remains")

    COMMON_PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
