"""Seedance 2.5 video-reference retail pricing compatibility.

The product rule is simple and server-authoritative: when a Seedance generation
contains at least one video reference, charge the configured base price once at
x2. Multiple video references do not stack the multiplier.
"""

from __future__ import annotations

from functools import wraps

from bot.video_reference_policy import apply_video_reference_cost

from . import seedance_25_preview as preview_module

MODEL_KEY = "seedance_2_5"
_installed = False


def install_seedance_25_video_ref_pricing() -> None:
    """Wrap the shared Seedance 2.5 quote used by Telegram and Mini App."""
    global _installed
    if _installed:
        return

    original = preview_module._price_quote

    @wraps(original)
    def priced(data: dict) -> float:
        base_cost = float(original(data))
        return float(
            apply_video_reference_cost(
                MODEL_KEY,
                base_cost,
                data.get("v_reference_videos") or [],
            )
        )

    preview_module._price_quote = priced
    _installed = True
