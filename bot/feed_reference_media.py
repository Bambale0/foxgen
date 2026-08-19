import asyncio
import hashlib
from pathlib import Path

from aiohttp import web
from PIL import Image, ImageOps

from bot.database import get_feed_generation_card
from bot.services.media_input_utils import resolve_local_upload_path

REFERENCE_THUMB_CACHE_DIR = Path("static/uploads/feed-reference-thumbs")
REFERENCE_THUMB_MAX_EDGE = 320
REFERENCE_THUMB_QUALITY = 72
_reference_thumb_locks: dict[str, asyncio.Lock] = {}


def _parse_reference_index(raw: str | None) -> int:
    try:
        index = int(raw or "0")
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="Invalid reference index") from exc
    if index < 0:
        raise web.HTTPBadRequest(text="Invalid reference index")
    return index


async def _public_image_reference_path(gen_id: str, index: int) -> Path:
    card = await get_feed_generation_card(gen_id)
    if not card:
        raise web.HTTPNotFound(text="Reference not found")
    if card.get("references_hidden") or card.get("feed_references_visible") is False:
        raise web.HTTPNotFound(text="Reference not found")

    references = [
        str(url).strip()
        for url in list(card.get("reference_images") or [])
        if str(url or "").strip()
    ]
    if index >= len(references):
        raise web.HTTPNotFound(text="Reference not found")

    local_path = resolve_local_upload_path(references[index])
    if not local_path:
        raise web.HTTPNotFound(text="Reference not found")

    path = Path(local_path)
    if not path.is_file():
        raise web.HTTPNotFound(text="Reference not found")
    return path


def _thumbnail_cache_path(source: Path) -> Path:
    stat = source.stat()
    fingerprint = f"{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return REFERENCE_THUMB_CACHE_DIR / f"{digest}.webp"


def _build_thumbnail(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.webp")
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image.thumbnail(
            (REFERENCE_THUMB_MAX_EDGE, REFERENCE_THUMB_MAX_EDGE),
            Image.Resampling.LANCZOS,
        )
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        image.save(
            temporary,
            format="WEBP",
            quality=REFERENCE_THUMB_QUALITY,
            method=4,
        )
    temporary.replace(target)


async def feed_reference_image_thumbnail(request: web.Request) -> web.StreamResponse:
    gen_id = str(request.match_info.get("gen_id") or "").strip()
    if not gen_id:
        raise web.HTTPNotFound(text="Reference not found")
    index = _parse_reference_index(request.match_info.get("index"))
    source = await _public_image_reference_path(gen_id, index)
    target = _thumbnail_cache_path(source)

    if not target.is_file():
        cache_key = target.name
        lock = _reference_thumb_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            if not target.is_file():
                try:
                    await asyncio.to_thread(_build_thumbnail, source, target)
                except Exception as exc:
                    raise web.HTTPUnsupportedMediaType(
                        text="Reference preview is unavailable"
                    ) from exc

    response = web.FileResponse(target)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


async def feed_reference_image_full(request: web.Request) -> web.StreamResponse:
    gen_id = str(request.match_info.get("gen_id") or "").strip()
    if not gen_id:
        raise web.HTTPNotFound(text="Reference not found")
    index = _parse_reference_index(request.match_info.get("index"))
    source = await _public_image_reference_path(gen_id, index)

    response = web.FileResponse(source)
    response.headers["Cache-Control"] = "public, max-age=86400"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def setup_feed_reference_media_routes(
    app: web.Application,
    *,
    miniapp_root: str = "/mini-app",
) -> None:
    root = miniapp_root.rstrip("/")
    app.router.add_get(
        root + "/api/feed/reference-image/{gen_id}/{index}/thumbnail",
        feed_reference_image_thumbnail,
    )
    app.router.add_get(
        root + "/api/feed/reference-image/{gen_id}/{index}/full",
        feed_reference_image_full,
    )
