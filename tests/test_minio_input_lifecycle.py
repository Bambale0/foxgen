from pathlib import Path
from typing import Any

from scripts.configure_minio_input_lifecycle import (
    INPUT_PREFIX,
    RULE_ID,
    configure_lifecycle,
    lifecycle_rule_matches,
    merge_lifecycle_rules,
)


class FakeS3Client:
    def __init__(self, rules: list[dict[str, Any]] | None = None) -> None:
        self.rules = list(rules or [])
        self.created_buckets: list[str] = []
        self.put_calls = 0

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]:
        assert Bucket == "foxgen-media"
        return {}

    def create_bucket(self, *, Bucket: str) -> dict[str, Any]:
        self.created_buckets.append(Bucket)
        return {}

    def get_bucket_lifecycle_configuration(self, *, Bucket: str) -> dict[str, Any]:
        assert Bucket == "foxgen-media"
        return {"Rules": list(self.rules)}

    def put_bucket_lifecycle_configuration(
        self,
        *,
        Bucket: str,
        LifecycleConfiguration: dict[str, Any],
    ) -> dict[str, Any]:
        assert Bucket == "foxgen-media"
        self.put_calls += 1
        self.rules = list(LifecycleConfiguration["Rules"])
        return {}


def test_merge_preserves_unrelated_rules_and_replaces_foxgen_rule_once() -> None:
    unrelated = {
        "ID": "retain-generation-results",
        "Status": "Enabled",
        "Filter": {"Prefix": "generations/"},
        "Expiration": {"Days": 365},
    }
    old_rule = {
        "ID": RULE_ID,
        "Status": "Enabled",
        "Filter": {"Prefix": INPUT_PREFIX},
        "Expiration": {"Days": 7},
    }

    merged = merge_lifecycle_rules(
        [unrelated, old_rule, old_rule],
        retention_days=2,
    )

    assert unrelated in merged
    assert sum(rule.get("ID") == RULE_ID for rule in merged) == 1
    assert any(lifecycle_rule_matches(rule, retention_days=2) for rule in merged)


def test_configure_lifecycle_is_idempotent_and_never_targets_results() -> None:
    unrelated = {
        "ID": "retain-generation-results",
        "Status": "Enabled",
        "Filter": {"Prefix": "generations/"},
        "Expiration": {"Days": 365},
    }
    client = FakeS3Client([unrelated])

    configure_lifecycle(client, bucket="foxgen-media", retention_days=2)
    configure_lifecycle(client, bucket="foxgen-media", retention_days=2)

    assert client.created_buckets == []
    assert client.put_calls == 2
    assert unrelated in client.rules
    matching = [rule for rule in client.rules if rule.get("ID") == RULE_ID]
    assert len(matching) == 1
    assert matching[0]["Filter"] == {"Prefix": "inputs/"}
    assert matching[0]["Filter"] != {"Prefix": "generations/"}


def test_both_compose_stacks_gate_app_services_on_verified_lifecycle() -> None:
    root = Path(__file__).resolve().parents[1]
    development = (root / "docker-compose.yml").read_text(encoding="utf-8")
    production = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    for compose in (development, production):
        assert "scripts/configure_minio_input_lifecycle.py" in compose
        assert "FOXGEN_INPUT_RETENTION_DAYS" in compose
        assert "condition: service_completed_successfully" in compose
        assert "minio/mc:" not in compose

    assert "COPY scripts ./scripts" in dockerfile
