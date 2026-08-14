import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from fastapi.testclient import TestClient

from foxgen.api.app import create_app
from foxgen.application.media import DownloadedMedia
from foxgen.bot.quick_start import REFERENCE_DRAFT
from foxgen.core.config import Settings
from foxgen.core.errors import SubmissionError
from foxgen.infra.input_media import (
    LocalInputMediaStorage,
    local_input_media_url,
    resolve_input_media_path,
)


class StubState:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)


async def test_reference_filter_accepts_callback_and_state() -> None:
    state = StubState({"entrypoint": "reference"})

    result = await REFERENCE_DRAFT(
        cast(CallbackQuery, object()),
        cast(FSMContext, state),
    )

    assert result is True


def test_local_input_storage_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(SubmissionError):
        resolve_input_media_path(tmp_path, "../secret.txt")


async def test_local_input_storage_persists_and_deletes_input_file(tmp_path: Path) -> None:
    source = NamedTemporaryFile(delete=False)
    try:
        source.write(b"foxgen-input")
        source.flush()
        media = DownloadedMedia(
            path=Path(source.name),
            filename="reference.jpg",
            content_type="image/jpeg",
            size_bytes=12,
            checksum_sha256="a" * 64,
        )
    finally:
        source.close()

    storage = LocalInputMediaStorage(
        root=tmp_path,
        public_base_url="https://foxgen.example.com",
        signing_secret="secret",
        presigned_url_ttl_seconds=600,
        retention_seconds=3600,
    )

    stored = await storage.store(key="inputs/7/reference.jpg", media=media)
    path = tmp_path / stored.storage_key
    assert path.read_bytes() == b"foxgen-input"

    await storage.delete(stored.storage_key)

    assert path.exists() is False


def test_input_media_route_serves_signed_local_file(tmp_path: Path) -> None:
    target = tmp_path / "inputs/7/reference.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"reference-bytes")

    settings = Settings(
        _env_file=None,
        env="test",
        internal_api_token="internal-secret",
        internal_api_base_url="http://testserver",
        telegram_input_storage_root=str(tmp_path),
    )
    expires = int(time.time()) + 600
    url = local_input_media_url(
        base_url="http://testserver",
        storage_key="inputs/7/reference.jpg",
        expires_at=expires,
        secret="internal-secret",
    )
    app = create_app(settings, manage_resources=False)

    with TestClient(app) as client:
        response = client.get(url)

    assert response.status_code == 200
    assert response.content == b"reference-bytes"
    assert response.headers["cache-control"] == "private, no-store"


def test_input_media_route_rejects_expired_signature(tmp_path: Path) -> None:
    target = tmp_path / "inputs/7/reference.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"reference-bytes")

    settings = Settings(
        _env_file=None,
        env="test",
        internal_api_token="internal-secret",
        internal_api_base_url="http://testserver",
        telegram_input_storage_root=str(tmp_path),
    )
    url = local_input_media_url(
        base_url="http://testserver",
        storage_key="inputs/7/reference.jpg",
        expires_at=int(time.time()) - 1,
        secret="internal-secret",
    )
    app = create_app(settings, manage_resources=False)

    with TestClient(app) as client:
        response = client.get(url)

    assert response.status_code == 403
