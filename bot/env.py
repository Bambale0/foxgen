from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKIP_PROJECT_ENV_VAR = "BANANO_SKIP_PROJECT_ENV"
DEFAULT_MINI_APP_URL = "https://tanyapp.xn--e1aikcel5c5a.online/mini-app/"


def _apply_runtime_defaults() -> None:
    """Force Telegram WebApp buttons to the deployed public frontend."""

    # This repository/branch has one production Mini App frontend. Do not trust
    # stale MINI_APP_URL values from systemd, Docker Compose or old .env files:
    # they previously pointed users to the backend HTML fallback.
    os.environ["MINI_APP_URL"] = DEFAULT_MINI_APP_URL


def load_project_env(project_root: Path | None = None) -> None:
    """Load project env files with Postgres overriding local SQLite defaults.

    Real process environment variables keep highest priority, except for the
    public Mini App URL which is pinned to the production frontend host above.
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
