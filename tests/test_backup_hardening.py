import subprocess
from pathlib import Path


def test_backup_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", "scripts/backup_db.sh"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_postgres_backup_is_verified_before_rotation() -> None:
    script = Path("scripts/backup_db.sh").read_text(encoding="utf-8")

    verify_pos = script.index('pg_restore --list "$TMP_PG_DUMP"')
    rotate_pos = script.index('mv -f "$TMP_PG_DUMP" "$LATEST_PG_DUMP"')
    assert verify_pos < rotate_pos
    assert "postgres backup verified and updated" in script
    assert "banano_kling DB backup" not in script


def test_runtime_installs_postgres_17_client() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "postgresql-client-17" in dockerfile
    assert "postgresql-client \\\n" not in dockerfile
