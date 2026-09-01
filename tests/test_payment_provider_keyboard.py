from bot.keyboards import get_payment_method_keyboard


def test_payment_keyboard_shows_yookassa_and_eur() -> None:
    keyboard = get_payment_method_keyboard(
        "optimal",
        has_crypto=False,
        has_lava=True,
        has_stars=False,
        has_yookassa=True,
        lava_currency="EUR",
    )

    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [(button.text, button.callback_data) for button in buttons] == [
        ("💳 ЮKassa · ₽ / СБП", "buy_yookassa_optimal"),
        ("💶 EUR", "buy_lava_optimal"),
        ("◀️ Назад", "menu_topup"),
    ]
