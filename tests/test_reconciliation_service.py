from uuid import UUID

import pytest

from foxgen.application.reconciliation import (
    DeliveryResolutionAction,
    ReconciliationFinding,
    ReconciliationService,
)
from foxgen.core.errors import ErrorCode, SubmissionError


GENERATION_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


class FakeReconciliationRepository:
    def __init__(self) -> None:
        self.findings = (
            ReconciliationFinding(
                code="delivery_unknown",
                severity="critical",
                generation_id=GENERATION_ID,
                resource_id=None,
                status="delivery_unknown",
                details={},
            ),
        )
        self.actions: list[tuple[str, object]] = []

    async def list_reconciliation_findings(
        self,
        *,
        limit: int,
    ) -> tuple[ReconciliationFinding, ...]:
        assert limit == 100
        return self.findings

    async def apply_safe_reconciliation(self, *, limit: int) -> tuple[str, ...]:
        assert limit == 100
        self.actions.append(("safe", limit))
        return ("settle_reservation:test",)

    async def resolve_delivery_unknown_sent(
        self,
        *,
        generation_id: UUID,
        message_ids: list[int],
        reason: str,
    ) -> None:
        assert generation_id == GENERATION_ID
        self.actions.append(("sent", (message_ids, reason)))

    async def requeue_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        idempotency_key: str,
        reason: str,
    ) -> None:
        assert generation_id == GENERATION_ID
        self.actions.append(("retry", (idempotency_key, reason)))

    async def fail_delivery_unknown(
        self,
        *,
        generation_id: UUID,
        reason: str,
    ) -> None:
        assert generation_id == GENERATION_ID
        self.actions.append(("failed", reason))


@pytest.mark.asyncio
async def test_safe_run_reports_remaining_findings_after_fixes() -> None:
    repository = FakeReconciliationRepository()
    service = ReconciliationService(repository)

    result = await service.run_safe(limit=100)

    assert result.fixed_codes == ("settle_reservation:test",)
    assert result.findings == repository.findings
    assert repository.actions == [("safe", 100)]


@pytest.mark.asyncio
async def test_delivery_retry_requires_explicit_not_sent_confirmation() -> None:
    service = ReconciliationService(FakeReconciliationRepository())

    with pytest.raises(SubmissionError) as captured:
        await service.resolve_delivery_unknown(
            generation_id=GENERATION_ID,
            action=DeliveryResolutionAction.RETRY,
            message_ids=None,
            confirmed_not_sent=False,
            idempotency_key="retry-key-123",
            reason="Telegram history checked",
        )

    assert captured.value.code == ErrorCode.VALIDATION


@pytest.mark.asyncio
async def test_mark_sent_requires_verified_message_ids() -> None:
    service = ReconciliationService(FakeReconciliationRepository())

    with pytest.raises(SubmissionError):
        await service.resolve_delivery_unknown(
            generation_id=GENERATION_ID,
            action=DeliveryResolutionAction.MARK_SENT,
            message_ids=[],
            confirmed_not_sent=False,
            idempotency_key=None,
            reason="Telegram history checked",
        )


@pytest.mark.asyncio
async def test_confirmed_retry_uses_operator_idempotency_key() -> None:
    repository = FakeReconciliationRepository()
    service = ReconciliationService(repository)

    await service.resolve_delivery_unknown(
        generation_id=GENERATION_ID,
        action=DeliveryResolutionAction.RETRY,
        message_ids=None,
        confirmed_not_sent=True,
        idempotency_key="retry-key-123",
        reason="Telegram history confirms no message",
    )

    assert repository.actions == [
        (
            "retry",
            ("retry-key-123", "Telegram history confirms no message"),
        )
    ]
