from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    # Screen-level generation wizard. The state names intentionally describe
    # the current user-visible screen, mirroring the proven tanyapi flow.
    image_selecting_model = State()
    image_uploading_references = State()
    image_configuring = State()
    image_waiting_prompt = State()
    video_selecting_model = State()
    video_selecting_type = State()
    video_uploading_media = State()
    video_configuring = State()
    video_waiting_prompt = State()

    # Quick Start/reference entrypoints keep their dedicated states so stored
    # Telegram inputs remain recoverable across navigation.
    quick_start_waiting_media = State()
    reference_choosing_product = State()
    reference_choosing_model = State()
    reference_waiting_prompt = State()

    # Legacy generation states remain during the migration window. Existing
    # Redis drafts from the previous release can still recover instead of
    # becoming unknown state names after deploy.
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
