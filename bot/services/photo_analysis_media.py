"""Normalize local reference images before sending them to vision providers."""

import base64
import io

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
except ImportError:  # pragma: no cover - optional on constrained local installs
    register_heif_opener = None

from bot.services.media_input_utils import resolve_local_upload_path

if register_heif_opener is not None:
    register_heif_opener()


def image_source_to_analysis_input(source: str, *, max_edge: int = 2048) -> str:
    """Return a compact data URI for own uploads and leave external URLs untouched."""
    if not isinstance(source, str) or not source or source.startswith("data:image/"):
        return source

    local_path = resolve_local_upload_path(source)
    if not local_path:
        return source

    try:
        with Image.open(local_path) as image:
            normalized = ImageOps.exif_transpose(image).convert("RGB")
            normalized.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            normalized.save(buffer, format="JPEG", quality=90, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except (OSError, ValueError):
        return source
