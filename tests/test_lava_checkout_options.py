from bot.handlers.lava_checkout import _payment_options_keyboard


def _buttons(markup):
    return [(button.text, button.callback_data) for row in markup.inline_keyboard for button in row]


def test_payment_options_shows_yookassa_and_eur() -> None:
    keyboard = _payment_options_keyboard(
        "optimal",
        stars=False,
        direct_rub=False,
        crypto=True,
        freekassa=False,
        yookassa=True,
        eur=True,
    )
    buttons = _buttons(keyboard)
    assert ("💳 ЮKassa · ₽ / СБП", "buy_yookassa_optimal") in buttons
    assert ("💶 EUR", "buy_eur_optimal") in buttons


def test_payment_options_hides_disabled_providers() -> None:
    keyboard = _payment_options_keyboard(
        "pro",
        stars=False,
        direct_rub=False,
        crypto=False,
        freekassa=False,
        yookassa=False,
        eur=False,
    )
    texts = _buttons(keyboard)
    assert all("ЮKassa" not in text for text, _ in texts)
    assert all("EUR" not in text for text, _ in texts)