"""Cloudflare-safe chunk assembly for large Seedance 2.5 video references."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiohttp import web

from bot.config import config
from bot.database import get_saved_reference_by_hash, save_user_reference
from bot.services.media_input_utils import resolve_local_upload_path

from . import seedance_25_fullstack as fullstack

MAX_ASSEMBLED_VIDEO_BYTES = 200 * 1024 * 1024
MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_CHUNKS = 32
UPLOAD_ROOT = Path("static/uploads").resolve()


def _safe_original_filename(value: Any) -> str:
    name = Path(str(value or "seedance25-video.mp4")).name
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in {"mp4", "mov"}:
        raise ValueError("Seedance 2.5 large video must be MP4 or MOV")
    return name


def _public_reference_url(relative_path: Path) -> str:
    base = str(config.static_base_url or "").rstrip("/")
    return f"{base}/uploads/{relative_path.as_posix()}"


def _resolve_chunk_paths(urls: list[str]) -> list[Path]:
    if not urls or len(urls) > MAX_CHUNKS:
        raise ValueError(f"Chunk count must be 1-{MAX_CHUNKS}")

    paths: list[Path] = []
    for raw_url in urls:
        local = resolve_local_upload_path(str(raw_url or "").strip())
        if not local:
            raise ValueError("One or more Seedance upload chunks are unavailable")
        path = Path(local).resolve()
        if not path.is_relative_to(UPLOAD_ROOT):
            raise ValueError("Invalid Seedance chunk path")
        if not path.is_file():
            raise ValueError("One or more Seedance upload chunks are missing")
        size = path.stat().st_size
        if size <= 0 or size > MAX_CHUNK_BYTES:
            raise ValueError("Seedance upload chunk has an invalid size")
        paths.append(path)
    return paths


def _cleanup_chunks(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            fullstack.logger.warning("Failed to remove Seedance upload chunk: %s", path)


async def _assemble_seedance25_video(
    request: web.Request,
    body: dict[str, Any],
) -> web.Response:
    import bot.miniapp as miniapp_module

    telegram_id, _ctx = await miniapp_module._get_user_context(
        request.app,
        str(body.get("init_data") or ""),
        body.get("start_param_fallback"),
    )
    if not fullstack._is_admin(telegram_id):
        return web.json_response(
            {"ok": False, "error": "Seedance 2.5 доступна только администраторам"},
            status=403,
        )

    filename = _safe_original_filename(body.get("seedance25_original_filename"))
    ext = Path(filename).suffix.lower().lstrip(".")
    raw_urls = body.get("seedance25_chunk_urls") or []
    if not isinstance(raw_urls, list):
        return web.json_response({"ok": False, "error": "Некорректный список частей"}, status=400)

    try:
        chunk_urls = fullstack._clean_urls(raw_urls, MAX_CHUNKS)
        chunk_paths = _resolve_chunk_paths(chunk_urls)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    expected_size = int(body.get("seedance25_original_size") or 0)
    if expected_size <= 0 or expected_size > MAX_ASSEMBLED_VIDEO_BYTES:
        _cleanup_chunks(chunk_paths)
        return web.json_response(
            {"ok": False, "error": "Seedance video size must be 1-200 MB"},
            status=400,
        )

    temp_dir = Path("tmp/seedance25-chunks")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"assemble-{telegram_id}-{os.urandom(8).hex()}.{ext}"

    digest = hashlib.sha256()
    assembled_size = 0
    try:
        with temp_path.open("wb") as target:
            for chunk_path in chunk_paths:
                with chunk_path.open("rb") as source:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        assembled_size += len(block)
                        if assembled_size > MAX_ASSEMBLED_VIDEO_BYTES:
                            raise ValueError("Seedance video exceeds 200 MB")
                        digest.update(block)
                        target.write(block)

        if assembled_size != expected_size:
            raise ValueError(
                f"Seedance chunk assembly size mismatch: expected {expected_size}, got {assembled_size}"
            )

        # Full server-side validation: MP4/MOV, 2-30s, 24-60 FPS, dimensions,
        # aspect ratio, and provider pixel-count range.
        await fullstack._validate_video_path(str(temp_path))

        file_hash = digest.hexdigest()
        existing = await get_saved_reference_by_hash(telegram_id, "video", file_hash)
        if existing:
            existing_path = resolve_local_upload_path(existing.file_url)
            if existing_path and Path(existing_path).is_file():
                payload = miniapp_module._saved_reference_payload(existing)
                return web.json_response(
                    {
                        "ok": True,
                        "url": payload["url"],
                        "kind": "video",
                        "filename": filename,
                        "reference": payload,
                    }
                )

        month = datetime.now(UTC).strftime("%Y%m")
        relative_dir = Path("refs") / "video" / str(telegram_id) / month
        target_dir = Path("static/uploads") / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        final_relative = relative_dir / f"{file_hash[:32]}.{ext}"
        final_path = Path("static/uploads") / final_relative
        os.replace(temp_path, final_path)

        public_url = _public_reference_url(final_relative)
        reference = await save_user_reference(
            telegram_id,
            kind="video",
            file_url=public_url,
            file_hash=file_hash,
            original_filename=filename,
            content_type="video/quicktime" if ext == "mov" else "video/mp4",
            source="miniapp_seedance25",
        )
        payload = miniapp_module._saved_reference_payload(reference)
        return web.json_response(
            {
                "ok": True,
                "url": payload["url"],
                "kind": "video",
                "filename": filename,
                "reference": payload,
            }
        )
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        fullstack.logger.exception("Seedance 2.5 chunk assembly failed")
        return web.json_response({"ok": False, "error": str(exc)}, status=500)
    finally:
        _cleanup_chunks(chunk_paths)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            fullstack.logger.warning("Failed to remove Seedance assembly temp file: %s", temp_path)


def install_seedance_25_chunk_upload() -> None:
    if getattr(fullstack, "_seedance25_chunk_upload_installed", False):
        return

    original_generate = fullstack._miniapp_seedance25_generate

    async def generate_or_assemble(request: web.Request, body: dict[str, Any]) -> web.Response:
        if body.get("seedance25_upload_only"):
            return await _assemble_seedance25_video(request, body)
        return await original_generate(request, body)

    fullstack._miniapp_seedance25_generate = generate_or_assemble
    fullstack._seedance25_chunk_upload_installed = True
