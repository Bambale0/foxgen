"""Self-healing Telegram webhook registration guard for HappyFox."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from aiogram import Bot

logger = logging.getLogger("bot.telemetry.telegram")


@dataclass(frozen=True)
class WebhookGuardCheck:
    drift_reasons: tuple[str, ...]
    remaining_drift_reasons: tuple[str, ...]
    pending_update_count: int
    silence_detected: bool
    repaired: bool
    last_error_message: str

    @property
    def incident_key(self) -> str | None:
        parts: list[str] = []
        if self.drift_reasons:
            parts.append("drift:" + ",".join(self.drift_reasons))
        if self.silence_detected:
            parts.append("silence")
        return "|".join(parts) or None


def _normalise_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _normalise_updates(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    result: set[str] = set()
    for value in values:
        raw = getattr(value, "value", value)
        text = str(raw or "").strip()
        if text:
            result.add(text)
    return tuple(sorted(result))


def webhook_drift_reasons(
    info: Any,
    *,
    expected_url: str,
    expected_ip: str,
    expected_allowed_updates: Sequence[str],
) -> tuple[str, ...]:
    """Return only registration-contract drift, not historical delivery errors."""
    reasons: list[str] = []
    if _normalise_url(getattr(info, "url", "")) != _normalise_url(expected_url):
        reasons.append("url")

    expected_ip = str(expected_ip or "").strip()
    if expected_ip and str(getattr(info, "ip_address", "") or "").strip() != expected_ip:
        reasons.append("ip_address")

    expected_updates = _normalise_updates(expected_allowed_updates)
    actual_updates = _normalise_updates(getattr(info, "allowed_updates", None))
    if actual_updates != expected_updates:
        reasons.append("allowed_updates")

    return tuple(reasons)


async def _notify_admins(bot: Bot, admin_ids: Sequence[int], text: str) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=int(admin_id), text=text)
        except Exception:
            logger.exception(
                "telegram_webhook_guard_admin_alert_failed admin_id=%s",
                admin_id,
            )


async def inspect_and_reconcile_telegram_webhook(
    bot: Bot,
    *,
    expected_url: str,
    expected_ip: str,
    secret: str,
    expected_allowed_updates: Sequence[str],
    silence_seconds: int,
    last_update_age_seconds: float | None,
) -> WebhookGuardCheck:
    """Inspect one live registration and repair only deterministic drift."""
    info = await bot.get_webhook_info()
    reasons = webhook_drift_reasons(
        info,
        expected_url=expected_url,
        expected_ip=expected_ip,
        expected_allowed_updates=expected_allowed_updates,
    )
    pending = int(getattr(info, "pending_update_count", 0) or 0)
    silence_detected = bool(
        pending > 0
        and (
            last_update_age_seconds is None
            or last_update_age_seconds >= float(silence_seconds)
        )
    )
    last_error = str(getattr(info, "last_error_message", "") or "")

    repaired = False
    remaining = reasons
    if reasons:
        logger.warning(
            "telegram_webhook_drift reasons=%s expected_url=%s actual_url=%s "
            "expected_ip=%s actual_ip=%s expected_updates=%s actual_updates=%s "
            "pending=%s last_error=%s",
            ",".join(reasons),
            _normalise_url(expected_url),
            _normalise_url(getattr(info, "url", "")),
            str(expected_ip or "").strip() or "-",
            str(getattr(info, "ip_address", "") or "").strip() or "-",
            ",".join(_normalise_updates(expected_allowed_updates)) or "-",
            ",".join(_normalise_updates(getattr(info, "allowed_updates", None))) or "-",
            pending,
            last_error or "-",
        )
        kwargs: dict[str, object] = {
            "url": expected_url,
            "drop_pending_updates": False,
            "allowed_updates": list(expected_allowed_updates),
        }
        if secret:
            kwargs["secret_token"] = secret
        if expected_ip:
            kwargs["ip_address"] = expected_ip

        await bot.set_webhook(**kwargs)
        verified = await bot.get_webhook_info()
        remaining = webhook_drift_reasons(
            verified,
            expected_url=expected_url,
            expected_ip=expected_ip,
            expected_allowed_updates=expected_allowed_updates,
        )
        repaired = not remaining
        logger.info(
            "telegram_webhook_reconcile outcome=%s reasons=%s pending=%s",
            "repaired" if repaired else "still_drifted",
            ",".join(reasons),
            int(getattr(verified, "pending_update_count", 0) or 0),
        )

    if silence_detected:
        age_text = (
            "unknown"
            if last_update_age_seconds is None
            else f"{last_update_age_seconds:.1f}"
        )
        logger.warning(
            "telegram_webhook_silence pending=%s last_update_age_s=%s threshold_s=%s "
            "last_error=%s",
            pending,
            age_text,
            silence_seconds,
            last_error or "-",
        )

    return WebhookGuardCheck(
        drift_reasons=reasons,
        remaining_drift_reasons=remaining,
        pending_update_count=pending,
        silence_detected=silence_detected,
        repaired=repaired,
        last_error_message=last_error,
    )


async def webhook_guard_loop(
    bot: Bot,
    *,
    interval: int,
    expected_url: str,
    expected_ip: str,
    secret: str,
    expected_allowed_updates: Sequence[str],
    admin_ids: Sequence[int],
    silence_seconds: int,
    last_update_age: Callable[[], float | None],
) -> None:
    """Continuously reconcile registration drift and surface delivery silence."""
    if interval <= 0:
        raise ValueError("Telegram webhook guard interval must be positive")
    if silence_seconds <= 0:
        raise ValueError("Telegram webhook silence threshold must be positive")

    last_alert_key: str | None = None
    while True:
        try:
            check = await inspect_and_reconcile_telegram_webhook(
                bot,
                expected_url=expected_url,
                expected_ip=expected_ip,
                secret=secret,
                expected_allowed_updates=expected_allowed_updates,
                silence_seconds=silence_seconds,
                last_update_age_seconds=last_update_age(),
            )
            incident_key = check.incident_key
            if incident_key and incident_key != last_alert_key:
                details: list[str] = []
                if check.drift_reasons:
                    if check.repaired:
                        details.append(
                            "регистрация webhook была изменена и автоматически восстановлена"
                        )
                    else:
                        details.append(
                            "регистрация webhook отличается от ожидаемой и не восстановилась"
                        )
                if check.silence_detected:
                    details.append(
                        f"в очереди Telegram {check.pending_update_count} update(ов), "
                        "но входящих апдейтов в HappyFox давно не наблюдалось"
                    )
                await _notify_admins(
                    bot,
                    admin_ids,
                    "⚠️ HappyFox Telegram: " + "; ".join(details),
                )
            last_alert_key = incident_key
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telegram_webhook_guard_failed")

        await asyncio.sleep(interval)
