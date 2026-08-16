from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from foxgen.bot.catalog import (
    IMAGE_ASPECT_RATIOS,
    MODELS_BY_MODE,
    VIDEO_ASPECT_RATIOS,
    GenerationMode,
    Product,
)
from foxgen.core.config import Settings, get_settings


def resolve_miniapp_url(settings: Settings | None = None) -> str | None:
    """Return the public Happy Fox Mini App URL when Telegram can reach it."""

    resolved = settings or get_settings()
    if not resolved.miniapp_enabled:
        return None
    if resolved.miniapp_public_url is not None:
        return f"{str(resolved.miniapp_public_url).rstrip('/')}/"
    if resolved.kie_callback_base_url is None:
        return None
    base_url = str(resolved.kie_callback_base_url).rstrip("/")
    return f"{base_url}/mini-app/"


def main_menu(*, miniapp_url: str | None = None) -> InlineKeyboardMarkup:
    """Return the product menu with the real Happy Fox WebApp entrypoint."""

    resolved_miniapp_url = miniapp_url or resolve_miniapp_url()
    if resolved_miniapp_url is not None:
        miniapp_button = InlineKeyboardButton(
            text="🦊 Открыть Happy Fox",
            web_app=WebAppInfo(url=resolved_miniapp_url),
        )
    else:
        miniapp_button = InlineKeyboardButton(
            text="🦊 Happy Fox Mini App",
            callback_data="miniapp:unavailable",
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [miniapp_button],
            [
                InlineKeyboardButton(text="🌐 Лента", callback_data="feed:open"),
                InlineKeyboardButton(text="👤 Профиль", callback_data="feed:profile:me"),
            ],
            [
                InlineKeyboardButton(
                    text="📣 Опубликовать генерацию", callback_data="feed:publish:start"
                )
            ],
            [InlineKeyboardButton(text="Быстрый запуск", callback_data="quick:start")],
            [
                InlineKeyboardButton(text="Создать видео", callback_data="create:video"),
                InlineKeyboardButton(
                    text="Создать озвучку (голос)",
                    callback_data="create:voice",
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
                InlineKeyboardButton(text="AI-помощник", callback_data="planned:assistant"),
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


def quick_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
        ]
    )


def reference_product_keyboard(reference_kind: str) -> InlineKeyboardMarkup:
    image_title = "Создать фото"
    if reference_kind == "video":
        image_title = "Создать фото по обложке"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=image_title,
                    callback_data="reference:product:image",
                ),
                InlineKeyboardButton(
                    text="Создать видео",
                    callback_data="reference:product:video",
                ),
            ],
            [InlineKeyboardButton(text="⬅️ Другой референс", callback_data="nav:back")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
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
        rows.append(
            [InlineKeyboardButton(text="✅ Референсы добавлены", callback_data="media:done")]
        )
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
                [
                    InlineKeyboardButton(
                        text="🔄 Обновить цену и баланс", callback_data="draft:refresh"
                    )
                ],
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


def after_submit_keyboard(generation_id: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if generation_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🌐 В ленту",
                    callback_data=f"feed:publish:feed:{generation_id}",
                ),
                InlineKeyboardButton(
                    text="👤 В профиль",
                    callback_data=f"feed:publish:profile:{generation_id}",
                ),
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="➕ Создать ещё", callback_data="nav:menu")],
            [
                InlineKeyboardButton(text="🌐 Лента", callback_data="feed:open"),
                InlineKeyboardButton(text="💳 Баланс", callback_data="account:balance"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
