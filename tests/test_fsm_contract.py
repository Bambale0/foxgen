from foxgen.bot.fsm_contract import STATE_CONTRACTS, contract_for, is_reference_draft
from foxgen.bot.states import GenerationStates, MusicExtendStates, MusicStates, VoiceStates


def test_every_declared_product_state_has_a_behavior_contract() -> None:
    declared = {
        *(state.state for state in GenerationStates.__all_states__),
        *(state.state for state in VoiceStates.__all_states__),
        *(state.state for state in MusicStates.__all_states__),
        *(state.state for state in MusicExtendStates.__all_states__),
    }

    assert set(STATE_CONTRACTS) == declared


def test_every_state_contract_defines_all_exit_classes() -> None:
    for state_name, contract in STATE_CONTRACTS.items():
        assert state_name
        assert contract.success
        assert contract.back
        assert contract.cancel
        assert contract.timeout
        assert contract.invalid_input
        assert contract.stale_callback


def test_unknown_or_expired_state_has_no_live_contract() -> None:
    assert contract_for(None) is None
    assert contract_for("GenerationStates:removed_state") is None
    assert contract_for("VoiceStates:removed_state") is None
    assert contract_for("MusicStates:removed_state") is None
    assert contract_for("MusicExtendStates:removed_state") is None


def test_reference_entrypoint_is_explicit_not_inferred_from_media() -> None:
    assert is_reference_draft({"entrypoint": "reference", "media": []}) is True
    assert is_reference_draft({"entrypoint": "menu", "media": [{"kind": "image"}]}) is False
    assert is_reference_draft({"media": [{"kind": "image"}]}) is False
