from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from pathlib import Path

_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_UPSTREAM_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+(?::[0-9]{1,5})?$")
_SERVER_START_RE = re.compile(r"^\s*server\s*\{")
_SERVER_NAME_RE = re.compile(r"^\s*server_name\s+([^;]+);", re.MULTILINE)
_LISTEN_443_RE = re.compile(r"^\s*listen\s+[^;]*\b443\b[^;]*;", re.MULTILINE)
_HEALTH_RE = re.compile(r"^\s*location\s*=\s*/health\s*\{", re.MULTILINE)
_MAX_WEBHOOK_RE = re.compile(
    r"^\s*location\s*=\s*/max/webhook\s*\{", re.MULTILINE
)
_INSTAGRAM_WEBHOOK_RE = re.compile(
    r"^\s*location\s*=\s*/instagram/webhook\s*\{", re.MULTILINE
)
_INSERT_BEFORE_RE = re.compile(
    r"^\s*location\s+\^~\s+/mini-app/api/\s*\{", re.MULTILINE
)
_CATCH_ALL_RE = re.compile(r"^\s*location\s+/\s*\{", re.MULTILINE)


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


def _server_ranges(text: str) -> list[tuple[int, int]]:
    return _named_block_ranges(text, _SERVER_START_RE)


def _upstream_range(text: str, upstream: str) -> tuple[int, int]:
    start_pattern = re.compile(rf"^\s*upstream\s+{re.escape(upstream)}\s*\{{")
    ranges = _named_block_ranges(text, start_pattern)
    if len(ranges) != 1:
        raise ValueError(
            f"expected exactly one nginx upstream {upstream!r}, found {len(ranges)}"
        )
    return ranges[0]


def _server_names(block: str) -> set[str]:
    names: set[str] = set()
    for match in _SERVER_NAME_RE.finditer(block):
        names.update(match.group(1).split())
    return names


def _validate_target(target: str) -> None:
    if not _TARGET_RE.fullmatch(target):
        raise ValueError(f"invalid nginx upstream target: {target!r}")
    if ":" in target:
        port = int(target.rsplit(":", 1)[1])
        if not 1 <= port <= 65535:
            raise ValueError(f"invalid nginx upstream port: {port}")


def _switch_upstream_target(text: str, *, upstream: str, target: str) -> tuple[str, bool]:
    _validate_target(target)
    start, end = _upstream_range(text, upstream)
    block = text[start:end]
    server_re = re.compile(r"^(\s*server\s+)([^;\s]+)([^;]*;.*)$", re.MULTILINE)
    matches = list(server_re.finditer(block))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one server directive in upstream {upstream!r}, "
            f"found {len(matches)}"
        )
    match = matches[0]
    if match.group(2) == target:
        return text, False

    replacement = f"{match.group(1)}{target}{match.group(3)}"
    block = block[: match.start()] + replacement + block[match.end() :]
    return text[:start] + block + text[end:], True


def _health_location(upstream: str) -> str:
    return (
        "    location = /health {\n"
        f"        proxy_pass http://{upstream};\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Connection \"\";\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "        proxy_set_header X-Forwarded-Host $host;\n"
        "        proxy_connect_timeout 5s;\n"
        "        proxy_read_timeout 30s;\n"
        "    }\n\n"
    )


def _max_webhook_location(upstream: str) -> str:
    return (
        "    location = /max/webhook {\n"
        f"        proxy_pass http://{upstream};\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Connection \"\";\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "        proxy_set_header X-Forwarded-Host $host;\n"
        "        proxy_set_header X-Max-Bot-Api-Secret $http_x_max_bot_api_secret;\n"
        "        proxy_request_buffering off;\n"
        "        proxy_connect_timeout 5s;\n"
        "        proxy_send_timeout 30s;\n"
        "        proxy_read_timeout 30s;\n"
        "        client_max_body_size 1m;\n"
        "        limit_except POST {\n"
        "            deny all;\n"
        "        }\n"
        "    }\n\n"
    )


def _instagram_webhook_location(upstream: str) -> str:
    return (
        "    location = /instagram/webhook {\n"
        f"        proxy_pass http://{upstream};\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Connection \"\";\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "        proxy_set_header X-Forwarded-Host $host;\n"
        "        proxy_set_header X-Hub-Signature-256 $http_x_hub_signature_256;\n"
        "        proxy_request_buffering off;\n"
        "        proxy_connect_timeout 5s;\n"
        "        proxy_send_timeout 30s;\n"
        "        proxy_read_timeout 30s;\n"
        "        client_max_body_size 1m;\n"
        "        limit_except GET POST {\n"
        "            deny all;\n"
        "        }\n"
        "    }\n\n"
    )


def patch_text(
    text: str,
    *,
    domain: str,
    upstream: str = "happyfox_backend",
    target: str | None = None,
) -> tuple[str, bool]:
    if not _DOMAIN_RE.fullmatch(domain):
        raise ValueError(f"invalid public domain: {domain!r}")
    if not _UPSTREAM_RE.fullmatch(upstream):
        raise ValueError(f"invalid nginx upstream name: {upstream!r}")

    changed = False
    if target is not None:
        text, target_changed = _switch_upstream_target(
            text, upstream=upstream, target=target
        )
        changed = changed or target_changed

    server_target: tuple[int, int] | None = None
    health_present = False
    max_webhook_present = False
    instagram_webhook_present = False

    for start, end in _server_ranges(text):
        block = text[start:end]
        if domain not in _server_names(block):
            continue
        if not _LISTEN_443_RE.search(block):
            continue
        if f"http://{upstream}" not in block:
            continue
        if server_target is not None:
            raise ValueError(f"multiple HTTPS server blocks matched {domain!r}")
        server_target = (start, end)
        health_present = bool(_HEALTH_RE.search(block))
        max_webhook_present = bool(_MAX_WEBHOOK_RE.search(block))
        instagram_webhook_present = bool(_INSTAGRAM_WEBHOOK_RE.search(block))

    if server_target is None:
        raise ValueError(
            f"could not find HTTPS server block for {domain!r} using upstream {upstream!r}"
        )
    if health_present and max_webhook_present and instagram_webhook_present:
        return text, changed

    start, end = server_target
    block = text[start:end]
    insert_match = _INSERT_BEFORE_RE.search(block) or _CATCH_ALL_RE.search(block)
    if insert_match is None:
        raise ValueError(f"could not find a safe insertion point in server block for {domain!r}")

    additions = ""
    if not health_present:
        additions += _health_location(upstream)
    if not max_webhook_present:
        additions += _max_webhook_location(upstream)
    if not instagram_webhook_present:
        additions += _instagram_webhook_location(upstream)

    absolute = start + insert_match.start()
    patched = text[:absolute] + additions + text[absolute:]
    return patched, True


def patch_file(
    path: Path,
    *,
    domain: str,
    upstream: str = "happyfox_backend",
    target: str | None = None,
) -> bool:
    original = path.read_text(encoding="utf-8")
    patched, changed = patch_text(
        original,
        domain=domain,
        upstream=upstream,
        target=target,
    )
    if not changed:
        return False

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.happyfox-",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(patched)
        handle.flush()

    try:
        # Truncate the existing bind-mount source in place. Replacing the host
        # inode would leave a running container attached to the old file.
        shutil.copyfile(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch HappyFox nginx upstream, health and channel webhook routes"
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("domain")
    parser.add_argument("--upstream", default="happyfox_backend")
    parser.add_argument("--target")
    args = parser.parse_args()

    changed = patch_file(
        args.config,
        domain=args.domain,
        upstream=args.upstream,
        target=args.target,
    )
    print("patched" if changed else "already-present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
