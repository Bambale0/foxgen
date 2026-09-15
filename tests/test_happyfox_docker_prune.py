from pathlib import Path


def test_happyfox_docker_prune_is_age_bounded_and_never_prunes_volumes() -> None:
    script = Path("scripts/happyfox_docker_prune.sh").read_text(encoding="utf-8")

    assert "120h" in script
    assert 'docker container prune -f --filter "until=$MAX_AGE"' in script
    assert 'docker image prune -af --filter "until=$MAX_AGE"' in script
    assert 'docker builder prune -af --filter "until=$MAX_AGE"' in script
    assert "docker volume prune" not in script
    assert "--volumes" not in script
    assert "flock -n" in script
    assert "happyfox_docker_prune stage=disk_before" in script
    assert "happyfox_docker_prune stage=disk_after" in script


def test_happyfox_docker_prune_timer_runs_daily_and_is_persistent() -> None:
    timer = Path("deploy/systemd/happyfox-docker-prune.timer").read_text(
        encoding="utf-8"
    )
    service = Path("deploy/systemd/happyfox-docker-prune.service").read_text(
        encoding="utf-8"
    )

    assert "OnCalendar=*-*-* 04:30:00" in timer
    assert "RandomizedDelaySec=15m" in timer
    assert "Persistent=true" in timer
    assert "happyfox-docker-prune.service" in timer
    assert "ExecStart=/usr/local/sbin/happyfox-docker-prune" in service
    assert "Requires=docker.service" in service
