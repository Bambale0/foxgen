from __future__ import annotations

from foxgen.bot.states import MusicCoverStates


COVER_STATE_NAMES: frozenset[str] = frozenset(
    state.state for state in MusicCoverStates.__all_states__
)


def is_cover_state(state_name: str | None) -> bool:
    return state_name in COVER_STATE_NAMES if state_name is not None else False
