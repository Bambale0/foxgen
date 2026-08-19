import asyncio
import hashlib
import logging
import mimetypes
import os
import time
from collections.abc import Iterable
from pathlib import Path

import aiohttp

from bot.config import config
from bot.services.media_input_utils import (
    image_source_to_provider_safe_png_url,
    is_local_upload_source,
    resolve_local_upload_path,
)

logger = logging.getLogger(__name__)


class KieFileUploadService:
    """Uploads local static media to KIE's temporary file store."""

    CACHE_TTL_SECONDS = 20 * 60 * 60

    def __init__(self, api_key: str, base_url: str = "https://kieai.redpandaai.co"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._cache: dict[str, tuple[str, float]] = {}

    def _cache_key(self, local_path: str, *, prefer_stable_public_url: bool) -> str:
        try:
            stat = os.stat(local_path)
            mode = "public" if prefer_stable_public_url else "upload"
            return f"{local_path}:{stat.st_size}:{stat.st_mtime_ns}:{mode}"
        except OSError:
            return local_path

    @staticmethod
    def _fallback_value(source: str, *, fallback_to_source: bool) -> str:
        return source if fallback_to_source else ""

    async def upload_local_image_source(
        self,
        source: str,
        *,
        prefer_stable_public_url: bool = True,
        fallback_to_source: bool = True,
    ) -> str:
        local_path = resolve_local_upload_path(source)
        if not local_path:
            if is_local_upload_source(source):
                logger.warning(
                    "Local upload reference is missing on disk; dropping source before KIE upload: %s",
                    source,
                )
                return ""
            return source
        if not self.api_key:
            logger.error("KIE file upload skipped because API key is missing")
            return self._fallback_value(source, fallback_to_source=fallback_to_source)

        cache_key = self._cache_key(
            local_path,
            prefer_stable_public_url=prefer_stable_public_url,
        )
        cached_entry = self._cache.get(cache_key)
        if cached_entry and time.time() - cached_entry[1] < self.CACHE_TTL_SECONDS:
            return cached_entry[0]

        if prefer_stable_public_url:
            stable_public_url = image_source_to_provider_safe_png_url(source)
            if isinstance(stable_public_url, str) and stable_public_url.startswith(("http://", "https://")):
                self._cache[cache_key] = (stable_public_url, time.time())
                logger.info(
                    "Using stable public URL for KIE reference instead of temp upload: %s",
                    stable_public_url,
                )
                return stable_public_url

        try:
            rel_name = os.path.relpath(local_path, os.path.join("static", "uploads"))
            original_filename = rel_name.replace(os.sep, "_")
        except ValueError:
            original_filename = os.path.basename(local_path)

        stem, ext = os.path.splitext(original_filename)
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:12]
        filename = f"{stem}_{digest}{ext or '.png'}"
        mime_type = mimetypes.guess_type(local_path)[0] or "image/png"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            file_bytes = await asyncio.to_thread(Path(local_path).read_bytes)
            form = aiohttp.FormData()
            form.add_field(
                "file",
                file_bytes,
                filename=filename,
                content_type=mime_type,
            )
            form.add_field("uploadPath", "image-references")
            form.add_field("fileName", filename)

            timeout = aiohttp.ClientTimeout(total=90, connect=15, sock_read=60)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(
                    f"{self.base_url}/api/file-stream-upload",
                    headers=headers,
                    data=form,
                ) as resp,
            ):
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    logger.warning(
                        "KIE file upload HTTP %s for %s: %s",
                        resp.status,
                        local_path,
                        data,
                    )
                    return self._fallback_value(
                        source,
                        fallback_to_source=fallback_to_source,
                    )
        except Exception:
            logger.exception("KIE file upload failed for %s", local_path)
            return self._fallback_value(source, fallback_to_source=fallback_to_source)

        if not isinstance(data, dict) or not data.get("success"):
            logger.warning("KIE file upload rejected %s: %s", local_path, data)
            return self._fallback_value(source, fallback_to_source=fallback_to_source)

        data_block = data.get("data") or {}
        file_url = (
            data_block.get("downloadUrl")
            or data_block.get("fileUrl")
            or ""
        ).strip()
        if not file_url:
            logger.warning(
                "KIE file upload returned no downloadable URL for %s: %s",
                local_path,
                data,
            )
            return self._fallback_value(source, fallback_to_source=fallback_to_source)

        self._cache[cache_key] = (file_url, time.time())
        logger.info("KIE file upload ready for provider reference: %s", file_url)
        return file_url

    async def upload_local_image_sources(
        self,
        sources: Iterable[str] | None,
        *,
        prefer_stable_public_url: bool = True,
        fallback_to_source: bool = True,
    ) -> list[str]:
        if not sources:
            return []
        uploaded_sources = []
        for source in sources:
            if isinstance(source, str) and source:
                uploaded_sources.append(
                    await self.upload_local_image_source(
                        source,
                        prefer_stable_public_url=prefer_stable_public_url,
                        fallback_to_source=fallback_to_source,
                    )
                )
        return uploaded_sources


kie_file_upload_service = KieFileUploadService(
    api_key=config.KIE_AI_API_KEY or config.NANOBANANA_API_KEY
)
