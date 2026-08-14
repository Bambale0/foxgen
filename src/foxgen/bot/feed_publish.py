from __future__ import annotations

from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.states import FeedStates


router = Router(name="foxgen-feed-publish")


@router.callback_query(F.data == "feed:publish:start")
async def start_publish(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedStates.waiting_publish_generation)
    await safe_edit_callback_message(
        callback,
        (
            "<b>Опубликовать генерацию</b>\n\n"
            "Отправьте UUID завершённой генерации. Он показан в сообщении после запуска. "
            "Публикация сработает только после статуса succeeded и сохранения всех медиа."
        ),
    )


@router.message(FeedStates.waiting_publish_generation, F.text)
async def receive_generation_id(message: Message, state: FSMContext) -> None:
    generation_id = (message.text or "").strip()
    try:
        UUID(generation_id)
    except ValueError:
        await message.answer("Нужен UUID генерации, например 550e8400-e29b-41d4-a716-446655440000.")
        return
    await state.update_data(publish_generation_id=generation_id)
    await state.set_state(FeedStates.choosing_publish_scope)
    await message.answer(
        "Куда опубликовать?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🌐 Общая лента", callback_data="feed:publish:scope:feed"
                    ),
                    InlineKeyboardButton(
                        text="👤 Профиль", callback_data="feed:publish:scope:profile"
                    ),
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="nav:cancel")],
            ]
        ),
    )


@router.callback_query(
    FeedStates.choosing_publish_scope,
    F.data.in_({"feed:publish:scope:feed", "feed:publish:scope:profile"}),
)
async def choose_scope(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    generation_id = str(data.get("publish_generation_id") or "")
    scope = (callback.data or "").rsplit(":", 1)[-1]
    try:
        UUID(generation_id)
        item = await api_client.publish_generation(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            generation_id=generation_id,
            scope=scope,
        )
    except ValueError:
        await state.clear()
        await callback.answer("Черновик публикации повреждён. Начните заново.", show_alert=True)
        return
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await state.clear()
    publication_id = escape(str(item.get("id") or ""))
    await safe_edit_callback_message(
        callback,
        (f"✅ <b>Опубликовано</b>\n\nПубликация: <code>{publication_id}</code>"),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Открыть публикацию",
                        callback_data=f"feed:post:{item.get('id')}",
                    )
                ],
                [InlineKeyboardButton(text="Мои публикации", callback_data="feed:mine")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )


@router.message(FeedStates.waiting_publish_generation)
async def invalid_generation_id(message: Message) -> None:
    await message.answer("Отправьте UUID генерации текстом или /start для отмены.")


@router.message(FeedStates.choosing_publish_scope)
async def invalid_scope_message(message: Message) -> None:
    await message.answer("Выберите область публикации кнопкой или /start для отмены.")
