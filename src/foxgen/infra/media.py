import asyncio
import hashlib
import ipaddress
import mimetypes
import os
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlparse

import boto3  # type: ignore[import-untyped]
import httpx
from aiogram import Bot
from botocore.config import Config  # type: ignore[import-untyped]

from foxgen.core.errors import ErrorCode, SubmissionError


@dataclass(frozen=True, slots=True)
class DownloadedMedia:
    path: Path
    filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str

    def cleanup(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class StoredMedia:
    storage_key: str
    content_type: str
    size_bytes: int
    checksum_sha256: str


class SecureMediaDownloader:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_bytes: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 15.0)),
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._max_bytes = max_bytes

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def download(self, url: str) -> DownloadedMedia:
        await _validate_public_https_url(url)
        try:
            async with self._client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise SubmissionError(
                        ErrorCode.PROVIDER_PROTOCOL,
                        "Провайдер вернул перенаправление вместо медиафайла.",
                    )
                response.raise_for_status()
                declared_size = _content_length(response.headers.get("Content-Length"))
                if declared_size is not None and declared_size > self._max_bytes:
                    raise SubmissionError(
                        ErrorCode.PROVIDER_REJECTED,
                        "Результат генерации превышает допустимый размер.",
                        details={"declared_size": declared_size, "max_bytes": self._max_bytes},
                    )

                content_type = (
                    response.headers.get("Content-Type", "application/octet-stream")
                    .partition(";")[0]
                    .strip()
                    or "application/octet-stream"
                )
                filename = _safe_filename(url, content_type)
                digest = hashlib.sha256()
                size = 0
                temporary = tempfile.NamedTemporaryFile(prefix="foxgen-", delete=False)
                path = Path(temporary.name)
                try:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise SubmissionError(
                                ErrorCode.PROVIDER_REJECTED,
                                "Результат генерации превышает допустимый размер.",
                                details={"max_bytes": self._max_bytes},
                            )
                        digest.update(chunk)
                        temporary.write(chunk)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                except Exception:
                    temporary.close()
                    path.unlink(missing_ok=True)
                    raise
                finally:
                    if not temporary.closed:
                        temporary.close()
        except httpx.HTTPStatusError as exc:
            raise SubmissionError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Не удалось скачать результат генерации у провайдера.",
                retryable=exc.response.status_code >= 500,
                details={"status": exc.response.status_code},
            ) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SubmissionError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Временная ошибка при скачивании результата генерации.",
                retryable=True,
            ) from exc

        return DownloadedMedia(
            path=path,
            filename=filename,
            content_type=content_type,
            size_bytes=size,
            checksum_sha256=digest.hexdigest(),
        )


class S3MediaStorage:
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        force_path_style: bool,
        presigned_url_ttl_seconds: int,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket is required")
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
        self._ttl = presigned_url_ttl_seconds

    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia:
        await asyncio.to_thread(self._put_file, key, media)
        return StoredMedia(
            storage_key=key,
            content_type=media.content_type,
            size_bytes=media.size_bytes,
            checksum_sha256=media.checksum_sha256,
        )

    def _put_file(self, key: str, media: DownloadedMedia) -> None:
        with media.path.open("rb") as body:
            self._put_object(key=key, body=body, content_type=media.content_type)

    def _put_object(self, *, key: str, body: BinaryIO, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata={"sha256": "foxgen-managed"},
        )

    async def presigned_url(self, storage_key: str) -> str:
        value = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": storage_key},
            ExpiresIn=self._ttl,
        )
        if not isinstance(value, str) or not value:
            raise SubmissionError(
                ErrorCode.PROVIDER_PROTOCOL,
                "Не удалось подготовить ссылку на сохранённый результат.",
            )
        return value

    async def ping(self) -> None:
        await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)


class TelegramMediaSender:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(
        self,
        *,
        recipient_id: int,
        urls: list[str],
        caption: str,
    ) -> list[int]:
        message_ids: list[int] = []
        for index, url in enumerate(urls):
            message = await self._bot.send_document(
                chat_id=recipient_id,
                document=url,
                caption=caption if index == 0 else None,
                disable_content_type_detection=False,
            )
            message_ids.append(message.message_id)
        return message_ids


def storage_key_for(
    *,
    generation_id: str,
    index: int,
    media: DownloadedMedia,
) -> str:
    suffix = Path(media.filename).suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(media.content_type) or ".bin"
    return (
        f"generations/{generation_id}/{index:03d}-"
        f"{media.checksum_sha256[:24]}{suffix[:16]}"
    )


def extract_result_urls(payload: dict[str, object]) -> tuple[str, ...]:
    collected: list[str] = []

    def visit(value: object, *, key_hint: str = "") -> None:
        if isinstance(value, str):
            if "url" in key_hint.lower() and value.startswith("https://"):
                collected.append(value)
            return
        if isinstance(value, list):
            for item in value:
                visit(item, key_hint=key_hint)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, key_hint=str(key))

    visit(payload)
    return tuple(dict.fromkeys(collected))


async def _validate_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Результат провайдера содержит небезопасную ссылку.",
        )
    port = parsed.port or 443
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise SubmissionError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Не удалось разрешить адрес медиафайла провайдера.",
            retryable=True,
        ) from exc
    if not infos:
        raise SubmissionError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Провайдер вернул недоступный адрес медиафайла.",
            retryable=True,
        )
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Результат провайдера ссылается на закрытый сетевой адрес.",
            )


def _content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _safe_filename(url: str, content_type: str) -> str:
    raw_name = unquote(Path(urlparse(url).path).name)
    clean = "".join(character for character in raw_name if character.isalnum() or character in "-_.")
    if clean and len(clean) <= 120:
        return clean
    extension = mimetypes.guess_extension(content_type) or ".bin"
    return f"result{extension}"
