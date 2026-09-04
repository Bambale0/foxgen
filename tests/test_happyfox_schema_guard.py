from pathlib import Path

from scripts.ensure_happyfox_schema import PROMPT_FEED_COLUMNS, _postgres_dsn


def test_schema_guard_covers_generation_settings(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://foxgen:secret@postgres/happyfox",
    )

    assert _postgres_dsn() == "postgresql://foxgen:secret@postgres/happyfox"
    assert (
        "user_prompts",
        "generation_settings",
        "TEXT DEFAULT '{}'",
    ) in PROMPT_FEED_COLUMNS


def test_schema_guard_skips_non_postgres(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///bot.db")
    assert _postgres_dsn() is None


def test_happyfox_container_runs_schema_guard_before_bot() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    startup = Path("scripts/start_happyfox.sh").read_text(encoding="utf-8")

    assert 'CMD ["bash", "scripts/start_happyfox.sh"]' in dockerfile
    assert "python -m scripts.ensure_happyfox_schema" in startup
    assert "exec python -m bot.main" in startup
    assert startup.index("ensure_happyfox_schema") < startup.index("bot.main")
