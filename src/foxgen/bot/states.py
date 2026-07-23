from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    choosing_model = State()
    waiting_prompt = State()
    waiting_media = State()
    choosing_options = State()
    confirming = State()
    submitting = State()
