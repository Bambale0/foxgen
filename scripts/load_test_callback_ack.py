"""Synthetic load test for HappyFox early Telegram callback acknowledgements.

No real Telegram requests are made. The harness runs the production middleware
against an in-memory Bot transport with configurable concurrency, latency, and
transient failures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from bot.services import callback_ack


@dataclass
class ScenarioMetrics:
    name: str
    requests: int
    concurrency: int
    network_calls: int
    failures_injected: int
    max_in_flight: int
    total_ms: float
    throughput_rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    pending_ack_tasks: int


@dataclass
class SyntheticTransport:
    network_delay_s: float
    fail_once_every: int = 0
    calls: int = 0
    failures_injected: int = 0
    in_flight: int = 0
    max_in_flight: int = 0
    attempts: dict[str, int] = field(default_factory=dict)

    async def request(self, _bot: Any, method: Any) -> bool:
        callback_id = str(getattr(method, "callback_query_id", "unknown"))
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.attempts[callback_id] = self.attempts.get(callback_id, 0) + 1
        try:
            await asyncio.sleep(self.network_delay_s)
            if (
                self.fail_once_every > 0
                and _numeric_suffix(callback_id) % self.fail_once_every == 0
                and self.attempts[callback_id] == 1
            ):
                self.failures_injected += 1
                raise TelegramBadRequest(
                    method=method,
                    message="synthetic transient callback ACK failure",
                )
            return True
        finally:
            self.in_flight -= 1


class FakeBot:
    id = 999_001

    def __init__(self, transport: SyntheticTransport) -> None:
        self.transport = transport

    async def __call__(self, method: Any) -> Any:
        return await callback_ack.early_callback_ack_session_middleware(
            self.transport.request,
            self,
            method,
        )


def _numeric_suffix(value: str) -> int:
    try:
        return int(value.rsplit("-", 1)[-1])
    except ValueError:
        return 0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[rank]


def _callback(bot: FakeBot, index: int) -> CallbackQuery:
    return CallbackQuery.model_validate(
        {
            "id": f"load-{index}",
            "from": {
                "id": 100_000 + index,
                "is_bot": False,
                "first_name": "Load",
            },
            "chat_instance": "synthetic-load",
            "data": "create_image_text_new",
        },
        context={"bot": bot},
    )


async def _legacy_request(
    callback: CallbackQuery,
    handler_delay_s: float,
) -> None:
    await asyncio.sleep(handler_delay_s)
    await callback.answer()


async def _optimized_request(
    middleware: callback_ack.EarlyCallbackAckMiddleware,
    callback: CallbackQuery,
    handler_delay_s: float,
) -> None:
    async def legacy_handler(event: CallbackQuery, _data: dict[str, Any]) -> None:
        await asyncio.sleep(handler_delay_s)
        await event.answer()

    await middleware(legacy_handler, callback, {})


async def _run_scenario(
    *,
    name: str,
    requests: int,
    concurrency: int,
    network_delay_s: float,
    handler_delay_s: float,
    optimized: bool,
    fail_once_every: int = 0,
) -> ScenarioMetrics:
    transport = SyntheticTransport(
        network_delay_s=network_delay_s,
        fail_once_every=fail_once_every,
    )
    bot = FakeBot(transport)
    middleware = callback_ack.EarlyCallbackAckMiddleware()
    semaphore = asyncio.Semaphore(concurrency)
    latencies_ms: list[float] = []

    async def worker(index: int) -> None:
        async with semaphore:
            callback = _callback(bot, index)
            started = time.perf_counter()
            if optimized:
                await _optimized_request(middleware, callback, handler_delay_s)
            else:
                await _legacy_request(callback, handler_delay_s)
            latencies_ms.append((time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    await asyncio.gather(*(worker(index) for index in range(1, requests + 1)))
    total_s = time.perf_counter() - started

    await asyncio.sleep(0)
    current = asyncio.current_task()
    pending_ack_tasks = sum(
        1
        for task in asyncio.all_tasks()
        if task is not current
        and not task.done()
        and task.get_name().startswith("early-callback-ack:")
    )

    return ScenarioMetrics(
        name=name,
        requests=requests,
        concurrency=concurrency,
        network_calls=transport.calls,
        failures_injected=transport.failures_injected,
        max_in_flight=transport.max_in_flight,
        total_ms=total_s * 1000,
        throughput_rps=requests / total_s if total_s else 0.0,
        p50_ms=_percentile(latencies_ms, 0.50),
        p95_ms=_percentile(latencies_ms, 0.95),
        p99_ms=_percentile(latencies_ms, 0.99),
        pending_ack_tasks=pending_ack_tasks,
    )


async def run_load_suite(
    *,
    requests: int = 500,
    concurrency: int = 100,
    network_delay_ms: float = 340.0,
    handler_delay_ms: float = 520.0,
    failure_every: int = 17,
) -> dict[str, Any]:
    legacy = await _run_scenario(
        name="legacy_sequential",
        requests=requests,
        concurrency=concurrency,
        network_delay_s=network_delay_ms / 1000,
        handler_delay_s=handler_delay_ms / 1000,
        optimized=False,
    )
    optimized = await _run_scenario(
        name="early_ack_overlap",
        requests=requests,
        concurrency=concurrency,
        network_delay_s=network_delay_ms / 1000,
        handler_delay_s=handler_delay_ms / 1000,
        optimized=True,
    )
    failure_storm = await _run_scenario(
        name="early_ack_with_transient_failures",
        requests=max(200, requests // 2),
        concurrency=concurrency,
        network_delay_s=network_delay_ms / 1000,
        handler_delay_s=handler_delay_ms / 1000,
        optimized=True,
        fail_once_every=failure_every,
    )

    improvement_pct = (
        (legacy.p95_ms - optimized.p95_ms) / legacy.p95_ms * 100
        if legacy.p95_ms
        else 0.0
    )

    return {
        "config": {
            "requests": requests,
            "concurrency": concurrency,
            "network_delay_ms": network_delay_ms,
            "handler_delay_ms": handler_delay_ms,
            "failure_every": failure_every,
        },
        "scenarios": [
            asdict(legacy),
            asdict(optimized),
            asdict(failure_storm),
        ],
        "p95_improvement_pct": improvement_pct,
    }


def validate_report(
    report: dict[str, Any],
    *,
    require_latency_slo: bool = True,
) -> list[str]:
    _legacy, optimized, failure_storm = report["scenarios"]
    errors: list[str] = []

    if optimized["network_calls"] != optimized["requests"]:
        errors.append(
            "optimized path made duplicate/missing network calls: "
            f"{optimized['network_calls']} for {optimized['requests']} requests"
        )
    if optimized["pending_ack_tasks"] != 0:
        errors.append(
            f"optimized path leaked {optimized['pending_ack_tasks']} ACK tasks"
        )
    if optimized["max_in_flight"] < min(10, optimized["concurrency"]):
        errors.append(
            "optimized path did not exercise meaningful concurrency: "
            f"max_in_flight={optimized['max_in_flight']}"
        )
    if require_latency_slo and report["p95_improvement_pct"] < 20.0:
        errors.append(
            "p95 latency improvement is below 20%: "
            f"{report['p95_improvement_pct']:.1f}%"
        )

    expected_failure_calls = (
        failure_storm["requests"] + failure_storm["failures_injected"]
    )
    if failure_storm["network_calls"] != expected_failure_calls:
        errors.append(
            "failure-retry path call count mismatch: "
            f"{failure_storm['network_calls']} != {expected_failure_calls}"
        )
    if failure_storm["pending_ack_tasks"] != 0:
        errors.append(
            "failure-retry path leaked "
            f"{failure_storm['pending_ack_tasks']} ACK tasks"
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--network-delay-ms", type=float, default=340.0)
    parser.add_argument("--handler-delay-ms", type=float, default=520.0)
    parser.add_argument("--failure-every", type=int, default=17)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = asyncio.run(
        run_load_suite(
            requests=args.requests,
            concurrency=args.concurrency,
            network_delay_ms=args.network_delay_ms,
            handler_delay_ms=args.handler_delay_ms,
            failure_every=args.failure_every,
        )
    )
    errors = validate_report(report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Callback ACK synthetic load test")
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if not args.json:
        print("PASS: load-test invariants and latency SLO satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
