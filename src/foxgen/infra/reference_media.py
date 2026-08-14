from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import quote
from uuid import UUID

import boto3
from botocore.config import Config

from foxgen.application.reference_memory import ReferenceAssetSnapshot
from foxgen.core.errors import ErrorCode, SubmissionError


@dataclass(slots=True)
class ReferenceObjectStream:
    content_type: str
    size_bytes: int
    _body: Any

    async def chunks(self, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await asyncio.to_thread(self._body.read, chunk_size)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise SubmissionError(
                        ErrorCode.PROVIDER_PROTOCOL,
                        "Хранилище вернуло повреждённый референс.",
                    )
                yield chunk
        finally:
            await asyncio.to_thread(self._body.close)


class S3ReferenceMediaReader:
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        force_path_style: bool,
    ) -> None:
        addressing_style = "path" if force_path_style else "virtual"
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(s3={"addressing_style": addressing_style}),
        )
        self._bucket = bucket

    async def open(self, storage_key: str) -> ReferenceObjectStream:
        response = await asyncio.to_thread(
            self._client.get_object,
            Bucket=self._bucket,
            Key=storage_key,
        )
        body = response.get("Body")
        if body is None:
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Хранилище не вернуло содержимое референса.",
            )
        content_type = response.get("ContentType")
        content_length = response.get("ContentLength")
        return ReferenceObjectStream(
            content_type=(
                content_type if isinstance(content_type, str) else "application/octet-stream"
            ),
            size_bytes=(
                int(content_length)
                if isinstance(content_length, int) and content_length >= 0
                else 0
            ),
            _body=body,
        )


def sign_reference_media_url(asset_id: UUID, expires_at: int, secret: str) -> str:
    payload = f"reference-media\n{asset_id}\n{expires_at}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class ReferenceMediaUrlSigner:
    def __init__(
        self,
        *,
        public_base_url: str,
        secret: str,
        ttl_seconds: int,
    ) -> None:
        self._base_url = public_base_url.rstrip("/")
        self._secret = secret
        self._ttl_seconds = ttl_seconds

    async def url(self, asset_id: UUID) -> str:
        expires_at = int(time.time()) + self._ttl_seconds
        signature = sign_reference_media_url(asset_id, expires_at, self._secret)
        return (
            f"{self._base_url}/v1/reference-media/{quote(str(asset_id), safe='')}"
            f"?expires={expires_at}&signature={signature}"
        )

    def verify(self, *, asset_id: UUID, expires_at: int, signature: str) -> None:
        if expires_at < int(time.time()):
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Ссылка на сохранённый референс истекла.",
            )
        expected = sign_reference_media_url(asset_id, expires_at, self._secret)
        if not hmac.compare_digest(signature, expected):
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Ссылка на сохранённый референс недействительна.",
            )


class ReferenceMediaRepositoryProtocol:
    async def get_active_by_id(self, asset_id: UUID) -> ReferenceAssetSnapshot | None: ...


class ReferenceMediaDelivery:
    def __init__(
        self,
        *,
        repository: ReferenceMediaRepositoryProtocol,
        reader: S3ReferenceMediaReader,
        signer: ReferenceMediaUrlSigner,
    ) -> None:
        self._repository = repository
        self._reader = reader
        self._signer = signer

    async def open(
        self,
        *,
        asset_id: UUID,
        expires_at: int,
        signature: str,
    ) -> ReferenceObjectStream:
        self._signer.verify(
            asset_id=asset_id,
            expires_at=expires_at,
            signature=signature,
        )
        asset = await self._repository.get_active_by_id(asset_id)
        if asset is None:
            raise SubmissionError(
                ErrorCode.TASK_NOT_FOUND,
                "Сохранённый референс больше недоступен.",
            )
        stream = await self._reader.open(asset.storage_key)
        if stream.size_bytes and stream.size_bytes != asset.size_bytes:
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Размер сохранённого референса не совпадает с метаданными.",
            )
        return stream
