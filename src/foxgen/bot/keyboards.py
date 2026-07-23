from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from foxgen.bot.catalog import (
    IMAGE_ASPECT_RATIOS,
    MODELS_BY_MODE,
    VIDEO_ASPECT_RATIOS,
    GenerationMode,
    Product,
)


def main_menu() -> InlineKeyboardMarkup:
    """Return the product menu in the exact row order from the approved sketch."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мини-апп", callback_data="planned:mini_app")],
            [
                InlineKeyboardButton(text="Создать видео", callback_data="create:video"),
                InlineKeyboardButton(
                    text="Создать озвучку (голос)",
                    callback_data="planned:voice",
                ),
            ],
            [
                InlineKeyboardButton(text="Создать фото", callback_data="create:image"),
                InlineKeyboardButton(
                    text="Создать музыку (песню)",
                    callback_data="planned:music",
                ),
            ],
            [
                InlineKeyboardButton(text="Motion Control", callback_data="planned:motion"),
                InlineKeyboardButton(text="Промпты AI", callback_data="planned:prompt"),
            ],
            [
                InlineKeyboardButton(text="Gemini Omni", callback_data="planned:gemini_omni"),
                InlineKeyboardButton(text="AI-компаньон", callback_data="planned:companion"),
            ],
            [
                InlineKeyboardButton(text="Скучная работа", callback_data="planned:boring_work"),
                InlineKeyboardButton(text="Поддержка", callback_data="planned:support"),
            ],
            [
                InlineKeyboardButton(text="Баланс", callback_data="account:balance"),
                InlineKeyboardButton(text="Партнёры", callback_data="planned:partners"),
            ],
            [InlineKeyboardButton(text="Тарифы", callback_data="planned:tariffs")],
        ]
    )


def mode_keyboard(product: Product) -> InlineKeyboardMarkup:
    if product == Product.IMAGE:
        rows = [
            [InlineKeyboardButton(text="✨ По описанию", callback_data="mode:image:text")],
            [InlineKeyboardButton(text="🪄 Изменить фото", callback_data="mode:image:edit")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="✨ По описанию", callback_data="mode:video:text")],
            [InlineKeyboardButton(text="🖼 Оживить фото", callback_data="mode:video:image")],
            [InlineKeyboardButton(text="🎞 По референсам", callback_data="mode:video:reference")],
        ]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def model_keyboard(mode: GenerationMode) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{choice.title} — {choice.summary}",
                callback_data=f"model:{choice.slug}",
            )
        ]
        for choice in MODELS_BY_MODE[mode]
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def navigation_keyboard(*, media_done: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if media_done:
        rows.append([InlineKeyboardButton(text="✅ Референсы добавлены", callback_data="media:done")])
    rows.extend(
        [
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def aspect_ratio_keyboard(product: Product) -> InlineKeyboardMarkup:
    ratios = IMAGE_ASPECT_RATIOS if product == Product.IMAGE else VIDEO_ASPECT_RATIOS
    rows = [
        [
            InlineKeyboardButton(
                text=title,
                callback_data=f"aspect:{value.replace(':', 'x')}",
            )
            for value, title in ratios[index : index + 2]
        ]
        for index in range(0, len(ratios), 2)
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_quality_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡ Basic", callback_data="quality:basic"),
                InlineKeyboardButton(text="💎 High", callback_data="quality:high"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
        ]
    )


def video_duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="5 секунд", callback_data="duration:5"),
                InlineKeyboardButton(text="10 секунд", callback_data="duration:10"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
        ]
    )


def video_audio_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔊 Со звуком", callback_data="audio:yes"),
                InlineKeyboardButton(text="🔇 Без звука", callback_data="audio:no"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
        ]
    )


def confirmation_keyboard(*, can_submit: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_submit:
        rows.append([InlineKeyboardButton(text="🚀 Запустить", callback_data="draft:confirm")])
    else:
        rows.extend(
            [
                [InlineKeyboardButton(text="🔄 Обновить цену и баланс", callback_data="draft:refresh")],
                [InlineKeyboardButton(text="💳 Открыть баланс", callback_data="account:balance")],
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="✏️ Изменить описание", callback_data="draft:edit")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_submit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать ещё", callback_data="nav:menu")],
            [InlineKeyboardButton(text="💳 Баланс", callback_data="account:balance")],
        ]
    )
