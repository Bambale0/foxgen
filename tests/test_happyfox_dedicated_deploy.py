from pathlib import Path


def test_dedicated_deploy_pins_three_public_origins_and_runtime_db() -> None:
    deploy = Path("scripts/deploy_happyfox_dedicated.sh").read_text(encoding="utf-8")

    assert "https://api.happy-fox.online" in deploy
    assert "https://app.happy-fox.online" in deploy
    assert "https://happy-fox.online" in deploy
    assert "HAPPYFOX_DATABASE_NAME:-happyfox_cutover" in deploy
    assert "recover_happyfox_channel_runtime.py" in deploy
    assert "chown -R 10001:10001" in deploy
    assert "ensure_telegram_webhook.py" in deploy
    assert "TELEGRAM_WEBHOOK_URL" in deploy
    assert "TELEGRAM_WEBHOOK_IP_ADDRESS" in deploy
    assert "HAPPYFOX_TELEGRAM_RELAY_IP:-2.27.160.11" in deploy
    assert 'values["TELEGRAM_WEBHOOK_URL"] = f"{api}/webhook"' in deploy
    assert 'values["TELEGRAM_WEBHOOK_IP_ADDRESS"] = telegram_relay_ip' in deploy
    assert 'values["PERSIST_PROVIDER_RESULTS"] = "1"' in deploy
    assert "HAPPYFOX_GITHUB_REPO:-Bambale0/foxgen" in deploy
    assert 'gh api "repos/${GITHUB_REPO}/commits/main" --jq .sha' in deploy
    assert "gh auth status -h github.com" in deploy
    assert '"$API_ORIGIN/yookassa/webhook"' in deploy
    assert "backup_db.sh" in deploy


def test_production_workflow_targets_dedicated_host_with_server_side_gh() -> None:
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert "5.35.124.201" in workflow
    assert "/opt/happyfox/repo" in workflow
    assert "SHA256:NjLkwjwPwDroguKC0FMTFEjaSJD+vFEfL3EsjEN0pI4" in workflow
    assert "Sync exact main on HappyFox host with gh" in workflow
    assert "gh auth status -h github.com" in workflow
    assert "gh auth setup-git" in workflow
    assert "gh api repos/Bambale0/foxgen/commits/main --jq .sha" in workflow
    assert "deploy_happyfox_dedicated.sh" in workflow
    assert "HAPPYFOX_DATABASE_NAME=happyfox_cutover" in workflow
    assert "DEPLOY_KNOWN_HOSTS" not in workflow
    assert "ssh-keyscan" in workflow
    assert "HAPPYFOX_RUNTIME_ENV" not in workflow
    assert "Sync protected HappyFox runtime overlay" not in workflow


def test_telegram_webhook_reconciliation_preserves_pending_updates() -> None:
    script = Path("scripts/ensure_telegram_webhook.py").read_text(encoding="utf-8")

    assert "set_webhook" in script
    assert '"drop_pending_updates": False' in script
    assert "get_webhook_info" in script
    assert "set_chat_menu_button" in script
    assert "MenuButtonCommands" in script
    assert "MenuButtonWebApp" not in script
    assert "WEBHOOK_HOST" in script
    assert "TELEGRAM_WEBHOOK_URL" in script
    assert "WEBHOOK_SECRET_TOKEN" in script
    assert "INTERNAL_API_SECRET" in script
    assert "TELEGRAM_WEBHOOK_IP_ADDRESS" in script
    assert "secret_token" in script
    assert "ip_address" in script
