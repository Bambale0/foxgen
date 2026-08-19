"""
Скачивание результатов генерации с внешних хостов
на backend в static/uploads/feed, чтобы публичная лента не зависела
от TTL, CORS/Range-поведения и доступности хоста провайдера.

Вызывается из share_to_feed() при публикации в ленту.
"""

import asyncio
import logging
import os
import shutil
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from PIL import Image, ImageOps

from bot.config import config

logger = logging.getLogger(__name__)

FEED_STORAGE_DIR = Path("static/uploads/feed")
FEED_THUMB_STORAGE_DIR = FEED_STORAGE_DIR / "thumbs"
FEED_MEDIA_MAX_BYTES = int(os.getenv("FEED_MEDIA_MAX_BYTES", str(200 * 1024 * 1024)))
FEED_DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("FEED_DOWNLOAD_TIMEOUT_SECONDS", "180"))
FEED_THUMB_MAX_SIDE = 768
FEED_THUMB_MIN_BYTES = 50 * 1024
FEED_THUMB_MAX_BYTES = 200 * 1024
FEED_THUMB_MIN_QUALITY = 35
FEED_THUMB_MAX_QUALITY = 90
FEED_THUMB_BACKGROUND = (255, 255, 255)


async def download_to_local(url: str, max_size_bytes: int = FEED_MEDIA_MAX_BYTES) -> str | None:
    """
    Скачивает файл по URL в static/uploads/feed/<uuid>.<ext>.
    Возвращает локальный URL (STATIC_BASE_URL/uploads/feed/<filename>),
    который обслуживается Nginx/aiohttp.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=FEED_DOWNLOAD_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.warning("Feed persist: HTTP %s for %s", resp.status, url)
                    return None

                content_length = resp.headers.get("Content-Length", "").strip()
                if content_length.isdigit() and int(content_length) > max_size_bytes:
                    logger.warning(
                        "Feed persist: content-length too large (%s > %d) for %s",
                        content_length,
                        max_size_bytes,
                        url,
                    )
                    return None

                content_type = resp.headers.get("Content-Type", "")
                ext = _content_type_to_ext(content_type, url)
                filename = f"{uuid.uuid4().hex}{ext}"

                FEED_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                filepath = FEED_STORAGE_DIR / filename

                downloaded = 0
                with open(filepath, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > max_size_bytes:
                            os.remove(filepath)
                            logger.warning("Feed persist: file too large (>%d) for %s", max_size_bytes, url)
                            return None

                filepath = _rename_to_detected_ext(filepath)
                local_url = f"{config.static_base_url.rstrip('/')}/uploads/feed/{filepath.name}"
                logger.info("Feed persist: downloaded %s -> %s (%d bytes)", url, local_url, downloaded)
                return local_url

    except asyncio.TimeoutError:
        logger.warning("Feed persist: timeout downloading %s", url)
    except Exception:
        logger.exception("Feed persist: failed to download %s", url)

    return None


def _content_type_to_ext(content_type: str, fallback_url: str) -> str:
    """Определяет расширение файла по Content-Type или URL."""
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
    }

    for ct, ext in ext_map.items():
        if ct in content_type:
            return ext

    parsed = urlparse(fallback_url)
    path = parsed.path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"):
        if path.endswith(ext):
            return ext

    return ".jpg"


def _detect_file_ext_by_magic(path: Path) -> str | None:
    try:
        header = path.read_bytes()[:16]
    except OSError:
        return None
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return ".gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return ".mp4"
    return None


def _rename_to_detected_ext(path: Path) -> Path:
    detected_ext = _detect_file_ext_by_magic(path)
    if not detected_ext or path.suffix.lower() == detected_ext:
        return path
    destination = path.with_suffix(detected_ext)
    if destination.exists():
        destination = path.with_name(f"{path.stem}-{uuid.uuid4().hex[:8]}{detected_ext}")
    os.replace(path, destination)
    logger.info("Feed persist: corrected media extension %s -> %s", path, destination)
    return destination


def _local_feed_upload_path(url: str) -> Path | None:
    parsed = urlparse(str(url or ""))
    path = parsed.path if parsed.scheme else str(url or "")
    prefix = "/uploads/feed/"
    if not path.startswith(prefix) or "/thumbs/" in path:
        return None
    rel = path[len("/uploads/") :].lstrip("/")
    candidate = Path("static/uploads") / rel
    try:
        candidate.resolve().relative_to(Path("static/uploads").resolve())
    except ValueError:
        return None
    return candidate


def _thumbnail_paths(source: Path) -> tuple[Path, Path]:
    return (
        FEED_THUMB_STORAGE_DIR / f"{source.stem}.jpg",
        FEED_THUMB_STORAGE_DIR / f"{source.stem}.webp",
    )


def _has_alpha_channel(image: Image.Image) -> bool:
    return image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)


def _flatten_transparency(image: Image.Image) -> Image.Image:
    if not _has_alpha_channel(image):
        return image.convert("RGB")

    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, FEED_THUMB_BACKGROUND)
    background.paste(rgba, mask=rgba.getchannel("A"))
    rgba.close()
    return background


def _thumbnail_is_usable(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.load()
            return not _has_alpha_channel(image)
    except Exception:
        logger.warning("Feed thumbnail: existing thumbnail is unreadable %s", path)
        return False


def feed_thumbnail_url_for(url: str) -> str | None:
    """Return an existing lightweight thumbnail URL for a local feed image."""
    source = _local_feed_upload_path(url)
    if not source or source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None

    jpg_thumb, legacy_webp_thumb = _thumbnail_paths(source)
    for thumb in (jpg_thumb,):
        if thumb.exists() and _thumbnail_is_usable(thumb):
            return f"{config.static_base_url.rstrip('/')}/uploads/feed/thumbs/{thumb.name}"
    if legacy_webp_thumb.exists():
        try:
            legacy_webp_thumb.unlink()
        except OSError:
            logger.warning("Feed thumbnail: failed to remove legacy thumbnail %s", legacy_webp_thumb)
            return None
    return ensure_feed_thumbnail(url)


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(
        buffer,
        "JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
    )
    return buffer.getvalue()


def _best_jpeg_under_limit(image: Image.Image) -> tuple[bytes, int]:
    low = FEED_THUMB_MIN_QUALITY
    high = FEED_THUMB_MAX_QUALITY
    best: tuple[bytes, int] | None = None

    while low <= high:
        quality = (low + high) // 2
        encoded = _encode_jpeg(image, quality)
        if len(encoded) <= FEED_THUMB_MAX_BYTES:
            best = (encoded, quality)
            low = quality + 1
        else:
            high = quality - 1

    if best is not None:
        return best
    return _encode_jpeg(image, FEED_THUMB_MIN_QUALITY), FEED_THUMB_MIN_QUALITY


def _build_jpeg_thumbnail(source: Path) -> tuple[bytes, int, tuple[int, int]]:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()

    image = _flatten_transparency(image)

    image.thumbnail(
        (FEED_THUMB_MAX_SIDE, FEED_THUMB_MAX_SIDE),
        Image.Resampling.LANCZOS,
    )

    try:
        while True:
            encoded, quality = _best_jpeg_under_limit(image)
            if len(encoded) <= FEED_THUMB_MAX_BYTES or max(image.size) <= 320:
                return encoded, quality, image.size

            next_size = (
                max(1, round(image.width * 0.85)),
                max(1, round(image.height * 0.85)),
            )
            resized = image.resize(next_size, Image.Resampling.LANCZOS)
            image.close()
            image = resized
    finally:
        image.close()


def ensure_feed_thumbnail(url: str) -> str | None:
    """Create a bounded JPEG thumbnail for a local feed image."""
    source = _local_feed_upload_path(url)
    if not source or not source.exists() or not source.is_file():
        return None
    if source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None
    if _detect_file_ext_by_magic(source) not in {".jpg", ".png", ".gif", ".webp"}:
        logger.warning("Feed thumbnail: skipped non-image feed file %s", source)
        return None

    jpg_thumb, legacy_webp_thumb = _thumbnail_paths(source)
    if jpg_thumb.exists() and _thumbnail_is_usable(jpg_thumb):
        return f"{config.static_base_url.rstrip('/')}/uploads/feed/thumbs/{jpg_thumb.name}"
    if jpg_thumb.exists():
        try:
            jpg_thumb.unlink()
        except OSError:
            logger.warning("Feed thumbnail: failed to remove unusable thumbnail %s", jpg_thumb)
            return None
    legacy_webp_thumb.unlink(missing_ok=True)

    tmp = jpg_thumb.with_suffix(".tmp.jpg")
    try:
        FEED_THUMB_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        encoded, quality, size = _build_jpeg_thumbnail(source)
        tmp.write_bytes(encoded)
        os.replace(tmp, jpg_thumb)
        os.chmod(jpg_thumb, 0o644)
        logger.info(
            "Feed thumbnail: built %s (%dx%d, q=%d, %.1f KB)",
            jpg_thumb,
            size[0],
            size[1],
            quality,
            len(encoded) / 1024,
        )
        if len(encoded) < FEED_THUMB_MIN_BYTES:
            logger.debug(
                "Feed thumbnail smaller than preferred minimum: %s (%.1f KB)",
                jpg_thumb,
                len(encoded) / 1024,
            )
        return f"{config.static_base_url.rstrip('/')}/uploads/feed/thumbs/{jpg_thumb.name}"
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        logger.exception("Feed thumbnail: failed for %s", url)
        return None


def _copy_local_upload_to_feed(url: str) -> str | None:
    """Copy an existing local /uploads result into durable feed storage."""
    try:
        from bot.services.media_input_utils import (
            is_local_upload_source,
            resolve_local_upload_path,
        )

        if not is_local_upload_source(url):
            return None

        source_path = resolve_local_upload_path(url)
        if not source_path:
            return None

        source = Path(source_path)
        try:
            source.resolve().relative_to(FEED_STORAGE_DIR.resolve())
            ensure_feed_thumbnail(url)
            return url
        except ValueError:
            pass

        ext = source.suffix.lower() or _content_type_to_ext("", str(source))
        filename = f"{uuid.uuid4().hex}{ext}"
        FEED_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        destination = FEED_STORAGE_DIR / filename
        shutil.copy2(source, destination)
        destination = _rename_to_detected_ext(destination)

        local_url = f"{config.static_base_url.rstrip('/')}/uploads/feed/{destination.name}"
        ensure_feed_thumbnail(local_url)
        logger.info("Feed persist: copied local upload %s -> %s", url, local_url)
        return local_url
    except Exception:
        logger.exception("Feed persist: failed to copy local upload %s", url)
        return None


def _remove_new_feed_files(urls: list[str]) -> None:
    """Remove files created by an incomplete all-or-nothing persistence attempt."""
    for url in urls:
        path = _local_feed_upload_path(url)
        if not path:
            continue
        try:
            path.unlink(missing_ok=True)
            jpg_thumb, legacy_webp_thumb = _thumbnail_paths(path)
            jpg_thumb.unlink(missing_ok=True)
            legacy_webp_thumb.unlink(missing_ok=True)
        except OSError:
            logger.exception("Feed persist: failed to remove orphaned file %s", path)


def _is_external_http_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


async def persist_feed_result_urls(
    result_urls: list[str],
    *,
    require_local: bool = False,
    max_size_bytes: int = FEED_MEDIA_MAX_BYTES,
) -> list[str]:
    """
    Принимает список URL результатов генерации.

    Локальные /uploads копируются в durable feed storage. Любой внешний HTTP(S)
    результат сначала локализуется на backend: публичная лента не должна
    зависеть от срока жизни URL провайдера, его CORS/Range или геодоступности.
    При require_local=True возвращает пустой список, если хотя бы один файл
    сохранить не удалось. Для require_local=False внешний URL остаётся только
    как аварийный fallback, если скачивание провайдера временно недоступно.
    """
    from bot.database import FEED_EPHEMERAL_RESULT_HOSTS, _feed_result_host

    persisted: list[str] = []
    created_urls: list[str] = []
    for url in result_urls:
        local = _copy_local_upload_to_feed(url)
        if local:
            persisted.append(local)
            if local != url:
                created_urls.append(local)
            continue

        host = _feed_result_host(url)
        is_ephemeral = any(
            host == ephemeral or host.endswith(f".{ephemeral}")
            for ephemeral in FEED_EPHEMERAL_RESULT_HOSTS
        )
        should_download = _is_external_http_url(url) or is_ephemeral or require_local
        if should_download:
            if max_size_bytes == FEED_MEDIA_MAX_BYTES:
                local = await download_to_local(url)
            else:
                local = await download_to_local(url, max_size_bytes=max_size_bytes)
            if local:
                ensure_feed_thumbnail(local)
                persisted.append(local)
                created_urls.append(local)
            else:
                if require_local:
                    _remove_new_feed_files(created_urls)
                    return []
                logger.warning(
                    "Feed persist: keeping external fallback because localization failed: %s",
                    url,
                )
                persisted.append(url)
        else:
            persisted.append(url)

    return persisted
