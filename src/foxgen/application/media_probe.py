from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from foxgen.core.errors import ErrorCode, SubmissionError


@dataclass(frozen=True, slots=True)
class VisualMediaProbe:
    width: int
    height: int
    duration_seconds: float | None = None

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height


def probe_image(path: Path, content_type: str) -> VisualMediaProbe:
    normalized = content_type.lower()
    if normalized == "image/png":
        return _probe_png(path)
    if normalized in {"image/jpeg", "image/jpg"}:
        return _probe_jpeg(path)
    raise SubmissionError(ErrorCode.VALIDATION, "Поддерживаются только JPEG и PNG изображения.")


def probe_iso_video(path: Path) -> VisualMediaProbe:
    """Read duration and display dimensions from MP4/QuickTime ISO-BMFF metadata."""

    try:
        with path.open("rb") as stream:
            moov = _find_box(stream, 0, path.stat().st_size, b"moov")
            if moov is None:
                raise ValueError("moov atom is missing")
            moov_start, moov_end = moov
            mvhd = _find_box(stream, moov_start, moov_end, b"mvhd")
            if mvhd is None:
                raise ValueError("mvhd atom is missing")
            duration_seconds = _read_mvhd_duration(stream, *mvhd)
            width, height = _read_video_dimensions(stream, moov_start, moov_end)
    except (OSError, ValueError, struct.error) as exc:
        raise SubmissionError(
            ErrorCode.VALIDATION,
            "Не удалось прочитать параметры MP4/QuickTime видео.",
            retryable=False,
        ) from exc
    return VisualMediaProbe(width=width, height=height, duration_seconds=duration_seconds)


def _probe_png(path: Path) -> VisualMediaProbe:
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise ValueError("invalid PNG header")
        width, height = struct.unpack(">II", header[16:24])
    except (OSError, ValueError, struct.error) as exc:
        raise SubmissionError(ErrorCode.VALIDATION, "Повреждённый PNG файл.") from exc
    return VisualMediaProbe(width=width, height=height)


def _probe_jpeg(path: Path) -> VisualMediaProbe:
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"\xff\xd8":
                raise ValueError("invalid JPEG signature")
            while True:
                prefix = stream.read(1)
                if not prefix:
                    break
                if prefix != b"\xff":
                    continue
                marker = stream.read(1)
                while marker == b"\xff":
                    marker = stream.read(1)
                if not marker:
                    break
                marker_value = marker[0]
                if marker_value in {0xD8, 0xD9} or 0xD0 <= marker_value <= 0xD7:
                    continue
                raw_length = stream.read(2)
                if len(raw_length) != 2:
                    raise ValueError("truncated JPEG segment")
                segment_length = struct.unpack(">H", raw_length)[0]
                if segment_length < 2:
                    raise ValueError("invalid JPEG segment length")
                if marker_value in sof_markers:
                    payload = stream.read(5)
                    if len(payload) != 5:
                        raise ValueError("truncated JPEG SOF")
                    height, width = struct.unpack(">HH", payload[1:5])
                    return VisualMediaProbe(width=width, height=height)
                stream.seek(segment_length - 2, 1)
    except (OSError, ValueError, struct.error) as exc:
        raise SubmissionError(ErrorCode.VALIDATION, "Повреждённый JPEG файл.") from exc
    raise SubmissionError(ErrorCode.VALIDATION, "Не удалось определить размер JPEG изображения.")


def _box_header(stream: object, offset: int, limit: int) -> tuple[int, bytes, int] | None:
    stream.seek(offset)  # type: ignore[attr-defined]
    raw = stream.read(8)  # type: ignore[attr-defined]
    if len(raw) != 8:
        return None
    size, kind = struct.unpack(">I4s", raw)
    header_size = 8
    if size == 1:
        extended = stream.read(8)  # type: ignore[attr-defined]
        if len(extended) != 8:
            return None
        size = struct.unpack(">Q", extended)[0]
        header_size = 16
    elif size == 0:
        size = limit - offset
    if size < header_size or offset + size > limit:
        return None
    return int(size), kind, header_size


def _find_box(stream: object, start: int, end: int, kind: bytes) -> tuple[int, int] | None:
    offset = start
    while offset + 8 <= end:
        header = _box_header(stream, offset, end)
        if header is None:
            return None
        size, current_kind, header_size = header
        payload_start = offset + header_size
        box_end = offset + size
        if current_kind == kind:
            return payload_start, box_end
        offset = box_end
    return None


def _read_mvhd_duration(stream: object, start: int, end: int) -> float:
    stream.seek(start)  # type: ignore[attr-defined]
    version_flags = stream.read(4)  # type: ignore[attr-defined]
    if len(version_flags) != 4:
        raise ValueError("truncated mvhd")
    version = version_flags[0]
    if version == 1:
        raw = stream.read(28)  # type: ignore[attr-defined]
        if len(raw) != 28:
            raise ValueError("truncated mvhd v1")
        timescale = struct.unpack(">I", raw[16:20])[0]
        duration = struct.unpack(">Q", raw[20:28])[0]
    else:
        raw = stream.read(16)  # type: ignore[attr-defined]
        if len(raw) != 16:
            raise ValueError("truncated mvhd v0")
        timescale = struct.unpack(">I", raw[8:12])[0]
        duration = struct.unpack(">I", raw[12:16])[0]
    if timescale <= 0 or duration <= 0:
        raise ValueError("invalid mvhd timing")
    result = duration / timescale
    if result <= 0 or result > 24 * 60 * 60:
        raise ValueError("unreasonable video duration")
    return result


def _read_video_dimensions(stream: object, moov_start: int, moov_end: int) -> tuple[int, int]:
    offset = moov_start
    while offset + 8 <= moov_end:
        header = _box_header(stream, offset, moov_end)
        if header is None:
            break
        size, kind, header_size = header
        box_end = offset + size
        if kind == b"trak":
            tkhd = _find_box(stream, offset + header_size, box_end, b"tkhd")
            if tkhd is not None:
                width, height = _read_tkhd_dimensions(stream, *tkhd)
                if width > 0 and height > 0:
                    return width, height
        offset = box_end
    raise ValueError("video track dimensions are missing")


def _read_tkhd_dimensions(stream: object, start: int, end: int) -> tuple[int, int]:
    stream.seek(start)  # type: ignore[attr-defined]
    version_flags = stream.read(4)  # type: ignore[attr-defined]
    if len(version_flags) != 4:
        raise ValueError("truncated tkhd")
    version = version_flags[0]
    # Width and height are the final two 16.16 fixed-point values in tkhd.
    if end - start < 12:
        raise ValueError("truncated tkhd payload")
    stream.seek(end - 8)  # type: ignore[attr-defined]
    raw = stream.read(8)  # type: ignore[attr-defined]
    if len(raw) != 8:
        raise ValueError("truncated tkhd dimensions")
    width_fixed, height_fixed = struct.unpack(">II", raw)
    width = width_fixed >> 16
    height = height_fixed >> 16
    # Version is deliberately read above: it catches malformed headers and documents
    # that both v0/v1 layout variants are accepted while using their common tail.
    if version not in {0, 1}:
        raise ValueError("unsupported tkhd version")
    return width, height
