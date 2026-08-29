"""Apply the HappyFox Telegram main-menu layout.

The source runtime is intentionally kept close to tanyapi. HappyFox-owned menu
composition lives in this product delta so future upstream syncs fail closed when
menu anchors change instead of silently restoring the old navigation.
"""

from pathlib import Path

KEYBOARDS_PATH = Path("bot/keyboards.py")
COMMON_PATH = Path("bot/handlers/common.py")

OLD_MAIN_MENU = '''def get_main_menu_keyboard(user_credits: int = 0, telegram_id: int | None = None, mini_app_referral_code: str | None = None):
    """Аккуратное главное меню: сценарии сверху, детали моделей внутри разделов."""
    builder = InlineKeyboardBuilder()

    if config.mini_app_url:
        builder.row(
            InlineKeyboardButton(
                text="🚀 Открыть Mini App",
                web_app=WebAppInfo(url=_mini_app_url_with_referral(mini_app_referral_code) or config.mini_app_url),
            )
        )
    builder.row(
        InlineKeyboardButton(text="🖼 Создать фото", callback_data="create_image_text_new"),
        InlineKeyboardButton(text="🎬 Создать видео", callback_data="create_video_new"),
    )
    builder.row(
        InlineKeyboardButton(text="🎯 Motion Control", callback_data="motion_control"),
        InlineKeyboardButton(text="✍️ Промпт по описанию", callback_data="photo_to_prompt"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🎞 Промпт по видео • {_video_prompt_price_label()}🍌", callback_data="video_to_prompt"),
        InlineKeyboardButton(text="🤖 AI-помощник", callback_data="menu_ai_assistant"),
    )
    builder.row(
        InlineKeyboardButton(text="📚 Библиотека промптов", callback_data="menu_prompts"),
        InlineKeyboardButton(text="🖼 Лента", callback_data="menu_feed"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🍌 Баланс: {user_credits}", callback_data="menu_balance"),
        InlineKeyboardButton(text="💬 Поддержка", callback_data="menu_support"),
    )
    builder.row(
        InlineKeyboardButton(text="🤝 Партнёрам", callback_data="menu_partner"),
        InlineKeyboardButton(text="⋯ Ещё", callback_data="ux_more"),
    )

    return builder.as_markup()
'''

NEW_MAIN_MENU = '''def get_main_menu_keyboard(user_credits: int = 0, telegram_id: int | None = None, mini_app_referral_code: str | None = None):
    """Главное меню HappyFox: короткий путь к ключевым сценариям."""
    builder = InlineKeyboardBuilder()

    if config.mini_app_url:
        builder.row(
            InlineKeyboardButton(
                text="🚀 Mini App",
                web_app=WebAppInfo(url=_mini_app_url_with_referral(mini_app_referral_code) or config.mini_app_url),
            )
        )

    builder.row(
        InlineKeyboardButton(text="🖼 Создать фото", callback_data="create_image_text_new"),
        InlineKeyboardButton(text="🎙 Создать озвучку", callback_data="omni_mode_audio"),
    )
    builder.row(
        InlineKeyboardButton(text="🎬 Создать видео", callback_data="create_video_new"),
        InlineKeyboardButton(text="🎵 Создать музыку · Suno", callback_data="happyfox_music"),
    )
    builder.row(
        InlineKeyboardButton(text="🎯 Motion Control", callback_data="motion_control"),
        InlineKeyboardButton(text="✨ Промпты", callback_data="menu_prompts"),
    )
    builder.row(
        InlineKeyboardButton(text="🔷 Gemini Omni", callback_data="v_model_gemini_omni"),
        InlineKeyboardButton(text="🤖 AI-помощник", callback_data="menu_ai_assistant"),
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Ссылки на работы", callback_data="menu_feed"),
        InlineKeyboardButton(text="💬 Поддержка", callback_data="menu_support"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🍌 Баланс: {user_credits}", callback_data="menu_balance"),
        InlineKeyboardButton(text="🤝 Партнёры", callback_data="menu_partner"),
    )
    builder.row(
        InlineKeyboardButton(text="💳 Тарифы", callback_data="menu_topup")
    )

    return builder.as_markup()
'''

OLD_MORE_MENU = '''def get_more_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❓ Как пользоваться", callback_data="menu_help")
    builder.button(text="💬 Поддержка", callback_data="menu_support")
    builder.button(text="💰 Пополнить", callback_data="menu_topup")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 1, 1)
    return builder.as_markup()
'''

NEW_MORE_MENU = '''def get_more_menu_keyboard():
    """Дополнительные AI-сценарии из главного меню HappyFox."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Видео", callback_data="create_video_new")
    builder.button(text="🖼 Фото", callback_data="create_image_text_new")
    builder.button(text="✨ Улучшение", callback_data="create_image_refs_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 1, 1)
    return builder.as_markup()
'''

MUSIC_HANDLER_ANCHOR = '@router.callback_query(F.data == "ux_more")\n'
MUSIC_HANDLER = '''@router.callback_query(F.data == "happyfox_music")
async def show_happyfox_music(callback: types.CallbackQuery):
    """Keep the planned Suno entry visible without leaving a dead callback."""
    await callback.answer(
        "🎵 Создание музыки через Suno скоро появится в HappyFox.",
        show_alert=True,
    )


'''


def _replace_once_or_verify(text: str, old: str, new: str, *, context: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise RuntimeError(f"{context} anchor was not found")


def _patch_keyboards() -> None:
    text = KEYBOARDS_PATH.read_text(encoding="utf-8")
    text = _replace_once_or_verify(
        text,
        OLD_MAIN_MENU,
        NEW_MAIN_MENU,
        context="HappyFox main menu",
    )
    text = _replace_once_or_verify(
        text,
        OLD_MORE_MENU,
        NEW_MORE_MENU,
        context="HappyFox other-AI menu",
    )

    stale_labels = (
        "✍️ Промпт по описанию",
        "🎞 Промпт по видео",
        "📚 Библиотека промптов",
        "✨ Прочий AI",
        "⋯ Ещё",
    )
    main_menu_block = text.split("def get_main_menu_keyboard", 1)[1].split(
        "def get_create_hub_keyboard", 1
    )[0]
    if any(label in main_menu_block for label in stale_labels):
        raise RuntimeError("Stale HappyFox main-menu entries remain")

    KEYBOARDS_PATH.write_text(text, encoding="utf-8")


def _patch_common() -> None:
    text = COMMON_PATH.read_text(encoding="utf-8")
    if MUSIC_HANDLER not in text:
        if MUSIC_HANDLER_ANCHOR not in text:
            raise RuntimeError("HappyFox Suno handler anchor was not found")
        text = text.replace(
            MUSIC_HANDLER_ANCHOR,
            MUSIC_HANDLER + MUSIC_HANDLER_ANCHOR,
            1,
        )

    old_title = "⋯ <b>Ещё</b>"
    new_title = "✨ <b>Прочий AI</b>"
    if old_title in text:
        text = text.replace(old_title, new_title, 1)
    elif new_title not in text:
        raise RuntimeError("HappyFox other-AI title anchor was not found")

    old_body = "Здесь находятся баланс, история, помощь и поддержка."
    new_body = "Выберите дополнительный сценарий: видео, фото или улучшение."
    if old_body in text:
        text = text.replace(old_body, new_body, 1)
    elif new_body not in text:
        raise RuntimeError("HappyFox other-AI body anchor was not found")

    COMMON_PATH.write_text(text, encoding="utf-8")


def apply_happyfox_main_menu() -> None:
    _patch_keyboards()
    _patch_common()


if __name__ == "__main__":
    apply_happyfox_main_menu()
