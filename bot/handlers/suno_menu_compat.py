from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_INSTALLED = False


def _append_row(markup: InlineKeyboardMarkup, button: InlineKeyboardButton, *, before_last: bool = False) -> InlineKeyboardMarkup:
    rows = [list(row) for row in markup.inline_keyboard]
    if any(any(item.callback_data == button.callback_data for item in row) for row in rows):
        return markup
    if before_last and rows:
        rows.insert(max(0, len(rows) - 1), [button])
    else:
        rows.append([button])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def install_suno_menu_compat(common_module, admin_module, keyboards_module) -> None:
    """Add Suno entry points without duplicating the legacy keyboard monolith."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_main = keyboards_module.get_main_menu_keyboard
    original_admin = keyboards_module.get_admin_keyboard

    def main_with_suno(*args, **kwargs):
        markup = original_main(*args, **kwargs)
        return _append_row(
            markup,
            InlineKeyboardButton(text="🎵 Suno · музыка", callback_data="menu_suno"),
            before_last=True,
        )

    def admin_with_suno(*args, **kwargs):
        markup = original_admin(*args, **kwargs)
        return _append_row(
            markup,
            InlineKeyboardButton(text="🎵 Suno цены", callback_data="admin_suno_prices"),
            before_last=True,
        )

    keyboards_module.get_main_menu_keyboard = main_with_suno
    keyboards_module.get_admin_keyboard = admin_with_suno
    common_module.get_main_menu_keyboard = main_with_suno
    common_module.get_admin_keyboard = admin_with_suno
    admin_module.get_admin_keyboard = admin_with_suno
    _INSTALLED = True
