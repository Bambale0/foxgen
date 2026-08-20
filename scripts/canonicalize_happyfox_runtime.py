from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


def _parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def canonicalize(path: Path) -> str:
    values = _parse(path)
    webhook_host = values.get("WEBHOOK_HOST", "").strip().rstrip("/")
    parsed = urlsplit(webhook_host)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("WEBHOOK_HOST must be a public HTTPS origin")

    canonical_url = f"https://{parsed.netloc}/mini-app/"
    values["MINI_APP_URL"] = canonical_url

    lines = [
        "# Generated HappyFox production runtime overlay.",
        "# MINI_APP_URL is pinned to WEBHOOK_HOST so legacy frontend domains cannot survive cutover.",
    ]
    for key in sorted(values):
        lines.append(f"{key}={_quote(values[key])}")
    content = "\n".join(lines) + "\n"

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return canonical_url


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env.happyfox.runtime")
    url = canonicalize(path)
    print(f"happyfox_miniapp_url={url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
