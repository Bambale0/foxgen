from bot.handlers.video_generation_compat import (
    PUBLIC_VIDEO_MODEL_GROUPS,
    _advanced_video_models_keyboard,
)
from bot.max_catalog import MAX_VIDEO_TYPES


def test_seedance25_is_exposed_in_telegram_and_max_video_menus() -> None:
    telegram_models = {
        model_key
        for _group_name, model_keys in PUBLIC_VIDEO_MODEL_GROUPS
        for model_key in model_keys
    }
    assert "seedance_2_5" in telegram_models

    telegram_callbacks = {
        button.callback_data
        for row in _advanced_video_models_keyboard().inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "advanced_v_model_seedance_2_5" in telegram_callbacks

    assert "seedance_2_5" in MAX_VIDEO_TYPES["text"]
    assert "seedance_2_5" in MAX_VIDEO_TYPES["imgtxt"]
    assert "seedance_2_5" in MAX_VIDEO_TYPES["video"]
