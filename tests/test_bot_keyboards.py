from foxgen.bot.catalog import GenerationMode, Product
from foxgen.bot.keyboards import (
    confirmation_keyboard,
    main_menu,
    mode_keyboard,
    model_keyboard,
)


def _callbacks(markup: object) -> set[str]:
    inline_keyboard = getattr(markup, "inline_keyboard")
    return {
        button.callback_data
        for row in inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def _rows(markup: object) -> list[list[tuple[str, str | None]]]:
    inline_keyboard = getattr(markup, "inline_keyboard")
    return [
        [(button.text, button.callback_data) for button in row]
        for row in inline_keyboard
    ]


def test_launch_button_is_hidden_until_quote_and_balance_are_valid() -> None:
    blocked = _callbacks(confirmation_keyboard(can_submit=False))
    allowed = _callbacks(confirmation_keyboard(can_submit=True))

    assert "draft:confirm" not in blocked
    assert "draft:refresh" in blocked
    assert "account:balance" in blocked
    assert "draft:confirm" in allowed
    assert "draft:refresh" not in allowed


def test_main_menu_matches_approved_product_sketch() -> None:
    assert _rows(main_menu()) == [
        [("Мини апп", "planned:mini_app")],
        [
            ("Создать видео", "create:video"),
            ("Создать озвучку (голос)", "planned:voice"),
        ],
        [
            ("Создать фото", "create:image"),
            ("Создать музыку (песню)", "planned:music"),
        ],
        [
            ("Motion Control", "planned:motion"),
            ("Промпты AI", "planned:prompt"),
        ],
        [
            ("Gemini Omni", "planned:gemini_omni"),
            ("AI-помощник", "planned:assistant"),
        ],
        [
            ("Скучная работа", "planned:boring_work"),
            ("Поддержка", "planned:support"),
        ],
        [
            ("Баланс", "account:balance"),
            ("Партнёры", "planned:partners"),
        ],
        [("Тарифы", "planned:tariffs")],
    ]


def test_main_menu_exposes_image_video_and_balance_actions() -> None:
    callbacks = _callbacks(main_menu())

    assert {"create:image", "create:video", "account:balance"} <= callbacks


def test_every_mode_and_model_screen_has_a_safe_exit() -> None:
    for product in Product:
        assert "nav:menu" in _callbacks(mode_keyboard(product))

    for mode in GenerationMode:
        callbacks = _callbacks(model_keyboard(mode))
        assert "nav:back" in callbacks
        assert "nav:cancel" in callbacks
