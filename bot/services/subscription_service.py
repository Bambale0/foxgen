"""Required Telegram channel subscription helpers."""

import asyncio
import logging
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

REQUIRED_CHANNEL_USERNAME = "neuromix_prompt"
REQUIRED_CHANNEL_CHAT_ID = f"@{REQUIRED_CHANNEL_USERNAME}"
REQUIRED_CHANNEL_URL = f"https://t.me/{REQUIRED_CHANNEL_USERNAME}"
SUBSCRIPTION_CHECK_CALLBACK = "check_required_channel_subscription"
SUBSCRIPTION_CACHE_TTL_SECONDS = 15 * 60
SUBSCRIPTION_CHECK_TIMEOUT_SECONDS = 2.0

logger = logging.getLogger(__name__)

_positive_subscription_cache: dict[int, float] = {}


@dataclass(frozen=True)
class SubscriptionCheckResult:
    ok: bool
    status: str = ""
    error: str = ""


def should_block_for_subscription(result: "SubscriptionCheckResult | None") -> bool:
    """Block access only on explicit non-member states; soft-fail on check errors/unknowns."""
    if result is None:
        return False
    if result.ok:
        return False
    if result.error:
        return False
    return _normalize_status(result.status) in {"left", "kicked"}


def _normalize_status(status) -> str:
    value = getattr(status, "value", status)
    return str(value or "").lower()


def _is_member_status(member) -> bool:
    status = _normalize_status(getattr(member, "status", ""))
    if status in {"creator", "administrator", "member"}:
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False


def clear_required_subscription_cache(telegram_id: int | None = None) -> None:
    if telegram_id is None:
        _positive_subscription_cache.clear()
        return
    _positive_subscription_cache.pop(int(telegram_id), None)


async def check_required_channel_subscription(
    bot: Bot,
    telegram_id: int,
    *,
    use_cache: bool = True,
) -> SubscriptionCheckResult:
    """Return whether a user is subscribed to the required channel."""
    normalized_id = int(telegram_id)
    now = time.monotonic()
    cached_until = _positive_subscription_cache.get(normalized_id, 0)
    if use_cache and cached_until > now:
        return SubscriptionCheckResult(ok=True, status="cached")

    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(REQUIRED_CHANNEL_CHAT_ID, normalized_id),
            timeout=SUBSCRIPTION_CHECK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "Required channel subscription check timed out for user=%s",
            normalized_id,
        )
        return SubscriptionCheckResult(ok=False, error="timeout")
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        message = str(exc)
        logger.info(
            "Required channel subscription check failed for user=%s channel=%s: %s",
            normalized_id,
            REQUIRED_CHANNEL_CHAT_ID,
            message,
        )
        return SubscriptionCheckResult(ok=False, error=message)
    except Exception as exc:
        logger.exception(
            "Unexpected required channel subscription check error for user=%s",
            normalized_id,
        )
        return SubscriptionCheckResult(ok=False, error=str(exc))

    if _is_member_status(member):
        _positive_subscription_cache[normalized_id] = (
            now + SUBSCRIPTION_CACHE_TTL_SECONDS
        )
        return SubscriptionCheckResult(
            ok=True,
            status=_normalize_status(getattr(member, "status", "")),
        )

    clear_required_subscription_cache(normalized_id)
    return SubscriptionCheckResult(
        ok=False,
        status=_normalize_status(getattr(member, "status", "")),
    )
