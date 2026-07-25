import pytest

from foxgen.domain.lifecycle import (
    ALLOWED_GENERATION_TRANSITIONS,
    can_transition,
    failure_stage_for,
    require_transition,
)
from foxgen.domain.models import ACTIVE_GENERATION_STATUSES, GenerationStatus


def test_every_generation_status_has_an_explicit_transition_set() -> None:
    assert set(ALLOWED_GENERATION_TRANSITIONS) == set(GenerationStatus)


def test_provider_and_postprocessing_stages_are_active() -> None:
    assert {
        GenerationStatus.PROCESSING,
        GenerationStatus.RESULT_READY,
        GenerationStatus.STORING_MEDIA,
        GenerationStatus.DELIVERY_PENDING,
    } <= ACTIVE_GENERATION_STATUSES


def test_result_must_be_stored_and_delivered_before_success() -> None:
    assert can_transition(GenerationStatus.RESULT_READY, GenerationStatus.STORING_MEDIA)
    assert can_transition(
        GenerationStatus.STORING_MEDIA,
        GenerationStatus.DELIVERY_PENDING,
    )
    assert can_transition(
        GenerationStatus.DELIVERY_PENDING,
        GenerationStatus.SUCCEEDED,
    )
    assert not can_transition(GenerationStatus.RESULT_READY, GenerationStatus.SUCCEEDED)
    assert not can_transition(GenerationStatus.PROCESSING, GenerationStatus.SUCCEEDED)


def test_submission_unknown_can_only_be_resolved_from_provider_evidence() -> None:
    assert can_transition(
        GenerationStatus.SUBMISSION_UNKNOWN,
        GenerationStatus.PROCESSING,
    )
    assert can_transition(
        GenerationStatus.SUBMISSION_UNKNOWN,
        GenerationStatus.RESULT_READY,
    )
    assert not can_transition(
        GenerationStatus.SUBMISSION_UNKNOWN,
        GenerationStatus.SUBMITTING,
    )


def test_terminal_states_cannot_transition() -> None:
    for terminal in {
        GenerationStatus.SUCCEEDED,
        GenerationStatus.FAILED,
        GenerationStatus.CANCELLED,
    }:
        assert ALLOWED_GENERATION_TRANSITIONS[terminal] == frozenset()
        with pytest.raises(ValueError):
            require_transition(terminal, GenerationStatus.QUEUED)


def test_failure_stage_is_derived_from_current_stage() -> None:
    assert failure_stage_for(GenerationStatus.SUBMITTING) == "submission"
    assert failure_stage_for(GenerationStatus.PROCESSING) == "provider"
    assert failure_stage_for(GenerationStatus.STORING_MEDIA) == "storage"
    assert failure_stage_for(GenerationStatus.DELIVERY_PENDING) == "delivery"
