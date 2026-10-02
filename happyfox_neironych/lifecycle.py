"""Retry-safe operation state stored by each channel in its existing task row.

This module does not debit, refund, create users, or own a second task database.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol

from .client import Client, Outcome, ProviderError
from .contracts import PreparedRequest, media_url

logger = logging.getLogger(__name__)


class Journal(Protocol):
    async def load(self) -> str: ...
    async def replace(self, expected: str, value: str) -> bool: ...


def encoded(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def new_operation(request: PreparedRequest) -> dict[str, Any]:
    return {"version": 1, "request": request.to_dict(), "phase": "prepared",
            "lease_until": 0, "next_at": 0, "attempt": 0, "external_id": ""}


class Artifacts:
    """Persist provider bytes before publishing a URL or completing a task."""
    def __init__(self, root: Path, public_base: str | None = None):
        self.root = Path(root)
        self.public_base = public_base.rstrip("/") if public_base else None
        if self.public_base:
            media_url(self.public_base)

    def _asset(self, name: str) -> dict[str, str]:
        if Path(name).name != name or not name:
            raise ValueError("Invalid artifact name")
        asset = {"file": name}
        if self.public_base:
            asset["url"] = self.public_base + "/" + name
        return asset

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".native-", delete=False) as out:
                temporary = out.name
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)

    async def synchronous(self, request: PreparedRequest, outcome: Outcome) -> dict[str, Any]:
        if request.model.kind == "text":
            return {"text": outcome.text, "assets": []}
        prefix = hashlib.sha256(request.key.encode()).hexdigest()
        assets = []
        for index, image in enumerate(outcome.images):
            name = f"{prefix}-{index}.{image.extension}"
            await asyncio.to_thread(self._write, self.root / name, image.data)
            assets.append({**self._asset(name), "content_type": image.content_type})
        return {"assets": assets}

    async def video(self, client: Client, request: PreparedRequest, external_id: str) -> dict[str, Any]:
        name = hashlib.sha256(request.key.encode()).hexdigest() + ".mp4"
        await client.download_video(external_id, self.root / name)
        return {"assets": [{**self._asset(name), "content_type": "video/mp4"}]}


async def advance(journal: Journal, client: Client, artifacts: Artifacts, *, now: float | None = None) -> dict[str, Any]:
    """Perform one bounded step. Only phase=failed permits a terminal refund.

    An expired sending lease is replayable for video only: the provider returns
    the same request ID. Synchronous requests become held for reconciliation.
    Leases and compare-and-swap prevent competing workers from submitting twice.
    """
    timestamp = time.time() if now is None else now
    raw = await journal.load()
    operation = json.loads(raw)
    if operation.get("version") != 1:
        raise ValueError("Unknown operation journal version")
    phase = operation["phase"]
    if phase in {"ready", "failed", "held"} or operation.get("lease_until", 0) > timestamp or operation.get("next_at", 0) > timestamp:
        return operation
    request = PreparedRequest.from_dict(operation["request"])
    if not client.settings.ready:
        return operation
    claimed = {**operation, "lease_until": timestamp + client.settings.timeout * 3 + 30,
               "attempt": operation.get("attempt", 0) + 1}
    claimed_raw = encoded(claimed)
    if not await journal.replace(raw, claimed_raw):
        return json.loads(await journal.load())
    operation = claimed
    raw = claimed_raw

    async def save(**changes: Any) -> bool:
        nonlocal raw, operation
        updated = {**operation, **changes}
        updated_raw = encoded(updated)
        if not await journal.replace(raw, updated_raw):
            return False
        operation, raw = updated, updated_raw
        return True

    try:
        if phase == "sending" and request.model.kind != "video":
            await save(phase="held", error="submission_outcome_unknown", lease_until=0)
            return operation
        if phase in {"prepared", "sending"}:
            # This durable checkpoint precedes the external side effect.
            if not await save(phase="sending"):
                return json.loads(await journal.load())
            outcome = await client.submit(request)
            if request.model.kind == "video":
                await save(phase="waiting", external_id=outcome.request_id,
                           lease_until=0, next_at=timestamp + client.settings.poll_interval)
            else:
                result = await artifacts.synchronous(request, outcome)
                await save(phase="ready", external_id=outcome.request_id,
                           lease_until=0, next_at=0, **result)
        elif phase == "waiting":
            status = await client.video_status(operation["external_id"])
            if status.status in {"failed", "expired"}:
                await save(phase="failed", error="provider_" + status.status, lease_until=0)
            elif status.status == "done":
                result = await artifacts.video(client, request, status.request_id)
                await save(phase="ready", lease_until=0, next_at=0,
                           billed_seconds=status.billed_seconds, **result)
            else:
                await save(lease_until=0, next_at=timestamp + client.settings.poll_interval)
        else:
            await save(phase="held", error="invalid_journal_phase", lease_until=0)
    except ProviderError as exc:
        if operation["phase"] == "waiting":
            # Poll/download failure is not proof the generation failed.
            target = "waiting"
        elif exc.uncertain:
            target = "sending" if request.model.kind == "video" else "held"
        else:
            target = "failed"
        await save(phase=target, error=exc.code, provider_request_id=exc.request_id,
                   lease_until=0, next_at=timestamp + max(client.settings.poll_interval, exc.retry_after))
    except (OSError, ValueError, TypeError):
        # Bytes may already have been paid for. Never turn persistence/parsing
        # failures into another generation or an automatic free retry.
        target = "waiting" if operation["phase"] == "waiting" else "held"
        await save(phase=target, error="result_persistence_or_journal_error", lease_until=0,
                   next_at=timestamp + client.settings.poll_interval)
    finally:
        logger.info("neironych_operation correlation=%s model=%s phase=%s attempt=%s request_id=%s error=%s",
                    hashlib.sha256(request.key.encode()).hexdigest()[:16], request.model.id,
                    operation.get("phase"), operation.get("attempt"), operation.get("external_id", ""),
                    operation.get("error", ""))
    return operation
