from __future__ import annotations

import argparse
import re
from pathlib import Path

UPSTREAM_BLOCK = """upstream happyfox_backend {
    server 127.0.0.1:1888;
    keepalive 64;
}

"""

STATIC_BLOCK = """    location ^~ /mini-app/_next/static/ {
        try_files $uri =404;
        access_log off;
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options nosniff always;
    }

"""


def tune_certbot_options(text: str) -> str:
    pattern = re.compile(r"(?m)^ssl_protocols\s+[^;]+;\s*$")
    if not pattern.search(text):
        raise ValueError("Certbot SSL options do not contain ssl_protocols")
    return pattern.sub("ssl_protocols TLSv1.2;", text, count=1)


def _enable_http2(text: str) -> str:
    pattern = re.compile(r"(?m)^(\s*listen\s+[^;]*\b443\b[^;]*\bssl\b)([^;]*);$")

    def repl(match: re.Match[str]) -> str:
        full = match.group(0)
        if re.search(r"\bhttp2\b", full):
            return full
        prefix = match.group(1)
        suffix = match.group(2)
        return f"{prefix} http2{suffix};"

    return pattern.sub(repl, text)


def _remove_site_ssl_protocols(text: str) -> str:
    # The dedicated Certbot include is the single source of truth for protocols.
    return re.sub(r"(?m)^\s*ssl_protocols\s+[^;]+;\s*\n", "", text)


def _tune_proxy_locations(text: str) -> str:
    text = text.replace(
        "proxy_pass http://127.0.0.1:1888;",
        "proxy_pass http://happyfox_backend;",
    )

    marker = "proxy_http_version 1.1;"
    lines = text.splitlines()
    output: list[str] = []
    for index, line in enumerate(lines):
        output.append(line)
        if line.strip() != marker:
            continue

        indent = line[: len(line) - len(line.lstrip())]
        nearby = "\n".join(lines[index + 1 : index + 10])
        directives = (
            ('proxy_set_header Connection "";', "proxy_set_header Connection"),
            ("proxy_socket_keepalive on;", "proxy_socket_keepalive"),
            ("proxy_buffering off;", "proxy_buffering"),
            ("proxy_request_buffering off;", "proxy_request_buffering"),
        )
        for directive, key in directives:
            if key not in nearby:
                output.append(f"{indent}{directive}")

    return "\n".join(output) + "\n"


def _add_static_cache(text: str) -> str:
    if "location ^~ /mini-app/_next/static/" in text:
        return text

    marker = "    location /mini-app/ { try_files $uri $uri/ /mini-app/index.html; }"
    if marker not in text:
        raise ValueError("HappyFox app static fallback location was not found")
    return text.replace(marker, STATIC_BLOCK + marker, 1)


def tune_site(text: str) -> str:
    if "server_name api.happy-fox.online;" not in text:
        raise ValueError("HappyFox API server block was not found")
    if "server_name app.happy-fox.online;" not in text:
        raise ValueError("HappyFox app server block was not found")

    if "upstream happyfox_backend {" not in text:
        text = UPSTREAM_BLOCK + text

    text = _enable_http2(text)
    text = _remove_site_ssl_protocols(text)
    text = _tune_proxy_locations(text)
    text = _add_static_cache(text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--certbot-options", required=True, type=Path)
    args = parser.parse_args()

    site_text = args.site.read_text(encoding="utf-8")
    certbot_text = args.certbot_options.read_text(encoding="utf-8")

    args.site.write_text(tune_site(site_text), encoding="utf-8")
    args.certbot_options.write_text(
        tune_certbot_options(certbot_text),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
