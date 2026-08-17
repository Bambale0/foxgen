from foxgen.bot.generation_draft import default_image_flow_data
from foxgen.bot.generation_screens import image_settings_text


def test_generation_screen_escapes_dynamic_html() -> None:
    data = default_image_flow_data(42)
    data["aspect_ratio"] = "1:1 <b>bold</b> & sky"

    rendered = image_settings_text(data)

    assert "&lt;b&gt;bold&lt;/b&gt;" in rendered
    assert "&amp; sky" in rendered
    assert "1:1 <b>bold</b>" not in rendered
