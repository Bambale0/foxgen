import asyncio
import logging
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from foxgen.bot.states import GenerationStates
from foxgen.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = Router(name="foxgen")


MENU_ITEMS: tuple[tuple[str, str], ...] = (
    ("🎬 Создать видео", "create:video"),
    ("🖼 Создать фото", "create:image"),
    ("🗣 Создать озвучку", "create:voice"),
    ("🎵 Создать музыку", "create:music"),
    ("🕺 Motion Control", "create:motion"),
    ("✨ Промпт AI", "prompt:ai"),
    ("🤖 AI-помощник", "assistant"),
    ("💳 Баланс", "balance"),
    ("👥 Рефералы", "referrals"),
    ("🤝 Партнёры", "partners"),
)


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=title, callback_data=callback)]
        for title, callback in MENU_ITEMS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
        ]
    )


def confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Продолжить", callback_data="draft:confirm")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="draft:edit")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
        ]
    )


def render_prompt_confirmation(product: str, prompt: str) -> str:
    return (
        "<b>Черновик готов</b>\n\n"
        f"Тип: <code>{escape(product)}</code>\n"
        f"Описание: {escape(prompt)}\n\n"
        "Следующим шагом выберем модель и покажем точную стоимость."
    )


@router.message(CommandStart())
@router.message(Command("menu"))
async def show_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    text = (
        "<b>FoxGen</b> — что создаём?\n\n"
        "Выберите действие. Я проведу по шагам и покажу стоимость до запуска."
    )
    await message.answer(text, reply_markup=main_menu())


@router.callback_query(F.data == "nav:menu")
async def return_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Что создаём?", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "nav:cancel")
async def cancel_flow(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            "Действие отменено. Выберите новый сценарий.",
            reply_markup=main_menu(),
        )
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("create:"))
async def start_generation(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data is None:
        await callback.answer("Кнопка устарела", show_alert=True)
        return
    product = callback.data.partition(":")[2]
    await state.clear()
    await state.update_data(product=product)
    await state.set_state(GenerationStates.waiting_prompt)
    if callback.message:
        text = (
            "Опишите результат одним сообщением. Можно писать обычными словами — "
            "промпт улучшим позже."
        )
        await callback.message.edit_text(text, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(GenerationStates.waiting_prompt, F.text)
async def receive_prompt(message: Message, state: FSMContext) -> None:
    prompt = (message.text or "").strip()
    if len(prompt) < 3:
        await message.answer("Описание слишком короткое. Добавьте хотя бы несколько слов.")
        return
    if len(prompt) > 3500:
        await message.answer("Описание длиннее 3500 символов. Сократите его и отправьте снова.")
        return
    await state.update_data(prompt=prompt)
    await state.set_state(GenerationStates.confirming)
    data = await state.get_data()
    text = render_prompt_confirmation(str(data.get("product", "unknown")), prompt)
    await message.answer(text, reply_markup=confirmation_keyboard())


@router.callback_query(GenerationStates.confirming, F.data == "draft:edit")
async def edit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GenerationStates.waiting_prompt)
    if callback.message:
        await callback.message.edit_text(
            "Отправьте новое описание.",
            reply_markup=cancel_keyboard(),
        )
    await callback.answer()


@router.callback_query(GenerationStates.confirming, F.data == "draft:confirm")
async def confirm_draft(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    if callback.message:
        text = (
            "Черновик сохранён. Подключение каталога моделей и расчёта цены "
            "выполняется в следующем PR.\n\n"
            f"Сценарий: <code>{escape(str(data.get('product', 'unknown')))}</code>"
        )
        await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer("Черновик сохранён")


@router.callback_query(
    F.data.in_({"prompt:ai", "assistant", "balance", "referrals", "partners"})
)
async def planned_section(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text(
            "Раздел уже включён в дорожную карту и будет подключён отдельным PR.",
            reply_markup=main_menu(),
        )
    await callback.answer()


@router.callback_query()
async def stale_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Эта кнопка устарела. Открыл главное меню.", show_alert=True)
    if callback.message:
        await callback.message.edit_text("Что создаём?", reply_markup=main_menu())


@router.message()
async def fallback_message(message: Message) -> None:
    await message.answer(
        "Не понял действие. Используйте кнопки — так быстрее и без ошибок.",
        reply_markup=main_menu(),
    )


@router.error()
async def global_error(event: ErrorEvent) -> bool:
    logger.exception("Unhandled Telegram update", exc_info=event.exception)
    update_message = event.update.message
    if update_message:
        await update_message.answer(
            "Что-то пошло не так. Состояние не потеряно: откройте /menu и повторите шаг."
        )
    return True


async def run(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    token = resolved.telegram_bot_token
    if token is None:
        raise RuntimeError("FOXGEN_TELEGRAM_BOT_TOKEN is required")
    storage = RedisStorage.from_url(resolved.redis_url)
    dispatcher = Dispatcher(storage=storage)
    dispatcher.include_router(router)
    bot = Bot(
        token=token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()
        await storage.close()


def run_sync() -> None:
    asyncio.run(run())
