from __future__ import annotations

import asyncio
import base64
import logging
import os
from io import BytesIO

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.env import load_project_env
from bot.services.redis_service import redis_service
from bot.services.support_ai_service import support_ai_service
from bot.support_service import (
    SupportAttachment,
    create_support_ticket,
    ensure_support_outbox_worker,
)

load_project_env()
logger = logging.getLogger(__name__)

SUPPORT_SOURCE = "telegram_support_bot"
router = Router()

_OPERATOR_COMMANDS = {
    "оператор",
    "живой оператор",
    "живой человек",
    "человек",
    "поддержка оператора",
}


def _subject(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    return (normalized or "Обращение из AI-поддержки")[:120]


def _explicit_operator_request(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split()).strip(" .,!?:;")
    return normalized in _OPERATOR_COMMANDS or normalized.startswith("позови оператора")


async def _send_chunks(message: types.Message, text: str) -> None:
    clean = str(text or "").strip()
    if not clean:
        return
    while clean:
        chunk = clean[:3900]
        if len(clean) > 3900:
            split_at = max(chunk.rfind("\n"), chunk.rfind(". "))
            if split_at > 1200:
                chunk = chunk[: split_at + 1]
        await message.answer(chunk, parse_mode=None)
        clean = clean[len(chunk) :].lstrip()


async def _download_photo_data_url(message: types.Message) -> str | None:
    if not message.photo:
        return None
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > 10 * 1024 * 1024:
        raise ValueError("Скриншот слишком большой. Максимум 10 МБ.")
    file = await message.bot.get_file(photo.file_id)
    if not file.file_path:
        raise RuntimeError("Telegram did not return photo path")
    buffer = BytesIO()
    await message.bot.download_file(file.file_path, destination=buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


async def _create_operator_ticket(
    message: types.Message,
    *,
    reason: str,
    attachment: SupportAttachment | None = None,
) -> int:
    if not message.from_user:
        raise RuntimeError("support user is missing")
    transcript = await support_ai_service.export_transcript(message.from_user.id)
    current = (message.text or message.caption or "").strip()
    body_parts = [reason]
    if transcript:
        body_parts.append("Последний AI-диалог:\n" + transcript)
    if current and current not in transcript:
        body_parts.append("Текущее сообщение:\n" + current)
    return await create_support_ticket(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        subject=_subject(current or reason),
        body="\n\n".join(body_parts),
        telegram_message_id=message.message_id,
        attachments=[attachment] if attachment else [],
        source=SUPPORT_SOURCE,
    )


@router.message(CommandStart())
async def start_support_bot(message: types.Message) -> None:
    if message.from_user:
        await support_ai_service.clear_history(message.from_user.id)
    await message.answer(
        "👋 <b>Поддержка HappyFox</b>\n\n"
        "Опишите вопрос своими словами или пришлите скриншот — сначала попробую "
        "решить проблему сразу через GPT‑5.5.\n\n"
        "Если нужна ручная проверка, подключу оператора.\n"
        "Команды: /new — новый диалог, /operator — оператор."
    )


@router.message(Command("new"))
async def new_support_dialog(message: types.Message) -> None:
    if message.from_user:
        await support_ai_service.clear_history(message.from_user.id)
    await message.answer("Новый диалог начат. Что случилось?")


@router.message(Command("operator"))
async def operator_command(message: types.Message) -> None:
    ticket_id = await _create_operator_ticket(
        message,
        reason="Пользователь запросил живого оператора.",
    )
    await message.answer(
        f"✅ Передал оператору. Обращение <b>#{ticket_id}</b>.\n"
        "Ответ придёт сюда, в этот бот."
    )


@router.message(F.text | F.photo)
async def ai_support_message(message: types.Message) -> None:
    if not message.from_user:
        return

    text = (message.text or message.caption or "").strip()
    if text and _explicit_operator_request(text):
        await operator_command(message)
        return

    attachment = None
    image_data_url = None
    if message.photo:
        photo = message.photo[-1]
        attachment = SupportAttachment(
            kind="photo",
            telegram_file_id=photo.file_id,
            size_bytes=photo.file_size,
        )
        try:
            image_data_url = await _download_photo_data_url(message)
        except ValueError as exc:
            await message.answer(str(exc))
            return

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        answer = await support_ai_service.answer(
            telegram_id=message.from_user.id,
            user_text=text,
            image_data_url=image_data_url,
        )
    except Exception:
        logger.exception(
            "Support GPT-5.5 request failed for telegram_id=%s",
            message.from_user.id,
        )
        ticket_id = await _create_operator_ticket(
            message,
            reason="AI-поддержка временно недоступна; требуется ответ оператора.",
            attachment=attachment,
        )
        await message.answer(
            "Сейчас AI-поддержка не смогла ответить. Я уже передал вопрос оператору "
            f"как обращение <b>#{ticket_id}</b>. Ответ придёт сюда."
        )
        return

    await _send_chunks(message, answer.text)
    if answer.escalate:
        ticket_id = await _create_operator_ticket(
            message,
            reason="GPT‑5.5 определил, что вопрос требует ручной проверки.",
            attachment=attachment,
        )
        await message.answer(
            f"👤 Для этого нужна ручная проверка. Создал обращение <b>#{ticket_id}</b>. "
            "Оператор ответит в этом чате."
        )


@router.message()
async def unsupported_support_message(message: types.Message) -> None:
    if not message.from_user:
        return
    attachment: SupportAttachment | None = None
    if message.document:
        attachment = SupportAttachment(
            kind="document",
            telegram_file_id=message.document.file_id,
            file_name=message.document.file_name,
            mime_type=message.document.mime_type,
            size_bytes=message.document.file_size,
        )
    elif message.video:
        attachment = SupportAttachment(
            kind="video",
            telegram_file_id=message.video.file_id,
            file_name=message.video.file_name,
            mime_type=message.video.mime_type,
            size_bytes=message.video.file_size,
        )
    elif message.audio:
        attachment = SupportAttachment(
            kind="audio",
            telegram_file_id=message.audio.file_id,
            file_name=message.audio.file_name,
            mime_type=message.audio.mime_type,
            size_bytes=message.audio.file_size,
        )

    if attachment is None:
        await message.answer("Пришлите текст или скриншот. Для оператора — /operator.")
        return

    ticket_id = await _create_operator_ticket(
        message,
        reason="Пользователь прислал вложение, требующее ручной проверки.",
        attachment=attachment,
    )
    await message.answer(
        f"📎 Вложение передал оператору. Обращение <b>#{ticket_id}</b>. "
        "Ответ придёт сюда."
    )


async def main() -> None:
    token = os.getenv("SUPPORT_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SUPPORT_BOT_TOKEN is required for support bot runtime")
    if not (
        os.getenv("SUPPORT_KIE_API_KEY", "").strip()
        or os.getenv("KIE_AI_API_KEY", "").strip()
    ):
        raise RuntimeError("SUPPORT_KIE_API_KEY or KIE_AI_API_KEY is required")

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    outbox_task = ensure_support_outbox_worker(bot, source=SUPPORT_SOURCE)

    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Начать поддержку"),
                BotCommand(command="new", description="Новый AI-диалог"),
                BotCommand(command="operator", description="Позвать оператора"),
            ]
        )
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("HappyFox support bot started in isolated long-polling mode")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=True,
            close_bot_session=False,
        )
    finally:
        outbox_task.cancel()
        await asyncio.gather(outbox_task, return_exceptions=True)
        await redis_service.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
