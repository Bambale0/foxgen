from bot.product import product


SUPPORT_USERNAME = product.support_contact
SUPPORT_URL = (
    f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"
    if SUPPORT_USERNAME.startswith("@")
    else ""
)
