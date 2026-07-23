from foxgen.bot.app import render_prompt_confirmation


def test_prompt_confirmation_escapes_html() -> None:
    rendered = render_prompt_confirmation("image", "fox <b>bold</b> & sky")

    assert "&lt;b&gt;bold&lt;/b&gt;" in rendered
    assert "&amp; sky" in rendered
    assert "fox <b>bold</b>" not in rendered
