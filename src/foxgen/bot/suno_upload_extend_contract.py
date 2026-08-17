from __future__ import annotations

from foxgen.bot.states import MusicUploadExtendStates

UPLOAD_EXTEND_STATE_NAMES: frozenset[str] = frozenset(
    state_name
    for state in MusicUploadExtendStates.__all_states__
    if (state_name := state.state) is not None
)


def is_upload_extend_state(state_name: str | None) -> bool:
    return state_name in UPLOAD_EXTEND_STATE_NAMES if state_name is not None else False
