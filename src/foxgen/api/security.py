from dataclasses import dataclass
from secrets import compare_digest

from fastapi import HTTPException

from foxgen.core.config import Settings


@dataclass(frozen=True, slots=True)
class SubmissionPrincipal:
    user_id: int


def _authenticate_bearer(
    *,
    authorization: str | None,
    expected_token: str,
    error_detail: str,
) -> None:
    scheme, _, supplied_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied_token or not compare_digest(
        supplied_token,
        expected_token,
    ):
        raise HTTPException(
            status_code=401,
            detail=error_detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


def authenticate_internal_service(
    *,
    settings: Settings,
    authorization: str | None,
) -> None:
    configured_token = settings.internal_api_token
    if configured_token is None:
        raise HTTPException(status_code=503, detail="Internal service authentication is not configured")
    _authenticate_bearer(
        authorization=authorization,
        expected_token=configured_token.get_secret_value(),
        error_detail="Invalid internal API credentials",
    )


def authenticate_submission(
    *,
    settings: Settings,
    authorization: str | None,
    user_id_header: str | None,
) -> SubmissionPrincipal:
    if not settings.task_submission_enabled:
        raise HTTPException(status_code=503, detail="Task submission is disabled")

    authenticate_internal_service(
        settings=settings,
        authorization=authorization,
    )

    try:
        user_id = int(user_id_header or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-FoxGen-User-Id must be an integer") from exc
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="X-FoxGen-User-Id must be positive")

    return SubmissionPrincipal(user_id=user_id)


def authenticate_billing_admin(
    *,
    settings: Settings,
    authorization: str | None,
) -> None:
    if not settings.billing_admin_api_enabled:
        raise HTTPException(status_code=503, detail="Billing administration is disabled")
    configured_token = settings.billing_admin_api_token
    if configured_token is None:
        raise HTTPException(status_code=503, detail="Billing administration is not configured")
    _authenticate_bearer(
        authorization=authorization,
        expected_token=configured_token.get_secret_value(),
        error_detail="Invalid billing administrator credentials",
    )


def validate_idempotency_key(value: str | None) -> str:
    key = (value or "").strip()
    if not 8 <= len(key) <= 128:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must contain between 8 and 128 characters",
        )
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")
    if any(character not in allowed for character in key):
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key contains unsupported characters",
        )
    return key
