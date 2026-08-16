from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from foxgen.bot.states import GenerationStates, VoiceStates


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
        GenerationStates.image_selecting_model.state: StateContract(
            success=(GenerationStates.image_uploading_references.state,),
            back=_TO_MENU,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat image model choices",
            stale_callback=_STALE,
        ),
        GenerationStates.image_uploading_references.state: StateContract(
            success=(
                GenerationStates.image_configuring.state,
                GenerationStates.reference_memory_browsing.state,
            ),
            back=GenerationStates.image_selecting_model.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request image references or skip",
            stale_callback=_STALE,
        ),
        GenerationStates.image_configuring.state: StateContract(
            success=(GenerationStates.image_waiting_prompt.state,),
            back=GenerationStates.image_uploading_references.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat dynamic image settings",
            stale_callback=_STALE,
        ),
        GenerationStates.image_waiting_prompt.state: StateContract(
            success=(GenerationStates.confirming.state,),
            back=GenerationStates.image_configuring.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request image prompt text",
            stale_callback=_STALE,
        ),
        GenerationStates.video_selecting_model.state: StateContract(
            success=(GenerationStates.video_selecting_type.state,),
            back=_TO_MENU,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat video model choices",
            stale_callback=_STALE,
        ),
        GenerationStates.video_selecting_type.state: StateContract(
            success=(
                GenerationStates.video_uploading_media.state,
                GenerationStates.video_configuring.state,
            ),
            back=GenerationStates.video_selecting_model.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat video input-type choices",
            stale_callback=_STALE,
        ),
        GenerationStates.video_uploading_media.state: StateContract(
            success=(
                GenerationStates.video_configuring.state,
                GenerationStates.reference_memory_browsing.state,
            ),
            back=GenerationStates.video_selecting_type.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat model/type-specific media requirements",
            stale_callback=_STALE,
        ),
        GenerationStates.video_configuring.state: StateContract(
            success=(GenerationStates.video_waiting_prompt.state,),
            back="video media screen when required, otherwise video type screen",
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat dynamic video settings",
            stale_callback=_STALE,
        ),
        GenerationStates.video_waiting_prompt.state: StateContract(
            success=(GenerationStates.confirming.state,),
            back=GenerationStates.video_configuring.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request video prompt text",
            stale_callback=_STALE,
        ),
        GenerationStates.reference_memory_browsing.state: StateContract(
            success=(
                GenerationStates.reference_memory_adding.state,
                GenerationStates.image_uploading_references.state,
                GenerationStates.video_uploading_media.state,
            ),
            back="return to the origin generation reference screen without applying selection",
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and use memory browser buttons",
            stale_callback=_STALE,
        ),
        GenerationStates.reference_memory_adding.state: StateContract(
            success=(GenerationStates.reference_memory_browsing.state,),
            back=GenerationStates.reference_memory_browsing.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request one image to save",
            stale_callback=_STALE,
        ),
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
            back=GenerationStates.choosing_mode.state,
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
            back="last flow-specific prompt/settings screen",
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
        VoiceStates.waiting_text.state: StateContract(
            success=(VoiceStates.waiting_voice.state,),
            back=_TO_MENU,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request TTS text",
            stale_callback=_STALE,
        ),
        VoiceStates.waiting_voice.state: StateContract(
            success=(VoiceStates.choosing_speed.state,),
            back=VoiceStates.waiting_text.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and request voice name/id or default voice button",
            stale_callback=_STALE,
        ),
        VoiceStates.choosing_speed.state: StateContract(
            success=(VoiceStates.confirming.state,),
            back=VoiceStates.waiting_voice.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat verified speed presets",
            stale_callback=_STALE,
        ),
        VoiceStates.confirming.state: StateContract(
            success=(VoiceStates.submitting.state,),
            back=VoiceStates.choosing_speed.state,
            cancel=_TO_MENU,
            timeout=_EXPIRED,
            invalid_input="keep state and repeat TTS confirmation actions",
            stale_callback=_STALE,
        ),
        VoiceStates.submitting.state: StateContract(
            success=(_TO_MENU,),
            back="blocked while atomic TTS admission is in progress",
            cancel="blocked while atomic TTS admission is in progress",
            timeout="recover from durable generation/idempotency state",
            invalid_input="report that TTS generation is already launching",
            stale_callback="resolve through durable generation/idempotency state",
        ),
    }
)


def contract_for(state_name: str | None) -> StateContract | None:
    if state_name is None:
        return None
    return STATE_CONTRACTS.get(state_name)


def is_reference_draft(data: Mapping[str, object]) -> bool:
    return data.get("entrypoint") == "reference"
