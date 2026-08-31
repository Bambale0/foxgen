from __future__ import annotations

import html
import io
from typing import Any

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.services.suno_upload_service import suno_upload_service
from bot.suno_jobs import enqueue_suno_job, get_suno_job, list_suno_jobs
from bot.suno_pricing import SUNO_MODELS, SUNO_OPERATION_LABELS, get_suno_price

router = Router()


class SunoStates(StatesGroup):
    waiting_generate_prompt = State()
    waiting_custom = State()
    waiting_audio = State()
    waiting_audio_params = State()
    waiting_id_pair = State()
    waiting_persona = State()
    waiting_voice_audio = State()


_MODEL_LABELS = {
    "V5_5": "Suno V5.5",
    "V5": "Suno V5",
    "V4_5PLUS": "Suno V4.5+",
    "V4_5": "Suno V4.5",
    "V4_5ALL": "Suno V4.5 All",
    "V4": "Suno V4",
}
_UPLOAD_OPERATIONS = {"upload_extend", "upload_cover", "add_vocals", "add_instrumental"}
_ID_OPERATIONS = {"separate_vocal", "split_stem", "split_stem_advanced", "wav", "music_video", "timestamped_lyrics"}


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _home_keyboard() -> InlineKeyboardMarkup:
    return _kb([[InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")]])


async def suno_menu_keyboard() -> InlineKeyboardMarkup:
    generate = await get_suno_price("telegram", "generate", "V5_5")
    lyrics = await get_suno_price("telegram", "lyrics")
    cover = await get_suno_price("telegram", "upload_cover", "V5_5")
    stems = await get_suno_price("telegram", "separate_vocal")
    sounds = await get_suno_price("telegram", "sounds")
    voice = await get_suno_price("telegram", "voice_validate")
    return _kb(
        [
            [InlineKeyboardButton(text=f"🎵 Создать трек · {_fmt(generate)}🍌", callback_data="suno:generate")],
            [
                InlineKeyboardButton(text=f"✍️ Текст песни · {_fmt(lyrics)}🍌", callback_data="suno:lyrics"),
                InlineKeyboardButton(text=f"🎛 Cover · {_fmt(cover)}🍌", callback_data="suno:op:upload_cover"),
            ],
            [
                InlineKeyboardButton(text="➕ Продолжить / загрузить", callback_data="suno:uploads"),
                InlineKeyboardButton(text=f"🎚 Стемы · {_fmt(stems)}🍌", callback_data="suno:tools"),
            ],
            [
                InlineKeyboardButton(text=f"🌊 Sounds · {_fmt(sounds)}🍌", callback_data="suno:sounds"),
                InlineKeyboardButton(text=f"🎙 Suno Voice · {_fmt(voice)}🍌", callback_data="suno:voice"),
            ],
            [InlineKeyboardButton(text="🕘 Мои Suno-задачи", callback_data="suno:history")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")],
        ]
    )


async def _model_keyboard(prefix: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for model in SUNO_MODELS:
        price = await get_suno_price("telegram", prefix if prefix != "generate_custom" else "generate", model)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{_MODEL_LABELS.get(model, model)} · {_fmt(price)}🍌",
                    callback_data=f"suno:model:{prefix}:{model}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")])
    return _kb(rows)


async def _start_menu(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🎵 <b>Suno Studio</b>\n\nСоздавайте песни, инструменталы, каверы, продолжения, стемы, WAV, music video и другие Suno-инструменты прямо в Telegram.",
        reply_markup=await suno_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("suno"))
async def suno_command(message: types.Message, state: FSMContext) -> None:
    await _start_menu(message, state)


@router.callback_query(F.data == "menu_suno")
async def suno_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🎵 <b>Suno Studio</b>\n\nМузыка, вокал, каверы и профессиональная обработка в одном разделе.",
            reply_markup=await suno_menu_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "suno:generate")
async def suno_generate(callback: types.CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.edit_text(
        "🎼 <b>Как создаём?</b>\n\nБыстрый режим — достаточно описания. В Custom можно отдельно задать название, стиль и собственный текст песни.",
        reply_markup=_kb(
            [
                [
                    InlineKeyboardButton(text="⚡ Быстро с вокалом", callback_data="suno:genmode:simple:vocals"),
                    InlineKeyboardButton(text="🎹 Инструментал", callback_data="suno:genmode:simple:instrumental"),
                ],
                [InlineKeyboardButton(text="🎚 Custom", callback_data="suno:genmode:custom:vocals")],
                [InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")],
            ]
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("suno:genmode:"))
async def suno_generation_mode(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = str(callback.data).split(":")
    custom = len(parts) > 2 and parts[2] == "custom"
    instrumental = parts[-1] == "instrumental"
    await state.update_data(custom_mode=custom, instrumental=instrumental)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🧠 <b>Выберите версию Suno</b>",
            reply_markup=await _model_keyboard("generate_custom" if custom else "generate"),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("suno:model:"))
async def suno_model(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = str(callback.data).split(":", 3)
    if len(parts) != 4:
        await callback.answer("Не удалось выбрать модель", show_alert=True)
        return
    _, _, operation, model = parts
    if model not in SUNO_MODELS:
        await callback.answer("Модель недоступна", show_alert=True)
        return
    await state.update_data(model=model, operation=("generate" if operation == "generate_custom" else operation))
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    if operation in {"generate", "generate_custom"}:
        if bool(data.get("custom_mode")):
            await state.set_state(SunoStates.waiting_custom)
            text = (
                "🎚 <b>Custom Suno</b>\n\nПришлите одним сообщением:\n"
                "1-я строка — название\n"
                "2-я строка — стиль\n"
                "с 3-й строки — ваш текст песни.\n\n"
                "Для инструментала текст после второй строки можно не добавлять."
            )
        else:
            await state.set_state(SunoStates.waiting_generate_prompt)
            text = "✍️ Опишите трек обычным текстом: настроение, жанр, сюжет, голос или инструменты."
        await callback.message.edit_text(text, reply_markup=_home_keyboard(), parse_mode="HTML")
        return
    if operation in _UPLOAD_OPERATIONS:
        await state.set_state(SunoStates.waiting_audio)
        await callback.message.edit_text(
            "🎧 Пришлите аудио как Telegram-аудио или файл. Можно также отправить публичную HTTPS-ссылку.",
            reply_markup=_home_keyboard(),
            parse_mode="HTML",
        )


async def _enqueue_and_reply(message: types.Message, state: FSMContext, operation: str, request: dict[str, Any], model: str | None = None) -> None:
    try:
        job = await enqueue_suno_job(
            "telegram",
            message.from_user.id,
            operation=operation,
            request_data=request,
            model=model,
        )
    except ValueError as exc:
        if "insufficient_balance" in str(exc):
            await message.answer("🍌 Баланса не хватает для этой Suno-задачи. Пополните баланс и повторите запуск.")
        else:
            await message.answer(f"Не удалось запустить Suno: {html.escape(str(exc)[:300])}", parse_mode="HTML")
        return
    await state.clear()
    await message.answer(
        "🚀 <b>Suno уже работает</b>\n\n"
        f"Задача: <code>{job.id[:12]}</code>\n"
        f"Списано: <b>{_fmt(job.cost)}🍌</b>\n\n"
        "Результат придёт сюда автоматически. Можно сразу запускать следующую задачу.",
        reply_markup=await suno_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(SunoStates.waiting_generate_prompt)
async def suno_simple_prompt(message: types.Message, state: FSMContext) -> None:
    prompt = str(message.text or "").strip()
    if not prompt:
        await message.answer("Пришлите описание трека текстом.")
        return
    data = await state.get_data()
    model = str(data.get("model") or "V5_5")
    await _enqueue_and_reply(
        message,
        state,
        "generate",
        {
            "prompt": prompt[:3000],
            "customMode": False,
            "instrumental": bool(data.get("instrumental")),
            "model": model,
        },
        model,
    )


@router.message(SunoStates.waiting_custom)
async def suno_custom_prompt(message: types.Message, state: FSMContext) -> None:
    text = str(message.text or "").strip()
    lines = text.splitlines()
    if len(lines) < 2 or not lines[0].strip() or not lines[1].strip():
        await message.answer("Нужно минимум две строки: название и стиль.")
        return
    data = await state.get_data()
    instrumental = bool(data.get("instrumental"))
    lyrics = "\n".join(lines[2:]).strip()
    if not instrumental and not lyrics:
        await message.answer("Для Custom с вокалом добавьте текст песни с третьей строки.")
        return
    model = str(data.get("model") or "V5_5")
    request: dict[str, Any] = {
        "prompt": lyrics[:5000],
        "customMode": True,
        "instrumental": instrumental,
        "style": lines[1].strip()[:1000],
        "title": lines[0].strip()[:80],
        "model": model,
    }
    if instrumental:
        request.pop("prompt", None)
    await _enqueue_and_reply(message, state, "generate", request, model)


@router.callback_query(F.data == "suno:lyrics")
async def suno_lyrics(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SunoStates.waiting_generate_prompt)
    await state.update_data(operation="lyrics", model=None, lyrics_mode=True)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "✍️ Опишите тему, историю и настроение будущего текста песни.",
            reply_markup=_home_keyboard(),
        )


@router.message(SunoStates.waiting_generate_prompt, F.text)
async def suno_generic_text(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    operation = str(data.get("operation") or "generate")
    if operation != "lyrics":
        return
    prompt = str(message.text or "").strip()
    if not prompt:
        await message.answer("Пришлите описание текста.")
        return
    await _enqueue_and_reply(message, state, "lyrics", {"prompt": prompt[:3000]})


@router.callback_query(F.data == "suno:uploads")
async def suno_uploads(callback: types.CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🎧 <b>Работа со своим аудио</b>",
            reply_markup=_kb(
                [
                    [InlineKeyboardButton(text="➕ Загрузить и продолжить", callback_data="suno:op:upload_extend")],
                    [InlineKeyboardButton(text="🎛 Сделать cover", callback_data="suno:op:upload_cover")],
                    [InlineKeyboardButton(text="🎤 Добавить вокал", callback_data="suno:op:add_vocals")],
                    [InlineKeyboardButton(text="🎹 Добавить инструментал", callback_data="suno:op:add_instrumental")],
                    [InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")],
                ]
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("suno:op:"))
async def suno_upload_operation(callback: types.CallbackQuery, state: FSMContext) -> None:
    operation = str(callback.data).split(":", 2)[2]
    if operation not in _UPLOAD_OPERATIONS:
        await callback.answer("Операция недоступна", show_alert=True)
        return
    await state.update_data(operation=operation)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🧠 Сначала выберите модель.",
            reply_markup=await _model_keyboard(operation),
        )


async def _telegram_audio_url(message: types.Message) -> str:
    text = str(message.text or "").strip()
    if text.startswith("https://"):
        return text
    media = message.audio or message.voice or message.document
    if media is None:
        return ""
    file_id = media.file_id
    file = await message.bot.get_file(file_id)
    destination = io.BytesIO()
    await message.bot.download_file(file.file_path, destination=destination)
    name = getattr(media, "file_name", None) or f"telegram-{message.message_id}.mp3"
    mime = getattr(media, "mime_type", None) or "audio/mpeg"
    return await suno_upload_service.upload_bytes(destination.getvalue(), filename=name, content_type=mime)


@router.message(SunoStates.waiting_audio)
async def suno_audio_input(message: types.Message, state: FSMContext) -> None:
    try:
        url = await _telegram_audio_url(message)
    except Exception as exc:
        await message.answer(f"Не удалось загрузить аудио: {html.escape(str(exc)[:300])}", parse_mode="HTML")
        return
    if not url:
        await message.answer("Пришлите аудио, файл или публичную HTTPS-ссылку.")
        return
    await state.update_data(upload_url=url)
    await state.set_state(SunoStates.waiting_audio_params)
    data = await state.get_data()
    operation = str(data.get("operation") or "")
    if operation == "upload_extend":
        prompt = "Опишите, как продолжить трек."
    elif operation == "upload_cover":
        prompt = "Опишите новый стиль кавера."
    elif operation == "add_vocals":
        prompt = "Пришлите: первая строка — название, вторая — стиль, с третьей — текст вокала."
    else:
        prompt = "Пришлите: первая строка — название, вторая — стиль инструментала."
    await message.answer(prompt)


@router.message(SunoStates.waiting_audio_params)
async def suno_audio_params(message: types.Message, state: FSMContext) -> None:
    text = str(message.text or "").strip()
    if not text:
        await message.answer("Добавьте параметры текстом.")
        return
    data = await state.get_data()
    operation = str(data.get("operation") or "")
    model = str(data.get("model") or "V5_5")
    upload_url = str(data.get("upload_url") or "")
    request: dict[str, Any] = {"uploadUrl": upload_url, "model": model}
    if operation == "upload_extend":
        request.update({"defaultParamFlag": True, "prompt": text[:5000], "style": "Original continuation", "title": "Extended", "continueAt": 0})
    elif operation == "upload_cover":
        request.update({"prompt": text[:500], "customMode": False, "instrumental": False})
    elif operation == "add_vocals":
        lines = text.splitlines()
        if len(lines) < 3:
            await message.answer("Нужно три части: название, стиль и текст вокала.")
            return
        request.update({"title": lines[0][:80], "style": lines[1][:1000], "prompt": "\n".join(lines[2:])[:5000]})
    elif operation == "add_instrumental":
        lines = text.splitlines()
        if len(lines) < 2:
            await message.answer("Нужно две строки: название и стиль.")
            return
        request.update({"title": lines[0][:80], "tags": lines[1][:1000]})
    await _enqueue_and_reply(message, state, operation, request, model)


@router.callback_query(F.data == "suno:tools")
async def suno_tools(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🧰 <b>Suno Tools</b>\n\nДля инструментов по готовому треку можно использовать кнопки под результатом. Либо пришлите Task ID и Audio ID вручную.",
            reply_markup=_kb(
                [
                    [InlineKeyboardButton(text="🎚 Вокал / инструментал", callback_data="suno:ids:separate_vocal")],
                    [InlineKeyboardButton(text="🧩 Полные стемы", callback_data="suno:ids:split_stem")],
                    [InlineKeyboardButton(text="🎧 WAV", callback_data="suno:ids:wav")],
                    [InlineKeyboardButton(text="🎬 Music Video", callback_data="suno:ids:music_video")],
                    [InlineKeyboardButton(text="📝 Текст с таймкодами", callback_data="suno:ids:timestamped_lyrics")],
                    [InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")],
                ]
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("suno:ids:"))
async def suno_ids(callback: types.CallbackQuery, state: FSMContext) -> None:
    operation = str(callback.data).split(":", 2)[2]
    if operation not in _ID_OPERATIONS:
        await callback.answer("Операция недоступна", show_alert=True)
        return
    await state.update_data(operation=operation)
    await state.set_state(SunoStates.waiting_id_pair)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text("Пришлите одной строкой: <code>TaskID AudioID</code>", reply_markup=_home_keyboard(), parse_mode="HTML")


@router.message(SunoStates.waiting_id_pair)
async def suno_id_pair(message: types.Message, state: FSMContext) -> None:
    parts = str(message.text or "").split()
    if len(parts) < 2:
        await message.answer("Нужны два ID через пробел: TaskID и AudioID.")
        return
    data = await state.get_data()
    operation = str(data.get("operation") or "")
    await _enqueue_and_reply(message, state, operation, {"taskId": parts[0][:200], "audioId": parts[1][:200]})


@router.callback_query(F.data == "suno:sounds")
async def suno_sounds(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.update_data(operation="sounds")
    await state.set_state(SunoStates.waiting_generate_prompt)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text("🌊 Опишите звук, атмосферу, фон или музыкальный луп.", reply_markup=_home_keyboard())


@router.callback_query(F.data == "suno:voice")
async def suno_voice(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🎙 <b>Suno Voice</b>",
            reply_markup=_kb(
                [
                    [InlineKeyboardButton(text="1️⃣ Получить проверочную фразу", callback_data="suno:voice_validate")],
                    [InlineKeyboardButton(text="2️⃣ Создать Voice ID", callback_data="suno:voice_generate")],
                    [InlineKeyboardButton(text="⬅️ Suno", callback_data="menu_suno")],
                ]
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "suno:voice_validate")
async def suno_voice_validate(callback: types.CallbackQuery) -> None:
    await callback.answer()
    try:
        job = await enqueue_suno_job("telegram", callback.from_user.id, operation="voice_validate", request_data={})
    except ValueError:
        if callback.message:
            await callback.message.answer("🍌 Баланса не хватает для Suno Voice.")
        return
    if callback.message:
        await callback.message.answer(f"🎙 Проверочная фраза создаётся. Списано {_fmt(job.cost)}🍌.")


@router.callback_query(F.data == "suno:voice_generate")
async def suno_voice_generate(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SunoStates.waiting_voice_audio)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "🎙 Пришлите запись проверочной фразы как аудио/файл. В подписи укажите имя будущего голоса.",
            reply_markup=_home_keyboard(),
        )


@router.message(SunoStates.waiting_voice_audio)
async def suno_voice_audio(message: types.Message, state: FSMContext) -> None:
    try:
        url = await _telegram_audio_url(message)
    except Exception as exc:
        await message.answer(f"Не удалось загрузить запись: {html.escape(str(exc)[:300])}", parse_mode="HTML")
        return
    if not url:
        await message.answer("Пришлите запись как аудио или файл.")
        return
    name = str(message.caption or "My Voice").strip()[:80]
    await _enqueue_and_reply(message, state, "voice_generate", {"uploadUrl": url, "name": name})


@router.callback_query(F.data.startswith("suno:from:"))
async def suno_from_result(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = str(callback.data).split(":")
    if len(parts) != 5:
        await callback.answer("Кнопка устарела", show_alert=True)
        return
    operation, job_id, raw_index = parts[2], parts[3], parts[4]
    source = await get_suno_job(job_id)
    if source is None or source.user_id != callback.from_user.id or source.channel != "telegram":
        await callback.answer("Исходный трек не найден", show_alert=True)
        return
    try:
        index = int(raw_index)
        track = (source.result_data.get("tracks") or [])[index]
    except (ValueError, IndexError, TypeError):
        await callback.answer("Трек не найден", show_alert=True)
        return
    audio_id = str(track.get("audio_id") or "").strip()
    if not audio_id or not source.provider_task_id:
        await callback.answer("У трека нет нужных Suno ID", show_alert=True)
        return
    request = {"taskId": source.provider_task_id, "audioId": audio_id}
    model: str | None = None
    if operation == "extend":
        model = source.model or "V5_5"
        request = {"audioId": audio_id, "defaultParamFlag": False, "model": model}
    elif operation == "persona":
        await state.set_state(SunoStates.waiting_persona)
        await state.update_data(source_task_id=source.provider_task_id, source_audio_id=audio_id)
        await callback.answer()
        if callback.message:
            await callback.message.answer("🎭 Пришлите 3 строки: имя Persona, описание, стиль.")
        return
    try:
        job = await enqueue_suno_job("telegram", callback.from_user.id, operation=operation, request_data=request, model=model)
    except ValueError:
        await callback.answer("Баланс недостаточен", show_alert=True)
        return
    await callback.answer("Запущено")
    if callback.message:
        await callback.message.answer(f"🚀 {SUNO_OPERATION_LABELS.get(operation, operation)} запущено · {_fmt(job.cost)}🍌")


@router.message(SunoStates.waiting_persona)
async def suno_persona(message: types.Message, state: FSMContext) -> None:
    lines = [line.strip() for line in str(message.text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        await message.answer("Нужно 3 строки: имя, описание и стиль.")
        return
    data = await state.get_data()
    await _enqueue_and_reply(
        message,
        state,
        "persona",
        {
            "taskId": str(data.get("source_task_id") or ""),
            "audioId": str(data.get("source_audio_id") or ""),
            "name": lines[0][:100],
            "description": lines[1][:1000],
            "style": lines[2][:1000],
            "vocalStart": 0,
            "vocalEnd": 30,
        },
    )


@router.callback_query(F.data == "suno:history")
async def suno_history(callback: types.CallbackQuery) -> None:
    jobs = await list_suno_jobs("telegram", callback.from_user.id, limit=8)
    await callback.answer()
    if not callback.message:
        return
    if not jobs:
        text = "🕘 Suno-задач пока нет."
    else:
        lines = ["🕘 <b>Последние Suno-задачи</b>"]
        for job in jobs:
            lines.append(
                f"• {html.escape(SUNO_OPERATION_LABELS.get(job.operation, job.operation))} · "
                f"<code>{job.status}</code> · {_fmt(job.cost)}🍌 · <code>{job.id[:10]}</code>"
            )
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=await suno_menu_keyboard(), parse_mode="HTML")
