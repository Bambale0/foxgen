"""Helpers for protecting credit balance from duplicate payment callbacks."""

from __future__ import annotations

import hashlib


def payment_event_key(provider: str, external_payment_id: str) -> str:
    raw = f"{provider}:{external_payment_id}".encode()
    return hashlib.sha256(raw).hexdigest()


def already_processed(existing_key: str | None, incoming_key: str) -> bool:
    return bool(existing_key and existing_key == incoming_key)
