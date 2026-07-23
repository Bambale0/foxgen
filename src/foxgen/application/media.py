import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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


class MediaDownloader(Protocol):
    async def download(self, url: str) -> DownloadedMedia: ...


class MediaStorage(Protocol):
    async def store(self, *, key: str, media: DownloadedMedia) -> StoredMedia: ...

    async def presigned_url(self, storage_key: str) -> str: ...


class MediaSender(Protocol):
    async def send(
        self,
        *,
        recipient_id: int,
        urls: list[str],
        caption: str,
    ) -> list[int]: ...


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
