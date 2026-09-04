from __future__ import annotations

from bot import happyfox_video_ui, keyboards

EXPECTED_CALLBACK = "v_model_seedance_2_5"
VIDEO_TYPES = ("text", "imgtxt", "video")


def _callbacks(markup) -> list[str]:
    return [
        str(button.callback_data or "")
        for row in markup.inline_keyboard
        for button in row
    ]


def main() -> int:
    # Keep this production smoke deterministic and independent of mutable prices.
    happyfox_video_ui.preset_manager.get_video_cost_per_second = (
        lambda *args, **kwargs: 1
    )
    happyfox_video_ui.preset_manager.get_video_cost_with_quality = (
        lambda *args, **kwargs: 5
    )
    happyfox_video_ui.preset_manager.get_video_cost = lambda *args, **kwargs: 5

    for video_type in VIDEO_TYPES:
        markup = keyboards.get_create_video_keyboard(current_v_type=video_type)
        callbacks = _callbacks(markup)
        model_callbacks = [value for value in callbacks if value.startswith("v_model_")]
        if not model_callbacks or model_callbacks[0] != EXPECTED_CALLBACK:
            raise SystemExit(
                "HappyFox Telegram Seedance 2.5 selector smoke failed: "
                f"type={video_type} models={model_callbacks}"
            )

    print("TELEGRAM_SEEDANCE25_MENU_OK text,imgtxt,video")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
