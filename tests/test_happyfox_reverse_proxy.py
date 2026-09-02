from pathlib import Path

import pytest


DOMAIN = "alena.xn--e1aikcel5c5a.online"


def _patch_text(*args, **kwargs):
    from scripts.patch_happyfox_reverse_proxy import patch_text

    return patch_text(*args, **kwargs)


def _config(target: str = "foxgen-happyfox-bot:8080") -> str:
    return f"""upstream happyfox_backend {{
    server {target};
    keepalive 32;
}}

server {{
    listen 80;
    server_name {DOMAIN};
    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    http2 on;
    server_name {DOMAIN};

    location ^~ /mini-app/api/ {{
        proxy_pass http://happyfox_backend;
    }}

    location = /webhook {{
        proxy_pass http://happyfox_backend;
    }}

    location / {{
        return 404;
    }}
}}

server {{
    listen 443 ssl;
    server_name unrelated.example;
    location = /health {{
        return 200;
    }}
}}
"""


def test_patch_adds_public_health_and_switches_to_new_backend() -> None:
    patched, changed = _patch_text(
        _config("172.20.0.6:8080"),
        domain=DOMAIN,
        target="foxgen-happyfox-bot:8080",
    )

    assert changed is True
    assert "server foxgen-happyfox-bot:8080;" in patched
    assert "server 172.20.0.6:8080;" not in patched
    assert patched.count("location = /health {") == 2
    domain_block = patched.split(f"server_name {DOMAIN};", 2)[2]
    assert "proxy_pass http://happyfox_backend;" in domain_block
    assert domain_block.index("location = /health") < domain_block.index(
        "location ^~ /mini-app/api/"
    )


def test_patch_can_switch_back_to_legacy_api_address() -> None:
    with_health, _ = _patch_text(_config(), domain=DOMAIN)

    patched, changed = _patch_text(
        with_health,
        domain=DOMAIN,
        target="172.20.0.6:8080",
    )

    assert changed is True
    assert "server 172.20.0.6:8080;" in patched
    assert "server foxgen-happyfox-bot:8080;" not in patched
    assert patched.count("location = /health {") == 2


def test_patch_is_idempotent_for_same_target() -> None:
    first, changed = _patch_text(
        _config(),
        domain=DOMAIN,
        target="foxgen-happyfox-bot:8080",
    )
    assert changed is True

    second, changed = _patch_text(
        first,
        domain=DOMAIN,
        target="foxgen-happyfox-bot:8080",
    )
    assert changed is False
    assert second == first


@pytest.mark.parametrize(
    ("domain", "target"),
    [
        ("bad domain", "foxgen-happyfox-bot:8080"),
        (DOMAIN, "http://foxgen-happyfox-bot:8080"),
        (DOMAIN, "foxgen-happyfox-bot:70000"),
    ],
)
def test_patch_rejects_unsafe_inputs(domain: str, target: str) -> None:
    with pytest.raises(ValueError):
        _patch_text(_config(), domain=domain, target=target)


def test_patch_requires_matching_happyfox_https_vhost() -> None:
    with pytest.raises(ValueError, match="could not find HTTPS server block"):
        _patch_text(_config(), domain="missing.example")


def test_deploy_script_keeps_public_health_gate_and_reversible_targets() -> None:
    script = Path("scripts/deploy_happyfox.sh").read_text(encoding="utf-8")

    assert 'HAPPYFOX_LEGACY_UPSTREAM_TARGET:-}' in script
    assert 'HAPPYFOX_NEW_UPSTREAM_TARGET:-${CONTAINER_NAME}:8080' in script
    assert 'os.environ["HAPPYFOX_BACKEND_NETWORK"]' in script
    assert 'docker inspect "$legacy_api_container"' in script
    assert 'LEGACY_UPSTREAM_TARGET="${legacy_ip}:8080"' in script
    assert 'Destination "/etc/nginx/conf.d/default.conf"' in script
    assert "scripts/patch_happyfox_reverse_proxy.py" in script
    assert '${PUBLIC_ORIGIN}/health' in script

    legacy_restore = script.index("restore_proxy_to_legacy")
    docker_cutover = script.rindex("bash scripts/deploy_backend_docker.sh deploy")
    new_switch = script.rindex(
        'patch_reverse_proxy_target "$HAPPYFOX_NEW_UPSTREAM_TARGET"'
    )
    public_gate = script.rindex('${PUBLIC_ORIGIN}/health')
    assert legacy_restore < docker_cutover < new_switch < public_gate
