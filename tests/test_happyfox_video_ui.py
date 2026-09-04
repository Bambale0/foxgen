from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.happyfox_video_ui import (
    VIDEO_TYPE_ROWS,
    compatible_video_model,
    compose_happyfox_video_keyboard,
)


def _callbacks(markup: InlineKeyboardMarkup) -> list[str]:
    return [
        str(button.callback_data or "")
        for row in markup.inline_keyboard
        for button in row
    ]


def _texts(markup: InlineKeyboardMarkup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def _base_settings_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Сменить модель", callback_data="video_change_model"
                ),
                InlineKeyboardButton(
                    text="🎞 Тип и медиа", callback_data="video_change_media"
                ),
            ],
            [
                InlineKeyboardButton(text="✅ 16∶9", callback_data="ratio_16_9"),
                InlineKeyboardButton(text="9∶16", callback_data="ratio_9_16"),
            ],
            [
                InlineKeyboardButton(text="Цена: 12🍌/с", callback_data="ignore"),
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"),
            ],
        ]
    )


def test_dynamic_keyboard_keeps_type_model_and_settings_on_one_screen(monkeypatch) -> None:
    from bot import happyfox_video_ui

    monkeypatch.setattr(
        happyfox_video_ui.preset_manager,
        "get_video_cost_per_second",
        lambda *args, **kwargs: 12,
    )

    markup = compose_happyfox_video_keyboard(
        _base_settings_markup(),
        current_v_type="text",
        current_model="v3_pro",
    )

    callbacks = _callbacks(markup)
    texts = _texts(markup)

    assert callbacks[:3] == ["v_type_text", "v_type_imgtxt", "v_type_video"]
    assert "v_model_v3_pro" in callbacks
    assert "v_model_grok_imagine" not in callbacks
    assert "ratio_16_9" in callbacks
    assert "video_change_model" not in callbacks
    assert "video_change_media" not in callbacks
    assert any(text.startswith("✅ 💎 Kling 3.0") for text in texts)
    assert "Цена: 12🐾/с" in texts
    assert all("🍌" not in text for text in texts)


def test_seedance_25_is_primary_in_every_happyfox_video_type(monkeypatch) -> None:
    from bot import happyfox_video_ui

    price_calls: list[tuple[str, int, str | None]] = []

    def fake_per_second(model: str, duration: int, quality: str | None = None) -> int:
        price_calls.append((model, duration, quality))
        return 4

    monkeypatch.setattr(
        happyfox_video_ui.preset_manager,
        "get_video_cost_per_second",
        fake_per_second,
    )
    monkeypatch.setattr(
        happyfox_video_ui.preset_manager,
        "get_video_cost_with_quality",
        lambda *args, **kwargs: 30,
    )

    for v_type in ("text", "imgtxt", "video"):
        markup = compose_happyfox_video_keyboard(
            _base_settings_markup(),
            current_v_type=v_type,
            current_model="v3_pro",
        )
        callbacks = _callbacks(markup)
        model_callbacks = [value for value in callbacks if value.startswith("v_model_")]

        assert VIDEO_TYPE_ROWS[v_type][0] == "seedance_2_5"
        assert model_callbacks[0] == "v_model_seedance_2_5"
        assert any("Seedance 2.5" in text for text in _texts(markup))

    assert ("seedance_2_5", 5, "720p") in price_calls


def test_models_redraw_for_image_to_video(monkeypatch) -> None:
    from bot import happyfox_video_ui

    monkeypatch.setattr(
        happyfox_video_ui.preset_manager,
        "get_video_cost_per_second",
        lambda *args, **kwargs: 8,
    )

    markup = compose_happyfox_video_keyboard(
        _base_settings_markup(),
        current_v_type="imgtxt",
        current_model="grok_imagine",
    )
    callbacks = _callbacks(markup)

    assert "v_model_seedance_2_5" in callbacks
    assert "v_model_grok_imagine" in callbacks
    assert "v_model_grok_imagine_v15" in callbacks
    assert "v_model_veo3" not in callbacks
    assert "v_model_veo3_lite" not in callbacks
    assert "v_model_veo3_fast" in callbacks


def test_models_redraw_for_video_to_video(monkeypatch) -> None:
    from bot import happyfox_video_ui

    monkeypatch.setattr(
        happyfox_video_ui.preset_manager,
        "get_video_cost_per_second",
        lambda *args, **kwargs: 5,
    )
    monkeypatch.setattr(
        happyfox_video_ui.preset_manager,
        "get_video_cost_with_quality",
        lambda *args, **kwargs: 30,
    )

    markup = compose_happyfox_video_keyboard(
        _base_settings_markup(),
        current_v_type="video",
        current_model="glow",
    )
    callbacks = _callbacks(markup)

    assert "v_model_seedance_2_5" in callbacks
    assert "v_model_seedance_2" in callbacks
    assert "v_model_glow" in callbacks
    assert "v_model_gemini_omni" in callbacks
    assert "v_model_v3_pro" not in callbacks
    assert "v_model_grok_imagine" not in callbacks


def test_incompatible_model_is_replaced_when_type_changes() -> None:
    assert compatible_video_model("text", "glow") == "v3_pro"
    assert compatible_video_model("imgtxt", "veo3") == "v3_pro"
    assert compatible_video_model("video", "v3_pro") == "seedance_2"
    assert compatible_video_model("video", "glow") == "glow"


def test_type_switch_does_not_auto_enter_seedance_25_dedicated_flow() -> None:
    assert compatible_video_model("text", "seedance_2_5") == "v3_pro"
    assert compatible_video_model("imgtxt", "seedance_2_5") == "v3_pro"
    assert compatible_video_model("video", "seedance_2_5") == "seedance_2"


def test_nonstandard_omni_modes_keep_provider_settings_without_standard_selector() -> None:
    markup = compose_happyfox_video_keyboard(
        _base_settings_markup(),
        current_v_type="audio",
        current_model="gemini_omni_audio",
    )

    callbacks = _callbacks(markup)
    assert "v_type_text" not in callbacks
    assert "video_change_model" not in callbacks
    assert "ratio_16_9" in callbacks