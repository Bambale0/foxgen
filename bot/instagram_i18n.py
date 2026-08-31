from __future__ import annotations

import asyncio
import re
import time

from bot import database
from bot import db as db_backend
from bot.channel_identity import ensure_channel_identity_schema

_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()
_SUPPORTED = {"ru", "en"}
_RU_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_EN_RE = re.compile(r"[a-z]", re.IGNORECASE)
_LANGUAGE_COMMANDS = {
    "ru": "ru",
    "русский": "ru",
    "russian": "ru",
    "en": "en",
    "english": "en",
    "английский": "en",
}

_COPY: dict[str, dict[str, str]] = {
    "ask_kind": {
        "ru": "Что хочешь создать?\n\n📸 Фото — Seedream 5 Pro\n🎬 Видео — Seedance 2.5\n\nОтветь «Фото» или «Видео».",
        "en": "What do you want to create?\n\n📸 Photo — Seedream 5 Pro\n🎬 Video — Seedance 2.5\n\nReply “Photo” or “Video”.",
    },
    "ask_kind_bilingual": {
        "ru": "Что хочешь создать? / What do you want to create?\n\n📸 Фото / Photo\n🎬 Видео / Video",
        "en": "Что хочешь создать? / What do you want to create?\n\n📸 Фото / Photo\n🎬 Видео / Video",
    },
    "photo_selected": {
        "ru": "📸 Фото выбрано. Пришли исходное фото, затем одним сообщением напиши, что хочешь получить. Первая фото-генерация бесплатная 🎁",
        "en": "📸 Photo selected. Send the source photo, then describe the result you want in one message. Your first photo generation is free 🎁",
    },
    "generation_busy_switch": {
        "ru": "Сначала закончу текущую генерацию, потом можно переключить тип.",
        "en": "I’ll finish the current generation first, then you can switch the type.",
    },
    "comment_invite": {
        "ru": "Привет! 👋 Напиши мне в Direct — сначала выберем, что создать: 📸 фото или 🎬 видео. Первое фото бесплатно 🎁, видео — платно.",
        "en": "Hi! 👋 Message me in Direct — first choose what to create: 📸 photo or 🎬 video. Your first photo is free 🎁; video is paid.",
    },
    "photo_received_free": {
        "ru": "Фото получил 📸 Первая фото-генерация будет бесплатно 🎁 Теперь одним сообщением напиши, что хочешь получить.",
        "en": "Photo received 📸 Your first photo generation is free 🎁 Now describe the result you want in one message.",
    },
    "photo_received_paid": {
        "ru": "Фото получил 📸 Теперь одним сообщением напиши, что хочешь получить.",
        "en": "Photo received 📸 Now describe the result you want in one message.",
    },
    "send_photo_first": {
        "ru": "Сначала пришли фото 📸, а следующим сообщением — что хочешь с ним сделать.",
        "en": "Send a photo first 📸, then tell me what you want to do with it in the next message.",
    },
    "generation_running": {
        "ru": "Генерация уже идёт. Результат пришлю сюда автоматически.",
        "en": "Generation is already running. I’ll send the result here automatically.",
    },
    "photo_generation_running": {
        "ru": "Я уже делаю предыдущую генерацию. Сначала пришлю результат, потом можно отправить новое фото.",
        "en": "I’m already working on the previous generation. I’ll send the result first, then you can send a new photo.",
    },
    "cancelled_keep_photo": {
        "ru": "Отменил. Фото сохранил — можешь написать новый запрос.",
        "en": "Cancelled. I kept the photo — you can send a new prompt.",
    },
    "confirm_yes_no": {
        "ru": "Ответь ДА, чтобы запустить платную генерацию, или НЕТ, чтобы отменить.",
        "en": "Reply YES to start the paid generation or NO to cancel.",
    },
    "free_already_starting": {
        "ru": "Бесплатная генерация уже запускается. Результат пришлю сюда автоматически.",
        "en": "Your free generation is already starting. I’ll send the result here automatically.",
    },
    "free_start": {
        "ru": "Запускаю Seedream 5 Pro ✨ Эта первая генерация бесплатная 🎁",
        "en": "Starting Seedream 5 Pro ✨ This first generation is free 🎁",
    },
    "paid_started": {
        "ru": "{cost:g} 🐾 списано ✅ Запускаю Seedream 5 Pro.",
        "en": "{cost:g} 🐾 charged ✅ Starting Seedream 5 Pro.",
    },
    "photo_insufficient": {
        "ru": "Не хватает баланса. Для Seedream 5 Pro нужно {cost:g} 🐾. Пополни баланс в Telegram и вернись с «Продолжить».",
        "en": "Insufficient balance. Seedream 5 Pro needs {cost:g} 🐾. Top up in Telegram, then come back and send “Continue”.",
    },
    "photo_paid_offer_ok": {
        "ru": "Seedream 5 Pro • {cost:g} 🐾 ({price:g} ₽). Баланс: {credits:g} 🐾. Ответь ДА для запуска или НЕТ для отмены.",
        "en": "Seedream 5 Pro • {cost:g} 🐾 ({price:g} ₽). Balance: {credits:g} 🐾. Reply YES to start or NO to cancel.",
    },
    "photo_paid_offer_low": {
        "ru": "Seedream 5 Pro • {cost:g} 🐾 ({price:g} ₽). Баланс: {credits:g} 🐾. Баланса не хватает — пополни его в Telegram, затем вернись сюда и напиши «Продолжить».",
        "en": "Seedream 5 Pro • {cost:g} 🐾 ({price:g} ₽). Balance: {credits:g} 🐾. Your balance is too low — top up in Telegram, then return here and send “Continue”.",
    },
    "photo_paid_done": {
        "ru": "Готово ✨ Хочешь ещё — пришли новое фото.",
        "en": "Done ✨ Want another one? Send a new photo.",
    },
    "photo_free_done": {
        "ru": "Готово 🎁 Первая генерация была бесплатной.\n\nХочешь продолжить — пополни баланс через ЮKassa или Lava Top. После оплаты вернись сюда и напиши «Продолжить».{suffix}",
        "en": "Done 🎁 Your first generation was free.\n\nWant to continue? Top up via YooKassa or Lava Top. After payment, come back here and send “Continue”.{suffix}",
    },
    "account_link": {
        "ru": "Первая бесплатная фото-генерация уже использована ✅ Следующие генерации оплачиваются по обычным ценам HappyFox. Привяжи Instagram к HappyFox, чтобы использовать общий баланс и историю.{suffix}",
        "en": "Your free first photo generation has already been used ✅ Further generations use regular HappyFox pricing. Link Instagram to HappyFox to use the shared balance and history.{suffix}",
    },
    "generation_failed_free": {
        "ru": "Не получилось завершить генерацию 😕 Попробуй ещё раз с тем же фото. Бесплатная попытка сохранена.",
        "en": "I couldn’t finish the generation 😕 Try again with the same photo. Your free attempt is preserved.",
    },
    "generation_failed_paid": {
        "ru": "Не получилось завершить генерацию 😕 Попробуй ещё раз с тем же фото. Списанные 🐾 уже возвращены.",
        "en": "I couldn’t finish the generation 😕 Try again with the same photo. The charged 🐾 have already been refunded.",
    },
    "video_paywall": {
        "ru": "🎬 Видео в Instagram — платное.\n\nSeedance 2.5 • {duration} сек • {cost:g} 🐾 ({price:g} ₽).{balance}\n\nСначала пополни баланс через ЮKassa или Lava Top. После оплаты вернись сюда и напиши «Продолжить». Только после этого попрошу фото или видео-референс.{link}",
        "en": "🎬 Instagram video is paid.\n\nSeedance 2.5 • {duration}s • {cost:g} 🐾 ({price:g} ₽).{balance}\n\nFirst top up via YooKassa or Lava Top. After payment, return here and send “Continue”. Only then I’ll ask for a photo or video reference.{link}",
    },
    "video_balance": {
        "ru": "\nТекущий баланс: {credits:g} 🐾.",
        "en": "\nCurrent balance: {credits:g} 🐾.",
    },
    "video_balance_enough": {
        "ru": " Уже хватает — можешь сразу написать «Продолжить».",
        "en": " That’s enough — you can send “Continue” right away.",
    },
    "video_topup_required": {
        "ru": "Для видео сначала пополни баланс по ссылке выше, затем напиши «Продолжить». Референс пока не нужен.",
        "en": "For video, top up using the link above first, then send “Continue”. You don’t need to send a reference yet.",
    },
    "video_balance_ready": {
        "ru": "Баланс готов ✅ Для Seedance 2.5 нужно {cost:g} 🐾.\n\nТеперь пришли фото или видео-референс.",
        "en": "Balance ready ✅ Seedance 2.5 needs {cost:g} 🐾.\n\nNow send a photo or video reference.",
    },
    "video_running": {
        "ru": "Seedance 2.5 уже создаёт ролик. Результат пришлю сюда автоматически.",
        "en": "Seedance 2.5 is already creating the video. I’ll send the result here automatically.",
    },
    "video_send_reference": {
        "ru": "Пришли фото или видео-референс для Seedance 2.5.",
        "en": "Send a photo or video reference for Seedance 2.5.",
    },
    "video_reference_received": {
        "ru": "Референс получил 🎬 Теперь одним сообщением напиши, что должно происходить в ролике.",
        "en": "Reference received 🎬 Now describe what should happen in the video in one message.",
    },
    "video_reference_replaced": {
        "ru": "Новый референс сохранил. Теперь напиши, что должно происходить в видео.",
        "en": "New reference saved. Now describe what should happen in the video.",
    },
    "video_reference_lost": {
        "ru": "Референс потерялся. Пришли фото или видео ещё раз.",
        "en": "The reference was lost. Please send the photo or video again.",
    },
    "video_cancelled": {
        "ru": "Отменил. Референс сохранил — можешь написать новый запрос.",
        "en": "Cancelled. I kept the reference — you can send a new prompt.",
    },
    "video_offer": {
        "ru": "Seedance 2.5 • {duration} сек • {cost:g} 🐾 ({price:g} ₽). Баланс: {credits:g} 🐾.\n\nОтветь ДА для запуска или НЕТ для отмены.",
        "en": "Seedance 2.5 • {duration}s • {cost:g} 🐾 ({price:g} ₽). Balance: {credits:g} 🐾.\n\nReply YES to start or NO to cancel.",
    },
    "video_started": {
        "ru": "{cost:g} 🐾 списано ✅ Запускаю Seedance 2.5.",
        "en": "{cost:g} 🐾 charged ✅ Starting Seedance 2.5.",
    },
    "video_done": {
        "ru": "Готово 🎬 Чтобы сделать ещё видео, снова выбери «Видео». Перед загрузкой нового референса предложу пополнить баланс.",
        "en": "Done 🎬 To create another video, choose “Video” again. I’ll offer a top-up before asking for a new reference.",
    },
}


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}"
    return f"sqlite:{database.DATABASE_PATH}"


def _statement() -> str:
    identity_type = "BIGINT" if db_backend.is_postgres() else "INTEGER"
    return f"""
        CREATE TABLE IF NOT EXISTS instagram_channel_languages (
            identity_id {identity_type} PRIMARY KEY,
            language TEXT NOT NULL,
            updated_at_epoch BIGINT NOT NULL,
            FOREIGN KEY (identity_id) REFERENCES channel_identities (id) ON DELETE CASCADE
        )
    """


async def ensure_instagram_language_schema() -> None:
    await ensure_channel_identity_schema()
    key = _schema_key()
    if key in _SCHEMA_READY:
        return
    async with _schema_lock():
        if key in _SCHEMA_READY:
            return
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                raw = getattr(db, "_conn", None)
                if raw is None:
                    raise RuntimeError("PostgreSQL migration handle is unavailable")
                async with raw.cursor() as cursor:
                    await cursor.execute(_statement())
                await raw.commit()
            else:
                await db.execute(_statement())
                await db.commit()
        _SCHEMA_READY.add(key)


def detect_instagram_language(text: str | None) -> str:
    normalized = " ".join(str(text or "").strip().casefold().split())
    if normalized in _LANGUAGE_COMMANDS:
        return _LANGUAGE_COMMANDS[normalized]
    ru_count = len(_RU_RE.findall(normalized))
    en_count = len(_EN_RE.findall(normalized))
    if ru_count == en_count == 0:
        return ""
    return "ru" if ru_count >= en_count else "en"


async def get_instagram_language(identity_id: int) -> str:
    await ensure_instagram_language_schema()
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT language FROM instagram_channel_languages WHERE identity_id = ?",
            (identity_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return ""
    language = str(row["language"] or "").strip().lower()
    return language if language in _SUPPORTED else ""


async def set_instagram_language(identity_id: int, language: str) -> str:
    normalized = str(language or "").strip().lower()
    if normalized not in _SUPPORTED:
        raise ValueError("language must be ru or en")
    await ensure_instagram_language_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO instagram_channel_languages (identity_id, language, updated_at_epoch)
            VALUES (?, ?, ?)
            ON CONFLICT(identity_id) DO UPDATE SET
                language = excluded.language,
                updated_at_epoch = excluded.updated_at_epoch
            """,
            (identity_id, normalized, now),
        )
        await db.commit()
    return normalized


async def resolve_instagram_language(
    identity_id: int,
    text: str | None = None,
    *,
    allow_switch: bool = False,
) -> str:
    current = await get_instagram_language(identity_id)
    detected = detect_instagram_language(text)
    normalized = " ".join(str(text or "").strip().casefold().split())
    explicit = normalized in _LANGUAGE_COMMANDS
    if detected and (not current or allow_switch or explicit):
        return await set_instagram_language(identity_id, detected)
    return current


def tr(language: str, key: str, **values: object) -> str:
    lang = language if language in _SUPPORTED else "ru"
    entry = _COPY[key]
    template = entry.get(lang) or entry["ru"]
    return template.format(**values)
