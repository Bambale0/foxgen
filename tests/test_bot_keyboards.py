from foxgen.bot.catalog import GenerationMode, Product
from foxgen.bot.keyboards import (
    confirmation_keyboard,
    main_menu,
    mode_keyboard,
    model_keyboard,
    quick_start_keyboard,
    reference_product_keyboard,
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
    return [[(button.text, button.callback_data) for button in row] for row in inline_keyboard]


def test_launch_button_is_hidden_until_quote_and_balance_are_valid() -> None:
    blocked = _callbacks(confirmation_keyboard(can_submit=False))
    allowed = _callbacks(confirmation_keyboard(can_submit=True))

    assert "draft:confirm" not in blocked
    assert "draft:refresh" in blocked
    assert "account:balance" in blocked
    assert "draft:confirm" in allowed
    assert "draft:refresh" not in allowed


def test_main_menu_matches_current_product_surface_with_quick_start() -> None:
    assert _rows(main_menu()) == [
        [("🦊 Happy Fox Mini App", "miniapp:unavailable")],
        [("🌐 Лента", "feed:open"), ("👤 Профиль", "feed:profile:me")],
        [("📣 Опубликовать генерацию", "feed:publish:start")],
        [("Быстрый запуск", "quick:start")],
        [
            ("Создать видео", "create:video"),
            ("Создать озвучку (голос)", "create:voice"),
        ],
        [
            ("Создать фото", "create:image"),
            ("Создать музыку (песню)", "create:music"),
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


def test_main_menu_renders_real_webapp_button_when_public_url_is_available() -> None:
    markup = main_menu(miniapp_url="https://fox.example.com/mini-app/")
    button = markup.inline_keyboard[0][0]

    assert button.callback_data is None
    assert button.text == "🦊 Открыть Happy Fox"
    assert button.web_app is not None
    assert button.web_app.url == "https://fox.example.com/mini-app/"


def test_main_menu_exposes_live_creation_feed_and_balance_actions() -> None:
    callbacks = _callbacks(main_menu())

    assert {
        "quick:start",
        "create:image",
        "create:video",
        "create:voice",
        "create:music",
        "feed:open",
        "feed:profile:me",
        "feed:publish:start",
        "account:balance",
    } <= callbacks


def test_reference_choice_keeps_photo_and_video_actions_visible() -> None:
    assert _rows(reference_product_keyboard("image"))[0] == [
        ("Создать фото", "reference:product:image"),
        ("Создать видео", "reference:product:video"),
    ]
    assert _rows(reference_product_keyboard("video"))[0] == [
        ("Создать фото по обложке", "reference:product:image"),
        ("Создать видео", "reference:product:video"),
    ]


def test_quick_start_has_safe_exit() -> None:
    callbacks = _callbacks(quick_start_keyboard())

    assert {"nav:menu", "nav:cancel"} <= callbacks


def test_every_mode_and_model_screen_has_a_safe_exit() -> None:
    for product in Product:
        assert "nav:menu" in _callbacks(mode_keyboard(product))

    for mode in GenerationMode:
        callbacks = _callbacks(model_keyboard(mode))
        assert "nav:back" in callbacks
        assert "nav:cancel" in callbacks
