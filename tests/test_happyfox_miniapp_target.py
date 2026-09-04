from scripts.resolve_happyfox_miniapp_nginx_target import resolve_miniapp_target


DOMAIN = "alena.xn--e1aikcel5c5a.online"


def test_resolves_direct_proxy_container_used_by_production() -> None:
    config = f"""
server {{
    listen 443 ssl;
    server_name {DOMAIN};

    location ^~ /mini-app/api/ {{
        proxy_pass http://happyfox_backend;
    }}

    location /mini-app/ {{
        proxy_pass http://banano-miniapp;
    }}
}}
"""

    assert resolve_miniapp_target(config, domain=DOMAIN) == (
        "proxy",
        "banano-miniapp",
    )


def test_resolves_nginx_alias_when_frontend_is_local_static() -> None:
    config = f"""
server {{
    listen 443 ssl;
    server_name {DOMAIN};

    location /mini-app/ {{
        alias /srv/happyfox-miniapp/;
    }}
}}
"""

    assert resolve_miniapp_target(config, domain=DOMAIN) == (
        "filesystem",
        "/srv/happyfox-miniapp",
    )


def test_rejects_variable_proxy_target() -> None:
    config = f"""
server {{
    listen 443 ssl;
    server_name {DOMAIN};

    location /mini-app/ {{
        proxy_pass http://$miniapp_upstream;
    }}
}}
"""

    try:
        resolve_miniapp_target(config, domain=DOMAIN)
    except ValueError as exc:
        assert "variable-based" in str(exc)
    else:
        raise AssertionError("variable proxy target must be rejected")
