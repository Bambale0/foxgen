# ruff: noqa: I001
import os


SUPPORT_USERNAME = os.getenv("SUPPORT_CONTACT", "").strip()
SUPPORT_URL = (
    f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"
    if SUPPORT_USERNAME.startswith("@")
    else ""
)
