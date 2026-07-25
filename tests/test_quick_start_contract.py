from foxgen.bot.quick_start import _reference_choice_text, _stored_input
from foxgen.bot.states import GenerationStates


def test_quick_start_states_are_explicit() -> None:
    assert GenerationStates.quick_start_waiting_media.state.endswith(
        ":quick_start_waiting_media"
    )
    assert GenerationStates.reference_choosing_product.state.endswith(
        ":reference_choosing_product"
    )
    assert GenerationStates.reference_choosing_model.state.endswith(
        ":reference_choosing_model"
    )
    assert GenerationStates.reference_waiting_prompt.state.endswith(
        ":reference_waiting_prompt"
    )


def test_reference_storage_contract_rejects_partial_values() -> None:
    valid = {"kind": "image", "storage_key": "inputs/1/reference.jpg"}

    assert _stored_input(valid) == valid
    assert _stored_input({"kind": "image"}) is None
    assert _stored_input({"storage_key": "inputs/1/reference.jpg"}) is None
    assert _stored_input("inputs/1/reference.jpg") is None


def test_reference_choice_copy_does_not_hide_video_to_photo_limitation() -> None:
    assert "Что создать по этому фото" in _reference_choice_text("image", False)
    assert "обложка видео" in _reference_choice_text("video", True)
    assert "отправьте нужный кадр отдельно" in _reference_choice_text("video", False)
