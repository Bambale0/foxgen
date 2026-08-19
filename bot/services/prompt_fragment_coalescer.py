"""Coalesce prompt fragments before generation handlers run.

Telegram text messages are limited to roughly 4096 characters. Long prompts
therefore often arrive as two consecutive messages. Generation handlers used to
submit the first message immediately and then submit the continuation as a
second generation while the FSM state was still active.

This inner middleware delays prompt-state text briefly, joins consecutive
fragments from the same chat/user/state, and invokes the already-selected
handler exactly once. It is provider-agnostic, so image/video models share the
same protection.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError

from bot.states import (
    BatchGenerationStates,
    GenerationStates,
    ImageAnalyzerStates,
    SeedreamVideoStates,
)

logger = logging.getLogger(__name__)

PROMPT_FRAGMENT_QUIET_SECONDS = max(
    0.15,
    float(os.getenv("PROMPT_FRAGMENT_QUIET_SECONDS", "0.65")),
)
PROMPT_FRAGMENT_LONG_QUIET_SECONDS = max(
    PROMPT_FRAGMENT_QUIET_SECONDS,
    float(os.getenv("PROMPT_FRAGMENT_LONG_QUIET_SECONDS", "2.0")),
)
PROMPT_FRAGMENT_LONG_THRESHOLD = max(
    1000,
    int(os.getenv("PROMPT_FRAGMENT_LONG_THRESHOLD", "3800")),
)
PROMPT_FRAGMENT_MAX_CHARS = max(
    4096,
    int(os.getenv("PROMPT_FRAGMENT_MAX_CHARS", "64000")),
)

# Only states whose free-form text is a prompt-like field. Numeric settings,
# names, IDs, payment/admin inputs, etc. intentionally remain immediate.
PROMPT_TEXT_STATES = {
    GenerationStates.waiting_for_input.state,
    GenerationStates.waiting_for_repeat_prompt.state,
    GenerationStates.waiting_for_video_prompt.state,
    GenerationStates.waiting_for_batch_prompt.state,
    GenerationStates.waiting_for_veo_extend_prompt.state,
    GenerationStates.waiting_for_kling_negative_prompt.state,
    GenerationStates.waiting_for_omni_voice_description.state,
    GenerationStates.waiting_for_omni_example_dialogue.state,
    BatchGenerationStates.entering_prompts.state,
    ImageAnalyzerStates.waiting_for_video_prompt.state,
    SeedreamVideoStates.waiting_for_prompt.state,
}

Handler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


@dataclass
class _PendingPrompt:
    state_name: str
    handler: Handler
    event: Any
    data: dict[str, Any]
    parts: list[str] = field(default_factory=list)
    version: int = 0
    task: asyncio.Task | None = None

    @property
    def text(self) -> str:
        return "\n".join(part for part in self.parts if part)

    @property
    def is_long(self) -> bool:
        return any(len(part) >= PROMPT_FRAGMENT_LONG_THRESHOLD for part in self.parts)


class PromptFragmentCoalescingMiddleware(BaseMiddleware):
    """Submit one generation for several consecutive prompt messages."""

    def __init__(
        self,
        *,
        quiet_seconds: float = PROMPT_FRAGMENT_QUIET_SECONDS,
        long_quiet_seconds: float = PROMPT_FRAGMENT_LONG_QUIET_SECONDS,
        max_chars: int = PROMPT_FRAGMENT_MAX_CHARS,
    ) -> None:
        self.quiet_seconds = max(0.01, float(quiet_seconds))
        self.long_quiet_seconds = max(self.quiet_seconds, float(long_quiet_seconds))
        self.max_chars = max(4096, int(max_chars))
        self._pending: dict[tuple[int, int, str], _PendingPrompt] = {}
        self._inflight: set[tuple[int, int, str]] = set()
        self._lock = asyncio.Lock()

    @staticmethod
    def _event_key(event: Any, state_name: str) -> tuple[int, int, str] | None:
        user = getattr(event, "from_user", None)
        chat = getattr(event, "chat", None)
        user_id = getattr(user, "id", None)
        chat_id = getattr(chat, "id", None)
        if user_id is None or chat_id is None:
            return None
        return int(chat_id), int(user_id), state_name

    @staticmethod
    def _clone_with_text(event: Any, text: str) -> Any:
        model_copy = getattr(event, "model_copy", None)
        if not callable(model_copy):
            logger.warning(
                "Prompt coalescer received event without model_copy: %s",
                type(event).__name__,
            )
            return event
        return model_copy(update={"text": text, "entities": []})

    async def _cancel_pending(self, key: tuple[int, int, str]) -> None:
        pending = self._pending.pop(key, None)
        if pending and pending.task and not pending.task.done():
            pending.task.cancel()

    async def _flush(self, key: tuple[int, int, str], version: int) -> None:
        pending: _PendingPrompt | None = None
        try:
            async with self._lock:
                current = self._pending.get(key)
                if current is None or current.version != version:
                    return
                delay = (
                    self.long_quiet_seconds
                    if current.is_long or len(current.text) > 4096
                    else self.quiet_seconds
                )

            await asyncio.sleep(delay)

            async with self._lock:
                current = self._pending.get(key)
                if current is None or current.version != version:
                    return
                pending = self._pending.pop(key)
                self._inflight.add(key)

            fsm = pending.data.get("state")
            if fsm is not None:
                current_state = await fsm.get_state()
                if current_state != pending.state_name:
                    logger.info(
                        "Prompt fragments discarded because FSM state changed: user=%s state=%s current=%s parts=%s chars=%s",
                        key[1],
                        pending.state_name,
                        current_state,
                        len(pending.parts),
                        len(pending.text),
                    )
                    return

            combined = pending.text
            if not combined.strip():
                return
            if len(combined) > self.max_chars:
                try:
                    await pending.event.answer(
                        f"❌ Промпт слишком длинный: {len(combined)} символов. Максимум для одного ввода — {self.max_chars}."
                    )
                except TelegramAPIError:
                    logger.debug(
                        "Unable to report oversized combined prompt",
                        exc_info=True,
                    )
                return

            logger.info(
                "Prompt fragments coalesced: user=%s state=%s parts=%s chars=%s",
                key[1],
                pending.state_name,
                len(pending.parts),
                len(combined),
            )
            combined_event = self._clone_with_text(pending.event, combined)
            await pending.handler(combined_event, dict(pending.data))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Prompt fragment flush failed: user=%s state=%s",
                key[1],
                key[2],
            )
            if pending is not None:
                try:
                    await pending.event.answer(
                        "❌ Не удалось обработать длинный промпт. Отправьте его ещё раз."
                    )
                except TelegramAPIError:
                    logger.debug(
                        "Unable to report prompt fragment failure",
                        exc_info=True,
                    )
        finally:
            async with self._lock:
                self._inflight.discard(key)
                current = self._pending.get(key)
                if current and current.version == version:
                    self._pending.pop(key, None)

    async def __call__(
        self,
        handler: Handler,
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        text = getattr(event, "text", None)
        if not isinstance(text, str) or not text.strip():
            return await handler(event, data)

        fsm = data.get("state")
        if fsm is None:
            return await handler(event, data)
        state_name = await fsm.get_state()
        if state_name not in PROMPT_TEXT_STATES:
            return await handler(event, data)

        key = self._event_key(event, state_name)
        if key is None:
            return await handler(event, data)

        # Commands must keep their normal cancellation/navigation semantics and
        # must never become part of a pending user prompt.
        if text.lstrip().startswith("/"):
            async with self._lock:
                await self._cancel_pending(key)
            return await handler(event, data)

        async with self._lock:
            if key in self._inflight:
                logger.info(
                    "Duplicate prompt message ignored while generation submit is in-flight: user=%s state=%s chars=%s",
                    key[1],
                    state_name,
                    len(text),
                )
                return None

            pending = self._pending.get(key)
            if pending is None:
                pending = _PendingPrompt(
                    state_name=state_name,
                    handler=handler,
                    event=event,
                    data=dict(data),
                )
                self._pending[key] = pending
            else:
                # Use the latest message as the reply target while preserving
                # the first matched handler/data chain for deterministic routing.
                pending.event = event

            pending.parts.append(text)
            pending.version += 1
            version = pending.version
            if pending.task and not pending.task.done():
                pending.task.cancel()
            pending.task = asyncio.create_task(self._flush(key, version))

        # Do not call the generation handler yet. The quiet-window task will
        # call the already-selected handler once with the combined prompt.
        return None
