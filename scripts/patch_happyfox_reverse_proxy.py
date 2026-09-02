from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from pathlib import Path

_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_SERVER_START_RE = re.compile(r"^\s*server\s*\{")
_SERVER_NAME_RE = re.compile(r"^\s*server_name\s+([^;]+);", re.MULTILINE)
_LISTEN_443_RE = re.compile(r"^\s*listen\s+[^;]*\b443\b[^;]*;", re.MULTILINE)
_HEALTH_RE = re.compile(r"^\s*location\s*=\s*/health\s*\{", re.MULTILINE)
_INSERT_BEFORE_RE = re.compile(r"^\s*location\s+\^~\s+/mini-app/api/\s*\{", re.MULTILINE)
_CATCH_ALL_RE = re.compile(r"^\s*location\s+/\s*\{", re.MULTILINE)


def _code_without_comment(line: str) -> str:
    return line.split("#", 1)[0]


def _server_ranges(text: str) -> list[tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    ranges: list[tuple[int, int]] = []
    offset = 0
    start_offset: int | None = None
    depth = 0

    for line in lines:
        code = _code_without_comment(line)
        if start_offset is None and _SERVER_START_RE.match(code):
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
        raise ValueError("nginx config contains an unterminated server block")
    return ranges


def _server_names(block: str) -> set[str]:
    names: set[str] = set()
    for match in _SERVER_NAME_RE.finditer(block):
        names.update(match.group(1).split())
    return names


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


def patch_text(text: str, *, domain: str, upstream: str = "happyfox_backend") -> tuple[str, bool]:
    if not _DOMAIN_RE.fullmatch(domain):
        raise ValueError(f"invalid public domain: {domain!r}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", upstream):
        raise ValueError(f"invalid nginx upstream name: {upstream!r}")

    target: tuple[int, int] | None = None
    already_patched = False

    for start, end in _server_ranges(text):
        block = text[start:end]
        if domain not in _server_names(block):
            continue
        if not _LISTEN_443_RE.search(block):
            continue
        if f"http://{upstream}" not in block:
            continue
        if _HEALTH_RE.search(block):
            already_patched = True
            break
        if target is not None:
            raise ValueError(f"multiple HTTPS server blocks matched {domain!r}")
        target = (start, end)

    if already_patched:
        return text, False
    if target is None:
        raise ValueError(
            f"could not find HTTPS server block for {domain!r} using upstream {upstream!r}"
        )

    start, end = target
    block = text[start:end]
    insert_match = _INSERT_BEFORE_RE.search(block) or _CATCH_ALL_RE.search(block)
    if insert_match is None:
        raise ValueError(f"could not find a safe insertion point in server block for {domain!r}")

    absolute = start + insert_match.start()
    patched = text[:absolute] + _health_location(upstream) + text[absolute:]
    return patched, True


def patch_file(path: Path, *, domain: str, upstream: str = "happyfox_backend") -> bool:
    original = path.read_text(encoding="utf-8")
    patched, changed = patch_text(original, domain=domain, upstream=upstream)
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
        # copyfile truncates the existing bind-mount source in place so a running
        # container continues to see the updated contents through the same inode.
        shutil.copyfile(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Add HappyFox /health proxy route to nginx")
    parser.add_argument("config", type=Path)
    parser.add_argument("domain")
    parser.add_argument("--upstream", default="happyfox_backend")
    args = parser.parse_args()

    changed = patch_file(args.config, domain=args.domain, upstream=args.upstream)
    print("patched" if changed else "already-present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
