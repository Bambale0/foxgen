from __future__ import annotations

from typing import TypedDict

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.generation_capabilities import VideoGenerationType
from foxgen.bot.generation_draft import (
    default_image_flow_data,
    default_video_flow_data,
    stored_media,
)
from foxgen.bot.generation_screens import render_image_model, render_video_model
from foxgen.bot.keyboards import main_menu, reference_product_keyboard
from foxgen.bot.states import GenerationStates


router = Router(name="foxgen-quick-start-wizard")


class StoredInput(TypedDict):
    kind: str
    storage_key: str


@router.callback_query(
    GenerationStates.reference_choosing_product,
    F.data.in_({"reference:product:image", "reference:product:video"}),
)
async def bridge_reference_to_wizard(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    reference_kind = str(data.get("reference_kind") or "")
    original = _stored_input(data.get("reference_original"))
    preview = _stored_input(data.get("reference_preview"))
    caption = str(data.get("reference_caption") or "").strip()
    previous_idempotency_key = str(data.get("idempotency_key") or "")

    if original is None or reference_kind not in {"image", "video"}:
        await state.clear()
        await callback.answer("Референс устарел. Отправьте его заново.", show_alert=True)
        await safe_edit_callback_message(
            callback,
            "Главное меню",
            main_menu(),
            answer_callback=False,
        )
        return

    if callback.data == "reference:product:image":
        selected = original if reference_kind == "image" else preview
        if selected is None:
            await callback.answer(
                "Telegram не передал обложку видео. Для создания фото отправьте нужный кадр как отдельное изображение.",
                show_alert=True,
            )
            return
        draft = default_image_flow_data(callback.from_user.id)
        draft.update(
            {
                "wizard_origin": "quick_start",
                "reference_kind": reference_kind,
                "reference_original": original,
                "reference_preview": preview,
                "reference_caption": caption,
                "media": [selected],
            }
        )
        if previous_idempotency_key:
            draft["idempotency_key"] = previous_idempotency_key
        await state.clear()
        await state.update_data(**draft)
        await render_image_model(callback, state)
        return

    preferred_type = (
        VideoGenerationType.FIRST_FRAME
        if reference_kind == "image"
        else VideoGenerationType.REFERENCES
    )
    draft = default_video_flow_data(callback.from_user.id)
    draft.update(
        {
            "wizard_origin": "quick_start",
            "reference_kind": reference_kind,
            "reference_original": original,
            "reference_preview": preview,
            "reference_caption": caption,
            "video_type": preferred_type.value,
            "media": [original],
        }
    )
    if previous_idempotency_key:
        draft["idempotency_key"] = previous_idempotency_key
    await state.clear()
    await state.update_data(**draft)
    await render_video_model(callback, state)


@router.callback_query(
    GenerationStates.image_selecting_model,
    F.data == "gw:back",
)
@router.callback_query(
    GenerationStates.video_selecting_model,
    F.data == "gw:back",
)
async def quick_start_back_to_product(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("wizard_origin") != "quick_start":
        return
    reference_kind = str(data.get("reference_kind") or "")
    original = _stored_input(data.get("reference_original"))
    if reference_kind not in {"image", "video"} or original is None or not stored_media(data):
        await state.clear()
        await safe_edit_callback_message(callback, "Что создаём?", main_menu())
        return
    await state.set_state(GenerationStates.reference_choosing_product)
    await safe_edit_callback_message(
        callback,
        "<b>Что создать по сохранённому референсу?</b>",
        reference_product_keyboard(reference_kind),
    )


def _stored_input(value: object) -> StoredInput | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    storage_key = value.get("storage_key")
    if not isinstance(kind, str) or not isinstance(storage_key, str):
        return None
    return {"kind": kind, "storage_key": storage_key}
