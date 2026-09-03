from __future__ import annotations

import re
from pathlib import Path

from scripts.recover_happyfox_channel_runtime import parse_env, recover


def test_recovery_restores_max_from_server_backup_without_logging_secret(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    (tmp_path / ".env").write_text("BOT_TOKEN='telegram'\n", encoding="utf-8")
    (tmp_path / ".env.happyfox.runtime").write_text(
        "WEBHOOK_HOST='https://old.example'\n",
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backups" / "manual"
    backup_dir.mkdir(parents=True)
    secret_token = "historic-max-access-token"
    (backup_dir / "happyfox.env.backup").write_text(
        "MAX_ACCESS_TOKEN='" + secret_token + "'\n"
        "MAX_BOT_NAME='happyfox_max'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HAPPYFOX_PUBLIC_ORIGIN", "https://alena.example")

    recovered = recover(tmp_path)

    assert recovered["MAX_ENABLED"] == "1"
    assert recovered["MAX_ACCESS_TOKEN"] == secret_token
    assert re.fullmatch(r"[A-Za-z0-9_-]{5,256}", recovered["MAX_WEBHOOK_SECRET"])
    assert recovered["MAX_WEBHOOK_URL"] == "https://alena.example/max/webhook"
    assert recovered["MAX_MINI_APP_URL"] == "https://alena.example/mini-app/"
    assert recovered["MAX_PAYMENT_RETURN_URL"] == "https://alena.example/mini-app/"

    seed = parse_env(tmp_path / ".env.happyfox.channels")
    runtime = parse_env(tmp_path / ".env.happyfox.runtime")
    assert seed["MAX_ACCESS_TOKEN"] == secret_token
    assert runtime["MAX_ACCESS_TOKEN"] == secret_token

    output = capsys.readouterr().out
    assert "max_access_token_recovered=yes" in output
    assert "max_runtime_recovery_ready=yes" in output
    assert secret_token not in output
    assert recovered["MAX_WEBHOOK_SECRET"] not in output


def test_recovery_is_dark_when_no_max_token_exists(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    (tmp_path / ".env").write_text("BOT_TOKEN='telegram'\n", encoding="utf-8")
    (tmp_path / ".env.happyfox.runtime").write_text(
        "INSTAGRAM_ENABLED='0'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HAPPYFOX_PUBLIC_ORIGIN", "https://alena.example")

    recovered = recover(tmp_path)

    assert "MAX_ACCESS_TOKEN" not in recovered
    assert "MAX_ENABLED" not in recovered
    output = capsys.readouterr().out
    assert "max_access_token_recovered=no" in output


def test_deploy_uses_runtime_post_smoke_not_edge_method_status() -> None:
    wrapper = Path("scripts/deploy_happyfox.sh").read_text(encoding="utf-8")

    assert "recover_happyfox_channel_runtime.py" in wrapper
    assert "MAX_WEBHOOK_ROUTE_OK" in wrapper
    assert "max_webhook_status" in wrapper
    assert "max_ingress_status" not in wrapper
    assert "instagram_ingress_status" not in wrapper


def test_production_workflow_bridges_max_token_without_logging_secret() -> None:
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert "MAX_ACCESS_TOKEN: ${{ secrets.MAX_ACCESS_TOKEN }}" in workflow
    assert 'Missing production secret MAX_ACCESS_TOKEN' in workflow
    assert "Stage protected MAX runtime seed" in workflow
    assert "backups/channel-actions/.env.max.actions" in workflow
    assert "chmod 0600" in workflow
    assert "MAX_ACCESS_TOKEN configured=yes" in workflow
    assert "Protected MAX runtime seed staged" in workflow
    assert 'echo "$MAX_ACCESS_TOKEN"' not in workflow
    assert "cat $MAX_ACCESS_TOKEN" not in workflow
    assert 'rm -f "$PROJECT_DIR/backups/channel-actions/.env.max.actions"' in workflow
