from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

BLOCKED_MARKERS = (
    "tanyapi.chillcreative.ru",
    "cdn.chillcreative.ru",
    "media.chillcreative.ru",
    "tanyapp.",
    "neuromix",
    "only_tany",
)

REQUIRED = (
    "BOT_TOKEN",
    "WEBHOOK_HOST",
    "MINI_APP_URL",
    "DATABASE_URL",
    "REDIS_URL",
    "REDIS_PREFIX",
    "KIE_AI_API_KEY",
    "KIE_AI_WEBHOOK_SECRET",
    "INTERNAL_API_SECRET",
    "ADMIN_IDS",
)

LAVA_OFFER_KEYS = (
    "LAVA_OFFER_ID_MINI",
    "LAVA_OFFER_ID_START",
    "LAVA_OFFER_ID_OPTIMAL",
    "LAVA_OFFER_ID_PRO",
    "LAVA_OFFER_ID_STUDIO",
    "LAVA_OFFER_ID_BUSINESS",
)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_values(paths: list[Path]) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        values.update(_parse_env_file(path))
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []

    product_id = values.get("PRODUCT_ID", "happyfox").strip().lower()
    if product_id != "happyfox":
        errors.append(f"PRODUCT_ID must be happyfox, got {product_id!r}")

    for key in REQUIRED:
        if not values.get(key, "").strip():
            errors.append(f"{key} is required")

    database_url = values.get("DATABASE_URL", "").strip().lower()
    if database_url and not database_url.startswith(("postgresql://", "postgres://", "postgresql+asyncpg://")):
        errors.append("DATABASE_URL must point to PostgreSQL in production")

    redis_prefix = values.get("REDIS_PREFIX", "").strip().lower()
    if redis_prefix and not ("happyfox" in redis_prefix or "foxgen" in redis_prefix):
        errors.append("REDIS_PREFIX must be HappyFox/FoxGen-specific")

    for key in (
        "WEBHOOK_HOST",
        "MINI_APP_URL",
        "STATIC_BASE_URL",
        "DATABASE_URL",
        "REDIS_URL",
        "SUPPORT_CONTACT",
    ):
        value = values.get(key, "").strip().lower()
        if not value:
            continue
        marker = next((item for item in BLOCKED_MARKERS if item in value), None)
        if marker:
            errors.append(f"{key} contains blocked NEUROMIX/Tanya marker {marker!r}")

    webhook_host = values.get("WEBHOOK_HOST", "").strip()
    mini_app_url = values.get("MINI_APP_URL", "").strip()
    if webhook_host and not webhook_host.startswith("https://"):
        errors.append("WEBHOOK_HOST must use https://")
    if mini_app_url and not mini_app_url.startswith("https://"):
        errors.append("MINI_APP_URL must use https://")

    admin_ids = values.get("ADMIN_IDS", "").strip()
    if admin_ids and not re.fullmatch(r"\d+(?:\s*,\s*\d+)*", admin_ids):
        errors.append("ADMIN_IDS must be a comma-separated list of Telegram numeric IDs")

    payment_provider = values.get("PAYMENT_PROVIDER", "lava").strip().lower()
    payment_requirements: dict[str, tuple[str, ...]] = {
        "lava": ("LAVA_API_KEY", "LAVA_WEBHOOK_SECRET", *LAVA_OFFER_KEYS),
        "tbank": ("TBANK_TERMINAL_KEY", "TBANK_SECRET_KEY"),
        "cryptobot": ("CRYPTOBOT_API_TOKEN",),
        "freekassa": (
            "FREEKASSA_MERCHANT_ID",
            "FREEKASSA_SECRET_WORD",
            "FREEKASSA_SECRET_WORD_2",
        ),
        "telegram_stars": (),
    }
    if payment_provider not in payment_requirements:
        errors.append(f"Unsupported PAYMENT_PROVIDER={payment_provider!r}")
    else:
        for key in payment_requirements[payment_provider]:
            if not values.get(key, "").strip():
                errors.append(f"{key} is required for PAYMENT_PROVIDER={payment_provider}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate isolated HappyFox production environment")
    parser.add_argument(
        "env_files",
        nargs="*",
        type=Path,
        default=[Path(".env"), Path(".env.postgres")],
    )
    args = parser.parse_args()

    values = load_values(args.env_files)
    errors = validate(values)
    if errors:
        print("HappyFox production environment validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("HappyFox production environment: isolated and valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
