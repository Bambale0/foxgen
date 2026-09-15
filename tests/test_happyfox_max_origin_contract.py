from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_max_origin_is_independent_from_telegram_origin() -> None:
    deploy = (ROOT / "scripts" / "deploy_happyfox_dedicated.sh").read_text()

    assert 'APP_ORIGIN="${HAPPYFOX_APP_ORIGIN:-https://app.happy-fox.online}"' in deploy
    assert 'MAX_APP_ORIGIN="${HAPPYFOX_MAX_APP_ORIGIN:-$APP_ORIGIN}"' in deploy
    assert 'values["MINI_APP_URL"] = f"{app}/mini-app/"' in deploy
    assert 'values["MAX_MINI_APP_URL"] = f"{max_app}/mini-app/"' in deploy
    assert '--max-app-origin "$MAX_APP_ORIGIN"' in deploy


def test_verified_bundle_is_published_to_dedicated_max_webroot() -> None:
    deploy = (ROOT / "scripts" / "deploy_happyfox_dedicated.sh").read_text()

    assert "/var/www/happyfox-max/mini-app" in deploy
    assert 'docker cp "$cid:/app/frontend/miniapp-v0/out/." /var/www/happyfox-max/mini-app/' in deploy
    assert '</var/www/happyfox-max/mini-app/revision.txt' in deploy
    assert '$MAX_APP_ORIGIN/mini-app/revision.txt' in deploy


def test_production_workflow_keeps_max_origin_configurable() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-production.yml").read_text()

    assert "MAX_APP_ORIGIN: ${{ vars.HAPPYFOX_MAX_APP_ORIGIN || 'https://app.happy-fox.online' }}" in workflow
    assert 'HAPPYFOX_MAX_APP_ORIGIN="$max_app_origin"' in workflow
    assert 'MAX Mini App: `\${MAX_APP_ORIGIN}/mini-app/`' not in workflow
    assert 'MAX Mini App: \\`${MAX_APP_ORIGIN}/mini-app/\\`' in workflow


def test_max_domain_activation_is_guarded_and_tls_only() -> None:
    activation = (ROOT / "scripts" / "activate_happyfox_max_domain.sh").read_text()

    assert '"${1:-}" == "--activate"' in activation
    assert "DNS for $DOMAIN is not resolvable yet; refusing activation" in activation
    assert "certbot certonly" in activation
    assert "--webroot" in activation
    assert "listen 443 ssl http2;" in activation
    assert "proxy_pass http://happyfox_backend;" in activation
    assert "EXPECTED_REVISION" in activation


def test_examples_document_platform_specific_origins() -> None:
    env_example = (ROOT / ".env.happyfox.example").read_text()
    max_docs = (ROOT / "docs" / "max-channel.md").read_text()

    assert "MINI_APP_URL=https://app.happyfox.example/mini-app/" in env_example
    assert "MAX_MINI_APP_URL=https://max.happyfox.example/mini-app/" in env_example
    assert "Telegram Mini App:  https://app.happy-fox.online/mini-app/" in max_docs
    assert "MAX Mini App:       https://max.happy-fox.online/mini-app/" in max_docs


def test_shell_scripts_parse() -> None:
    for relative in (
        "scripts/deploy_happyfox_dedicated.sh",
        "scripts/activate_happyfox_max_domain.sh",
    ):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / relative)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
