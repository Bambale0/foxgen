import asyncio

from bot import database
from bot.max_admin_channel import MaxAdminChannelService
from bot.max_admin_store import (
    create_max_admin_invite,
    grant_max_admin,
    is_max_admin,
)
from bot.max_api import MaxSettings


class FakeMaxClient:
    def __init__(self) -> None:
        self.sent = []
        self.answers = []

    async def send_message(self, user_id, text, *, attachments=None, format="html", notify=True):
        self.sent.append(
            {
                "user_id": user_id,
                "text": text,
                "attachments": attachments,
                "format": format,
                "notify": notify,
            }
        )
        return {"ok": True}

    async def answer_callback(self, callback_id, *, message=None):
        self.answers.append({"callback_id": callback_id, "message": message})
        return {"success": True}


class FakePayments:
    enabled = True


def _prepare_database(database_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", str(database_path))
    asyncio.run(database.init_db())


def _service() -> tuple[MaxAdminChannelService, FakeMaxClient]:
    client = FakeMaxClient()
    service = MaxAdminChannelService(
        settings=MaxSettings(
            enabled=True,
            access_token="token",
            webhook_secret="valid_secret",
            mini_app_url="https://example.invalid/mini-app/",
        ),
        client=client,
        payments=FakePayments(),
        bot_name="happyfox_bot",
        support_contact="https://max.ru/happyfox-support",
    )
    return service, client


def _callback(user_id: int, callback_id: str, payload: str) -> dict:
    return {
        "update_type": "message_callback",
        "callback": {
            "callback_id": callback_id,
            "payload": payload,
            "user": {"user_id": user_id, "first_name": "Creator"},
        },
    }


def _started(user_id: int, first_name: str, payload: str = "") -> dict:
    return {
        "update_type": "bot_started",
        "user": {"user_id": user_id, "first_name": first_name},
        "payload": payload,
    }


def _callback_payloads(message: dict) -> set[str]:
    rows = message["attachments"][0]["payload"]["buttons"]
    return {
        button.get("payload")
        for row in rows
        for button in row
        if button.get("type") == "callback"
    }


def test_max_admin_role_is_database_backed_and_controls_menu(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-admin-role.db", monkeypatch)
    service, client = _service()

    asyncio.run(service.handle_update(_started(1001, "Creator")))
    assert "max:admin" not in _callback_payloads(client.sent[-1])

    asyncio.run(grant_max_admin(1001, display_name="Игорь", granted_by="owner"))
    assert asyncio.run(is_max_admin(1001)) is True

    asyncio.run(service.handle_update(_callback(1001, "home", "max:home")))
    assert "max:admin" in _callback_payloads(client.answers[-1]["message"])

    asyncio.run(service.handle_update(_callback(1001, "admin", "max:admin")))
    assert "Админ-панель MAX" in client.answers[-1]["message"]["text"]


def test_non_admin_cannot_open_max_admin_screen_directly(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-admin-denied.db", monkeypatch)
    service, client = _service()

    asyncio.run(service.handle_update(_started(2001, "Guest")))
    asyncio.run(service.handle_update(_callback(2001, "admin", "max:admin")))

    assert asyncio.run(is_max_admin(2001)) is False
    assert "нет доступа" in client.answers[-1]["message"]["text"].lower()


def test_one_time_admin_invite_binds_real_max_user_id(tmp_path, monkeypatch) -> None:
    _prepare_database(tmp_path / "max-admin-invite.db", monkeypatch)
    service, client = _service()

    token = asyncio.run(create_max_admin_invite("Алена"))
    asyncio.run(service.handle_update(_started(3001, "Alena", f"admin_{token}")))

    assert asyncio.run(is_max_admin(3001)) is True
    assert any("Права администратора MAX активированы" in item["text"] for item in client.sent)

    other_service, other_client = _service()
    asyncio.run(other_service.handle_update(_started(3002, "Other", f"admin_{token}")))

    assert asyncio.run(is_max_admin(3002)) is False
    assert any("недействительна или уже использована" in item["text"] for item in other_client.sent)
