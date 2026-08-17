from __future__ import annotations

from foxgen.bot.states import MusicCoverStates, MusicUploadExtendStates


COVER_STATE_NAMES: frozenset[str] = frozenset(
    state.state for state in MusicCoverStates.__all_states__
)
MUSIC_UPLOAD_STATE_NAMES: frozenset[str] = COVER_STATE_NAMES | frozenset(
    state.state for state in MusicUploadExtendStates.__all_states__
)


def is_cover_state(state_name: str | None) -> bool:
    """Legacy shell guard for dedicated uploaded-audio music FSMs.

    The public name is retained to avoid a broad shell refactor in the product slice.
    COVER_STATE_NAMES remains Cover-only for callers that need exact Cover membership.
    """

    return state_name in MUSIC_UPLOAD_STATE_NAMES if state_name is not None else False
