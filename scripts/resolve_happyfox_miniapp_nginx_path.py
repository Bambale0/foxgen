from __future__ import annotations

import argparse
import re
from pathlib import Path

_SERVER_START_RE = re.compile(r"^\s*server\s*\{")
_SERVER_NAME_RE = re.compile(r"^\s*server_name\s+([^;]+);", re.MULTILINE)
_LISTEN_443_RE = re.compile(r"^\s*listen\s+[^;]*\b443\b[^;]*;", re.MULTILINE)
_MINIAPP_LOCATION_RE = re.compile(
    r"^\s*location\s+(?:(?:=|\^~|~\*?)\s+)?/mini-app/\s*\{",
    re.MULTILINE,
)
_ALIAS_RE = re.compile(r"^\s*alias\s+([^;]+);", re.MULTILINE)
_ROOT_RE = re.compile(r"^\s*root\s+([^;]+);", re.MULTILINE)
_PROXY_PASS_RE = re.compile(r"\bproxy_pass\s+http://([^/;\s]+)")
_CONTAINER_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")


def _code_without_comment(line: str) -> str:
    return line.split("#", 1)[0]


def _named_block_ranges(text: str, start_pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    ranges: list[tuple[int, int]] = []
    offset = 0
    start_offset: int | None = None
    depth = 0

    for line in lines:
        code = _code_without_comment(line)
        if start_offset is None and start_pattern.match(code):
            start_offset = offset
            depth = code.count("{") - code.count("}")
            if depth == 0:
                ranges.append((start_offset, offset + len(line)))
                start_offset = None
        elif start_offset is not None:
            depth += code.count("{") - code.count("}")
            if depth == 0:
                ranges.append((start_offset, offset + len(line)))
                start_offset = None
        offset += len(line)

    if start_offset is not None:
        raise ValueError("nginx config contains an unterminated block")
    return ranges


def _server_names(block: str) -> set[str]:
    names: set[str] = set()
    for match in _SERVER_NAME_RE.finditer(block):
        names.update(match.group(1).split())
    return names


def _location_block(server_block: str) -> str:
    matches = _named_block_ranges(server_block, _MINIAPP_LOCATION_RE)
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one /mini-app/ location in HappyFox HTTPS server "
            f"block, found {len(matches)}"
        )
    start, end = matches[0]
    return server_block[start:end]


def _happyfox_server_block(text: str, *, domain: str) -> str:
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
    return matched_servers[0]


def resolve_miniapp_path(text: str, *, domain: str) -> str:
    server_block = _happyfox_server_block(text, domain=domain)
    location = _location_block(server_block)

    alias_matches = _ALIAS_RE.findall(location)
    if len(alias_matches) == 1:
        path = alias_matches[0].strip()
    elif alias_matches:
        raise ValueError("multiple alias directives found in /mini-app/ location")
    else:
        root_matches = _ROOT_RE.findall(location)
        if not root_matches:
            # Nginx inherits a server-level root when the location has none.
            before_location = server_block[: server_block.find(location)]
            root_matches = _ROOT_RE.findall(before_location)
        if len(root_matches) != 1:
            raise ValueError(
                "could not resolve exactly one alias/root for /mini-app/ location"
            )
        path = str(Path(root_matches[0].strip()) / "mini-app")

    if "$" in path:
        raise ValueError("variable-based Mini App filesystem paths are not supported")
    resolved = Path(path)
    if not resolved.is_absolute():
        raise ValueError("Mini App filesystem path must be absolute")
    return str(resolved)


def resolve_miniapp_proxy_container(text: str, *, domain: str) -> str:
    """Return the direct Docker-style host used by a proxied /mini-app/ route.

    Production can serve the Mini App through a dedicated static nginx sidecar
    instead of a filesystem alias in the public reverse proxy. This resolver is
    deliberately strict: it accepts one direct http://host[:port] proxy target
    and rejects variables, credentials and ambiguous proxy_pass directives.
    """

    server_block = _happyfox_server_block(text, domain=domain)
    location = _location_block(server_block)
    matches = _PROXY_PASS_RE.findall(location)
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one direct proxy_pass in /mini-app/ location, "
            f"found {len(matches)}"
        )

    authority = matches[0].strip()
    if "$" in authority or "@" in authority:
        raise ValueError("dynamic or credentialed Mini App proxy targets are not supported")

    host = authority
    if ":" in authority:
        host, port = authority.rsplit(":", 1)
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("Mini App proxy target has an invalid port")

    if not _CONTAINER_NAME_RE.fullmatch(host):
        raise ValueError("Mini App proxy target is not a safe container/service name")
    return host


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve the effective nginx target serving /mini-app/"
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("domain")
    parser.add_argument(
        "--proxy-container",
        action="store_true",
        help="resolve a direct proxy_pass host instead of a filesystem path",
    )
    args = parser.parse_args()

    text = args.config.read_text(encoding="utf-8")
    if args.proxy_container:
        print(resolve_miniapp_proxy_container(text, domain=args.domain))
    else:
        print(resolve_miniapp_path(text, domain=args.domain))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
