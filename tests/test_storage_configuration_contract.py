from pathlib import Path

from foxgen.core.config import Settings


def test_bucket_creation_is_not_application_configuration() -> None:
    assert "s3_create_bucket" not in Settings.model_fields


def test_env_examples_do_not_advertise_removed_bucket_creation_flag() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (root / ".env.example", root / "deploy/production.env.example"):
        assert "FOXGEN_S3_CREATE_BUCKET" not in path.read_text(encoding="utf-8")
