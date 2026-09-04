from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit

from scripts.resolve_happyfox_miniapp_nginx_path import (
    _LISTEN_443_RE,
    _SERVER_NAME_RE,
    _SERVER_START_RE,
    _location_block,
    _named_block_ranges,
    _server_names,
    resolve_miniapp_path,
)

_PROXY_PASS_RE = re.compile(r"^\s*proxy_pass\s+(https?://[^;]+);", re.MULTILINE)


def resolve_miniapp_target(text: str, *, domain: str) -> tuple[str, str]:
    matched_servers: list[str] = []
    for start, end in _named_block_ranges(text, _SERVER_START_RE):
        block = text[start:end]
        if domain not in _server_names(block):
            continue
        if not _LISTEN_443_RE.search(block):
            continue
        if "/mini-app/" not in block:
            continue
        matched_servers.append(block)

    if len(matched_servers) != 1:
        raise ValueError(
            f"expected exactly one HTTPS server for {domain!r} with /mini-app/, "
            f"found {len(matched_servers)}"
        )

    location = _location_block(matched_servers[0])
    proxy_matches = _PROXY_PASS_RE.findall(location)
    if proxy_matches:
        if len(proxy_matches) != 1:
            raise ValueError("multiple proxy_pass directives found in /mini-app/ location")
        raw_url = proxy_matches[0].strip()
        if "$" in raw_url:
            raise ValueError("variable-based Mini App proxy targets are not supported")
        parsed = urlsplit(raw_url)
        host = parsed.hostname or ""
        if not host:
            raise ValueError("Mini App proxy_pass has no hostname")
        return "proxy", host

    return "filesystem", resolve_miniapp_path(text, domain=domain)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve whether /mini-app/ is served from nginx storage or a proxy container"
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("domain")
    args = parser.parse_args()

    text = args.config.read_text(encoding="utf-8")
    kind, value = resolve_miniapp_target(text, domain=args.domain)
    print(f"{kind}\t{value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
