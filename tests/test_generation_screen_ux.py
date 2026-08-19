from foxgen.bot.generation_capabilities import VideoGenerationType
from foxgen.bot.generation_draft import default_image_flow_data, default_video_flow_data
from foxgen.bot.generation_keyboards import (
    image_reference_keyboard,
    prompt_keyboard,
    video_media_keyboard,
)
from foxgen.bot.generation_screens import (
    image_references_text,
    image_settings_text,
    video_media_max_count,
    video_media_text,
    video_settings_text,
)


def _rows(markup: object) -> list[list[tuple[str, str | None]]]:
    keyboard = getattr(markup, "inline_keyboard")
    return [[(button.text, button.callback_data) for button in row] for row in keyboard]


def test_image_reference_screen_matches_current_compact_layout() -> None:
    assert _rows(image_reference_keyboard(count=0, max_count=14)) == [
        [("Загружено: 0/14", "gw:i:refs:status")],
        [
            ("⏭ Пропустить", "gw:i:refs:skip"),
            ("✅ Продолжить", "gw:i:refs:done"),
        ],
        [
            ("📚 Память реф", "gw:i:refs:memory"),
            ("🔄 Перезагрузить", "gw:i:refs:clear"),
        ],
        [("⬅️ Назад", "gw:back")],
    ]


def test_image_reference_text_has_live_count_without_wizard_numbering() -> None:
    data = default_image_flow_data(42)
    data["image_model_key"] = "nano-banana-2"
    text = image_references_text(data)

    assert text.startswith("📎 <b>Референсы</b>")
    assert "Загружено: <code>0/14</code>" in text
    assert "2/4" not in text


def test_settings_and_prompt_screens_do_not_expose_step_counters_or_cancel_button() -> None:
    image = default_image_flow_data(42)
    video = default_video_flow_data(42)

    assert "3/4" not in image_settings_text(image)
    assert image_settings_text(image).startswith("⚙️ <b>Параметры фото</b>")
    assert "4/5" not in video_settings_text(video)
    assert video_settings_text(video).startswith("⚙️ <b>Параметры видео</b>")
    assert _rows(prompt_keyboard()) == [[("⬅️ Назад", "gw:back")]]


def test_video_reference_screen_uses_scenario_specific_live_limit() -> None:
    data = default_video_flow_data(42)

    data["video_type"] = VideoGenerationType.FIRST_FRAME.value
    assert video_media_max_count(data) == 1
    assert "Загружено: <code>0/1</code>" in video_media_text(data)

    data["video_type"] = VideoGenerationType.FIRST_LAST.value
    assert video_media_max_count(data) == 2

    data["video_type"] = VideoGenerationType.REFERENCES.value
    assert video_media_max_count(data) == 6


def test_required_video_media_keeps_memory_continue_and_reload_visible() -> None:
    rows = _rows(
        video_media_keyboard(
            generation_type=VideoGenerationType.FIRST_LAST,
            count=0,
            max_count=2,
            can_continue=False,
        )
    )

    assert rows == [
        [("Загружено: 0/2", "gw:v:media:status")],
        [("✅ Продолжить", "gw:v:media:done")],
        [
            ("📚 Память реф", "gw:v:media:memory"),
            ("🔄 Перезагрузить", "gw:v:media:clear"),
        ],
        [("⬅️ Назад", "gw:back")],
    ]
