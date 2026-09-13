import asyncio

import pytest

from scripts.load_test_callback_ack import run_load_suite, validate_report


@pytest.mark.load
def test_callback_ack_load_suite() -> None:
    report = asyncio.run(
        run_load_suite(
            requests=600,
            concurrency=120,
            network_delay_ms=20.0,
            handler_delay_ms=12.0,
            failure_every=19,
        )
    )

    assert validate_report(report, require_latency_slo=False) == []

    _legacy, optimized, failure_storm = report["scenarios"]
    assert optimized["network_calls"] == optimized["requests"]
    assert optimized["pending_ack_tasks"] == 0
    assert failure_storm["failures_injected"] > 0
    assert failure_storm["pending_ack_tasks"] == 0
