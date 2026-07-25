from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    quick_start_waiting_media = State()
    reference_choosing_product = State()
    reference_choosing_model = State()
    reference_waiting_prompt = State()
    choosing_mode = State()
    choosing_model = State()
    waiting_prompt = State()
    waiting_media = State()
    choosing_aspect_ratio = State()
    choosing_quality = State()
    choosing_duration = State()
    choosing_audio = State()
    confirming = State()
    submitting = State()
