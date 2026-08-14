from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.catalog import GenerationMode, model_choice, product_for_mode
from foxgen.bot.flows import ResolvedInput, _provider_payload
from foxgen.bot.keyboards import (
    after_submit_keyboard,
    aspect_ratio_keyboard,
    confirmation_keyboard,
    main_menu,
)
from foxgen.bot.states import GenerationStates
from foxgen.core.errors import ErrorCode, SubmissionError


router = Router(name="foxgen-feed-remix")


class RemixDraftFilter(Filter):
    async def __call__(self, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("entrypoint") == "remix" and bool(data.get("source_publication_id"))


REMIX_DRAFT = RemixDraftFilter()


@router.callback_query(
    GenerationStates.choosing_model,
    REMIX_DRAFT,
    F.data.startswith("model:"),
)
async def choose_remix_model(callback: CallbackQuery, state: FSMContext) -> None:
    slug = (callback.data or "").partition(":")[2]
    data = await state.get_data()
    try:
        mode = GenerationMode(str(data.get("mode") or ""))
        choice = model_choice(mode, slug)
    except (KeyError, ValueError):
        await callback.answer("Эта модель недоступна для ремикса.", show_alert=True)
        return
    prompt = str(data.get("source_prompt") or "").strip()
    if len(prompt) < 3:
        await callback.answer("Исходный промпт больше недоступен.", show_alert=True)
        return
    await state.update_data(
        model_slug=choice.slug,
        model_title=choice.title,
        prompt=prompt,
        can_submit=False,
    )
    await state.set_state(GenerationStates.choosing_aspect_ratio)
    await safe_edit_callback_message(
        callback,
        (
            f"<b>{escape(choice.title)}</b>\n\n"
            "Исходный промпт подставлен. Выберите формат результата; "
            "на экране подтверждения его можно изменить."
        ),
        aspect_ratio_keyboard(product_for_mode(mode)),
    )


@router.callback_query(
    GenerationStates.choosing_model,
    REMIX_DRAFT,
    F.data == "nav:back",
)
async def cancel_remix_from_model(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit_callback_message(
        callback,
        "Ремикс отменён. Главное меню:",
        main_menu(),
    )


@router.callback_query(
    GenerationStates.confirming,
    REMIX_DRAFT,
    F.data == "draft:confirm",
)
async def confirm_remix(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    if not bool(data.get("can_submit")):
        await callback.answer("Сначала обновите цену и баланс.", show_alert=True)
        return
    source_publication_id = str(data.get("source_publication_id") or "")
    if not source_publication_id:
        await callback.answer(
            "Источник ремикса потерян. Откройте публикацию заново.", show_alert=True
        )
        return

    await state.set_state(GenerationStates.submitting)
    if callback.message:
        await callback.message.edit_text(
            "⏳ Проверяю источник ремикса и ставлю генерацию в очередь…"
        )
    await callback.answer()

    try:
        # Re-read both the eligibility contract and signed media immediately before
        # paid admission. An unpublished/derived source therefore cannot race through.
        await api_client.remix_source(
            user_id=callback.from_user.id,
            publication_id=source_publication_id,
        )
        media_payload = await api_client.publication_media(
            user_id=callback.from_user.id,
            publication_id=source_publication_id,
        )
        resolved_media = _resolved_publication_media(media_payload)
        payload = _provider_payload(data, resolved_media)
        model_slug = _required_text(data, "model_slug")
        queued = await api_client.submit(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            model_slug=model_slug,
            input_data=payload,
            idempotency_key=_required_text(data, "idempotency_key"),
            source_publication_id=source_publication_id,
        )
    except SubmissionError as exc:
        await _restore_confirmation(
            callback,
            state,
            exc.public_message,
        )
        return
    except FoxGenApiError as exc:
        await _restore_confirmation(callback, state, exc.message)
        return

    await state.clear()
    replay_text = (
        "\nПовторный запрос распознан — новая задача не создавалась." if queued.replayed else ""
    )
    if callback.message:
        await callback.message.edit_text(
            (
                "✅ <b>Ремикс поставлен в очередь</b>\n\n"
                f"ID: <code>{escape(queued.generation_id)}</code>\n"
                "Результат придёт сюда автоматически после сохранения."
                f"{replay_text}"
            ),
            reply_markup=after_submit_keyboard(queued.generation_id),
        )


def _resolved_publication_media(payload: dict[str, object]) -> list[ResolvedInput]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "У исходной публикации нет доступного медиа для ремикса.",
        )
    result: list[ResolvedInput] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        url = raw.get("url")
        content_type = str(raw.get("content_type") or "")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        if content_type.startswith("image/"):
            kind = "image"
        elif content_type.startswith("video/"):
            kind = "video"
        elif content_type.startswith("audio/"):
            kind = "audio"
        else:
            continue
        result.append({"kind": kind, "url": url})
    if not result:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "У исходной публикации нет совместимого медиа для ремикса.",
        )
    return result


async def _restore_confirmation(
    callback: CallbackQuery,
    state: FSMContext,
    message: str,
) -> None:
    await state.set_state(GenerationStates.confirming)
    await state.update_data(can_submit=False)
    if callback.message:
        await callback.message.edit_text(
            f"⚠️ {escape(message)}\n\nПараметры сохранены.",
            reply_markup=confirmation_keyboard(can_submit=False),
        )


def _required_text(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик ремикса повреждён. Откройте публикацию заново.",
        )
    return value
