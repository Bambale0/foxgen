from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]


RULE_ID = "foxgen-expire-telegram-inputs"
INPUT_PREFIX = "inputs/"
DEFAULT_RETENTION_DAYS = 2
DEFAULT_MULTIPART_ABORT_DAYS = 1
DEFAULT_ATTEMPTS = 30
DEFAULT_RETRY_SECONDS = 2.0


class S3LifecycleClient(Protocol):
    def head_bucket(self, *, Bucket: str) -> dict[str, Any]: ...

    def create_bucket(self, *, Bucket: str) -> dict[str, Any]: ...

    def get_bucket_lifecycle_configuration(self, *, Bucket: str) -> dict[str, Any]: ...

    def put_bucket_lifecycle_configuration(
        self,
        *,
        Bucket: str,
        LifecycleConfiguration: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class LifecycleSettings:
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    region: str
    retention_days: int
    multipart_abort_days: int
    attempts: int
    retry_seconds: float

    @classmethod
    def from_environment(cls) -> LifecycleSettings:
        return cls(
            endpoint_url=_required_env("FOXGEN_S3_ENDPOINT_URL"),
            access_key_id=_required_env("FOXGEN_S3_ACCESS_KEY_ID"),
            secret_access_key=_required_env("FOXGEN_S3_SECRET_ACCESS_KEY"),
            bucket=os.getenv("FOXGEN_S3_BUCKET", "foxgen-media").strip() or "foxgen-media",
            region=os.getenv("FOXGEN_S3_REGION", "us-east-1").strip() or "us-east-1",
            retention_days=_positive_int(
                os.getenv("FOXGEN_INPUT_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)),
                "FOXGEN_INPUT_RETENTION_DAYS",
            ),
            multipart_abort_days=_positive_int(
                os.getenv(
                    "FOXGEN_INPUT_MULTIPART_ABORT_DAYS",
                    str(DEFAULT_MULTIPART_ABORT_DAYS),
                ),
                "FOXGEN_INPUT_MULTIPART_ABORT_DAYS",
            ),
            attempts=_positive_int(
                os.getenv("FOXGEN_MINIO_INIT_ATTEMPTS", str(DEFAULT_ATTEMPTS)),
                "FOXGEN_MINIO_INIT_ATTEMPTS",
            ),
            retry_seconds=_positive_float(
                os.getenv("FOXGEN_MINIO_INIT_RETRY_SECONDS", str(DEFAULT_RETRY_SECONDS)),
                "FOXGEN_MINIO_INIT_RETRY_SECONDS",
            ),
        )


def desired_rule(*, retention_days: int, multipart_abort_days: int) -> dict[str, Any]:
    if retention_days <= 0 or multipart_abort_days <= 0:
        raise ValueError("lifecycle day values must be positive")
    return {
        "ID": RULE_ID,
        "Status": "Enabled",
        "Filter": {"Prefix": INPUT_PREFIX},
        "Expiration": {"Days": retention_days},
        "AbortIncompleteMultipartUpload": {
            "DaysAfterInitiation": multipart_abort_days,
        },
    }


def merge_lifecycle_rules(
    existing_rules: list[dict[str, Any]],
    *,
    retention_days: int,
    multipart_abort_days: int,
) -> list[dict[str, Any]]:
    preserved = [rule for rule in existing_rules if rule.get("ID") != RULE_ID]
    preserved.append(
        desired_rule(
            retention_days=retention_days,
            multipart_abort_days=multipart_abort_days,
        )
    )
    return preserved


def lifecycle_rule_matches(
    rule: dict[str, Any],
    *,
    retention_days: int,
    multipart_abort_days: int,
) -> bool:
    return (
        rule.get("ID") == RULE_ID
        and rule.get("Status") == "Enabled"
        and rule.get("Filter") == {"Prefix": INPUT_PREFIX}
        and rule.get("Expiration") == {"Days": retention_days}
        and rule.get("AbortIncompleteMultipartUpload")
        == {"DaysAfterInitiation": multipart_abort_days}
    )


def lifecycle_rule_matches_without_abort(
    rule: dict[str, Any],
    *,
    retention_days: int,
) -> bool:
    return (
        rule.get("ID") == RULE_ID
        and rule.get("Status") == "Enabled"
        and rule.get("Filter") == {"Prefix": INPUT_PREFIX}
        and rule.get("Expiration") == {"Days": retention_days}
        and "AbortIncompleteMultipartUpload" not in rule
    )


def configure_lifecycle(
    client: S3LifecycleClient,
    *,
    bucket: str,
    retention_days: int,
    multipart_abort_days: int,
) -> None:
    _ensure_bucket(client, bucket=bucket)
    merged_rules = merge_lifecycle_rules(
        _read_rules(client, bucket=bucket),
        retention_days=retention_days,
        multipart_abort_days=multipart_abort_days,
    )
    client.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={"Rules": merged_rules},
    )

    verified_rules = _read_rules(client, bucket=bucket)
    matching = [
        rule
        for rule in verified_rules
        if lifecycle_rule_matches(
            rule,
            retention_days=retention_days,
            multipart_abort_days=multipart_abort_days,
        )
    ]
    if len(matching) == 1:
        return

    compatible_without_abort = [
        rule
        for rule in verified_rules
        if lifecycle_rule_matches_without_abort(
            rule,
            retention_days=retention_days,
        )
    ]
    if len(compatible_without_abort) == 1:
        print(
            "Configured input lifecycle without multipart abort read-back: "
            f"bucket={bucket} prefix={INPUT_PREFIX} retention_days={retention_days}. "
            "Bundled MinIO omits AbortIncompleteMultipartUpload from "
            "GetBucketLifecycleConfiguration; rely on explicit MinIO stale multipart "
            "cleanup settings in Compose."
        )
        return

    raise RuntimeError(
        "Input lifecycle verification failed: expected exactly one enabled "
        f"{INPUT_PREFIX!r} rule with retention={retention_days}d and "
        f"multipart_abort={multipart_abort_days}d"
    )


def run(settings: LifecycleSettings | None = None) -> None:
    resolved = settings or LifecycleSettings.from_environment()
    client = boto3.client(
        "s3",
        endpoint_url=resolved.endpoint_url,
        region_name=resolved.region,
        aws_access_key_id=resolved.access_key_id,
        aws_secret_access_key=resolved.secret_access_key,
        config=Config(s3={"addressing_style": "path"}),
    )
    last_error: Exception | None = None
    for attempt in range(1, resolved.attempts + 1):
        try:
            configure_lifecycle(
                client,
                bucket=resolved.bucket,
                retention_days=resolved.retention_days,
                multipart_abort_days=resolved.multipart_abort_days,
            )
            print(
                "Configured input lifecycle: "
                f"bucket={resolved.bucket} prefix={INPUT_PREFIX} "
                f"retention_days={resolved.retention_days} "
                f"multipart_abort_days={resolved.multipart_abort_days}"
            )
            return
        except Exception as exc:
            last_error = exc
            if attempt >= resolved.attempts:
                break
            print(
                f"MinIO lifecycle attempt {attempt}/{resolved.attempts} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            time.sleep(resolved.retry_seconds)
    raise RuntimeError(
        f"Unable to configure MinIO input lifecycle after {resolved.attempts} attempts"
    ) from last_error


def _ensure_bucket(client: S3LifecycleClient, *, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
            raise
    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
            raise


def _read_rules(client: S3LifecycleClient, *, bucket: str) -> list[dict[str, Any]]:
    try:
        payload = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"NoSuchLifecycleConfiguration", "NoSuchConfiguration", "404"}:
            return []
        raise
    raw_rules = payload.get("Rules", [])
    if not isinstance(raw_rules, list):
        raise RuntimeError("S3 lifecycle response does not contain a rules list")
    return [dict(rule) for rule in raw_rules if isinstance(rule, dict)]


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _positive_int(raw: str, name: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _positive_float(raw: str, name: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


if __name__ == "__main__":
    run()