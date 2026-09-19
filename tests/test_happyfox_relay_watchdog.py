from pathlib import Path


def test_happyfox_relay_watchdog_uses_canonical_endpoint_and_safe_reload() -> None:
    script = Path("scripts/happyfox_relay_watchdog.sh").read_text(encoding="utf-8")

    assert "api.happy-fox.online" in script
    assert "2.27.160.11" in script
    assert 'https://$SNI/webhook' in script
    assert '"401"' in script
    assert "nginx -t" in script
    assert "nginx -s reload" in script
    assert "BOT_TOKEN" not in script
    assert "WEBHOOK_SECRET_TOKEN" not in script


def test_happyfox_relay_watchdog_timer_checks_every_fifteen_minutes() -> None:
    timer = Path("deploy/systemd/happyfox-relay-watchdog.timer").read_text(
        encoding="utf-8"
    )

    assert "OnBootSec=2m" in timer
    assert "OnUnitActiveSec=15m" in timer
    assert "Persistent=true" in timer
    assert "happyfox-relay-watchdog.service" in timer
