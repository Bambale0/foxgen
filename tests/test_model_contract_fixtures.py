import json
from pathlib import Path

from foxgen.providers.kie.contracts import InputContract, validate_input


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "kie_priority_contract_examples.json"


def test_reviewed_priority_fixtures_match_strict_contracts() -> None:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for contract_name, payload in fixtures.items():
        normalized = validate_input(InputContract(contract_name), payload)
        for key, value in payload.items():
            assert normalized[key] == value
