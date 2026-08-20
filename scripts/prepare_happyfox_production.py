# ruff: noqa: I001
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit


RUNTIME_ENV_NAME = ".env.happyfox.runtime"
DEFAULT_DATABASE_NAME = "happyfox"
DEFAULT_POSTGRES_CONTAINER = "foxgen-postgres-1"
DEFAULT_REDIS_CONTAINER = "foxgen-redis-1"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
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
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _dotenv_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def postgres_url_for_database(url: str, database: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("legacy database URL is not PostgreSQL")
    return urlunsplit(
        SplitResult(
            scheme="postgresql",
            netloc=parsed.netloc,
            path=f"/{database}",
            query=parsed.query,
            fragment="",
        )
    )


def redis_url_for_db(url: str, db_index: int) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("legacy Redis URL is invalid")
    return urlunsplit(
        SplitResult(
            scheme=parsed.scheme,
            netloc=parsed.netloc,
            path=f"/{db_index}",
            query=parsed.query,
            fragment="",
        )
    )


def mini_app_url_for_origin(origin: str) -> str:
    parsed = urlsplit(origin.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("HappyFox public origin must be HTTPS")
    return f"https://{parsed.netloc}/mini-app/"


def _run(
    args: list[str],
    *,
    input_file=None,
    output_file=None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        stdin=input_file,
        stdout=output_file or subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=output_file is None,
        check=check,
        env=env,
        timeout=180,
    )


def _container_exists(name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=15,
    )
    return result.returncode == 0


def backup_legacy_database(project_dir: Path, postgres_container: str) -> None:
    backup_dir = project_dir / "backups" / "pre-happyfox"
    backup_dir.mkdir(parents=True, exist_ok=True)
    latest = backup_dir / "legacy-foxgen-latest.dump"
    initial = backup_dir / "legacy-foxgen-initial.dump"
    tmp = backup_dir / ".legacy-foxgen.dump.tmp"

    with tmp.open("wb") as handle:
        result = subprocess.run(
            [
                "docker",
                "exec",
                postgres_container,
                "sh",
                "-lc",
                'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
            ],
            stdout=handle,
            stderr=subprocess.PIPE,
            check=False,
            timeout=300,
        )
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("failed to create legacy FoxGen database backup")

    tmp.replace(latest)
    if not initial.exists():
        shutil.copy2(latest, initial)
    print("legacy_database_backup=ready")


def ensure_happyfox_database(
    project_dir: Path,
    postgres_container: str,
    database_name: str,
) -> None:
    query = (
        "SELECT 1 FROM pg_database WHERE datname = "
        f"'{database_name.replace(chr(39), chr(39) * 2)}'"
    )
    result = _run(
        [
            "docker",
            "exec",
            postgres_container,
            "sh",
            "-lc",
            f'psql -U "$POSTGRES_USER" -d postgres -tAc "{query}"',
        ]
    )
    if result.stdout.strip() != "1":
        _run(
            [
                "docker",
                "exec",
                postgres_container,
                "sh",
                "-lc",
                f'exec createdb -U "$POSTGRES_USER" {database_name}',
            ]
        )
        print("happyfox_database=created")
    else:
        print("happyfox_database=present")

    schema_path = project_dir / "schema_postgres.sql"
    with schema_path.open("r", encoding="utf-8") as schema:
        _run(
            [
                "docker",
                "exec",
                "-i",
                postgres_container,
                "sh",
                "-lc",
                f'exec psql -U "$POSTGRES_USER" -d {database_name} -v ON_ERROR_STOP=1',
            ],
            input_file=schema,
        )
    print("happyfox_schema=ready")


def choose_redis_db(redis_container: str, legacy_url: str) -> int:
    parsed = urlsplit(legacy_url)
    docker_args = ["docker", "exec"]
    password = unquote(parsed.password or "")
    if password:
        docker_args.extend(["-e", f"REDISCLI_AUTH={password}"])
    redis_probe = (
        "for db in $(seq 1 15); do "
        "size=$(redis-cli -n \"$db\" --raw DBSIZE 2>/dev/null) || exit 2; "
        "if [ \"$size\" = 0 ]; then echo \"$db\"; exit 0; fi; "
        "done; exit 3"
    )
    docker_args.extend([redis_container, "sh", "-lc", redis_probe])
    result = _run(docker_args)
    value = result.stdout.strip()
    if not value.isdigit() or not 1 <= int(value) <= 15:
        raise RuntimeError("could not allocate an isolated Redis logical database")
    return int(value)


def build_runtime_values(
    legacy: dict[str, str],
    existing: dict[str, str],
    *,
    database_name: str,
    redis_db: int,
) -> dict[str, str]:
    def current_or_legacy(current: str, legacy_key: str) -> str:
        return existing.get(current, "").strip() or legacy.get(legacy_key, "").strip()

    webhook_host = current_or_legacy("WEBHOOK_HOST", "FOXGEN_KIE_CALLBACK_BASE_URL").rstrip("/")
    database_url = existing.get("DATABASE_URL", "").strip()
    if not database_url:
        database_url = postgres_url_for_database(
            legacy.get("FOXGEN_DATABASE_URL", ""), database_name
        )

    redis_url = existing.get("REDIS_URL", "").strip()
    if not redis_url:
        redis_url = redis_url_for_db(legacy.get("FOXGEN_REDIS_URL", ""), redis_db)

    mini_app_url = existing.get("MINI_APP_URL", "").strip()
    if not mini_app_url:
        legacy_miniapp = legacy.get("FOXGEN_MINIAPP_PUBLIC_URL", "").strip()
        mini_app_url = legacy_miniapp or mini_app_url_for_origin(webhook_host)

    values = {
        "PRODUCT_ID": "happyfox",
        "BOT_TOKEN": current_or_legacy("BOT_TOKEN", "FOXGEN_TELEGRAM_BOT_TOKEN"),
        "WEBHOOK_HOST": webhook_host,
        "MINI_APP_URL": mini_app_url,
        "STATIC_BASE_URL": existing.get("STATIC_BASE_URL", "").strip() or webhook_host,
        "DATABASE_URL": database_url,
        "REDIS_URL": redis_url,
        "REDIS_PREFIX": existing.get("REDIS_PREFIX", "").strip() or "foxgen_happyfox",
        "KIE_AI_API_KEY": current_or_legacy("KIE_AI_API_KEY", "FOXGEN_KIE_API_KEY"),
        "KIE_AI_WEBHOOK_SECRET": current_or_legacy(
            "KIE_AI_WEBHOOK_SECRET", "FOXGEN_KIE_WEBHOOK_HMAC_KEY"
        ),
        "KIE_WEBHOOK_HMAC_KEY": current_or_legacy(
            "KIE_WEBHOOK_HMAC_KEY", "FOXGEN_KIE_WEBHOOK_HMAC_KEY"
        ),
        "INTERNAL_API_SECRET": current_or_legacy(
            "INTERNAL_API_SECRET", "FOXGEN_INTERNAL_API_TOKEN"
        ),
        "PAYMENT_PROVIDER": existing.get("PAYMENT_PROVIDER", "").strip()
        or "telegram_stars",
        "WEBHOOK_BIND_HOST": "0.0.0.0",
        "WEBHOOK_PORT": "8080",
    }
    admin_ids = current_or_legacy("ADMIN_IDS", "FOXGEN_ADMIN_SUPERUSER_IDS")
    if admin_ids:
        values["ADMIN_IDS"] = admin_ids

    missing = [
        key
        for key in (
            "BOT_TOKEN",
            "WEBHOOK_HOST",
            "MINI_APP_URL",
            "DATABASE_URL",
            "REDIS_URL",
            "KIE_AI_API_KEY",
            "KIE_AI_WEBHOOK_SECRET",
            "INTERNAL_API_SECRET",
        )
        if not values.get(key, "").strip()
    ]
    if missing:
        raise RuntimeError("missing legacy sources for: " + ", ".join(missing))
    return values


def write_runtime_env(path: Path, values: dict[str, str]) -> None:
    lines = [
        "# Generated by scripts/prepare_happyfox_production.py",
        "# HappyFox-only runtime overlay. Legacy FOXGEN_* values stay in .env for rollback.",
    ]
    for key in sorted(values):
        lines.append(f"{key}={_dotenv_quote(values[key])}")
    content = "\n".join(lines) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    print("happyfox_runtime_env=ready")
    print("happyfox_runtime_keys=" + ",".join(sorted(values)))


def main() -> int:
    project_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    legacy_path = project_dir / ".env"
    runtime_path = project_dir / RUNTIME_ENV_NAME
    database_name = os.getenv("HAPPYFOX_DATABASE_NAME", DEFAULT_DATABASE_NAME)
    postgres_container = os.getenv(
        "HAPPYFOX_POSTGRES_CONTAINER", DEFAULT_POSTGRES_CONTAINER
    )
    redis_container = os.getenv("HAPPYFOX_REDIS_CONTAINER", DEFAULT_REDIS_CONTAINER)

    if (
        not database_name
        or database_name[0].isdigit()
        or not database_name.replace("_", "").isalnum()
    ):
        raise SystemExit("HAPPYFOX_DATABASE_NAME must be a simple SQL identifier")
    if not legacy_path.is_file():
        raise SystemExit("legacy production .env is missing")
    if not _container_exists(postgres_container):
        raise SystemExit(f"PostgreSQL container is missing: {postgres_container}")
    if not _container_exists(redis_container):
        raise SystemExit(f"Redis container is missing: {redis_container}")

    backup_dir = project_dir / "backups" / "pre-happyfox"
    backup_dir.mkdir(parents=True, exist_ok=True)
    initial_env = backup_dir / "legacy.env.initial"
    if not initial_env.exists():
        shutil.copy2(legacy_path, initial_env)
        os.chmod(initial_env, 0o600)
        print("legacy_env_backup=created")
    else:
        print("legacy_env_backup=present")

    legacy = parse_env(legacy_path)
    existing = parse_env(runtime_path)

    backup_legacy_database(project_dir, postgres_container)
    ensure_happyfox_database(project_dir, postgres_container, database_name)

    if existing.get("REDIS_URL", "").strip():
        redis_path = urlsplit(existing["REDIS_URL"]).path.lstrip("/")
        redis_db = int(redis_path or "0")
    else:
        redis_db = choose_redis_db(
            redis_container,
            legacy.get("FOXGEN_REDIS_URL", ""),
        )
    if redis_db == 0:
        raise SystemExit("HappyFox must not reuse legacy Redis DB 0")
    print(f"happyfox_redis_db={redis_db}")

    values = build_runtime_values(
        legacy,
        existing,
        database_name=database_name,
        redis_db=redis_db,
    )
    write_runtime_env(runtime_path, values)
    print("happyfox_production_bootstrap=ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
