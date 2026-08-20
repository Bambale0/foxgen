from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKIP_PROJECT_ENV_VAR = "BANANO_SKIP_PROJECT_ENV"
SOURCE_PRODUCT_MARKERS = (
    "tanyapi.chillcreative.ru",
    "cdn.chillcreative.ru",
    "media.chillcreative.ru",
    "tanyapp",
    "neuromix",
    "only_tany",
)


def _happyfox_miniapp_url_from_webhook() -> str:
    webhook_host = os.getenv("WEBHOOK_HOST", "").strip().rstrip("/")
    if not webhook_host:
        return ""
    parsed = urlsplit(webhook_host)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{webhook_host}/mini-app/"


def _apply_runtime_defaults() -> None:
    """Keep the public Mini App on the active HappyFox origin.

    A historic tanyapi snapshot pinned MINI_APP_URL to the Tanya/NEUROMIX
    frontend on every process start. That silently overrode Docker/environment
    configuration, including the isolated HappyFox production overlay. Preserve
    an explicitly configured HappyFox URL, repair known source-product residue
    from WEBHOOK_HOST, and otherwise let Config.mini_app_url derive its normal
    fallback.
    """

    current = os.getenv("MINI_APP_URL", "").strip()
    lowered = current.lower()
    is_source_product = bool(
        current and any(marker in lowered for marker in SOURCE_PRODUCT_MARKERS)
    )

    if current and not is_source_product:
        return

    derived = _happyfox_miniapp_url_from_webhook()
    if derived:
        os.environ["MINI_APP_URL"] = derived
    elif is_source_product:
        os.environ.pop("MINI_APP_URL", None)


def load_project_env(project_root: Path | None = None) -> None:
    """Load project env files without overriding the active HappyFox runtime.

    Real process environment variables keep highest priority. Postgres-specific
    values may fill keys that were not already supplied. The Mini App URL is
    never forcibly rewritten to a source-product domain.
    """

    if os.getenv(SKIP_PROJECT_ENV_VAR, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        _apply_runtime_defaults()
        return

    root = project_root or PROJECT_ROOT
    original_keys = set(os.environ)

    load_dotenv(root / ".env")

    for key, value in dotenv_values(root / ".env.postgres").items():
        if value is None or key in original_keys:
            continue
        os.environ[key] = value

    _apply_runtime_defaults()
