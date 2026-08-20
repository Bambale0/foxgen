"""Print a secret-safe production topology report for HappyFox cutover.

The report intentionally emits only environment key *names*, URL host metadata,
and Docker container/network metadata. It never prints token/password values or
full connection URLs.
"""

import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


LEGACY_KEYS = (
    "FOXGEN_TELEGRAM_BOT_TOKEN",
    "FOXGEN_MINIAPP_PUBLIC_URL",
    "FOXGEN_DATABASE_URL",
    "FOXGEN_REDIS_URL",
    "FOXGEN_KIE_API_KEY",
    "FOXGEN_KIE_CALLBACK_BASE_URL",
    "FOXGEN_KIE_WEBHOOK_HMAC_KEY",
    "FOXGEN_INTERNAL_API_TOKEN",
    "FOXGEN_ADMIN_SUPERUSER_IDS",
    "FOXGEN_S3_ENDPOINT_URL",
    "FOXGEN_S3_BUCKET",
    "FOXGEN_S3_ACCESS_KEY_ID",
    "FOXGEN_S3_SECRET_ACCESS_KEY",
)

CURRENT_KEYS = (
    "PRODUCT_ID",
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
    "PAYMENT_PROVIDER",
)

PAYMENT_PREFIXES = (
    "LAVA_",
    "CRYPTOBOT_",
    "TBANK_",
    "FREEKASSA_",
    "TELEGRAM_STARS_",
)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
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


def present(values: dict[str, str], keys: tuple[str, ...]) -> str:
    return ",".join(key for key in keys if values.get(key, "").strip()) or "none"


def report_url(values: dict[str, str], label: str, candidates: tuple[str, ...]) -> None:
    for key in candidates:
        raw = values.get(key, "").strip()
        if not raw:
            continue
        parsed = urlparse(raw)
        host = parsed.hostname or "none"
        port = parsed.port or "default"
        scheme = parsed.scheme or "none"
        path = parsed.path.lstrip("/") or "none"
        # URL usernames/passwords and query/fragment are deliberately omitted.
        print(
            f"{label}: source={key} scheme={scheme} host={host} "
            f"port={port} path={path}"
        )
        return
    print(f"{label}: none")


def run_metadata(command: list[str], label: str) -> None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"{label}: unavailable ({type(exc).__name__})")
        return

    print(f"{label}: exit={result.returncode}")
    output = result.stdout.strip()
    if output:
        print(output)


def main() -> int:
    env_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    if not env_path.is_file():
        print(f"env_file: missing ({env_path})")
        return 2

    values = parse_env(env_path)
    print("happyfox_production_topology_report=v1")
    print(f"legacy_env_nonempty_keys={present(values, LEGACY_KEYS)}")
    print(f"current_env_nonempty_keys={present(values, CURRENT_KEYS)}")

    payment_keys = sorted(
        key
        for key, value in values.items()
        if value.strip()
        and (key == "PAYMENT_PROVIDER" or key.startswith(PAYMENT_PREFIXES))
    )
    print("payment_env_nonempty_keys=" + (",".join(payment_keys) or "none"))

    report_url(values, "database_endpoint", ("DATABASE_URL", "FOXGEN_DATABASE_URL"))
    report_url(values, "redis_endpoint", ("REDIS_URL", "FOXGEN_REDIS_URL"))
    report_url(
        values,
        "miniapp_endpoint",
        ("MINI_APP_URL", "FOXGEN_MINIAPP_PUBLIC_URL"),
    )
    report_url(
        values,
        "webhook_endpoint",
        ("WEBHOOK_HOST", "FOXGEN_KIE_CALLBACK_BASE_URL"),
    )

    run_metadata(
        [
            "docker",
            "ps",
            "--format",
            "{{.Names}}|{{.Image}}|{{.Networks}}|{{.Ports}}",
        ],
        "docker_containers",
    )
    run_metadata(
        ["docker", "network", "ls", "--format", "{{.Name}}|{{.Driver}}|{{.Scope}}"],
        "docker_networks",
    )
    run_metadata(
        ["docker", "compose", "ls", "--format", "json"],
        "docker_compose_projects",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
