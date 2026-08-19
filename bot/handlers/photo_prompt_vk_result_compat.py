"""Readable prompt formatting without replacing the established result card.

The Telegram result keeps the legacy RU / EN / negative prompt / recommendation
layout, buttons and full text document. Only long prompt fields are split into
readable paragraphs before the legacy sender renders them.
"""

from __future__ import annotations

import importlib
import re
from functools import wraps
from typing import Any

_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ0-9«\"(])"
)
_CLAUSE_BOUNDARY_RE = re.compile(r"(?<=[;:])\s+")
_WHITESPACE_RE = re.compile(r"[ \t]+")

_MAX_PARAGRAPH_CHARS = 460
_MAX_SENTENCES_PER_PARAGRAPH = 2
_MIN_TEXT_TO_REFORMAT = 520


def _normalize_existing_paragraphs(value: str) -> str:
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", value.replace("\r\n", "\n")):
        lines = [
            _WHITESPACE_RE.sub(" ", line).strip()
            for line in paragraph.split("\n")
            if line.strip()
        ]
        if lines:
            paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs)


def _split_long_single_sentence(value: str) -> list[str]:
    clauses = [part.strip() for part in _CLAUSE_BOUNDARY_RE.split(value) if part.strip()]
    if len(clauses) > 1:
        return clauses

    chunks: list[str] = []
    current = ""
    for part in value.split(", "):
        candidate = f"{current}, {part}" if current else part
        if current and len(candidate) > _MAX_PARAGRAPH_CHARS:
            chunks.append(current.strip())
            current = part
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks or [value]


def format_prompt_readably(prompt: str) -> str:
    """Split a long prose prompt into paragraphs without rewriting its content."""

    value = _normalize_existing_paragraphs(str(prompt or "").strip())
    if not value or len(value) < _MIN_TEXT_TO_REFORMAT:
        return value

    if "\n\n" in value:
        return value

    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY_RE.split(value)
        if sentence.strip()
    ]
    if len(sentences) <= 1:
        sentences = _split_long_single_sentence(value)

    paragraphs: list[str] = []
    current: list[str] = []
    current_length = 0

    for sentence in sentences:
        separator_length = 1 if current else 0
        candidate_length = current_length + separator_length + len(sentence)
        should_flush = bool(current) and (
            len(current) >= _MAX_SENTENCES_PER_PARAGRAPH
            or candidate_length > _MAX_PARAGRAPH_CHARS
        )
        if should_flush:
            paragraphs.append(" ".join(current).strip())
            current = []
            current_length = 0

        current.append(sentence)
        current_length += (1 if current_length else 0) + len(sentence)

    if current:
        paragraphs.append(" ".join(current).strip())

    return "\n\n".join(paragraphs) if len(paragraphs) > 1 else value


def _prepare_readable_result(result: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(result)
    for key in ("prompt_ru", "prompt_en", "negative_prompt"):
        value = str(prepared.get(key) or "").strip()
        if value:
            prepared[key] = format_prompt_readably(value)

    raw = prepared.get("raw")
    if isinstance(raw, dict):
        prepared_raw = dict(raw)
        for key in ("prompt_ru", "prompt_en", "prompt", "output_text"):
            value = str(prepared_raw.get(key) or "").strip()
            if value:
                prepared_raw[key] = format_prompt_readably(value)
        prepared["raw"] = prepared_raw

    return prepared


def install_vk_photo_prompt_result_compat() -> None:
    """Restore the legacy detailed result and only improve prompt readability."""

    module = importlib.import_module("bot.handlers.image_analyzer")

    if getattr(module, "_vk_photo_prompt_result_compat_installed", False):
        return

    original_send = module._send_photo_prompt_result

    @wraps(original_send)
    async def send_photo_prompt_result(
        message: Any,
        result: dict[str, Any],
        *,
        filename: str = "photo_prompt_full.txt",
        document_caption: str = "📝 Полный prompt: RU + EN + negative",
    ) -> None:
        prepared = result
        if str(result.get("source_mode") or "").strip() == "photo":
            prepared = _prepare_readable_result(result)

        await original_send(
            message,
            prepared,
            filename=filename,
            document_caption=document_caption,
        )

    module._send_photo_prompt_result = send_photo_prompt_result
    module._vk_photo_prompt_result_compat_installed = True
