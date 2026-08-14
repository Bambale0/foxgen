import hashlib
import hmac
import mimetypes
import os
import shutil
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from foxgen.application.media import DownloadedMedia, StoredMedia
from foxgen.core.errors import ErrorCode, SubmissionError


def sign_local_input_media_url(storage_key: str, expires_at: int, secret: str) -> str:
    payload = f"{storage_key}\n{expires_at}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def local_input_media_url(
    *,
    base_url: str,
    storage_key: str,
    expires_at: int,
    secret: str,
) -> str:
    signature = sign_local_input_media_url(storage_key, expires_at, secret)
    quoted = quote(storage_key, safe="/")
    return (
        f"{base_url.rstrip('/')}/v1/input-media/{quoted}"
        f"?expires={expires_at}&signature={signature}"
    )


def normalize_input_storage_key(storage_key: str) -> str:
    candidate = storage_key.strip()
    normalized = str(PurePosixPath("/" + candidate).relative_to("/"))
    if not normalized.startswith("inputs/") or normalized.startswith("inputs/../"):
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик содержит некорректную ссылку на входной файл.",
        )
    return normalized


def resolve_input_media_path(root: Path, storage_key: str) -> Path:
    normalized = normalize_input_storage_key(storage_key)
    path = (root / normalized).resolve()
    resolved_root = root.resolve()
    if not path.is_relative_to(resolved_root):
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Черновик содержит некорректную ссылку на входной файл.",
        )
    return path


class LocalInputMediaStorage:
    def __init__(
        self,
        *,
        root: str | Path,
        public_base_url: str,
        signing_secret: str,
        presigned_url_ttl_seconds: int,
        retention_seconds: int,
    ) -> None:
        self._root = Path(root)
        self._public_base_url = public_base_url.rstrip("/")
        self._signing_secret = signing_secret
        self._ttl = presigned_url_ttl_seconds
        self._retention_seconds = retention_seconds

    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia:
        await self._prune_expired_inputs()
        path = resolve_input_media_path(self._root, key)
        await _copy_into_storage(path, media.path)
        return StoredMedia(
            storage_key=normalize_input_storage_key(key),
            content_type=media.content_type,
            size_bytes=media.size_bytes,
            checksum_sha256=media.checksum_sha256,
        )

    async def delete(self, storage_key: str) -> None:
        path = resolve_input_media_path(self._root, storage_key)
        await _delete_if_exists(path)
        await _delete_empty_parents(path.parent, self._root / "inputs")

    async def presigned_url(self, storage_key: str) -> str:
        normalized = normalize_input_storage_key(storage_key)
        expires_at = int(time.time()) + self._ttl
        return local_input_media_url(
            base_url=self._public_base_url,
            storage_key=normalized,
            expires_at=expires_at,
            secret=self._signing_secret,
        )

    async def validate_request(self, storage_key: str, expires_at: int, signature: str) -> Path:
        normalized = normalize_input_storage_key(storage_key)
        expected = sign_local_input_media_url(normalized, expires_at, self._signing_secret)
        if expires_at < int(time.time()):
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Ссылка на входной файл истекла.",
            )
        if not hmac.compare_digest(signature, expected):
            raise SubmissionError(
                ErrorCode.AUTHORIZATION,
                "Ссылка на входной файл недействительна.",
            )
        path = resolve_input_media_path(self._root, normalized)
        if not path.exists():
            raise SubmissionError(
                ErrorCode.TASK_NOT_FOUND,
                "Входной файл не найден.",
            )
        return path

    async def _prune_expired_inputs(self) -> None:
        cutoff = time.time() - self._retention_seconds
        inputs_root = (self._root / "inputs").resolve()
        if not inputs_root.exists():
            return
        for path in inputs_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
        await _delete_empty_parents(inputs_root, inputs_root)


async def _copy_into_storage(destination: Path, source: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    temporary.replace(destination)


async def _delete_if_exists(path: Path) -> None:
    path.unlink(missing_ok=True)


async def _delete_empty_parents(path: Path, stop_at: Path) -> None:
    current = path
    while current != stop_at and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
    if stop_at.exists():
        try:
            stop_at.rmdir()
        except OSError:
            return


def input_media_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(path.name)
    return content_type or "application/octet-stream"
