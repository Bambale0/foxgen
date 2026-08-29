"""Apply the HappyFox one-screen video-generation UX.

The provider-specific settings keyboard remains owned by the proven runtime.  This
product delta changes only composition and FSM navigation so HappyFox follows the
v7_kate reference: generation type, compatible models and settings live on one
screen and redraw from the current state.
"""

from __future__ import annotations

from pathlib import Path

KEYBOARDS_PATH = Path("bot/keyboards.py")
GENERATION_PATH = Path("bot/handlers/generation.py")

VIDEO_UI_IMPORT_AND_WRAP = '''\n\n# HappyFox product UI: v7_kate-style dynamic video controls on one screen.\nfrom bot.happyfox_video_ui import happyfox_dynamic_video_keyboard\n\nget_create_video_keyboard = happyfox_dynamic_video_keyboard(get_create_video_keyboard)\n'''

OLD_CREATE_VIDEO_ENTRY = '''@router.callback_query(F.data == "create_video_new")\nasync def show_create_video_menu(callback: types.CallbackQuery, state: FSMContext):\n    """Пошаговый вход в видео: модель -> настройки/медиа/промпт."""\n    await _init_default_video_state(state)\n    await state.update_data(video_flow_step="select_model")\n    await _show_video_model_selection_screen(callback, state)\n    await callback.answer()\n'''

NEW_CREATE_VIDEO_ENTRY = '''@router.callback_query(F.data == "create_video_new")\nasync def show_create_video_menu(callback: types.CallbackQuery, state: FSMContext):\n    """Открывает единый динамический экран создания видео HappyFox."""\n    await _init_default_video_state(state)\n    await state.update_data(video_flow_step="configure")\n    await _show_video_creation_screen(callback, state)\n    await callback.answer()\n'''

OLD_V_TYPE_TEXT = '''@router.callback_query(F.data == "v_type_text")\nasync def handle_v_type_text(callback: types.CallbackQuery, state: FSMContext):\n    """Выбор типа генерации: текст"""\n    data = await state.get_data()\n    current_model = data.get("v_model", "v26_pro")\n\n    if current_model in _GROK_VIDEO_MODELS:\n        await state.update_data(v_type="imgtxt")\n        await _show_video_media_screen(callback, state)\n        await callback.answer("Grok Imagine работает через стартовое фото")\n        return\n\n    updates = {"v_type": "text"}\n    if current_model.startswith("veo3"):\n        updates["veo_generation_type"] = "TEXT_2_VIDEO"\n    await state.update_data(**updates)\n    await _show_video_media_screen(callback, state)\n    await callback.answer()\n    await state.set_state(GenerationStates.waiting_for_input)\n'''

NEW_V_TYPE_TEXT = '''@router.callback_query(F.data == "v_type_text")\nasync def handle_v_type_text(callback: types.CallbackQuery, state: FSMContext):\n    """Переключает единый видео-экран в text-to-video."""\n    data = await state.get_data()\n    current_model = data.get("v_model", "v3_std")\n\n    if current_model in _GROK_VIDEO_MODELS:\n        await state.update_data(\n            v_type="imgtxt",\n            video_flow_step="configure",\n        )\n        await _show_video_creation_screen(callback, state)\n        await callback.answer("Grok Imagine работает через стартовое фото")\n        await state.set_state(GenerationStates.waiting_for_video_prompt)\n        return\n\n    updates = {"v_type": "text", "video_flow_step": "configure"}\n    if current_model.startswith("veo3"):\n        updates["veo_generation_type"] = "TEXT_2_VIDEO"\n    await state.update_data(**updates)\n    await _show_video_creation_screen(callback, state)\n    await callback.answer()\n    await state.set_state(GenerationStates.waiting_for_video_prompt)\n'''

OLD_V_TYPE_IMGTXT = '''@router.callback_query(F.data == "v_type_imgtxt")\nasync def handle_v_type_imgtxt(callback: types.CallbackQuery, state: FSMContext):\n    """Выбор типа генерации: фото+текст."""\n    data = await state.get_data()\n    current_model = data.get("v_model", "v26_pro")\n\n    updates = {"v_type": "imgtxt"}\n    if current_model.startswith("veo3"):\n        updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"\n    await state.update_data(**updates)\n    await _show_video_media_screen(callback, state)\n    await callback.answer()\n    await state.set_state(GenerationStates.waiting_for_video_prompt)\n'''

NEW_V_TYPE_IMGTXT = '''@router.callback_query(F.data == "v_type_imgtxt")\nasync def handle_v_type_imgtxt(callback: types.CallbackQuery, state: FSMContext):\n    """Переключает единый видео-экран в image-to-video."""\n    data = await state.get_data()\n    current_model = data.get("v_model", "v3_std")\n\n    updates = {"v_type": "imgtxt", "video_flow_step": "configure"}\n    if current_model.startswith("veo3"):\n        updates["veo_generation_type"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"\n    await state.update_data(**updates)\n    await _show_video_creation_screen(callback, state)\n    await callback.answer()\n    await state.set_state(GenerationStates.waiting_for_video_prompt)\n'''

OLD_V_TYPE_VIDEO = '''@router.callback_query(F.data == "v_type_video")\nasync def handle_v_type_video(callback: types.CallbackQuery, state: FSMContext):\n    """Выбор типа генерации: видео+текст."""\n    data = await state.get_data()\n    current_model = data.get("v_model")\n    if current_model in _GROK_VIDEO_MODELS:\n        await state.update_data(v_type="imgtxt")\n        await _show_video_media_screen(callback, state)\n        await callback.answer("Grok Imagine принимает фото, а не видео-референс")\n        return\n    selected_model = choose_video_reference_model(current_model)\n    updates = {"v_type": "video", "v_duration": 5, "v_model": selected_model}\n    await state.update_data(**updates)\n    await _show_video_media_screen(callback, state)\n    if selected_model != current_model:\n        await callback.answer("Для видео-референсов выбрана Seedance 2.0")\n    else:\n        await callback.answer("Загрузите видео-референсы")\n'''

NEW_V_TYPE_VIDEO = '''@router.callback_query(F.data == "v_type_video")\nasync def handle_v_type_video(callback: types.CallbackQuery, state: FSMContext):\n    """Переключает единый видео-экран в video-to-video/reference mode."""\n    data = await state.get_data()\n    current_model = data.get("v_model")\n    if current_model in _GROK_VIDEO_MODELS:\n        await state.update_data(\n            v_type="imgtxt",\n            video_flow_step="configure",\n        )\n        await _show_video_creation_screen(callback, state)\n        await callback.answer("Grok Imagine принимает фото, а не видео-референс")\n        await state.set_state(GenerationStates.waiting_for_video_prompt)\n        return\n\n    selected_model = choose_video_reference_model(current_model)\n    await state.update_data(\n        v_type="video",\n        v_duration=5,\n        v_model=selected_model,\n        video_flow_step="configure",\n    )\n    await _show_video_creation_screen(callback, state)\n    if selected_model != current_model:\n        await callback.answer("Для видео-референсов выбрана Seedance 2.0")\n    else:\n        await callback.answer("Загрузите видео-референсы")\n    await state.set_state(GenerationStates.uploading_reference_videos)\n'''

OLD_CREATION_STEP_TITLE = '        f"<b>Шаг 3. Настройки и промпт</b>\\n"\n'
NEW_CREATION_STEP_TITLE = '        f"<b>Тип, модель и настройки — на одном экране</b>\\n"\n'


def _replace_once_or_verify(text: str, old: str, new: str, *, context: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise RuntimeError(f"{context} anchor was not found")


def _patch_keyboards() -> None:
    text = KEYBOARDS_PATH.read_text(encoding="utf-8")
    if VIDEO_UI_IMPORT_AND_WRAP not in text:
        text = text.rstrip() + VIDEO_UI_IMPORT_AND_WRAP
    if text.count("happyfox_dynamic_video_keyboard(get_create_video_keyboard)") != 1:
        raise RuntimeError("HappyFox dynamic video keyboard must be installed exactly once")
    KEYBOARDS_PATH.write_text(text, encoding="utf-8")


def _patch_generation() -> None:
    text = GENERATION_PATH.read_text(encoding="utf-8")
    replacements = (
        (OLD_CREATE_VIDEO_ENTRY, NEW_CREATE_VIDEO_ENTRY, "HappyFox video entry"),
        (OLD_V_TYPE_TEXT, NEW_V_TYPE_TEXT, "HappyFox text video type"),
        (OLD_V_TYPE_IMGTXT, NEW_V_TYPE_IMGTXT, "HappyFox image video type"),
        (OLD_V_TYPE_VIDEO, NEW_V_TYPE_VIDEO, "HappyFox reference video type"),
        (OLD_CREATION_STEP_TITLE, NEW_CREATION_STEP_TITLE, "HappyFox video screen title"),
    )
    for old, new, context in replacements:
        text = _replace_once_or_verify(text, old, new, context=context)

    create_entry = text.split('@router.callback_query(F.data == "create_video_new")', 1)[1]
    create_entry = create_entry.split("@router.callback_query", 1)[0]
    if "_show_video_model_selection_screen" in create_entry:
        raise RuntimeError("HappyFox video entry still opens the model wizard")
    if 'video_flow_step="configure"' not in create_entry:
        raise RuntimeError("HappyFox video entry is not configured as a one-screen flow")

    GENERATION_PATH.write_text(text, encoding="utf-8")


def apply_happyfox_video_ui() -> None:
    _patch_keyboards()
    _patch_generation()


if __name__ == "__main__":
    apply_happyfox_video_ui()
