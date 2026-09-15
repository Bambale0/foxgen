from __future__ import annotations

from pathlib import Path

from scripts.render_happyfox_miniapp_channel import render_html, render_tree
from scripts.tune_happyfox_nginx import _add_max_webhook_launch_compat


HTML = """<!doctype html>
<html>
<head>
<script src="/mini-app/telegram-web-app.js"></script>
<script src="https://st.max.ru/js/max-web-app.js"></script>
<script src="/mini-app/_next/static/app.js"></script>
</head>
<body>HappyFox</body>
</html>
"""


def test_telegram_variant_keeps_only_telegram_bridge() -> None:
    rendered = render_html(HTML, "telegram")

    assert '/mini-app/telegram-web-app.js' in rendered
    assert 'https://st.max.ru/js/max-web-app.js' not in rendered
    assert 'happyfox-miniapp-channel" content="telegram' in rendered


def test_max_variant_keeps_only_max_bridge() -> None:
    rendered = render_html(HTML, "max")

    assert 'https://st.max.ru/js/max-web-app.js' in rendered
    assert '/mini-app/telegram-web-app.js' not in rendered
    assert 'happyfox-miniapp-channel" content="max' in rendered


def test_shared_variant_preserves_both_bridges_for_transition() -> None:
    rendered = render_html(HTML, "shared")

    assert '/mini-app/telegram-web-app.js' in rendered
    assert 'https://st.max.ru/js/max-web-app.js' in rendered
    assert 'happyfox-miniapp-channel" content="shared' in rendered


def test_render_tree_is_repeatable_for_same_channel(tmp_path: Path) -> None:
    first = tmp_path / "index.html"
    nested = tmp_path / "nested" / "index.html"
    nested.parent.mkdir()
    first.write_text(HTML, encoding="utf-8")
    nested.write_text(HTML, encoding="utf-8")

    assert render_tree(tmp_path, "telegram") == 2
    assert render_tree(tmp_path, "telegram") == 2
    assert 'https://st.max.ru/js/max-web-app.js' not in first.read_text(encoding="utf-8")
    assert 'https://st.max.ru/js/max-web-app.js' not in nested.read_text(encoding="utf-8")


def test_nginx_tuner_preserves_existing_custom_max_launch_redirect() -> None:
    text = """server {
    listen 443 ssl;
    server_name api.happy-fox.online;
    location = /max/webhook {
        if ($request_method = GET) { return 302 https://max.happy-fox.online/mini-app/; }
        proxy_pass http://happyfox_backend;
    }
    location / { proxy_pass http://happyfox_backend; }
}
server {
    listen 443 ssl;
    server_name app.happy-fox.online;
}
"""

    tuned = _add_max_webhook_launch_compat(text)

    assert tuned == text
    assert tuned.count("location = /max/webhook {") == 1
    assert "https://max.happy-fox.online/mini-app/" in tuned


def test_activation_is_noop_until_server_config_exists() -> None:
    script = Path("scripts/activate_happyfox_channel_miniapps.sh").read_text(encoding="utf-8")

    assert 'if [[ ! -s "$CONFIG_FILE" ]]; then' in script
    assert "keeping transitional shared Mini App host" in script
    assert "source \"$CONFIG_FILE\"" not in script
    assert 'APP_ROOT="/var/www/happyfox-app/mini-app"' in script
    assert 'MAX_MINIAPP_ROOT="/var/www/happyfox-max/mini-app"' in script
    assert 'docker cp "$cid:/app/frontend/miniapp-v0/out/." "$work/generic/"' in script
    assert 'render_happyfox_miniapp_channel.py" "$APP_ROOT" telegram' in script
    assert 'render_happyfox_miniapp_channel.py" "$MAX_MINIAPP_ROOT" max' in script


def test_provisioning_requires_dns_and_creates_server_side_activation_config() -> None:
    script = Path("scripts/provision_happyfox_max_miniapp_host.sh").read_text(encoding="utf-8")

    assert 'DOMAIN="max.happy-fox.online"' in script
    assert 'WEB_ROOT="/var/www/happyfox-max"' in script
    assert "getent ahostsv4" in script
    assert "certbot certonly" in script
    assert "/etc/foxgen-happyfox/max-miniapp.env" in script
    assert "MAX_MINIAPP_ROOT=" not in script
    assert "https://st.max.ru" in script


def test_canonical_production_deploy_owns_split_reconciliation() -> None:
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    deploy_index = workflow.index("bash scripts/deploy_happyfox_dedicated.sh")
    reconcile_index = workflow.index("bash scripts/activate_happyfox_channel_miniapps.sh")
    verify_index = workflow.index("- name: Verify public production revision")

    assert deploy_index < reconcile_index < verify_index
    assert "keeping transitional shared Mini App host" not in workflow
    assert not Path(".github/workflows/activate-miniapp-channel-split.yml").exists()
