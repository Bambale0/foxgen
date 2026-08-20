#!/usr/bin/env python3
"""Generate bounded-size WebP previews for existing feed uploads.

By default the script reads static/uploads/feed and writes to
static/uploads/feed/thumbs. The output tree is excluded from input scanning,
so repeated backfill runs never create thumbs/thumbs recursively.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageOps, UnidentifiedImageError

LOGGER = logging.getLogger("media-previews")
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".tif", ".tiff"}
DEFAULT_INPUT = Path("static/uploads/feed")
DEFAULT_OUTPUT = DEFAULT_INPUT / "thumbs"


@dataclass(frozen=True)
class PreviewResult:
    source: Path
    target: Path
    width: int
    height: int
    quality: int
    size_bytes: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build 50–200 KB WebP feed previews")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Source image directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Preview output directory")
    parser.add_argument("--max-edge", type=int, default=768, help="Maximum width or height")
    parser.add_argument("--min-kb", type=int, default=50, help="Preferred minimum output size")
    parser.add_argument("--max-kb", type=int, default=200, help="Hard maximum output size")
    parser.add_argument("--min-quality", type=int, default=35)
    parser.add_argument("--max-quality", type=int, default=90)
    parser.add_argument("--force", action="store_true", help="Rebuild current previews")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.input.is_dir():
        raise ValueError(f"Input directory does not exist: {args.input}")
    if args.input.resolve() == args.output.resolve():
        raise ValueError("--output must differ from --input")
    if args.max_edge < 128:
        raise ValueError("--max-edge must be at least 128")
    if args.min_kb < 1 or args.max_kb <= args.min_kb:
        raise ValueError("Expected 0 < --min-kb < --max-kb")
    if not 1 <= args.min_quality < args.max_quality <= 100:
        raise ValueError("Expected 1 <= min-quality < max-quality <= 100")


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def iter_sources(root: Path, output_root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_SUFFIXES
        and not _is_under(path, output_root)
    )


def output_path(source: Path, input_root: Path, output_root: Path) -> Path:
    relative = source.relative_to(input_root)
    return (output_root / relative).with_suffix(".webp")


def is_current(source: Path, target: Path) -> bool:
    try:
        stat = target.stat()
    except FileNotFoundError:
        return False
    return stat.st_size > 0 and stat.st_mtime_ns >= source.stat().st_mtime_ns


def normalize_image(source: Path) -> Image.Image:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()

    if image.mode in {"RGBA", "LA"}:
        return image.convert("RGBA")
    if image.mode == "P" and "transparency" in image.info:
        return image.convert("RGBA")
    return image.convert("RGB")


def resize_to_edge(image: Image.Image, max_edge: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_edge:
        return image.copy()

    ratio = max_edge / longest
    size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    return image.resize(size, Image.Resampling.LANCZOS)


def encode_webp(image: Image.Image, quality: int) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    image.save(
        buffer,
        format="WEBP",
        quality=quality,
        method=6,
        optimize=True,
        exact=image.mode == "RGBA",
    )
    return buffer.getvalue()


def choose_quality(
    image: Image.Image,
    *,
    max_bytes: int,
    min_quality: int,
    max_quality: int,
) -> tuple[bytes, int]:
    low = min_quality
    high = max_quality
    best_under: tuple[bytes, int] | None = None
    smallest: tuple[bytes, int] | None = None

    while low <= high:
        quality = (low + high) // 2
        encoded = encode_webp(image, quality)
        candidate = (encoded, quality)

        if smallest is None or len(encoded) < len(smallest[0]):
            smallest = candidate

        if len(encoded) <= max_bytes:
            best_under = candidate
            low = quality + 1
        else:
            high = quality - 1

    return best_under or smallest or (encode_webp(image, min_quality), min_quality)


def build_preview(
    source: Path,
    target: Path,
    *,
    max_edge: int,
    max_bytes: int,
    min_quality: int,
    max_quality: int,
) -> PreviewResult:
    original = normalize_image(source)
    current_edge = max_edge
    chosen: tuple[bytes, int, Image.Image] | None = None

    try:
        while current_edge >= 256:
            resized = resize_to_edge(original, current_edge)
            encoded, quality = choose_quality(
                resized,
                max_bytes=max_bytes,
                min_quality=min_quality,
                max_quality=max_quality,
            )
            if chosen is not None:
                chosen[2].close()
            chosen = (encoded, quality, resized)
            if len(encoded) <= max_bytes:
                break
            current_edge = int(current_edge * 0.85)

        if chosen is None:
            raise RuntimeError("Preview encoder did not produce output")

        encoded, quality, resized = chosen
        target.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)

        try:
            os.replace(temporary_path, target)
            os.chmod(target, 0o644)
        finally:
            temporary_path.unlink(missing_ok=True)

        return PreviewResult(
            source=source,
            target=target,
            width=resized.width,
            height=resized.height,
            quality=quality,
            size_bytes=len(encoded),
        )
    finally:
        original.close()
        if chosen is not None:
            chosen[2].close()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        validate_args(args)
    except ValueError as error:
        LOGGER.error("%s", error)
        return 2

    min_bytes = args.min_kb * 1024
    max_bytes = args.max_kb * 1024
    sources = iter_sources(args.input, args.output)
    LOGGER.info("Found %d source images", len(sources))

    built = 0
    skipped = 0
    failed = 0

    for source in sources:
        target = output_path(source, args.input, args.output)
        if not args.force and is_current(source, target):
            skipped += 1
            continue

        if args.dry_run:
            LOGGER.info("Would build %s -> %s", source, target)
            built += 1
            continue

        try:
            result = build_preview(
                source,
                target,
                max_edge=args.max_edge,
                max_bytes=max_bytes,
                min_quality=args.min_quality,
                max_quality=args.max_quality,
            )
        except (OSError, RuntimeError, UnidentifiedImageError) as error:
            failed += 1
            LOGGER.error("Failed %s: %s", source, error)
            continue

        built += 1
        size_note = ""
        if result.size_bytes < min_bytes:
            size_note = " (below preferred minimum)"
        LOGGER.info(
            "Built %s (%dx%d, q=%d, %.1f KB)%s",
            result.target,
            result.width,
            result.height,
            result.quality,
            result.size_bytes / 1024,
            size_note,
        )

    LOGGER.info("Done: built=%d skipped=%d failed=%d", built, skipped, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
