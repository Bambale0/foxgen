from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit


CHANNEL_SEED_NAME = ".env.happyfox.channels"
RUNTIME_ENV_NAME = ".env.happyfox.runtime"
MAX_DEFAULT_API_BASE = "https://platform-api2.max.ru"
MAX_DEFAULT_WEBHOOK_PATH = "/max/webhook"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_CHANNEL_KEYS = (
    "SUPPORT_CONTACT",
    "INSTAGRAM_ENABLED",
    "INSTAGRAM_APP_ID",
    "INSTAGRAM_APP_SECRET",
    "INSTAGRAM_VERIFY_TOKEN",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_IG_USER_ID",
    "INSTAGRAM_API_VERSION",
    "INSTAGRAM_WEBHOOK_PATH",
    "INSTAGRAM_REQUEST_TIMEOUT_SECONDS",
    "INSTAGRAM_IDEMPOTENCY_TTL_SECONDS",
    "INSTAGRAM_SUBSCRIBED_FIELDS",
    "MAX_ENABLED",
    "MAX_ACCESS_TOKEN",
    "MAX_WEBHOOK_SECRET",
    "MAX_WEBHOOK_URL",
    "MAX_WEBHOOK_PATH",
    "MAX_API_BASE",
    "MAX_BOT_NAME",
    "MAX_MINI_APP_URL",
    "MAX_PAYMENT_RETURN_URL",
    "MAX_PAYMENT_RECONCILE_SECONDS",
)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _write_env(path: Path, values: dict[str, str], *, header: str) -> None:
    lines = [header]
    for key in sorted(values):
        if values[key].strip():
            lines.append(f"{key}={_quote(values[key])}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _looks_like_env_backup(path: Path) -> bool:
    name = path.name.lower()
    if name in {".env", RUNTIME_ENV_NAME, CHANNEL_SEED_NAME}:
        return False
    return (
        ".env" in name
        or name.endswith(".env")
        or "runtime" in name and "env" in name
    )


def _backup_candidates(project_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    backup_root = project_dir / "backups"
    if backup_root.is_dir():
        for path in backup_root.rglob("*"):
            try:
                if (
                    path.is_file()
                    and _looks_like_env_backup(path)
                    and path.stat().st_size <= 2 * 1024 * 1024
                ):
                    candidates.append(path)
            except OSError:
                continue

    for pattern in (".env*.bak*", ".env*.backup*", ".env*.old*", ".env*~"):
        for path in project_dir.glob(pattern):
            try:
                if path.is_file() and path.stat().st_size <= 2 * 1024 * 1024:
                    candidates.append(path)
            except OSError:
                continue

    return sorted(set(candidates), key=lambda item: str(item))


def _public_origin_defaults(values: dict[str, str]) -> None:
    origin = os.getenv("HAPPYFOX_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if not origin:
        return
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname:
        return
    canonical = f"https://{parsed.netloc}"
    path = values.get("MAX_WEBHOOK_PATH", "").strip() or MAX_DEFAULT_WEBHOOK_PATH
    values["MAX_WEBHOOK_PATH"] = path
    values["MAX_WEBHOOK_URL"] = f"{canonical}{path}"
    values.setdefault("MAX_MINI_APP_URL", f"{canonical}/mini-app/")
    values.setdefault("MAX_PAYMENT_RETURN_URL", f"{canonical}/mini-app/")


def recover(project_dir: Path) -> dict[str, str]:
    seed_path = project_dir / CHANNEL_SEED_NAME
    runtime_path = project_dir / RUNTIME_ENV_NAME
    base_env_path = project_dir / ".env"

    recovered: dict[str, str] = {}
    source_by_key: dict[str, str] = {}

    sources = [seed_path, runtime_path, base_env_path, *_backup_candidates(project_dir)]
    seen: set[Path] = set()
    for source in sources:
        try:
            resolved = source.resolve()
        except OSError:
            continue
        if resolved in seen or not source.is_file():
            continue
        seen.add(resolved)
        values = parse_env(source)
        for key in _CHANNEL_KEYS:
            if recovered.get(key, "").strip() or not values.get(key, "").strip():
                continue
            recovered[key] = values[key].strip()
            try:
                source_name = str(source.relative_to(project_dir))
            except ValueError:
                source_name = source.name
            source_by_key[key] = source_name

    access_token = recovered.get("MAX_ACCESS_TOKEN", "").strip()
    if access_token:
        # This recovery command is invoked only for the HappyFox production
        # contour. A recovered MAX token means the operator intended this
        # channel to be live; fail closed later if the token is stale/revoked.
        recovered["MAX_ENABLED"] = "1"
        recovered.setdefault("MAX_API_BASE", MAX_DEFAULT_API_BASE)
        recovered.setdefault("MAX_WEBHOOK_PATH", MAX_DEFAULT_WEBHOOK_PATH)
        if not recovered.get("MAX_WEBHOOK_SECRET", "").strip():
            recovered["MAX_WEBHOOK_SECRET"] = secrets.token_urlsafe(32)
            source_by_key["MAX_WEBHOOK_SECRET"] = "generated-on-server"
        _public_origin_defaults(recovered)

    channel_values = {
        key: recovered[key]
        for key in _CHANNEL_KEYS
        if recovered.get(key, "").strip()
    }
    if channel_values:
        _write_env(
            seed_path,
            channel_values,
            header="# Protected HappyFox channel runtime. Never commit this file.",
        )

        runtime = parse_env(runtime_path)
        runtime.update(channel_values)
        _write_env(
            runtime_path,
            runtime,
            header="# HappyFox runtime with recovered protected channel values.",
        )

    source_summary = ",".join(
        f"{key}:{source_by_key.get(key, 'derived')}"
        for key in sorted(channel_values)
    ) or "none"
    print(f"channel_runtime_recovery_sources={source_summary}")
    print("max_access_token_recovered=" + ("yes" if access_token else "no"))
    if access_token:
        secret = recovered.get("MAX_WEBHOOK_SECRET", "")
        print("max_webhook_secret_ready=" + ("yes" if secret else "no"))
        enabled = recovered.get("MAX_ENABLED", "").strip().lower() in _TRUE_VALUES
        print("max_runtime_recovery_ready=" + ("yes" if enabled and secret else "no"))
    return channel_values


def main() -> int:
    project_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not (project_dir / ".env").is_file():
        raise SystemExit("HappyFox production .env is missing")
    recover(project_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
