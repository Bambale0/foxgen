import asyncio
import hashlib
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from bot.config import config
from bot.database import (
    SavedReference,
    get_saved_reference_by_hash,
    save_user_reference,
    touch_saved_references,
)
from bot.services.media_input_utils import (
    image_source_to_provider_safe_png_url,
    resolve_local_upload_path,
)

logger = logging.getLogger(__name__)

REFERENCE_ROOT = os.path.join("static", "uploads", "refs")


def _build_reference_public_url(relative_path: str) -> str:
    return f"{config.static_base_url.rstrip('/')}/uploads/{relative_path.replace(os.sep, '/')}"


def _local_path_for_relative_upload(relative_path: str) -> str:
    return os.path.join("static", "uploads", relative_path)


def _provider_safe_reference_url(file_url: str, kind: str) -> str:
    if kind != "image":
        return file_url
    try:
        safe_url = image_source_to_provider_safe_png_url(file_url)
        return safe_url or file_url
    except Exception:
        logger.exception("Failed to normalize image reference: %s", file_url)
        return file_url


async def save_reference_file(
    telegram_id: int,
    file_bytes: bytes,
    *,
    file_ext: str,
    kind: str = "image",
    original_filename: str | None = None,
    content_type: str | None = None,
    source: str = "telegram",
) -> tuple[str | None, SavedReference | None]:
    """Persist reusable reference media outside the ephemeral uploads cleanup path."""
    try:
        if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
            return None, None

        normalized_kind = kind if kind in {"image", "video", "audio"} else "image"
        file_hash = hashlib.sha256(bytes(file_bytes)).hexdigest()
        existing = await get_saved_reference_by_hash(telegram_id, normalized_kind, file_hash)
        if existing:
            local_path = resolve_local_upload_path(existing.file_url)
            if local_path and os.path.exists(local_path):
                public_url = _provider_safe_reference_url(existing.file_url, normalized_kind)
                await touch_saved_references(
                    telegram_id, [existing.file_url], kind=normalized_kind
                )
                return public_url, existing

        safe_ext = (file_ext or "bin").lower().strip(".")
        month = datetime.now(UTC).strftime("%Y%m")
        relative_dir = os.path.join("refs", normalized_kind, str(telegram_id), month)
        full_dir = _local_path_for_relative_upload(relative_dir)
        os.makedirs(full_dir, exist_ok=True)

        filename = f"{file_hash[:32]}.{safe_ext}"
        relative_path = os.path.join(relative_dir, filename)
        full_path = _local_path_for_relative_upload(relative_path)

        if not os.path.exists(full_path):
            await asyncio.to_thread(Path(full_path).write_bytes, bytes(file_bytes))

        original_public_url = _build_reference_public_url(relative_path)
        public_url = _provider_safe_reference_url(original_public_url, normalized_kind)
        persisted_content_type = (
            "image/png"
            if normalized_kind == "image" and public_url != original_public_url
            else content_type
        )
        saved_reference = await save_user_reference(
            telegram_id,
            kind=normalized_kind,
            file_url=public_url,
            file_hash=file_hash,
            original_filename=original_filename,
            content_type=persisted_content_type,
            source=source,
        )
        return public_url, saved_reference
    except Exception:
        logger.exception("Failed to persist reusable reference for telegram_id=%s", telegram_id)
        return None, None
