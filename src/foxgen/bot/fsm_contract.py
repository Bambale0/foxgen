from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from foxgen.bot.states import FeedStates, GenerationStates


@dataclass(frozen=True, slots=True)
class StateContract:
    success: tuple[str, ...]
    back: str
    cancel: str
    timeout: str
    invalid_input: str
    stale_callback: str


_TO_MENU = "clear state and show main menu"
_EXPIRED = "clear state and explain that the draft expired"
_KEEP = "keep state and repeat the expected input"
_STALE = "keep state for an invalid current callback; clear only when state is absent"


STATE_CONTRACTS: Mapping[str, StateContract] = MappingProxyType(
    {
        GenerationStates.quick_start_waiting_media.state: StateContract(
            success=(GenerationStates.reference_choosing_product.state,),
            back=_TO_MENU,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request one photo or video",
            stale_callback=_STALE,
        ),
        GenerationStates.reference_choosing_product.state: StateContract(
            success=(GenerationStates.reference_choosing_model.state,),
            back=GenerationStates.quick_start_waiting_media.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat photo/video result choice",
            stale_callback=_STALE,
        ),
        GenerationStates.reference_choosing_model.state: StateContract(
            success=(
                GenerationStates.reference_waiting_prompt.state,
                GenerationStates.choosing_aspect_ratio.state,
            ),
            back=GenerationStates.reference_choosing_product.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat compatible model choices",
            stale_callback=_STALE,
        ),
        GenerationStates.reference_waiting_prompt.state: StateContract(
            success=(
                GenerationStates.choosing_aspect_ratio.state,
                GenerationStates.confirming.state,
            ),
            back=GenerationStates.reference_choosing_model.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request text",
            stale_callback=_STALE,
        ),
        GenerationStates.choosing_mode.state: StateContract(
            success=(GenerationStates.choosing_model.state,),
            back=_TO_MENU,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat mode choices",
            stale_callback=_STALE,
        ),
        GenerationStates.choosing_model.state: StateContract(
            success=(GenerationStates.waiting_prompt.state,),
            back="generation mode or cancel feed remix",
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat compatible model choices",
            stale_callback=_STALE,
        ),
        GenerationStates.waiting_prompt.state: StateContract(
            success=(
                GenerationStates.waiting_media.state,
                GenerationStates.choosing_aspect_ratio.state,
                GenerationStates.confirming.state,
            ),
            back=GenerationStates.choosing_model.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request text",
            stale_callback=_STALE,
        ),
        GenerationStates.waiting_media.state: StateContract(
            success=(GenerationStates.choosing_aspect_ratio.state,),
            back=GenerationStates.waiting_prompt.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat compatible media requirements",
            stale_callback=_STALE,
        ),
        GenerationStates.choosing_aspect_ratio.state: StateContract(
            success=(
                GenerationStates.choosing_quality.state,
                GenerationStates.choosing_duration.state,
                GenerationStates.confirming.state,
            ),
            back="prompt/media step selected by draft entrypoint",
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat aspect-ratio choices",
            stale_callback=_STALE,
        ),
        GenerationStates.choosing_quality.state: StateContract(
            success=(GenerationStates.confirming.state,),
            back=GenerationStates.choosing_aspect_ratio.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat quality choices",
            stale_callback=_STALE,
        ),
        GenerationStates.choosing_duration.state: StateContract(
            success=(GenerationStates.choosing_audio.state,),
            back=GenerationStates.choosing_aspect_ratio.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat duration choices",
            stale_callback=_STALE,
        ),
        GenerationStates.choosing_audio.state: StateContract(
            success=(GenerationStates.confirming.state,),
            back=GenerationStates.choosing_duration.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat audio choices",
            stale_callback=_STALE,
        ),
        GenerationStates.confirming.state: StateContract(
            success=(GenerationStates.submitting.state,),
            back="last model-specific option",
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat confirmation actions",
            stale_callback=_STALE,
        ),
        GenerationStates.submitting.state: StateContract(
            success=(_TO_MENU,),
            back="blocked while atomic admission is in progress",
            cancel="blocked while atomic admission is in progress",
            timeout="recover from durable generation/idempotency state",
            invalid_input="report that generation is already launching",
            stale_callback="resolve through durable generation/idempotency state",
        ),
        FeedStates.waiting_comment.state: StateContract(
            success=(_TO_MENU,),
            back="cancel comment and return to publication",
            cancel="clear comment draft without mutating the publication",
            timeout=_EXPIRED,
            invalid_input="keep state and request text up to 300 characters",
            stale_callback=_STALE,
        ),
    }
)


def contract_for(state_name: str | None) -> StateContract | None:
    if state_name is None:
        return None
    return STATE_CONTRACTS.get(state_name)


def is_reference_draft(data: Mapping[str, object]) -> bool:
    return data.get("entrypoint") == "reference"
