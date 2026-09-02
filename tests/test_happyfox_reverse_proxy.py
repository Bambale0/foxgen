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


def _config_with_health_only(target: str = "foxgen-happyfox-bot:8080") -> str:
    return _config(target).replace(
        "    location ^~ /mini-app/api/ {\n",
        "    location = /health {\n"
        "        proxy_pass http://happyfox_backend;\n"
        "    }\n\n"
        "    location ^~ /mini-app/api/ {\n",
        1,
    )


def test_patch_adds_public_health_max_webhook_and_switches_to_new_backend() -> None:
    patched, changed = _patch_text(
        _config("172.20.0.6:8080"),
        domain=DOMAIN,
        target="foxgen-happyfox-bot:8080",
    )

    assert changed is True
    assert "server foxgen-happyfox-bot:8080;" in patched
    assert "server 172.20.0.6:8080;" not in patched
    assert patched.count("location = /health {") == 2
    assert patched.count("location = /max/webhook {") == 1
    domain_block = patched.split(f"server_name {DOMAIN};", 2)[2]
    assert "proxy_pass http://happyfox_backend;" in domain_block
    assert "proxy_set_header X-Max-Bot-Api-Secret $http_x_max_bot_api_secret;" in domain_block
    assert domain_block.index("location = /health") < domain_block.index(
        "location = /max/webhook"
    )
    assert domain_block.index("location = /max/webhook") < domain_block.index(
        "location ^~ /mini-app/api/"
    )


def test_patch_repairs_existing_health_only_config_with_max_webhook() -> None:
    patched, changed = _patch_text(
        _config_with_health_only(),
        domain=DOMAIN,
        target="foxgen-happyfox-bot:8080",
    )

    assert changed is True
    assert patched.count("location = /health {") == 2
    assert patched.count("location = /max/webhook {") == 1


def test_patch_can_switch_back_to_legacy_api_address() -> None:
    with_routes, _ = _patch_text(_config(), domain=DOMAIN)

    patched, changed = _patch_text(
        with_routes,
        domain=DOMAIN,
        target="172.20.0.6:8080",
    )

    assert changed is True
    assert "server 172.20.0.6:8080;" in patched
    assert "server foxgen-happyfox-bot:8080;" not in patched
    assert patched.count("location = /health {") == 2
    assert patched.count("location = /max/webhook {") == 1


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


def test_deploy_script_ignores_stale_legacy_container_without_network_target() -> None:
    script = Path("scripts/deploy_happyfox.sh").read_text(encoding="utf-8")

    resolver_gate = "if resolve_legacy_upstream_target; then"
    redeploy_message = (
        "[happyfox-deploy] No usable legacy API target; preparing existing HappyFox proxy route"
    )
    new_target = 'patch_reverse_proxy_target "$HAPPYFOX_NEW_UPSTREAM_TARGET"'
    docker_deploy = "bash scripts/deploy_backend_docker.sh deploy"

    assert resolver_gate in script
    assert "LEGACY_ROLLBACK_AVAILABLE=0" in script
    assert "LEGACY_ROLLBACK_AVAILABLE=1" in script
    assert redeploy_message in script
    assert 'export CUTOVER_STOP_CONTAINERS=""' in script
    assert script.index(resolver_gate) < script.index(redeploy_message)
    assert script.index(redeploy_message) < script.index(new_target, script.index(redeploy_message))
    assert script.index(new_target, script.index(redeploy_message)) < script.rindex(docker_deploy)


def test_deploy_script_only_rolls_back_when_legacy_target_is_usable() -> None:
    script = Path("scripts/deploy_happyfox.sh").read_text(encoding="utf-8")

    assert 'if [ "$LEGACY_ROLLBACK_AVAILABLE" = "1" ]; then' in script
    assert "rollback_if_available" in script
    assert "No usable legacy rollback target; keeping HappyFox runtime online" in script


def test_deploy_script_gates_public_max_webhook_route() -> None:
    script = Path("scripts/deploy_happyfox.sh").read_text(encoding="utf-8")

    health_gate = script.rindex('${PUBLIC_ORIGIN}/health')
    max_gate = script.rindex('${PUBLIC_ORIGIN}/max/webhook')

    assert "max_webhook_status" in script
    assert 'if [ "$max_webhook_status" != "401" ]; then' in script
    assert "MAX_WEBHOOK_ROUTE_OK" in script
    assert health_gate < max_gate
