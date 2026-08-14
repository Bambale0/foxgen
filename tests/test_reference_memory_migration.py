from pathlib import Path


def test_reference_memory_migration_is_forward_linked_and_owner_scoped() -> None:
    migration = Path("migrations/versions/20260815_0009_reference_memory.py").read_text(
        encoding="utf-8"
    )
    assert 'revision: str = "20260815_0009"' in migration
    assert 'down_revision: str | None = "20260813_0008"' in migration
    assert '"reference_assets"' in migration
    assert 'sa.ForeignKey("users.id", ondelete="CASCADE")' in migration
    assert '"checksum_sha256"' in migration
    assert '"delete_pending"' in migration
    assert "uq_reference_assets_storage_key" in migration
