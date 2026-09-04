from __future__ import annotations

import pytest

from scripts.resolve_happyfox_miniapp_nginx_path import (
    resolve_miniapp_path,
    resolve_miniapp_proxy_container,
)

DOMAIN = "alena.xn--e1aikcel5c5a.online"


def _server(location: str, *, root: str = "") -> str:
    return f"""
server {{
    listen 443 ssl;
    server_name {DOMAIN};
    {root}
    {location}
}}
"""


def test_resolves_direct_alias_path() -> None:
    config = _server(
        """
        location /mini-app/ {
            alias /srv/happyfox-miniapp/;
        }
        """
    )

    assert resolve_miniapp_path(config, domain=DOMAIN) == "/srv/happyfox-miniapp"


def test_resolves_inherited_root_path() -> None:
    config = _server(
        """
        location /mini-app/ {
            try_files $uri $uri/ =404;
        }
        """,
        root="root /usr/share/nginx/html;",
    )

    assert resolve_miniapp_path(config, domain=DOMAIN) == "/usr/share/nginx/html/mini-app"


def test_resolves_static_proxy_container_for_production_topology() -> None:
    config = _server(
        """
        location /mini-app/ {
            proxy_pass http://banano-miniapp;
            proxy_http_version 1.1;
        }
        """
    )

    with pytest.raises(ValueError, match="alias/root"):
        resolve_miniapp_path(config, domain=DOMAIN)
    assert resolve_miniapp_proxy_container(config, domain=DOMAIN) == "banano-miniapp"


def test_resolves_static_proxy_container_with_port() -> None:
    config = _server(
        """
        location ^~ /mini-app/ {
            proxy_pass http://happyfox-static:8080;
        }
        """
    )

    assert resolve_miniapp_proxy_container(config, domain=DOMAIN) == "happyfox-static"


@pytest.mark.parametrize(
    "proxy_pass",
    [
        "proxy_pass http://$miniapp_upstream;",
        "proxy_pass http://user@static-sidecar;",
        "proxy_pass http://static-sidecar:99999;",
    ],
)
def test_rejects_unsafe_static_proxy_targets(proxy_pass: str) -> None:
    config = _server(
        f"""
        location /mini-app/ {{
            {proxy_pass}
        }}
        """
    )

    with pytest.raises(ValueError):
        resolve_miniapp_proxy_container(config, domain=DOMAIN)


def test_rejects_ambiguous_proxy_pass() -> None:
    config = _server(
        """
        location /mini-app/ {
            proxy_pass http://first-static;
            proxy_pass http://second-static;
        }
        """
    )

    with pytest.raises(ValueError, match="exactly one"):
        resolve_miniapp_proxy_container(config, domain=DOMAIN)
