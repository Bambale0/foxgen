from foxgen.bot.generation_draft import WIZARD_VERSION
from foxgen.bot.uploads import stored_input_keys


def test_reference_memory_keeps_deployed_wizard_version_compatible() -> None:
    assert WIZARD_VERSION == "screen-v2"


def test_global_cleanup_ignores_durable_reference_ids() -> None:
    data: dict[str, object] = {
        "media": [
            {"kind": "image", "storage_key": "inputs/42/temporary.png"},
            {"kind": "image", "reference_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        ]
    }

    assert stored_input_keys(data) == ("inputs/42/temporary.png",)
