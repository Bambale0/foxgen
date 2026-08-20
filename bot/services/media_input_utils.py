import base64
from datetime import datetime
from functools import lru_cache
import io
import mimetypes
import os
import uuid
from typing import Iterable
from urllib.parse import urlparse

from PIL import Image, ImageOps

from bot.config import config


def _guess_mime_type(source: str) -> str:
    mime, _ = mimetypes.guess_type(source)
    return mime or "image/png"


def _static_upload_hosts() -> set[str]:
    hosts: set[str] = set()
    for value in (
        config.static_base_url,
        getattr(config, "WEBHOOK_HOST", ""),
        getattr(config, "STATIC_BASE_URL", ""),
    ):
        parsed = urlparse(str(value or ""))
        host = (parsed.hostname or "").strip().lower().lstrip(".")
        if host:
            hosts.add(host)
    for item in os.getenv("STATIC_LOCAL_HOSTS", "").split(","):
        host = item.strip().lower().lstrip(".")
        if host:
            hosts.add(host)
    return hosts


def _local_upload_candidate(source: str) -> str | None:
    if not isinstance(source, str) or not source or source.startswith("data:image/"):
        return None

    parsed = urlparse(source)

    path = parsed.path or source
    is_local_path = not parsed.scheme and not parsed.netloc
    host = (parsed.hostname or "").strip().lower().lstrip(".")
    is_own_static_url = parsed.scheme in {"http", "https"} and host in _static_upload_hosts()

    # Only map bare /uploads paths or this app's configured public host to local
    # files. Do not reinterpret arbitrary external https://host/uploads/... URLs.
    if (is_local_path or is_own_static_url) and path.startswith("/uploads/"):
        rel_path = path[len("/uploads/") :].lstrip("/")
        return os.path.join("static", "uploads", rel_path)

    if is_local_path and path.startswith("static/uploads/"):
        return path

    return None


def is_local_upload_source(source: str) -> bool:
    """Return True when source points to this app's static/uploads storage."""
    return _local_upload_candidate(source) is not None


def missing_local_upload_sources(
    sources: Iterable[str | bytes | bytearray] | None,
) -> list[str]:
    """Return own /uploads sources whose backing file is no longer available."""
    if not sources:
        return []

    missing: list[str] = []
    for source in sources:
        if (
            isinstance(source, str)
            and source
            and is_local_upload_source(source)
            and not _resolve_local_upload_path(source)
        ):
            missing.append(source)
    return missing


def filter_available_image_sources(
    sources: Iterable[str | bytes | bytearray] | None,
) -> list[str | bytes | bytearray]:
    """Drop own /uploads sources that would be fetched as 404 by providers."""
    if not sources:
        return []

    available: list[str | bytes | bytearray] = []
    for source in sources:
        if (
            isinstance(source, str)
            and source
            and is_local_upload_source(source)
            and not _resolve_local_upload_path(source)
        ):
            continue
        available.append(source)
    return available


@lru_cache(maxsize=512)
def _upload_dir_variants(parent: str) -> dict[str, str]:
    variants: dict[str, str] = {}
    try:
        for entry in sorted(os.listdir(parent)):
            full_path = os.path.join(parent, entry)
            if not os.path.isfile(full_path):
                continue
            stem, _ext = os.path.splitext(full_path)
            variants.setdefault(stem, full_path)
    except OSError:
        return {}
    return variants


def _resolve_existing_upload_variant(candidate: str | None) -> str | None:
    if not candidate:
        return None
    if os.path.exists(candidate):
        return candidate

    parent = os.path.dirname(candidate)
    stem, _ext = os.path.splitext(candidate)
    if not parent or not os.path.isdir(parent):
        return None

    return _upload_dir_variants(parent).get(stem)


def _resolve_local_upload_path(source: str) -> str | None:
    candidate = _local_upload_candidate(source)
    return _resolve_existing_upload_variant(candidate)


def resolve_local_upload_path(source: str) -> str | None:
    """Return the local static upload path behind a public /uploads URL, if any."""
    return _resolve_local_upload_path(source)


def image_source_to_data_uri(source: str | bytes | bytearray) -> str:
    if isinstance(source, (bytes, bytearray)):
        try:
            image = Image.open(io.BytesIO(source))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            normalized = buffer.getvalue()
            return (
                f"data:image/png;base64,{base64.b64encode(normalized).decode('utf-8')}"
            )
        except Exception:
            return f"data:image/png;base64,{base64.b64encode(source).decode('utf-8')}"

    if not isinstance(source, str):
        return source

    if source.startswith("data:image/"):
        return source

    local_path = _resolve_local_upload_path(source)
    if not local_path:
        return source

    try:
        with Image.open(local_path) as image:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            raw = buffer.getvalue()
        return f"data:image/png;base64,{base64.b64encode(raw).decode('utf-8')}"
    except Exception:
        with open(local_path, "rb") as f:
            raw = f.read()
        mime_type = _guess_mime_type(local_path)
        return f"data:{mime_type};base64,{base64.b64encode(raw).decode('utf-8')}"


def image_sources_to_data_uris(
    sources: Iterable[str | bytes | bytearray] | None,
) -> list[str]:
    if not sources:
        return []
    return [image_source_to_data_uri(source) for source in sources]


def image_source_to_supported_image_url(source: str | bytes | bytearray) -> str:
    """Return a URL/file path for providers that require fetchable image URLs.

    For local uploaded images we normalize to PNG on disk so providers that reject
    WEBP still receive a supported file type.
    """
    if not isinstance(source, str) or not source or source.startswith("data:image/"):
        return source

    local_path = _resolve_local_upload_path(source)
    if not local_path:
        return source

    try:
        with Image.open(local_path) as image:
            image_format = (image.format or "").upper()
            if image_format in {"PNG", "JPEG", "JPG"}:
                return source

            png_path = os.path.splitext(local_path)[0] + ".png"
            if not os.path.exists(png_path):
                image.save(png_path, format="PNG")

            rel_path = os.path.relpath(png_path, os.path.join("static", "uploads"))
            rel_path = rel_path.replace(os.sep, "/")
            return f"{config.static_base_url.rstrip('/')}/uploads/{rel_path}"
    except Exception:
        return source


def image_sources_to_supported_image_urls(
    sources: Iterable[str | bytes | bytearray] | None,
) -> list[str]:
    if not sources:
        return []
    return [image_source_to_supported_image_url(source) for source in sources]


def image_source_to_provider_safe_png_url(source: str | bytes | bytearray) -> str:
    """Return a PNG URL for local uploads to reduce provider format issues."""
    if not isinstance(source, str) or not source or source.startswith("data:image/"):
        return source

    local_path = _resolve_local_upload_path(source)
    if not local_path:
        return source

    try:
        with Image.open(local_path) as image:
            png_path = os.path.splitext(local_path)[0] + ".png"
            if not os.path.exists(png_path):
                normalized = image.convert("RGBA" if "A" in image.mode else "RGB")
                normalized.save(png_path, format="PNG")

        rel_path = os.path.relpath(png_path, os.path.join("static", "uploads"))
        rel_path = rel_path.replace(os.sep, "/")
        return f"{config.static_base_url.rstrip('/')}/uploads/{rel_path}"
    except Exception:
        return source


def image_sources_to_provider_safe_png_urls(
    sources: Iterable[str | bytes | bytearray] | None,
) -> list[str]:
    if not sources:
        return []
    return [image_source_to_provider_safe_png_url(source) for source in sources]


def reference_sources_to_contact_sheet_url(
    sources: Iterable[str | bytes | bytearray] | None,
    *,
    max_sources: int = 4,
) -> str | None:
    """Build a local public contact sheet so multi-reference models see all refs.

    The board is only created from this app's local upload URLs. External URLs are
    left untouched because we should not fetch arbitrary remote media here.
    """
    if not sources:
        return None

    local_paths: list[str] = []
    for source in list(sources)[:max_sources]:
        if not isinstance(source, str):
            return None
        local_path = _resolve_local_upload_path(source)
        if not local_path or not os.path.exists(local_path):
            return None
        local_paths.append(local_path)

    if len(local_paths) < 2:
        return None

    cell_size = 512
    padding = 24
    columns = 2 if len(local_paths) > 1 else 1
    rows = (len(local_paths) + columns - 1) // columns
    width = columns * cell_size + (columns + 1) * padding
    height = rows * cell_size + (rows + 1) * padding

    board = Image.new("RGB", (width, height), "#f7f7f7")
    for idx, local_path in enumerate(local_paths):
        try:
            with Image.open(local_path) as image:
                normalized = ImageOps.exif_transpose(image).convert("RGB")
                normalized.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
                col = idx % columns
                row = idx // columns
                x = padding + col * (cell_size + padding)
                y = padding + row * (cell_size + padding)
                px = x + (cell_size - normalized.width) // 2
                py = y + (cell_size - normalized.height) // 2
                board.paste(normalized, (px, py))
        except Exception:
            return None

    period = datetime.utcnow().strftime("%Y%m")
    rel_dir = os.path.join("reference_boards", period)
    out_dir = os.path.join("static", "uploads", rel_dir)
    os.makedirs(out_dir, exist_ok=True)
    filename = f"ref_board_{uuid.uuid4().hex[:16]}.jpg"
    out_path = os.path.join(out_dir, filename)
    try:
        board.save(out_path, format="JPEG", quality=92, optimize=True)
    except Exception:
        return None

    rel_url = f"{rel_dir.replace(os.sep, '/')}/{filename}"
    return f"{config.static_base_url.rstrip('/')}/uploads/{rel_url}"


def is_reference_contact_sheet_url(source: str | None) -> bool:
    return isinstance(source, str) and "/uploads/reference_boards/" in source
