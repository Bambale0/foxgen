from types import MappingProxyType
from typing import Mapping

from foxgen.domain.models import GenerationStatus


_ALLOWED: dict[GenerationStatus, frozenset[GenerationStatus]] = {
    GenerationStatus.DRAFT: frozenset(
        {GenerationStatus.QUEUED, GenerationStatus.CANCELLED}
    ),
    GenerationStatus.QUEUED: frozenset(
        {
            GenerationStatus.SUBMITTING,
            GenerationStatus.CANCELLED,
            GenerationStatus.FAILED,
        }
    ),
    GenerationStatus.SUBMITTING: frozenset(
        {
            GenerationStatus.SUBMITTED,
            GenerationStatus.SUBMISSION_UNKNOWN,
            GenerationStatus.FAILED,
        }
    ),
    GenerationStatus.SUBMISSION_UNKNOWN: frozenset(
        {
            GenerationStatus.SUBMITTED,
            GenerationStatus.PROCESSING,
            GenerationStatus.RESULT_READY,
            GenerationStatus.FAILED,
        }
    ),
    GenerationStatus.SUBMITTED: frozenset(
        {
            GenerationStatus.PROCESSING,
            GenerationStatus.RESULT_READY,
            GenerationStatus.FAILED,
        }
    ),
    GenerationStatus.PROCESSING: frozenset(
        {
            GenerationStatus.PROCESSING,
            GenerationStatus.RESULT_READY,
            GenerationStatus.FAILED,
        }
    ),
    GenerationStatus.RESULT_READY: frozenset(
        {GenerationStatus.STORING_MEDIA, GenerationStatus.FAILED}
    ),
    GenerationStatus.STORING_MEDIA: frozenset(
        {GenerationStatus.DELIVERY_PENDING, GenerationStatus.FAILED}
    ),
    GenerationStatus.DELIVERY_PENDING: frozenset(
        {GenerationStatus.SUCCEEDED, GenerationStatus.FAILED}
    ),
    GenerationStatus.SUCCEEDED: frozenset(),
    GenerationStatus.FAILED: frozenset(),
    GenerationStatus.CANCELLED: frozenset(),
}

ALLOWED_GENERATION_TRANSITIONS: Mapping[
    GenerationStatus, frozenset[GenerationStatus]
] = MappingProxyType(_ALLOWED)


def can_transition(source: GenerationStatus, target: GenerationStatus) -> bool:
    return target in ALLOWED_GENERATION_TRANSITIONS[source]


def require_transition(source: GenerationStatus, target: GenerationStatus) -> None:
    if not can_transition(source, target):
        raise ValueError(f"Invalid generation transition: {source.value} -> {target.value}")


def failure_stage_for(status: GenerationStatus) -> str:
    if status in {
        GenerationStatus.DRAFT,
        GenerationStatus.QUEUED,
        GenerationStatus.SUBMITTING,
        GenerationStatus.SUBMISSION_UNKNOWN,
    }:
        return "submission"
    if status in {GenerationStatus.SUBMITTED, GenerationStatus.PROCESSING}:
        return "provider"
    if status in {GenerationStatus.RESULT_READY, GenerationStatus.STORING_MEDIA}:
        return "storage"
    if status == GenerationStatus.DELIVERY_PENDING:
        return "delivery"
    return "unknown"
