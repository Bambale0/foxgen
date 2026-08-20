from __future__ import annotations

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.internal_admin_cms import get_published_cms_content
from bot.support_service import (
    SupportAttachment,
    append_user_message,
    create_support_ticket,
    ensure_support_outbox_worker,
    latest_open_ticket_id,
)

router = Router()


class SupportStates(StatesGroup):
    waiting_new_message = State()
    waiting_followup = State()


async def _start_support_outbox(bot: Bot) -> None:
    ensure_support_outbox_worker(bot)


router.startup.register(_start_support_outbox)


def _extract_attachment(message: types.Message) -> SupportAttachment | None:
    if message.photo:
        photo = message.photo[-1]
        return SupportAttachment(
            kind="photo",
            telegram_file_id=photo.file_id,
            size_bytes=photo.file_size,
        )
    if message.document:
        document = message.document
        return SupportAttachment(
            kind="document",
            telegram_file_id=document.file_id,
            file_name=document.file_name,
            mime_type=document.mime_type,
            size_bytes=document.file_size,
        )
    if message.video:
        video = message.video
        return SupportAttachment(
            kind="video",
            telegram_file_id=video.file_id,
            file_name=video.file_name,
            mime_type=video.mime_type,
            size_bytes=video.file_size,
        )
    if message.audio:
        audio = message.audio
        return SupportAttachment(
            kind="audio",
            telegram_file_id=audio.file_id,
            file_name=audio.file_name,
            mime_type=audio.mime_type,
            size_bytes=audio.file_size,
        )
    return None


def _subject_from_text(text: str) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return "Обращение с вложением"
    return normalized[:120]


async def _support_intro() -> str:
    try:
        content = await get_published_cms_content("support.intro")
    except Exception:
        content = None
    if content and isinstance(content.get("text"), str):
        return str(content["text"])
    return (
        "💬 <b>Новое обращение в поддержку</b>\n\n"
        "Опишите проблему одним сообщением. Можно приложить фото, видео или документ.\n"
        "Для отмены отправьте /cancel."
    )


@router.message(Command("support"))
@router.message(F.text.in_({"Поддержка", "🆘 Поддержка", "💬 Поддержка"}))
async def open_support(message: types.Message, state: FSMContext) -> None:
    await state.set_state(SupportStates.waiting_new_message)
    await message.answer(await _support_intro())


@router.message(
    Command("cancel"),
    SupportStates.waiting_new_message,
)
@router.message(
    Command("cancel"),
    SupportStates.waiting_followup,
)
async def cancel_support(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание обращения отменено.")


@router.message(SupportStates.waiting_new_message)
async def create_support_from_message(message: types.Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    body = (message.text or message.caption or "").strip()
    attachment = _extract_attachment(message)
    if not body and attachment is None:
        await message.answer("Пришлите текст, фото, видео или документ с описанием проблемы.")
        return

    ticket_id = await create_support_ticket(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        subject=_subject_from_text(body),
        body=body,
        telegram_message_id=message.message_id,
        attachments=[attachment] if attachment else [],
    )
    await state.clear()
    await message.answer(
        f"✅ Обращение <b>#{ticket_id}</b> создано.\n\n"
        "Ответ придёт сюда от имени бота. Чтобы дополнить обращение, используйте "
        f"команду <code>/support_add {ticket_id}</code>."
    )


@router.message(Command("support_add"))
async def start_support_followup(message: types.Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    command_parts = (message.text or "").split(maxsplit=1)
    if len(command_parts) == 2 and command_parts[1].strip().isdigit():
        ticket_id = int(command_parts[1].strip())
    else:
        ticket_id = await latest_open_ticket_id(message.from_user.id) or 0
    if ticket_id <= 0:
        await message.answer("Открытое обращение не найдено. Создайте новое через /support.")
        return
    await state.set_state(SupportStates.waiting_followup)
    await state.update_data(support_ticket_id=ticket_id)
    await message.answer(
        f"Пришлите дополнение к обращению <b>#{ticket_id}</b>. Можно добавить вложение."
    )


@router.message(SupportStates.waiting_followup)
async def append_support_followup(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")
    if not ticket_id or not message.from_user:
        return
    body = (message.text or message.caption or "").strip()
    attachment = _extract_attachment(message)
    if not body and attachment is None:
        await message.answer("Пришлите текст или вложение.")
        return
    try:
        await append_user_message(
            ticket_id=int(ticket_id),
            telegram_id=message.from_user.id,
            body=body,
            telegram_message_id=message.message_id,
            attachments=[attachment] if attachment else [],
        )
    except LookupError:
        await state.clear()
        await message.answer("Обращение не найдено или уже закрыто.")
        return
    await state.clear()
    await message.answer(f"Дополнение к обращению <b>#{ticket_id}</b> сохранено.")
