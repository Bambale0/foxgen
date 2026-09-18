"""Shared mutable payment/partner policy, published by the audited tariffs API."""

from __future__ import annotations

import json
import math
from pathlib import Path
from string import Formatter
from bot.services.preset_manager import preset_manager

DEFAULT_RULES = json.loads(
    Path(__file__).with_name("business_rules_defaults.json").read_text()
)


def validate_business_rules(raw):
    if not isinstance(raw, dict) or set(raw) != set(DEFAULT_RULES):
        raise ValueError("business_rules must contain the documented policy fields")
    for key in (
        "level1_percent",
        "level2_percent",
        "new_user_bonus_credits",
        "inviter_bonus_credits",
        "rub_per_credit",
        "notification_max_attempts",
        "notification_retry_base_seconds",
        "notification_retry_max_seconds",
        "notification_poll_seconds",
    ):
        value = raw[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(
                f"business_rules.{key} must be a finite non-negative number"
            )
        if key.startswith("notification_") or key == "rub_per_credit":
            if value <= 0:
                raise ValueError(f"business_rules.{key} must be positive")
    if raw["level1_percent"] + raw["level2_percent"] > 100:
        raise ValueError("Total referral commission must not exceed 100%")
    if (
        int(raw["notification_max_attempts"]) != raw["notification_max_attempts"]
        or raw["notification_max_attempts"] > 100
    ):
        raise ValueError("notification_max_attempts must be an integer <= 100")
    if raw["notification_retry_base_seconds"] > raw["notification_retry_max_seconds"]:
        raise ValueError("notification retry base must not exceed its limit")
    if raw["notification_poll_seconds"] < 1:
        raise ValueError("notification poll interval must be at least one second")
    bonuses = raw["promo_bonus_by_credits"]
    if not isinstance(bonuses, dict):
        raise ValueError("promo_bonus_by_credits must be a map")
    for credits, bonus in bonuses.items():
        if (
            not str(credits).isdigit()
            or int(credits) <= 0
            or isinstance(bonus, bool)
            or not isinstance(bonus, int)
            or bonus < 0
        ):
            raise ValueError(
                "promo bonus map requires positive package credits and non-negative integer bonuses"
            )
    for key, fields in [
        ("buyer_notification_template", {"credits", "amount_rub"}),
        ("referrer_notification_template", {"level", "reward", "unit"}),
    ]:
        value = raw[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError(f"{key} must be a non-empty template <= 2000 characters")
        for _, field, spec, conversion in Formatter().parse(value):
            if field is not None and (field not in fields or spec or conversion):
                raise ValueError(f"Unsupported placeholder in {key}")
    return dict(raw)


def get_business_rules():
    return validate_business_rules(
        preset_manager.get_price_config().get("business_rules", DEFAULT_RULES)
    )


def promo_bonus_map():
    return {
        int(k): v for k, v in get_business_rules()["promo_bonus_by_credits"].items()
    }


def buyer_message(credits, amount_rub):
    return get_business_rules()["buyer_notification_template"].format(
        credits=f"{credits:g}", amount_rub=f"{amount_rub:g}"
    )


def referrer_message(level, reward, unit):
    return get_business_rules()["referrer_notification_template"].format(
        level=level, reward=f"{reward:g}", unit=unit
    )
