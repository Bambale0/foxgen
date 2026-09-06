import pytest

from bot.trend_parameters import (
    TrendParameterValidationError,
    extract_trend_template_fields,
    render_trend_prompt,
)
from bot.trend_visibility import sanitize_prompt_for_public


def _trend(prompt: str) -> dict:
    return {
        "id": 17,
        "title": "Возрастной тренд",
        "description": "Вирусный ролик с персональным возрастом",
        "prompt_text": prompt,
        "category": "video",
        "tags": ["trend", "trend-video"],
        "model": "v3_pro",
        "status": "approved",
        "is_public": True,
        "generation_settings": {
            "kind": "video",
            "user_input": "photo",
            "model": "v3_pro",
            "scenario": "imgtxt",
            "ratio": "9:16",
            "duration": 5,
        },
    }


def test_extracts_unique_friendly_template_fields_in_prompt_order() -> None:
    fields = extract_trend_template_fields(
        "Hero is {{name}}, age {{age}}. Date {{date}}. Again: {{ age }}."
    )

    assert [field.key for field in fields] == ["name", "age", "date"]
    assert [field.label for field in fields] == ["Имя", "Возраст", "Дата"]
    assert [field.field_type for field in fields] == ["text", "number", "date"]


def test_public_trend_exposes_fields_but_never_hidden_prompt_or_model() -> None:
    hidden = "Vertical viral video, person is {{age}} years old, name {{name}}."
    public = sanitize_prompt_for_public(_trend(hidden))

    assert public is not None
    assert public["prompt_text"] == ""
    assert public["model"] is None
    assert public["prompt_hidden"] is True
    settings = public["generation_settings"]
    assert settings["kind"] == "video"
    assert settings["ratio"] == "9:16"
    assert [field["key"] for field in settings["template_fields"]] == ["age", "name"]
    assert hidden not in str(public)
    assert "v3_pro" not in str(settings)


def test_renders_parameter_values_only_on_server() -> None:
    prompt = "Make a viral video: {{name}} is {{age}} years old on {{date}}."

    rendered = render_trend_prompt(
        prompt,
        {"name": "Анна", "age": "28", "date": "2026-09-06"},
    )

    assert rendered == "Make a viral video: Анна is 28 years old on 2026-09-06."
    assert "{{" not in rendered


def test_rejects_missing_unknown_and_invalid_parameter_values() -> None:
    prompt = "Person is {{age}} years old, name {{name}}."

    with pytest.raises(TrendParameterValidationError, match="Возраст"):
        render_trend_prompt(prompt, {"name": "Анна"})

    with pytest.raises(TrendParameterValidationError, match="неизвестный"):
        render_trend_prompt(prompt, {"age": "28", "name": "Анна", "prompt": "steal"})

    with pytest.raises(TrendParameterValidationError, match="число"):
        render_trend_prompt(prompt, {"age": "двадцать восемь", "name": "Анна"})

    with pytest.raises(TrendParameterValidationError, match="от 1 до 120"):
        render_trend_prompt(prompt, {"age": "999", "name": "Анна"})


def test_plain_trend_remains_backward_compatible() -> None:
    prompt = "A cinematic portrait in warm evening light."

    assert render_trend_prompt(prompt, {}) == prompt
    assert extract_trend_template_fields(prompt) == ()
