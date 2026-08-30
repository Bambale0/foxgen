import asyncio
import json
from types import SimpleNamespace

from bot import internal_api, internal_api_db


def test_internal_health_exposes_happyfox_identity(monkeypatch):
    async def db_ok() -> bool:
        return True

    monkeypatch.setattr(internal_api_db, "simple_db_query_ok", db_ok)
    request = SimpleNamespace(app={"bot_version": "test-revision"})

    response = asyncio.run(internal_api.handle_internal_health(request))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["service"] == "happyfox-backend"
    assert payload["version"] == "test-revision"
    assert payload["database"] == "connected"
    assert "tanya" not in json.dumps(payload).lower()
    assert "neuromix" not in json.dumps(payload).lower()
