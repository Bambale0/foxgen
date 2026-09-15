from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

UPSTREAM_BLOCK = """upstream happyfox_backend {
    server 127.0.0.1:1888;
    keepalive 64;
}

"""

MAX_WEBHOOK_LAUNCH_COMPAT_BLOCK = """    location = /max/webhook {
        if ($request_method = GET) { return 302 {max_miniapp_url}; }
        proxy_pass http://happyfox_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_socket_keepalive on;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
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

MINIAPP_ROOT_BLOCK = """    location = /mini-app/ {
        error_page 418 =200 /mini-app/index.html;
        if ($request_method = OPTIONS) { return 204; }
        if ($request_method = POST) { return 418; }
        try_files /mini-app/index.html =404;
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }

"""


LANDING_MINIAPP_COMPAT_BLOCK = """    location /mini-app/api/ {
        proxy_pass http://happyfox_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_socket_keepalive on;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
    }

    location = /mini-app/ {
        error_page 418 =200 /mini-app/index.html;
        if ($request_method = OPTIONS) { return 204; }
        if ($request_method = POST) { return 418; }
        try_files /mini-app/index.html =404;
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
    }

    location /mini-app/ { try_files $uri $uri/ /mini-app/index.html; }
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



def _normalize_public_https_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MAX Mini App URL must be a public HTTPS URL")
    path = parsed.path or "/"
    return urlunsplit(("https", parsed.netloc, path, "", ""))


def _add_max_webhook_launch_compat(text: str, *, max_miniapp_url: str) -> str:
    api_marker = "server_name api.happy-fox.online;"
    if api_marker not in text:
        raise ValueError("HappyFox API server block was not found")

    max_miniapp_url = _normalize_public_https_url(max_miniapp_url)
    prefix, rest = text.split(api_marker, 1)
    if "\nserver {" not in rest:
        raise ValueError("HappyFox API server block terminator was not found")
    api_section, suffix = rest.split("\nserver {", 1)

    if "location = /max/webhook {" in api_section:
        redirect_pattern = re.compile(
            r"if \(\$request_method = GET\) \{ return 302 https://[^;\s]+; \}"
        )
        if not redirect_pattern.search(api_section):
            raise ValueError("HappyFox MAX webhook GET redirect was not found")
        api_section = redirect_pattern.sub(
            f"if ($request_method = GET) {{ return 302 {max_miniapp_url}; }}",
            api_section,
            count=1,
        )
        return prefix + api_marker + api_section + "\nserver {" + suffix

    marker = "    location / {"
    if marker not in api_section:
        raise ValueError("HappyFox API proxy fallback was not found")
    api_section = api_section.replace(
        marker,
        MAX_WEBHOOK_LAUNCH_COMPAT_BLOCK.format(
            max_miniapp_url=max_miniapp_url,
        )
        + marker,
        1,
    )
    return prefix + api_marker + api_section + "\nserver {" + suffix


def _add_static_cache(text: str) -> str:
    if "location ^~ /mini-app/_next/static/" in text:
        return text

    marker = "    location /mini-app/ { try_files $uri $uri/ /mini-app/index.html; }"
    if marker not in text:
        raise ValueError("HappyFox app static fallback location was not found")
    return text.replace(marker, STATIC_BLOCK + marker, 1)


def _allow_max_root_launch_methods(text: str) -> str:
    if "location = /mini-app/ {" in text and "error_page 418 =200 /mini-app/index.html;" in text:
        return text

    marker = "    location /mini-app/ { try_files $uri $uri/ /mini-app/index.html; }"
    if marker not in text:
        raise ValueError("HappyFox app static fallback location was not found")
    return text.replace(marker, MINIAPP_ROOT_BLOCK + marker, 1)



def _enable_landing_miniapp_compat(text: str) -> str:
    landing_marker = "server_name happy-fox.online;"
    if landing_marker not in text:
        raise ValueError("HappyFox landing server block was not found")

    landing_section = text.split(landing_marker, 1)[1].split("\nserver {", 1)[0]
    if (
        "location /mini-app/api/ {" in landing_section
        and "location = /mini-app/ {" in landing_section
        and "try_files $uri $uri/ /mini-app/index.html;" in landing_section
    ):
        return text

    marker = """    location = / { try_files /mini-app/landing/index.html =404; }
    location /mini-app/ { try_files $uri $uri/ =404; }"""
    if marker not in text:
        raise ValueError("HappyFox landing Mini App fallback was not found")

    replacement = (
        "    location = / { try_files /mini-app/landing/index.html =404; }\n"
        + LANDING_MINIAPP_COMPAT_BLOCK
    )
    return text.replace(marker, replacement, 1)


def tune_site(
    text: str,
    *,
    max_miniapp_url: str = "https://app.happy-fox.online/mini-app/",
) -> str:
    if "server_name api.happy-fox.online;" not in text:
        raise ValueError("HappyFox API server block was not found")
    if "server_name app.happy-fox.online;" not in text:
        raise ValueError("HappyFox app server block was not found")

    if "upstream happyfox_backend {" not in text:
        text = UPSTREAM_BLOCK + text

    text = _enable_http2(text)
    text = _remove_site_ssl_protocols(text)
    text = _tune_proxy_locations(text)
    text = _add_max_webhook_launch_compat(
        text,
        max_miniapp_url=max_miniapp_url,
    )
    text = _add_static_cache(text)
    text = _allow_max_root_launch_methods(text)
    text = _enable_landing_miniapp_compat(text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--certbot-options", required=True, type=Path)
    parser.add_argument(
        "--max-miniapp-url",
        default="https://app.happy-fox.online/mini-app/",
    )
    args = parser.parse_args()

    site_text = args.site.read_text(encoding="utf-8")
    certbot_text = args.certbot_options.read_text(encoding="utf-8")

    args.site.write_text(
        tune_site(site_text, max_miniapp_url=args.max_miniapp_url),
        encoding="utf-8",
    )
    args.certbot_options.write_text(
        tune_certbot_options(certbot_text),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
