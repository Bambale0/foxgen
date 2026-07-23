from dataclasses import dataclass
from secrets import compare_digest

from fastapi import HTTPException

from foxgen.core.config import Settings


@dataclass(frozen=True, slots=True)
class SubmissionPrincipal:
    user_id: int


def authenticate_submission(
    *,
    settings: Settings,
    authorization: str | None,
    user_id_header: str | None,
) -> SubmissionPrincipal:
    if not settings.task_submission_enabled:
        raise HTTPException(status_code=503, detail="Task submission is disabled")

    configured_token = settings.internal_api_token
    if configured_token is None:
        raise HTTPException(status_code=503, detail="Task submission authentication is not configured")

    scheme, _, supplied_token = (authorization or "").partition(" ")
    expected_token = configured_token.get_secret_value()
    if scheme.lower() != "bearer" or not supplied_token or not compare_digest(
        supplied_token,
        expected_token,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid internal API credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_header or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-FoxGen-User-Id must be an integer") from exc
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="X-FoxGen-User-Id must be positive")

    return SubmissionPrincipal(user_id=user_id)


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
