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

    # Durable reference-memory browser. Selection/navigation is ephemeral Redis
    # FSM state; the image bytes and ownership metadata are durable S3/PostgreSQL state.
    reference_memory_browsing = State()
    reference_memory_adding = State()

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


class VoiceStates(StatesGroup):
    waiting_text = State()
    waiting_voice = State()
    choosing_speed = State()
    confirming = State()
    submitting = State()


class MusicStates(StatesGroup):
    choosing_mode = State()
    choosing_vocal_mode = State()
    waiting_prompt = State()
    waiting_style = State()
    waiting_title = State()
    confirming = State()
    submitting = State()


class MusicExtendStates(StatesGroup):
    choosing_action = State()
    choosing_source = State()
    choosing_mode = State()
    waiting_prompt = State()
    waiting_style = State()
    waiting_title = State()
    waiting_continue_at = State()
    confirming = State()
    submitting = State()


class MusicCoverStates(StatesGroup):
    waiting_audio = State()
    choosing_mode = State()
    choosing_vocal_mode = State()
    waiting_prompt = State()
    waiting_style = State()
    waiting_title = State()
    confirming = State()
    submitting = State()


class MusicUploadExtendStates(StatesGroup):
    waiting_audio = State()
    choosing_mode = State()
    choosing_vocal_mode = State()
    waiting_prompt = State()
    waiting_style = State()
    waiting_title = State()
    waiting_continue_at = State()
    confirming = State()
    submitting = State()


class FeedStates(StatesGroup):
    waiting_comment = State()
    editing_profile_slug = State()
    editing_profile_name = State()
    editing_profile_bio = State()
    waiting_publish_generation = State()
    choosing_publish_scope = State()
