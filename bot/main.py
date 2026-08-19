# ruff: noqa  # Legacy monolith; new modules are linted separately.
import asyncio
import hmac
import html
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlparse

# Добавляем родительскую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.env import load_project_env

load_project_env()

from aiogram import BaseMiddleware, Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    BufferedInputFile,
    Update,
)
from aiohttp import web
from bot.internal_api import setup_internal_api
from bot.internal_admin_api import setup_internal_admin_routes
import aiohttp

from bot import db as db_backend
from bot.config import config
from bot.database import (
    cleanup_orphaned_reference_files,
    _merge_task_id_aliases,
    cleanup_saved_references,
    cleanup_stale_local_generation_tasks,
    init_db,
    is_channel_subscription_required,
    is_maintenance_mode_enabled,
    is_user_banned,
)
from bot.handlers import (
    admin_router,
    batch_generation_router,
    common_router,
    generation_router,
    image_analyzer_router,
    payments_router,
)
from bot.handlers.common import ensure_feed_cache_warmup
from bot.handlers.payments import (
    cleanup_stale_cryptobot_pending,
    handle_cryptobot_webhook,
    handle_lava_webhook,
    handle_yookassa_webhook,
    reconcile_lava_pending_transactions,
)
from bot.browser_auth import setup_browser_auth_routes
from bot.feed_reference_media import setup_feed_reference_media_routes
from bot.miniapp import setup_miniapp_routes
from bot.keyboards import (
    get_main_menu_button_keyboard,
    get_required_subscription_keyboard,
)
from bot.services.preset_manager import preset_manager
from bot.services.redis_service import redis_service
from bot.services.subscription_service import (
    REQUIRED_CHANNEL_USERNAME,
    SUBSCRIPTION_CHECK_CALLBACK,
    check_required_channel_subscription,
    should_block_for_subscription,
)
from bot.services.memory_dump_service import build_memory_dump, ensure_memory_tracing
from bot.notification_service import ensure_notification_campaign_worker
from bot.support_service import ensure_support_outbox_worker
from bot.utils.user_facing_errors import make_user_friendly_generation_error
from bot.services.yookassa_service import yookassa_service

CLEANUP_INTERVAL_SECONDS = 24 * 3600
UPLOAD_RETENTION_SECONDS = 24 * 3600
LOG_RETENTION_SECONDS = 24 * 3600
ACTIVE_LOG_FILENAMES = {"bot.log"}

YOOKASSA_RECONCILE_INTERVAL_SECONDS = 5 * 60
YOOKASSA_RECONCILE_BATCH_SIZE = 50
LAVA_RECONCILE_INTERVAL_SECONDS = 5 * 60
LAVA_RECONCILE_BATCH_SIZE = 200
MEMORY_DUMP_INTERVAL_SECONDS = 3 * 3600
DB_BACKUP_INTERVAL_SECONDS = 3 * 3600
DB_BACKUP_TIMEOUT_SECONDS = 30 * 60
_TELEGRAM_WEBHOOK_TASKS: set[asyncio.Task] = set()
TELEGRAM_WEBHOOK_CONCURRENCY_LIMIT = 8
_TELEGRAM_WEBHOOK_SEMAPHORE = asyncio.Semaphore(TELEGRAM_WEBHOOK_CONCURRENCY_LIMIT)
_NEXUS_POLL_IN_FLIGHT: set[str] = set()

USER_BOT_COMMANDS = [
    BotCommand(command="start", description="Текстовый бот и главное меню"),
    BotCommand(command="feed", description="Лента работ"),
    BotCommand(command="prompts", description="Библиотека промптов"),
    BotCommand(command="help", description="Помощь и возможности"),
    BotCommand(command="ref", description="Партнёрская программа"),
    BotCommand(command="earn", description="Заработок на рефералах"),
]
USER_BOT_COMMAND_SCOPES = (
    BotCommandScopeDefault(),
    BotCommandScopeAllPrivateChats(),
)
USER_BOT_COMMAND_LANGUAGES = (None, "ru")

async def _set_commands_chat_menu_button() -> None:
    """Keep Telegram's system menu button on quick commands."""
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/setChatMenuButton"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            url,
            json={"menu_button": {"type": "commands"}},
        ) as response:
            payload = await response.json(content_type=None)
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or "setChatMenuButton failed")

async def _complete_reconciled_order(order_id: str, bot: Bot) -> dict:
    from bot.handlers.payments import _complete_transaction

    return await _complete_transaction(order_id, bot=bot)

async def _yookassa_reconcile_loop(bot: Bot) -> None:
    await asyncio.sleep(YOOKASSA_RECONCILE_INTERVAL_SECONDS)
    while True:
        try:
            results = await yookassa_service.poll_pending_transactions(
                limit=YOOKASSA_RECONCILE_BATCH_SIZE,
                complete_order=lambda order_id: _complete_reconciled_order(order_id, bot),
            )
            if results:
                completed = sum(1 for item in results if item.get("action") == "completed")
                failed = sum(1 for item in results if item.get("action") == "failed")
                still_pending = sum(1 for item in results if item.get("action") == "still_pending")
                not_found = sum(1 for item in results if item.get("status") == "not_found")
                errors = sum(1 for item in results if item.get("error"))
                logger.info(
                    "YooKassa reconcile tick: checked=%s completed=%s failed=%s pending=%s not_found=%s errors=%s",
                    len(results),
                    completed,
                    failed,
                    still_pending,
                    not_found,
                    errors,
                )
        except Exception:
            logger.exception("YooKassa reconcile loop failed")
        await asyncio.sleep(YOOKASSA_RECONCILE_INTERVAL_SECONDS)

async def _lava_reconcile_loop(bot: Bot) -> None:
    await asyncio.sleep(LAVA_RECONCILE_INTERVAL_SECONDS)
    while True:
        try:
            results = await reconcile_lava_pending_transactions(
                limit=LAVA_RECONCILE_BATCH_SIZE,
                bot=bot,
            )
            if results:
                completed = sum(1 for item in results if item.get("action") == "completed")
                failed = sum(1 for item in results if item.get("action") == "failed")
                still_pending = sum(1 for item in results if item.get("action") == "still_pending")
                expired = sum(item.get("count", 0) for item in results if item.get("action") == "expired")
                errors = sum(1 for item in results if item.get("error"))
                logger.info(
                    "Lava reconcile tick: checked=%s completed=%s failed=%s pending=%s expired=%s errors=%s",
                    len(results),
                    completed,
                    failed,
                    still_pending,
                    expired,
                    errors,
                )
        except Exception:
            logger.exception("Lava reconcile loop failed")
        await asyncio.sleep(LAVA_RECONCILE_INTERVAL_SECONDS)

async def _memory_dump_loop(bot: Bot) -> None:
    while True:
        await asyncio.sleep(MEMORY_DUMP_INTERVAL_SECONDS)
        admin_ids = config.admin_ids
        if not admin_ids:
            logger.info("Memory dump send skipped: ADMIN_IDS is empty")
            continue

        try:
            data, filename, caption = build_memory_dump()
        except Exception:
            logger.exception("Failed to build memory dump")
            continue

        for admin_id in admin_ids:
            try:
                await bot.send_document(
                    chat_id=admin_id,
                    document=BufferedInputFile(data, filename=filename),
                    caption=caption,
                )
            except Exception:
                logger.exception("Failed to send memory dump to admin_id=%s", admin_id)

async def _db_backup_loop() -> None:
    backup_script = Path(__file__).resolve().parents[1] / "scripts" / "backup_db.sh"
    while True:
        await asyncio.sleep(DB_BACKUP_INTERVAL_SECONDS)
        env = os.environ.copy()
        env.setdefault("SEND_BACKUP_TO_ADMINS", "1")
        process = None

        try:
            process = await asyncio.create_subprocess_exec(
                str(backup_script),
                cwd=str(backup_script.parent.parent),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=DB_BACKUP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            if process is not None:
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
            logger.exception(
                "DB backup timed out after %s seconds", DB_BACKUP_TIMEOUT_SECONDS
            )
            continue
        except Exception:
            logger.exception("Failed to run DB backup")
            continue

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode == 0:
            if stdout_text:
                logger.info("DB backup completed: %s", stdout_text)
            else:
                logger.info("DB backup completed")
        else:
            logger.error(
                "DB backup failed with code=%s stdout=%s stderr=%s",
                process.returncode,
                stdout_text[-1000:],
                stderr_text[-1000:],
            )

def _configure_logging() -> None:
    if os.environ.get("BANANO_DISABLE_FILE_LOGGING") == "1":
        logging.basicConfig(
            level=logging.INFO,
            handlers=[logging.NullHandler()],
            force=True,
        )
        return

    os.makedirs("logs", exist_ok=True)

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler = TimedRotatingFileHandler(
        "logs/bot.log",
        when="midnight",
        interval=1,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    handlers = [file_handler]
    if os.environ.get("BANANO_LOG_TO_STDOUT") == "1":
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)

    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
        force=True,
    )

    for logger_name in (
        "aiohttp.access",
        "aiohttp.server",
        "aiogram",
        "aiogram.event",
        "aiogram.dispatcher",
    ):
        named_logger = logging.getLogger(logger_name)
        named_logger.handlers.clear()
        named_logger.propagate = True

_configure_logging()
logger = logging.getLogger(__name__)
ensure_memory_tracing()

class FallbackFSMStorage(BaseStorage):
    """Keep handlers responsive if Redis FSM storage fails after startup."""

    def __init__(self, primary: BaseStorage, fallback: BaseStorage):
        self._primary = primary
        self._fallback = fallback
        self._fallback_active = False

    async def _call(self, method_name: str, *args, **kwargs):
        if not self._fallback_active:
            try:
                return await getattr(self._primary, method_name)(*args, **kwargs)
            except Exception:
                self._fallback_active = True
                logger.exception(
                    "FSM Redis storage failed; switching to in-memory FSM storage"
                )

        return await getattr(self._fallback, method_name)(*args, **kwargs)

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        await self._call("set_state", key=key, state=state)

    async def get_state(self, key: StorageKey) -> str | None:
        return await self._call("get_state", key=key)

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self._call("set_data", key=key, data=data)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        return await self._call("get_data", key=key)

    async def get_value(
        self,
        storage_key: StorageKey,
        dict_key: str,
        default: Any | None = None,
    ) -> Any | None:
        return await self._call(
            "get_value",
            storage_key=storage_key,
            dict_key=dict_key,
            default=default,
        )

    async def update_data(
        self, key: StorageKey, data: Mapping[str, Any]
    ) -> dict[str, Any]:
        return await self._call("update_data", key=key, data=data)

    def create_isolation(self, **kwargs: Any):
        if not self._fallback_active and hasattr(self._primary, "create_isolation"):
            try:
                return self._primary.create_isolation(**kwargs)
            except Exception:
                self._fallback_active = True
                logger.exception(
                    "FSM Redis isolation failed; switching to in-memory isolation"
                )
        return SimpleEventIsolation()

    async def close(self) -> None:
        for storage in (self._primary, self._fallback):
            try:
                await storage.close()
            except Exception:
                logger.exception("Failed to close FSM storage")

class AccessGuardMiddleware(BaseMiddleware):
    """Blocks banned users, maintenance traffic and unsubscribed users."""

    @staticmethod
    def _callback_data(event: types.TelegramObject) -> str:
        value = getattr(event, "data", "")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _message_text(event: types.TelegramObject) -> str:
        value = getattr(event, "text", "")
        return value if isinstance(value, str) else ""

    def _is_admin_management_event(self, event: types.TelegramObject) -> bool:
        callback_data = self._callback_data(event)
        if callback_data.startswith("admin_"):
            return True

        text = self._message_text(event).strip()
        if not text.startswith("/"):
            return False
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        return command in {"/admin", "/admin_ai"}

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        is_admin_user = config.is_admin(user.id)
        is_subscription_check_callback = (
            self._callback_data(event) == SUBSCRIPTION_CHECK_CALLBACK
        )
        is_admin_management_event = (
            is_admin_user and self._is_admin_management_event(event)
        )

        try:
            if not is_admin_user and await is_user_banned(user.id):
                await self._reply(event, "⛔ Доступ к боту ограничен.")
                return None
            if not is_admin_user and await is_maintenance_mode_enabled():
                await self._reply(
                    event,
                    "🛠 Бот временно на техническом обслуживании. Попробуйте позже.",
                )
                return None
            if is_subscription_check_callback:
                return await handler(event, data)
            if is_admin_management_event:
                return await handler(event, data)
            if await is_channel_subscription_required():
                bot = data.get("bot") or getattr(event, "bot", None)
                if not bot:
                    logger.warning("Access guard has no bot instance for subscription check")
                    await self._reply_required_subscription(event)
                    return None

                result = await check_required_channel_subscription(bot, user.id)
                if should_block_for_subscription(result):
                    await self._reply_required_subscription(event)
                    return None
        except Exception:
            logger.exception("Access guard failed; passing update through")

        return await handler(event, data)

    async def _reply(self, event: types.TelegramObject, text: str) -> None:
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer(text, show_alert=True)
            except Exception:
                logger.debug("Failed to answer blocked callback", exc_info=True)
            return
        if isinstance(event, types.Message):
            try:
                await event.answer(text)
            except Exception:
                logger.debug("Failed to answer blocked message", exc_info=True)

    async def _reply_required_subscription(self, event: types.TelegramObject) -> None:
        text = (
            "🔐 Доступ к боту открыт только подписчикам канала "
            f"@{REQUIRED_CHANNEL_USERNAME}.\n\n"
            "Подпишитесь на канал и нажмите «Проверить подписку»."
        )
        markup = get_required_subscription_keyboard()
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer("Сначала подпишитесь на канал", show_alert=True)
            except Exception:
                logger.debug("Failed to answer subscription callback", exc_info=True)
            try:
                await event.message.answer(text, reply_markup=markup)
            except Exception:
                logger.debug("Failed to send subscription message", exc_info=True)
            return
        if isinstance(event, types.Message):
            try:
                await event.answer(text, reply_markup=markup)
            except Exception:
                logger.debug("Failed to answer subscription message", exc_info=True)

def _preview_log_payload(value, limit: int = 1200) -> str:
    def _redact_payload(obj):
        if isinstance(obj, dict):
            redacted = {}
            for key, item in obj.items():
                key_str = str(key)
                lowered = key_str.lower()
                if any(
                    marker in lowered
                    for marker in (
                        "authorization",
                        "cookie",
                        "credential",
                        "password",
                        "signature",
                        "secret",
                        "token",
                        "api_key",
                        "apikey",
                    )
                ):
                    redacted[key_str] = "[redacted]"
                    continue
                if lowered in {"prompt", "negative_prompt", "system_prompt", "raw_body", "body_text", "param", "params"}:
                    if isinstance(item, str):
                        redacted[key_str] = f"[redacted:{len(item)} chars]"
                    else:
                        redacted[key_str] = "[redacted]"
                    continue
                if "url" in lowered and isinstance(item, str):
                    redacted[key_str] = "[redacted:url]"
                    continue
                redacted[key_str] = _redact_payload(item)
            return redacted
        if isinstance(obj, list):
            return [_redact_payload(item) for item in obj]
        if isinstance(obj, str):
            if "http://" in obj or "https://" in obj:
                return "[redacted:url]"
            return obj
        return obj

    try:
        prepared = _redact_payload(value)
        if isinstance(prepared, (dict, list)):
            text = json.dumps(prepared, ensure_ascii=False, default=str)
        elif isinstance(prepared, bytes):
            text = prepared.decode("utf-8", errors="replace")
        else:
            text = str(prepared)
    except Exception:
        text = repr(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"

def _safe_log_url(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if not parsed.scheme:
        return "[not configured]"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path or ""
    return f"{parsed.scheme}://{host}{path}"

def _preview_log_headers(headers, limit: int = 1200) -> str:
    return _preview_log_payload(dict(headers), limit=limit)

def _build_dispatcher_storage():
    try:
        from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage

        storage = RedisStorage.from_url(
            config.redis_url,
            key_builder=DefaultKeyBuilder(prefix=config.REDIS_PREFIX, with_bot_id=True),
        )
        logger.info("FSM storage configured via Redis: %s", _safe_log_url(config.redis_url))
        return FallbackFSMStorage(storage, MemoryStorage())
    except Exception as exc:
        logger.warning("Redis FSM storage unavailable, fallback to MemoryStorage: %s", exc)
        return MemoryStorage()

def _get_task_model_label(model: str | None, task_type: str | None = None) -> str:
    """Возвращает аккуратное имя модели для пользовательских уведомлений."""
    if not model:
        return "AI"

    mapping = {
        "aleph": "Aleph Video",
        "glow": "Kling Glow",
        "grok_imagine": "Grok Imagine",
        "grok_imagine_v15": "Grok Imagine 1.5 NEW🔥🔥🔥",
        "seedance_2": "Bytedance Seedance 2.0",
        "grok_imagine_i2i": "Grok Imagine i2i",
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "veo3": "Veo 3.1 Quality",
        "veo3_fast": "Veo 3.1 Fast",
        "veo3_lite": "Veo 3.1 Lite",
        "gemini_omni": "Gemini Omni",
        "gemini_omni_video": "Gemini Omni Video",
        "gemini_omni_audio": "Gemini Omni Audio",
        "gemini_omni_character": "Gemini Omni Character",
        "banana_pro": "Banana Pro",
        "banana_2": "Banana 2",
        "nano-banana-2-lite": "Nano Banana 2 Lite 🔥",
        "seedream_edit": "Seedream 4.5",
        "seedream_5_pro": "Seedream 5 Pro",
        "flux_pro": "GPT Image 2",
        "v26_pro": "Kling 2.5 Turbo Pro",
        "avatar_std": "Kling AI Avatar Standard",
        "avatar_pro": "Kling AI Avatar Pro",
        "nanobanana": "Nano Banana",
    }
    return mapping.get(
        model, model if task_type != "image" else model.replace("_", " ").title()
    )

async def _resolve_task_telegram_id(task, *, context: str = "") -> int | None:
    """Resolve the Telegram chat for a generation task.

    generation_tasks stores both the internal users.id and the launch-time
    telegram_id. Prefer the launch-time telegram_id because it is the exact chat
    that created the task; use users.id lookup only as a compatibility fallback.
    """
    if not task:
        return None

    stored_telegram_id = getattr(task, "telegram_id", None)
    internal_user_id = getattr(task, "user_id", None)
    task_id = getattr(task, "task_id", None)
    resolved_telegram_id = None

    if internal_user_id is not None:
        try:
            from bot.database import get_telegram_id_by_user_id

            resolved_telegram_id = await get_telegram_id_by_user_id(internal_user_id)
        except Exception:
            logger.exception(
                "Failed to resolve telegram_id by internal user_id=%s for task=%s context=%s",
                internal_user_id,
                task_id,
                context,
            )

    if stored_telegram_id:
        try:
            normalized_stored = int(stored_telegram_id)
        except (TypeError, ValueError):
            normalized_stored = None

        if normalized_stored:
            if (
                resolved_telegram_id
                and int(resolved_telegram_id) != normalized_stored
            ):
                logger.error(
                    "Task recipient mismatch: task=%s context=%s internal_user_id=%s "
                    "generation_tasks.telegram_id=%s users.telegram_id=%s. "
                    "Using generation_tasks.telegram_id.",
                    task_id,
                    context,
                    internal_user_id,
                    normalized_stored,
                    resolved_telegram_id,
                )
            return normalized_stored

    if resolved_telegram_id:
        logger.warning(
            "Task %s has no generation_tasks.telegram_id; using users.telegram_id=%s "
            "from internal_user_id=%s context=%s",
            task_id,
            resolved_telegram_id,
            internal_user_id,
            context,
        )
        return int(resolved_telegram_id)

    logger.error(
        "Cannot resolve telegram_id for task=%s internal_user_id=%s context=%s",
        task_id,
        internal_user_id,
        context,
    )
    return None

def _extract_first(obj, keys):
    """Рекурсивно извлекает первое непустое значение по списку ключей."""
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if value not in (None, ""):
                return value
        for value in obj.values():
            found = _extract_first(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _extract_first(item, keys)
            if found not in (None, ""):
                return found
    return None

def _extract_gemini_omni_asset_id(obj, asset_kind: str):
    """Extract Gemini Omni Audio ID or Character ID from async KIE payloads."""
    if asset_kind == "audio":
        keys = (
            "kieAudioId",
            "kieAudioID",
            "audioId",
            "audioID",
            "audio_id",
        )
    elif asset_kind == "character":
        keys = (
            "kieCharacterId",
            "kieCharacterID",
            "characterId",
            "characterID",
            "character_id",
        )
    else:
        return None

    candidates = [obj]
    result_json = _extract_first(obj, ("resultJson", "result_json"))
    if isinstance(result_json, str) and result_json.strip():
        try:
            candidates.append(json.loads(result_json))
        except json.JSONDecodeError:
            pass

    for candidate in candidates:
        found = _extract_first(candidate, keys)
        if isinstance(found, list):
            found = found[0] if found else None
        if found not in (None, ""):
            return str(found)
    return None

def _extract_task_request_data(task) -> dict:
    """Safely decode stored request_data for debug logging."""
    if not task or not getattr(task, "request_data", None):
        return {}
    try:
        return json.loads(task.request_data)
    except Exception:
        return {}

def _normalize_user_prompt(candidate: str) -> str:
    if not isinstance(candidate, str):
        return ""
    text = candidate.strip()
    if not text:
        return ""

    normalized = text.replace("\r\n", "\n")
    markers = [
        "User request:",
        "User prompt:",
        "Промпт пользователя:",
        "Запрос пользователя:",
    ]
    for marker in markers:
        idx = normalized.find(marker)
        if idx != -1:
            tail = normalized[idx + len(marker):].strip()
            if tail:
                return tail
    return text

def _extract_used_prompt(task) -> str:
    if getattr(task, "source_feed_gen_id", None):
        return ""
    request_data = _extract_task_request_data(task)
    for candidate in (
        request_data.get("user_prompt"),
        request_data.get("original_prompt"),
        request_data.get("prompt"),
        getattr(task, "prompt", None),
        request_data.get("effective_prompt"),
    ):
        normalized = _normalize_user_prompt(candidate)
        if normalized:
            return normalized
    return ""

def _get_result_prompt_caption(task) -> tuple[str, str]:
    if getattr(task, "source_feed_gen_id", None):
        return "<b>Промпт скрыт</b>", "Промпт"
    used_prompt = _extract_used_prompt(task)
    if not used_prompt:
        return "<pre>—</pre>", "Промпт"

    escaped = html.escape(used_prompt.strip())
    return f"<pre>{escaped}</pre>", "Промпт"

async def _send_full_prompt_message(bot_instance: Bot, telegram_id: int, task, reference_urls: list[str] | None = None) -> None:
    return

async def _download_remote_bytes(url: str, timeout_seconds: int = 30) -> bytes | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        import aiohttp

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=timeout_seconds) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Download failed: {resp.status}")
                return await resp.read()
    except Exception as e:
        logger.warning(f"aiohttp download failed for {url}: {e}")

    try:
        import asyncio
        import requests

        def _download_via_requests() -> bytes:
            resp = requests.get(url, timeout=timeout_seconds, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Download failed: {resp.status_code}")
            return resp.content

        return await asyncio.to_thread(_download_via_requests)
    except Exception as e:
        logger.error(f"Failed to download remote file {url}: {e}")
        return None

def _is_local_static_result_url(url: str) -> bool:
    candidate = str(url or "").strip()
    if not candidate:
        return False
    base_url = str(getattr(config, "static_base_url", "") or "").rstrip("/")
    return bool(base_url) and candidate.startswith(f"{base_url}/uploads/")

def _guess_storage_extension(result_url: str, task_type: str = "image") -> str:
    candidate = Path(urlparse(str(result_url or "")).path).suffix.lower().lstrip(".")
    if candidate in {"jpg", "jpeg", "png", "webp", "gif", "bmp", "mp4", "mov", "webm", "mkv", "avi", "m4v"}:
        return candidate
    return "mp4" if str(task_type or "").lower() == "video" else "png"

async def _persist_result_url_if_needed(result_url: str | None, *, task_type: str = "image") -> str | None:
    candidate = str(result_url or "").strip()
    if not candidate or not candidate.startswith(("http://", "https://")):
        return result_url
    if _is_local_static_result_url(candidate):
        return candidate
    if not getattr(config, "PERSIST_PROVIDER_RESULTS", False):
        return candidate

    file_bytes = await _download_remote_bytes(
        candidate,
        timeout_seconds=90 if str(task_type or "").lower() == "video" else 30,
    )
    if not file_bytes:
        return candidate

    try:
        from bot.handlers.generation import save_uploaded_file

        saved_url = save_uploaded_file(
            file_bytes,
            _guess_storage_extension(candidate, task_type=task_type),
        )
        if saved_url:
            logger.info("Persisted result url locally: %s -> %s", candidate, saved_url)
            return saved_url
    except Exception:
        logger.exception("Failed to persist result url locally: %s", candidate)

    return candidate

def _build_preview_photo_bytes(image_bytes: bytes, max_photo_size: int = 10 * 1024 * 1024) -> bytes | None:
    if not image_bytes:
        return None
    if len(image_bytes) <= max_photo_size:
        return image_bytes

    try:
        from io import BytesIO
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            max_side = 2048
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side))

            for quality in (92, 85, 78, 70, 62, 55):
                out = BytesIO()
                img.save(out, format="JPEG", quality=quality, optimize=True)
                data = out.getvalue()
                if len(data) <= max_photo_size:
                    logger.info(
                        "Built preview photo bytes: original=%s preview=%s quality=%s",
                        len(image_bytes),
                        len(data),
                        quality,
                    )
                    return data

            out = BytesIO()
            img.save(out, format="JPEG", quality=45, optimize=True)
            data = out.getvalue()
            logger.info(
                "Built oversized fallback preview photo bytes: original=%s preview=%s",
                len(image_bytes),
                len(data),
            )
            return data if data else None
    except Exception as e:
        logger.error(f"Failed to build preview photo bytes: {e}")
        return None

def _guess_result_filename(result_url: str, fallback_base: str = "original") -> str:
    from urllib.parse import urlparse
    parsed = urlparse(str(result_url or ""))
    name = Path(parsed.path).name or fallback_base
    if "." not in name:
        name = f"{name}.png"
    return name

async def _send_original_file(bot_instance: Bot, telegram_id: int, result_url: str, image_bytes: bytes | None = None) -> bool:
    if not result_url:
        return False
    filename = _guess_result_filename(result_url)
    try:
        if image_bytes:
            await bot_instance.send_document(
                chat_id=telegram_id,
                document=types.BufferedInputFile(image_bytes, filename=filename),
                caption="📎 Исходник файлом",
            )
            return True
        await bot_instance.send_document(
            chat_id=telegram_id,
            document=result_url,
            caption="📎 Исходник файлом",
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send original file to {telegram_id}: {e}")
        return False

async def _send_video_file_from_url(
    bot_instance: Bot,
    telegram_id: int,
    video_url: str,
    *,
    caption: str,
    reply_markup=None,
    timeout_seconds: int = 120,
    max_upload_bytes: int = 50 * 1024 * 1024,
) -> bool:
    if not isinstance(video_url, str) or not video_url.lower().startswith(
        ("http://", "https://")
    ):
        return False

    import tempfile

    from aiogram.types import FSInputFile

    tmp_file = None
    suffix = f".{_guess_storage_extension(video_url, task_type='video')}"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Telegram Bot SDK/1.0)",
        "Accept": "*/*",
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                video_url,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Download failed: status {resp.status}")

                content_length = getattr(resp, "content_length", None)
                if content_length and content_length > max_upload_bytes:
                    logger.warning(
                        "Video file is too large for upload fallback: size=%s limit=%s url=%s",
                        content_length,
                        max_upload_bytes,
                        video_url,
                    )
                    return False

                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp_file = tmp.name
                try:
                    downloaded = 0
                    async for chunk in resp.content.iter_chunked(1024 * 64):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > max_upload_bytes:
                            raise RuntimeError(
                                f"Video file exceeds upload fallback limit: {downloaded} > {max_upload_bytes}"
                            )
                        await asyncio.to_thread(tmp.write, chunk)
                finally:
                    await asyncio.to_thread(tmp.close)

        await bot_instance.send_video(
            chat_id=telegram_id,
            video=FSInputFile(tmp_file),
            caption=caption,
            parse_mode="HTML",
            supports_streaming=True,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        logger.error(
            "Failed to download and send video file to %s: %s",
            telegram_id,
            e,
        )
        return False
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                logger.exception("Failed to remove temporary video file")

def _should_send_prompt_followup(task, caption_prompt_threshold: int = 650) -> bool:
    if not task:
        return False
    if getattr(task, "source_feed_gen_id", None):
        return False
    return bool(_extract_used_prompt(task))

def _format_named_links(urls: list[str], label: str) -> str:
    if not urls:
        return ""
    parts = []
    for idx, url in enumerate(urls, start=1):
        safe_url = html.escape(url, quote=True)
        parts.append(f"<a href='{safe_url}'>#{idx}</a>")
    return f"{label}: " + ", ".join(parts)

def _get_task_resolution(task) -> str:
    request_data = _extract_task_request_data(task)
    for key in ("resolution", "quality"):
        value = request_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def _get_task_mode_label(task, reference_urls: list[str]) -> str:
    task_type = str(getattr(task, "type", "") or "").lower()
    if task_type == "video":
        return "Изображение → Видео" if reference_urls else "Текст → Видео"
    return "Изображение → Изображение" if reference_urls else "Текст → Изображение"

async def _send_used_prompt_message(bot_instance: Bot, telegram_id: int, task, result_url: str | None = None) -> None:
    prompt = (_extract_used_prompt(task) or "").strip()
    if not prompt:
        return
    # Не отправляем промпт, если он скрыт (повтор из публичной ленты)
    if getattr(task, "source_feed_gen_id", None):
        return

    result_urls = [result_url] if result_url else []
    source_urls = _extract_reference_image_urls(task)
    model_label = _get_task_model_label(getattr(task, "model", None), getattr(task, "type", None))
    mode_label = _get_task_mode_label(task, source_urls)
    resolution = _get_task_resolution(task)

    header_lines = [
        "✅ <b>Готово!</b>",
        "",
        f"ID: <code>{html.escape(str(_public_task_id(task, getattr(task, 'task_id', ''))))}</code>",
        "",
        f"Модель: <b>{html.escape(model_label)}</b>",
        f"Режим: {html.escape(mode_label)}",
    ]
    if getattr(task, "aspect_ratio", None):
        header_lines.append(f"Формат: {html.escape(str(task.aspect_ratio).replace(':', '∶'))}")
    if resolution:
        header_lines.append(f"Разрешение: {html.escape(resolution)}")
    if getattr(task, "cost", None) is not None:
        header_lines.append(f"Списано: <b>{html.escape(str(task.cost))}</b>")

    link_lines = []
    result_line = _format_named_links(result_urls, "Результат")
    if result_line:
        link_lines.append(result_line)
    source_line = _format_named_links(source_urls, "Исходники")
    if source_line:
        link_lines.append(source_line)

    prefix = "\n".join(header_lines)
    if link_lines:
        prefix += "\n\n" + "\n\n".join(link_lines)
    prefix += "\n\nПромпт:\n"

    def make_block(chunk: str) -> str:
        return f"<blockquote expandable><code>{html.escape(chunk)}</code></blockquote>"

    max_chars = 3900
    first_budget = max_chars - len(prefix) - 80
    if first_budget < 400:
        first_budget = 400

    if len(prompt) <= first_budget:
        await bot_instance.send_message(
            chat_id=telegram_id,
            text=prefix + make_block(prompt),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_main_menu_button_keyboard(),
        )
        return

    first_chunk = prompt[:first_budget]
    await bot_instance.send_message(
        chat_id=telegram_id,
        text=prefix + make_block(first_chunk),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    rest = prompt[first_budget:]
    chunk_size = 3200
    chunks = [rest[i:i + chunk_size] for i in range(0, len(rest), chunk_size)]
    for idx, chunk in enumerate(chunks, start=2):
        await bot_instance.send_message(
            chat_id=telegram_id,
            text=f"Промпт (продолжение {idx}):\n" + make_block(chunk),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=(
                get_main_menu_button_keyboard()
                if idx == len(chunks) + 1
                else None
            ),
        )

def _collect_http_urls(value) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.startswith(("http://", "https://")):
            urls.append(candidate)
        return urls
    if isinstance(value, dict):
        for key in ("url", "file_url", "public_url", "source_url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip().startswith(("http://", "https://")):
                urls.append(candidate.strip())
        for nested in value.values():
            urls.extend(_collect_http_urls(nested))
        return urls
    if isinstance(value, (list, tuple, set)):
        for item in value:
            urls.extend(_collect_http_urls(item))
    return urls

def _normalize_reference_key(url: str) -> str:
    candidate = str(url or "").strip().split("?")[0].rstrip("/")
    name = candidate.rsplit("/", 1)[-1]
    if name.startswith("refs_image_"):
        parts = name.split("_", 4)
        if len(parts) >= 5:
            name = parts[-1]
    return name.lower()

def _score_reference_url(url: str) -> tuple[int, int]:
    candidate = str(url or "")
    score = 0
    if "tanyapi.chillcreative.ru/uploads/refs/" in candidate:
        score += 20
    if "tempfile.redpandaai.co" in candidate:
        score -= 5
    if candidate.startswith("https://"):
        score += 1
    return (score, -len(candidate))

def _dedupe_urls(urls: list[str], limit: int = 6) -> list[str]:
    best_by_key: dict[str, str] = {}
    for raw in urls:
        url = str(raw or "").strip()
        if not url:
            continue
        key = _normalize_reference_key(url)
        prev = best_by_key.get(key)
        if prev is None or _score_reference_url(url) > _score_reference_url(prev):
            best_by_key[key] = url

    result = sorted(best_by_key.values(), key=lambda item: (_normalize_reference_key(item), item))
    return result[:limit]

def _extract_reference_image_urls(task=None, webhook_data: dict | None = None) -> list[str]:
    urls: list[str] = []
    request_data = _extract_task_request_data(task)
    for key in (
        "reference_images",
        "image_urls",
        "image_input",
        "input_urls",
        "first_frame_url",
        "last_frame_url",
        "reference_image_urls",
        "image_url",
    ):
        urls.extend(_collect_http_urls(request_data.get(key)))

    if webhook_data:
        try:
            param_str = webhook_data.get("param", "{}")
            param_json = json.loads(param_str) if isinstance(param_str, str) else (param_str or {})
            input_str = param_json.get("input", "{}")
            input_json = json.loads(input_str) if isinstance(input_str, str) else (input_str or {})
            for key in (
                "image_urls",
                "image_input",
                "input_urls",
                "first_frame_url",
                "last_frame_url",
                "reference_image_urls",
                "image_url",
            ):
                urls.extend(_collect_http_urls(input_json.get(key)))
        except Exception:
            pass

    return _dedupe_urls(urls, limit=4)

def _format_reference_links(urls: list[str]) -> str:
    return ""

def _sanitize_base_caption(base_caption: str) -> str:
    base = str(base_caption or "").strip()
    for marker in ("\n\n🎯", "🎯 Промпт:", "🎯 <b>Промпт</b>", "\n🖼 <b>Рефы:</b>"):
        idx = base.find(marker)
        if idx != -1:
            base = base[:idx].rstrip()
    return base

def _with_original_link(base_caption: str, result_url: str | None) -> str:
    base = str(base_caption or "").strip()
    if not result_url:
        return base
    if "Открыть оригинал" in base or "Скачать оригинал" in base:
        return base
    safe_url = html.escape(str(result_url), quote=True)
    return f"{base}\n\n🔗 <a href='{safe_url}'>Открыть оригинал</a>"

def _html_fragment(value, limit: int | None = None) -> str:
    text = "" if value is None else str(value)
    if limit is not None and len(text) > limit:
        text = text[:limit]
    return html.escape(text)

def _task_callback_id(task, fallback_task_id: str | None = None) -> str:
    if task and getattr(task, "id", None):
        return str(task.id)
    return str(fallback_task_id or "")

def _extract_task_id_aliases(task) -> list[str]:
    request_data = _extract_task_request_data(task)
    raw_aliases = request_data.get("task_id_aliases") or []
    if isinstance(raw_aliases, str):
        raw_aliases = [raw_aliases]
    aliases: list[str] = []
    for value in raw_aliases:
        normalized = str(value or "").strip()
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return aliases

def _public_task_id(task, fallback_task_id: str | None = None) -> str:
    for alias in _extract_task_id_aliases(task):
        if alias.startswith("img_"):
            return alias
    stored_task_id = str(getattr(task, "task_id", "") or "").strip() if task else ""
    if stored_task_id.startswith("img_"):
        return stored_task_id
    return stored_task_id or str(fallback_task_id or "")

def _provider_task_id_line(task, fallback_task_id: str | None = None) -> str:
    public_id = _public_task_id(task, fallback_task_id)
    candidates = []
    stored_task_id = str(getattr(task, "task_id", "") or "").strip() if task else ""
    if stored_task_id:
        candidates.append(stored_task_id)
    for alias in _extract_task_id_aliases(task):
        candidates.append(alias)
    fallback = str(fallback_task_id or "").strip()
    if fallback:
        candidates.append(fallback)
    for candidate in candidates:
        if candidate and candidate != public_id and not candidate.startswith("img_"):
            return f"\n• ID провайдера: <code>{_html_fragment(candidate)}</code>"
    return ""


def _build_plain_result_link_text(
    *,
    media_label: str,
    model_label: str,
    task_id: str,
    result_url: str,
    notice: str | None = None,
) -> str:
    lines = [
        f"{media_label} готово.",
        f"Модель: {model_label or 'AI'}",
        f"ID: {task_id}",
        "",
        notice or "Telegram не смог прикрепить файл автоматически.",
        "Оригинал можно открыть по ссылке:",
        str(result_url),
    ]
    text = "\n".join(lines)
    return text[:4000]

async def _send_plain_result_link(
    bot_instance: Bot,
    telegram_id: int,
    *,
    media_label: str,
    model_label: str,
    task_id: str,
    result_url: str,
    reply_markup=None,
    notice: str | None = None,
) -> None:
    await bot_instance.send_message(
        chat_id=telegram_id,
        text=_build_plain_result_link_text(
            media_label=media_label,
            model_label=model_label,
            task_id=task_id,
            result_url=result_url,
            notice=notice,
        ),
        reply_markup=reply_markup,
        disable_web_page_preview=False,
    )

async def _send_polled_nexus_image_result(
    bot_instance: Bot,
    task,
    result_url: str,
    *,
    provider_task_id: str | None = None,
    service_name: str = "Nano Banana",
) -> bool:
    from bot.database import complete_video_task
    from bot.keyboards import get_image_result_keyboard

    telegram_id = await _resolve_task_telegram_id(task, context="nexus_poller")
    if not telegram_id:
        logger.error(
            "Nexus poller: cannot resolve telegram_id for task %s",
            getattr(task, "task_id", None),
        )
        return False

    persisted_url = await _persist_result_url_if_needed(result_url, task_type="image")
    reference_preview_urls = _extract_reference_image_urls(task)
    model_label = _get_task_model_label(getattr(task, "model", None), getattr(task, "type", None))
    task_lookup_id = provider_task_id or getattr(task, "task_id", "")
    display_task_id = _public_task_id(task, task_lookup_id)
    full_caption = (
        "✅ <b>Изображение готово</b>\n"
        f"• Модель: <code>{_html_fragment(model_label)}</code>\n"
        f"• ID: <code>{_html_fragment(display_task_id)}</code>"
        f"{_provider_task_id_line(task, task_lookup_id)}"
    )
    if getattr(task, "cost", None):
        full_caption += f"\n• Стоимость: <code>{_html_fragment(task.cost)}🍌</code>"
    if getattr(task, "aspect_ratio", None):
        full_caption += (
            f"\n• Формат: <code>{_html_fragment(str(task.aspect_ratio).replace(':', '∶'))}</code>"
        )
    preview_caption = _build_single_result_caption(
        _with_original_link(full_caption, persisted_url),
        task,
        reference_preview_urls,
    )
    keyboard = get_image_result_keyboard(
        persisted_url,
        task_id=_task_callback_id(task, task_lookup_id),
    )

    sent_media = False
    image_bytes = await _download_remote_bytes(persisted_url, timeout_seconds=30)
    preview_sent = False
    if image_bytes:
        preview_bytes = _build_preview_photo_bytes(image_bytes)
        if preview_bytes:
            try:
                photo = types.BufferedInputFile(
                    preview_bytes,
                    filename="generated_preview.jpg",
                )
                await bot_instance.send_photo(
                    chat_id=telegram_id,
                    photo=photo,
                    caption=preview_caption,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
                preview_sent = True
                logger.info(
                    "Nexus poller: %s image preview sent as file-photo to user %s",
                    service_name,
                    telegram_id,
                )
            except Exception as exc:
                logger.info(
                    "Nexus poller: preview file-photo send failed for task %s (%s)",
                    task_lookup_id,
                    exc,
                )

    if not preview_sent:
        try:
            await bot_instance.send_photo(
                chat_id=telegram_id,
                photo=persisted_url,
                caption=preview_caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            preview_sent = True
            logger.info(
                "Nexus poller: %s image preview sent via URL to user %s",
                service_name,
                telegram_id,
            )
        except Exception as exc:
            logger.info(
                "Nexus poller: image URL send failed for task %s (%s)",
                task_lookup_id,
                exc,
            )

    original_sent = await _send_original_file(
        bot_instance,
        telegram_id,
        persisted_url,
        image_bytes,
    )
    if preview_sent or original_sent:
        await complete_video_task(task_lookup_id, persisted_url)
        sent_media = True
        if _should_send_prompt_followup(task):
            try:
                await _send_used_prompt_message(
                    bot_instance,
                    telegram_id,
                    task,
                    persisted_url,
                )
            except Exception:
                logger.exception(
                    "Nexus poller: failed to send prompt follow-up for task %s",
                    task_lookup_id,
                )
        return True

    try:
        await _send_plain_result_link(
            bot_instance,
            telegram_id,
            media_label="Изображение",
            model_label=model_label,
            task_id=display_task_id,
            result_url=persisted_url,
            reply_markup=keyboard,
            notice="Telegram не смог отправить превью автоматически.",
        )
        logger.info(
            "Nexus poller: fallback text sent for task %s to user %s",
            task_lookup_id,
            telegram_id,
        )
    except Exception:
        logger.exception(
            "Nexus poller: all Telegram delivery attempts failed for task %s",
            task_lookup_id,
        )
    finally:
        await complete_video_task(task_lookup_id, persisted_url)
    return True

async def _fail_polled_nexus_image_task(
    bot_instance: Bot,
    task,
    *,
    provider_task_id: str | None = None,
    service_name: str = "Nano Banana",
    reason: str | None = None,
) -> bool:
    from bot.database import add_credits, complete_video_task
    from bot.keyboards import get_failed_image_retry_keyboard

    task_lookup_id = provider_task_id or getattr(task, "task_id", "")
    telegram_id = await _resolve_task_telegram_id(task, context="nexus_poller")
    if telegram_id and getattr(task, "cost", None):
        try:
            await add_credits(telegram_id, task.cost)
        except Exception:
            logger.exception(
                "Nexus poller: failed to refund credits for task %s",
                task_lookup_id,
            )

    await complete_video_task(task_lookup_id, None)

    if not telegram_id:
        return False

    try:
        await bot_instance.send_message(
            chat_id=telegram_id,
            text=_build_failure_notification_text(
                service_name=service_name,
                task_id=_public_task_id(task, task_lookup_id),
                reason=reason,
                media_kind="результата",
                refund_text=(
                    "\n\nБананы за эту попытку уже возвращены."
                    if getattr(task, "cost", None)
                    else "\n\nПопробуйте повторить попытку немного позже."
                ),
            ),
            parse_mode="HTML",
            reply_markup=get_failed_image_retry_keyboard(_task_callback_id(task, task_lookup_id)),
        )
        return True
    except Exception:
        logger.exception(
            "Nexus poller: failed to notify user about task failure %s",
            task_lookup_id,
        )
        return False

async def _poll_single_nexus_image_task(bot_instance: Bot, task_row: dict[str, Any]) -> None:
    from bot.database import get_task_by_id
    from bot.handlers.generation import save_uploaded_file
    from bot.services.nano_banana_2_service import nano_banana_2_service
    from bot.services.nano_banana_pro_service import nano_banana_pro_service

    request_data = task_row.get("request_data") or {}
    provider_task_id = str(
        request_data.get("provider_task_id") or task_row.get("task_id") or ""
    ).strip()
    if not provider_task_id or provider_task_id in _NEXUS_POLL_IN_FLIGHT:
        return

    _NEXUS_POLL_IN_FLIGHT.add(provider_task_id)
    try:
        task = await get_task_by_id(provider_task_id)
        if not task or getattr(task, "status", "") == "completed":
            return

        provider_model = str(
            request_data.get("provider_model") or getattr(task, "model", "") or ""
        ).strip().lower()
        if provider_model == "nano-banana-pro":
            service = nano_banana_pro_service
            service_name = "Nano Banana Pro"
        else:
            service = nano_banana_2_service
            service_name = "Nano Banana 2"

        payload = await service.get_task_status(provider_task_id)
        if not payload:
            return

        status = str(payload.get("status") or payload.get("state") or "").strip().lower()
        if status in {"pending", "processing", "running", "queued", "accepted"}:
            return

        if status == "completed":
            provider = getattr(service, "primary_provider", None)
            if not provider or not hasattr(provider, "get_completed_result"):
                logger.error(
                    "Nexus poller: provider for task %s cannot resolve completed result",
                    provider_task_id,
                )
                return
            result = await provider.get_completed_result(provider_task_id, payload)
            if not result:
                retried_task_id = await _retry_nexus_banana_image_failure(
                    task,
                    provider_task_id,
                    reason="Nexus completed task without a usable image result",
                )
                if retried_task_id:
                    return
                await _fail_polled_nexus_image_task(
                    bot_instance,
                    task,
                    provider_task_id=provider_task_id,
                    service_name=service_name,
                    reason="Nexus completed task without a usable image result",
                )
                return
            result_url = str(result.get("result_url") or "").strip()
            if not result_url and result.get("image_bytes"):
                result_url = save_uploaded_file(result["image_bytes"], "png")
            if not result_url:
                retried_task_id = await _retry_nexus_banana_image_failure(
                    task,
                    provider_task_id,
                    reason="Nexus returned an empty image payload",
                )
                if retried_task_id:
                    return
                await _fail_polled_nexus_image_task(
                    bot_instance,
                    task,
                    provider_task_id=provider_task_id,
                    service_name=service_name,
                    reason="Nexus returned an empty image payload",
                )
                return
            await _send_polled_nexus_image_result(
                bot_instance,
                task,
                result_url,
                provider_task_id=provider_task_id,
                service_name=service_name,
            )
            return

        if status == "failed":
            retried_task_id = await _retry_nexus_banana_image_failure(
                task,
                provider_task_id,
                reason=str(payload.get("error") or "unknown provider failure"),
            )
            if retried_task_id:
                return
            await _fail_polled_nexus_image_task(
                bot_instance,
                task,
                provider_task_id=provider_task_id,
                service_name=service_name,
                reason=str(payload.get("error") or "unknown provider failure"),
            )
    finally:
        _NEXUS_POLL_IN_FLIGHT.discard(provider_task_id)

async def _nexus_image_poller_loop(bot_instance: Bot) -> None:
    from bot.services.nexus_task_poller import (
        NEXUS_POLL_BATCH_SIZE,
        NEXUS_POLL_INTERVAL_SECONDS,
        get_pending_nexus_image_tasks,
    )

    await asyncio.sleep(5)
    logger.info(
        "Nexus image poller started: interval=%ss batch_size=%s",
        NEXUS_POLL_INTERVAL_SECONDS,
        NEXUS_POLL_BATCH_SIZE,
    )
    while True:
        try:
            pending_tasks = await get_pending_nexus_image_tasks(
                limit=NEXUS_POLL_BATCH_SIZE,
            )
            for task_row in pending_tasks:
                await _poll_single_nexus_image_task(bot_instance, task_row)
        except Exception:
            logger.exception("Nexus image poller cycle error")
        await asyncio.sleep(NEXUS_POLL_INTERVAL_SECONDS)

def _build_failure_notification_text(
    *,
    service_name: str,
    task_id: str,
    reason: str | None,
    media_kind: str = "результата",
    refund_text: str = "",
) -> str:
    friendly_reason = make_user_friendly_generation_error(reason)
    safe_reason = _html_fragment(
        friendly_reason or "сервис не смог обработать запрос",
        limit=700,
    )
    return (
        f"Не удалось завершить генерацию {media_kind}.\n"
        f"• Модель: <code>{_html_fragment(service_name or 'AI')}</code>\n"
        f"• ID: <code>{_html_fragment(task_id)}</code>\n"
        f"• Причина: <code>{safe_reason}</code>"
        f"{refund_text}"
    )

def _build_single_result_caption(base_caption: str, task, reference_urls: list[str] | None = None, max_length: int = 980) -> str:
    return _sanitize_base_caption(base_caption)[:max_length]

async def _send_reference_preview(bot_instance: Bot, telegram_id: int, urls: list[str]) -> None:
    return

def _is_retryable_kie_blank_task_failure(fail_code, fail_msg) -> bool:
    return str(fail_code) == "422" and "task id is blank" in str(fail_msg or "").lower()

def _is_retryable_kie_timeout_failure(task, fail_code, fail_msg) -> bool:
    if not task or getattr(task, "type", None) != "image":
        return False
    model_name = str(getattr(task, "model", "") or "").strip()
    if model_name not in {
        "banana_pro",
        "nanobanana",
        "banana_2",
        "nano-banana-2-lite",
        "seedream_edit",
        "seedream_5_pro",
    }:
        return False
    normalized = str(fail_msg or "").lower()
    retryable_markers = (
        "timed out",
        "timeout while downloading",
        "timeout downloading",
        "no results were returned",
    )
    return str(fail_code) == "500" and any(marker in normalized for marker in retryable_markers)

def _is_retryable_wan_timeout_failure(task, fail_code, fail_msg) -> bool:
    if not task or getattr(task, "type", None) != "image":
        return False
    model_name = str(getattr(task, "model", "") or "").strip()
    if model_name != "wan_27":
        return False
    return str(fail_code) == "500" and "timed out" in str(fail_msg or "").lower()


def _is_retryable_seedance_real_person_failure(task, fail_msg) -> bool:
    if not task or getattr(task, "type", None) != "video":
        return False
    if str(getattr(task, "model", "") or "").strip() != "seedance_2":
        return False
    normalized = " ".join(str(fail_msg or "").lower().split())
    return (
        "input image" in normalized
        and "real person" in normalized
        and ("may contain" in normalized or "contains" in normalized)
    )


async def _retry_transient_seedance_real_person_failure(
    task,
    failed_task_id: str,
) -> str | None:
    if not _is_retryable_seedance_real_person_failure(
        task,
        "input image may contain real person",
    ):
        return None

    request_data = _extract_task_request_data(task)
    retry_attempt = int(request_data.get("seedance_real_person_retry_attempt") or 0)
    if retry_attempt >= 1:
        return None

    prompt = request_data.get("prompt") or getattr(task, "prompt", None)
    if not prompt:
        return None

    from bot.handlers.generation import _seedance_media_inputs
    from bot.services.seedance_service import seedance_service

    v_type = str(request_data.get("v_type") or "text")
    first_frame, image_refs, video_refs = _seedance_media_inputs(
        v_type,
        request_data.get("v_image_url"),
        request_data.get("reference_images") or [],
        request_data.get("v_reference_videos") or [],
    )
    result = await seedance_service.generate_video(
        prompt=str(prompt),
        duration=int(getattr(task, "duration", None) or 5),
        aspect_ratio=str(getattr(task, "aspect_ratio", None) or "16:9"),
        resolution="720p",
        generate_audio=True,
        first_frame_url=first_frame,
        reference_image_urls=image_refs or None,
        reference_video_urls=video_refs or None,
        callBackUrl=config.kie_notification_url if config.WEBHOOK_HOST else None,
    )
    new_task_id = result.get("task_id") if isinstance(result, dict) else None
    if not new_task_id or new_task_id == failed_task_id:
        return None

    retry_request_data = dict(request_data)
    retry_request_data["seedance_real_person_retry_attempt"] = retry_attempt + 1
    retry_request_data["last_auto_retry_from_task_id"] = failed_task_id
    retry_request_data = _merge_task_id_aliases(
        retry_request_data,
        failed_task_id,
        new_task_id,
    )

    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE generation_tasks SET task_id = ?, request_data = ?, status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?",
            (
                new_task_id,
                json.dumps(retry_request_data, ensure_ascii=False),
                failed_task_id,
                task.user_id,
            ),
        )
        await db.commit()

    logger.warning(
        "Auto-retried Seedance real-person false positive: old_task_id=%s new_task_id=%s attempt=%s",
        failed_task_id,
        new_task_id,
        retry_attempt + 1,
    )
    return new_task_id

async def _retry_transient_wan_timeout_failure(task, failed_task_id: str) -> str | None:
    if not task or getattr(task, "type", None) != "image":
        return None

    request_data = _extract_task_request_data(task)
    retry_attempt = int(request_data.get("auto_retry_attempt") or 0)
    if retry_attempt >= 1:
        return None

    prompt = (
        request_data.get("prompt")
        or getattr(task, "prompt", None)
        or request_data.get("effective_prompt")
    )
    if not prompt:
        return None

    from bot.services.wan27_service import wan27_service

    reference_images = request_data.get("reference_images") or []
    img_ratio = request_data.get("img_ratio") or getattr(task, "aspect_ratio", None) or "1:1"
    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None
    result = await wan27_service.generate_image(
        prompt=prompt,
        aspect_ratio=img_ratio,
        input_urls=reference_images,
        n=1,
        resolution="2K",
        pro=True,
        enable_sequential=False,
        thinking_mode=False,
        watermark=False,
        seed=random.randint(1, 2147483647),
        nsfw_checker=False,
        callBackUrl=callback_url,
    )

    new_task_id = result.get("task_id") if isinstance(result, dict) else None
    if not new_task_id or new_task_id == failed_task_id:
        return None

    retry_request_data = dict(request_data)
    retry_request_data["auto_retry_attempt"] = retry_attempt + 1
    retry_request_data["last_auto_retry_from_task_id"] = failed_task_id
    retry_request_data = _merge_task_id_aliases(retry_request_data, failed_task_id, new_task_id)

    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE generation_tasks SET task_id = ?, request_data = ?, status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?",
            (new_task_id, json.dumps(retry_request_data, ensure_ascii=False), failed_task_id, task.user_id),
        )
        await db.commit()

    logger.warning(
        "Auto-retried Wan timeout failure: old_task_id=%s new_task_id=%s attempt=%s",
        failed_task_id,
        new_task_id,
        retry_attempt + 1,
    )
    return new_task_id

async def _retry_transient_kie_image_failure(task, failed_task_id: str) -> str | None:
    if not task or getattr(task, "type", None) != "image":
        return None

    request_data = _extract_task_request_data(task)
    runtime_img_service = (
        request_data.get("img_service") or getattr(task, "model", None) or ""
    ).strip()
    if runtime_img_service not in {
        "banana_pro",
        "nanobanana",
        "banana_2",
        "nano-banana-2-lite",
        "seedream_edit",
        "seedream_5_pro",
    }:
        return None

    retry_attempt = int(request_data.get("auto_retry_attempt") or 0)
    if retry_attempt >= 1:
        return None

    prompt = (
        request_data.get("prompt")
        or getattr(task, "prompt", None)
        or request_data.get("effective_prompt")
    )
    if not prompt:
        return None

    reference_images = request_data.get("reference_images") or []
    img_ratio = request_data.get("img_ratio") or getattr(task, "aspect_ratio", None) or "1:1"
    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None

    if runtime_img_service in {"seedream_edit", "seedream_5_pro"}:
        from bot.services.seedream_service import seedream_service

        if runtime_img_service == "seedream_edit" or reference_images:
            result = await seedream_service.generate_image(
                prompt=prompt,
                model=(
                    "seedream/4.5-edit"
                    if runtime_img_service == "seedream_edit"
                    else "seedream/5-pro-image-to-image"
                ),
                aspect_ratio=img_ratio,
                image_urls=reference_images,
                quality=str(request_data.get("img_quality") or "basic"),
                nsfw_checker=False,
                callBackUrl=callback_url,
            )
        else:
            result = await seedream_service.generate_text_to_image(
                prompt=prompt,
                model="seedream/5-pro-text-to-image",
                aspect_ratio=img_ratio,
                quality=str(request_data.get("img_quality") or "basic"),
                callBackUrl=callback_url,
            )
    elif runtime_img_service in {"banana_2", "nano-banana-2-lite"}:
        from bot.services.nano_banana_2_service import nano_banana_2_service

        retry_callback_url = (
            config.kie_market_notification_url
            if runtime_img_service == "nano-banana-2-lite" and config.WEBHOOK_HOST
            else callback_url
        )
        result = await nano_banana_2_service.generate_image(
            prompt=prompt,
            aspect_ratio=img_ratio,
            resolution=str(request_data.get("img_quality") or "2K").upper(),
            image_input=reference_images,
            callback_url=retry_callback_url,
            model=(
                "nano-banana-2-lite"
                if runtime_img_service == "nano-banana-2-lite"
                else "nano-banana-2"
            ),
        )
    else:
        from bot.services.nano_banana_pro_service import nano_banana_pro_service

        result = await nano_banana_pro_service.generate_image(
            prompt=prompt,
            aspect_ratio=img_ratio,
            resolution=str(request_data.get("img_quality") or "2K").upper(),
            image_input=reference_images,
            callback_url=callback_url,
        )

    new_task_id = result.get("task_id") if isinstance(result, dict) else None
    if not new_task_id or new_task_id == failed_task_id:
        return None

    retry_request_data = dict(request_data)
    retry_request_data["auto_retry_attempt"] = retry_attempt + 1
    retry_request_data["last_auto_retry_from_task_id"] = failed_task_id
    retry_request_data = _merge_task_id_aliases(retry_request_data, failed_task_id, new_task_id)

    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE generation_tasks SET task_id = ?, request_data = ?, status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?",
            (new_task_id, json.dumps(retry_request_data, ensure_ascii=False), failed_task_id, task.user_id),
        )
        await db.commit()

    logger.warning(
        "Auto-retried transient KIE image failure: old_task_id=%s new_task_id=%s model=%s attempt=%s",
        failed_task_id,
        new_task_id,
        runtime_img_service,
        retry_attempt + 1,
    )
    return new_task_id


async def _retry_nexus_banana_image_failure(
    task,
    failed_task_id: str,
    *,
    reason: str | None = None,
) -> str | None:
    if not task or getattr(task, "type", None) != "image":
        return None

    request_data = _extract_task_request_data(task)
    runtime_img_service = (
        request_data.get("img_service") or getattr(task, "model", None) or ""
    ).strip()
    if runtime_img_service not in {"banana_pro", "banana_2"}:
        return None

    if str(request_data.get("provider") or "").strip().lower() != "nexus":
        return None

    retry_attempt = int(request_data.get("auto_retry_attempt") or 0)
    if retry_attempt >= 1:
        return None

    prompt = (
        request_data.get("effective_prompt")
        or request_data.get("prompt")
        or getattr(task, "prompt", None)
    )
    if not prompt:
        return None

    reference_images = (
        request_data.get("source_reference_images")
        or request_data.get("reference_images")
        or []
    )
    img_ratio = (
        request_data.get("img_ratio")
        or getattr(task, "aspect_ratio", None)
        or "1:1"
    )
    resolution = str(request_data.get("img_quality") or "2K").upper()
    callback_url = config.kie_notification_url if config.WEBHOOK_HOST else None

    if runtime_img_service == "banana_2":
        from bot.services.nano_banana_2_service import nano_banana_2_service

        new_task_id = await nano_banana_2_service.create_task(
            prompt=prompt,
            image_input=reference_images,
            aspect_ratio=img_ratio,
            resolution=resolution,
            callback_url=callback_url,
            model="nano-banana-2",
        )
        provider_model = "nano-banana-2"
    else:
        from bot.services.nano_banana_pro_service import nano_banana_pro_service

        new_task_id = await nano_banana_pro_service.create_task(
            prompt=prompt,
            image_input=reference_images,
            aspect_ratio=img_ratio,
            resolution=resolution,
            callback_url=callback_url,
        )
        provider_model = "nano-banana-pro"

    if not new_task_id or new_task_id == failed_task_id:
        return None

    retry_request_data = dict(request_data)
    retry_request_data["auto_retry_attempt"] = retry_attempt + 1
    retry_request_data["last_auto_retry_from_task_id"] = failed_task_id
    retry_request_data["provider"] = "kie"
    retry_request_data["provider_model"] = provider_model
    retry_request_data["provider_task_id"] = new_task_id
    retry_request_data = _merge_task_id_aliases(
        retry_request_data, failed_task_id, new_task_id
    )

    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE generation_tasks SET task_id = ?, request_data = ?, status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?",
            (
                new_task_id,
                json.dumps(retry_request_data, ensure_ascii=False),
                failed_task_id,
                task.user_id,
            ),
        )
        await db.commit()

    logger.warning(
        "Auto-retried Nexus image failure via KIE fallback: old_task_id=%s new_task_id=%s model=%s attempt=%s reason=%s",
        failed_task_id,
        new_task_id,
        runtime_img_service,
        retry_attempt + 1,
        str(reason or "")[:500],
    )
    return new_task_id

async def _remove_old_files(
    base_dir: str,
    max_age_seconds: int,
    *,
    skip_filenames: set[str] | None = None,
    skip_dirnames: set[str] | None = None,
    protected_paths: set[str] | None = None,
):
    """Удаляет файлы старше max_age_seconds в каталоге base_dir (рекурсивно)."""
    try:
        now = time.time()
        if not os.path.exists(base_dir):
            return
        skip_filenames = skip_filenames or set()
        skip_dirnames = skip_dirnames or set()
        protected_paths = {os.path.abspath(path) for path in (protected_paths or set())}

        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [name for name in dirs if name not in skip_dirnames]
            for name in files:
                if name in skip_filenames:
                    continue
                path = os.path.join(root, name)
                try:
                    if os.path.abspath(path) in protected_paths:
                        logger.info("Cleanup kept public feed file: %s", path)
                        continue
                    mtime = os.path.getmtime(path)
                    if now - mtime > max_age_seconds:
                        os.remove(path)
                        logger.info(f"Removed old file: {path}")
                except Exception:
                    logger.exception(f"Failed to remove file: {path}")

            # После обработки файлов: если папка пуста — удаляем её
            try:
                if not os.listdir(root):
                    os.rmdir(root)
                    logger.info(f"Removed empty dir: {root}")
            except Exception as e:
                # Игнорируем ошибки удаления каталогов
                pass
    except Exception:
        logger.exception("Error during cleanup for %s", base_dir)


async def _public_feed_protected_upload_paths() -> set[str]:
    """Return local upload files that must never be removed by generic cleanup."""
    protected: set[str] = set()
    try:
        from bot.services.media_input_utils import (
            is_local_upload_source,
            resolve_local_upload_path,
        )

        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                """
                SELECT result_url, result_urls
                FROM generation_tasks
                WHERE is_public_feed = 1
                  AND status = 'completed'
                  AND (result_url IS NOT NULL OR result_urls IS NOT NULL)
                """
            )
            rows = await cursor.fetchall()

        for row in rows:
            urls: list[str] = []
            result_url = str(row["result_url"] or "").strip()
            if result_url:
                urls.append(result_url)

            raw_result_urls = row["result_urls"] if "result_urls" in row.keys() else None
            if raw_result_urls:
                try:
                    parsed = json.loads(raw_result_urls)
                except (TypeError, json.JSONDecodeError):
                    parsed = []
                if isinstance(parsed, list):
                    urls.extend(str(item or "").strip() for item in parsed)

            for url in urls:
                if not url or not is_local_upload_source(url):
                    continue
                local_path = resolve_local_upload_path(url)
                if local_path:
                    protected.add(os.path.abspath(local_path))
    except Exception:
        logger.exception("Failed to collect public feed protected upload paths")
    return protected


def _row_public_result_urls(row) -> list[str]:
    urls: list[str] = []
    result_url = str(row["result_url"] or "").strip()
    if result_url:
        urls.append(result_url)

    raw_result_urls = row["result_urls"] if "result_urls" in row.keys() else None
    if raw_result_urls:
        try:
            parsed = json.loads(raw_result_urls)
        except (TypeError, json.JSONDecodeError):
            parsed = []
        if isinstance(parsed, list):
            for item in parsed:
                url = str(item or "").strip()
                if url and url not in urls:
                    urls.append(url)
    return urls


async def _normalize_public_feed_storage() -> dict[str, int]:
    """Move every available public feed result into static/uploads/feed."""
    stats = {"checked": 0, "updated": 0, "unchanged": 0, "failed": 0}
    try:
        from bot.services.feed_persist import persist_feed_result_urls

        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                """
                SELECT id, result_url, result_urls
                FROM generation_tasks
                WHERE is_public_feed = 1
                  AND status = 'completed'
                  AND (result_url IS NOT NULL OR result_urls IS NOT NULL)
                """
            )
            rows = await cursor.fetchall()

            for row in rows:
                stats["checked"] += 1
                result_urls = _row_public_result_urls(row)
                if not result_urls:
                    stats["unchanged"] += 1
                    continue

                try:
                    persisted = await persist_feed_result_urls(result_urls)
                except Exception:
                    logger.exception(
                        "Failed to persist public feed storage for generation %s",
                        row["id"],
                    )
                    stats["failed"] += 1
                    continue

                if not persisted or persisted == result_urls:
                    stats["unchanged"] += 1
                    continue

                await db.execute(
                    """
                    UPDATE generation_tasks
                    SET result_url = ?,
                        result_urls = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        persisted[0],
                        json.dumps(persisted, ensure_ascii=False),
                        row["id"],
                    ),
                )
                stats["updated"] += 1

            await db.commit()
    except Exception:
        logger.exception("Failed to normalize public feed storage")
        stats["failed"] += 1
    return stats


async def _cleanup_loop():
    """Фоновая задача, очищающая временные файлы и старые логи раз в 24 часа."""
    await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
    while True:
        try:
            feed_storage_stats = await _normalize_public_feed_storage()
            if feed_storage_stats["updated"] or feed_storage_stats["failed"]:
                logger.info("Public feed storage normalization stats: %s", feed_storage_stats)
            public_feed_paths = await _public_feed_protected_upload_paths()
            await _remove_old_files(
                "static/uploads",
                max_age_seconds=UPLOAD_RETENTION_SECONDS,
                skip_filenames=set(),
                skip_dirnames={"refs", "feed"},
                protected_paths=public_feed_paths,
            )
            await _remove_old_files(
                "logs",
                max_age_seconds=LOG_RETENTION_SECONDS,
                skip_filenames=ACTIVE_LOG_FILENAMES,
            )
            pruned_refs = await cleanup_saved_references()
            orphaned_refs = await cleanup_orphaned_reference_files(
                max_age_seconds=UPLOAD_RETENTION_SECONDS
            )
            stale_tasks = await cleanup_stale_local_generation_tasks()
            if pruned_refs or orphaned_refs["removed_count"]:
                logger.info(
                    "Reference cleanup removed db_rows=%s orphan_files=%s orphan_bytes=%s",
                    pruned_refs,
                    orphaned_refs["removed_count"],
                    orphaned_refs["removed_bytes"],
                )
            if stale_tasks["failed_count"]:
                logger.info("Stale local generation cleanup stats: %s", stale_tasks)
        except Exception:
            logger.exception("Cleanup iteration failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

async def on_startup(bot: Bot, dispatcher: Dispatcher | None = None):
    """Действия при старте бота"""
    logger.info("Bot starting...")

    # База данных уже инициализирована в main() функции
    logger.info("Database already initialized")

    try:
        for scope in USER_BOT_COMMAND_SCOPES:
            for language_code in USER_BOT_COMMAND_LANGUAGES:
                await bot.set_my_commands(
                    USER_BOT_COMMANDS,
                    scope=scope,
                    language_code=language_code,
                )
        logger.info(
            "Registered user bot commands: %s",
            ", ".join(f"/{command.command}" for command in USER_BOT_COMMANDS),
        )
    except Exception:
        logger.exception("Failed to register user bot commands")

    try:
        for language_code in USER_BOT_COMMAND_LANGUAGES:
            await bot.set_my_short_description(
                "",
                language_code=language_code,
            )
            await bot.set_my_description(
                "",
                language_code=language_code,
            )
        logger.info("Cleared Telegram bot profile descriptions")
    except Exception:
        logger.exception("Failed to clear Telegram bot descriptions")

    try:
        await _set_commands_chat_menu_button()
        logger.info("Configured Telegram chat menu button for bot commands")
    except Exception:
        logger.exception("Failed to configure Telegram chat menu button")

    try:
        await redis_service.get_client()
    except Exception:
        logger.exception("Redis warmup failed during startup")

    # Устанавливаем вебхук для Telegram (если используем webhook mode)
    if config.WEBHOOK_HOST:
        try:
            webhook_kwargs = {}
            if dispatcher is not None:
                webhook_kwargs["allowed_updates"] = dispatcher.resolve_used_update_types()
            await bot.set_webhook(config.webhook_url, **webhook_kwargs)
            logger.info(f"Webhook set to {config.webhook_url}")
        except Exception:
            logger.exception("Failed to set webhook on startup")

    # Загружаем пресеты
    preset_manager.load_all()
    logger.info(f"Loaded {len(preset_manager._presets)} presets")

    try:
        cleanup_stats = await cleanup_stale_cryptobot_pending()
        logger.info("Startup payment cleanup stats: %s", cleanup_stats)
    except Exception:
        logger.exception("Failed startup cleanup for stale CryptoBot pending transactions")

    try:
        stale_task_stats = await cleanup_stale_local_generation_tasks()
        logger.info("Startup stale local generation cleanup stats: %s", stale_task_stats)
    except Exception:
        logger.exception("Failed startup cleanup for stale local generation tasks")

    # Запускаем фоновую очистку static/uploads и старых логов раз в 24 часа
    try:
        # aiogram.Bot does not expose an event loop attribute in some versions.
        # Use asyncio.create_task to schedule background tasks on the running loop.
        asyncio.create_task(_cleanup_loop())
        asyncio.create_task(_yookassa_reconcile_loop(bot))
        asyncio.create_task(_lava_reconcile_loop(bot))
        asyncio.create_task(_memory_dump_loop(bot))
        asyncio.create_task(_db_backup_loop())
        ensure_notification_campaign_worker(bot)
        ensure_support_outbox_worker(bot)
        ensure_feed_cache_warmup()
        logger.info(
            "Scheduled cleanup task for static/uploads/logs, payment reconciliation, memory dumps, DB backups, support outbox, and notification campaigns"
        )
    except Exception:
        logger.exception("Failed to schedule background tasks")

async def on_shutdown(bot: Bot):
    """Действия при остановке"""
    logger.info("Bot shutting down...")
    try:
        from bot.services.cryptobot_service import cryptobot_service

        await cryptobot_service.close()
    except Exception:
        logger.exception("Failed to close CryptoBot session")

    try:
        from bot.services.lava_service import lava_service

        await lava_service.close()
    except Exception:
        logger.exception("Failed to close Lava session")

    try:
        await redis_service.close()
    except Exception:
        logger.exception("Failed to close Redis client")
    await bot.delete_webhook()
    await bot.session.close()

async def errors_handler(event: types.ErrorEvent):
    """Глобальный обработчик ошибок"""
    error = event.exception

    # Обработка ошибок Telegram API
    if isinstance(error, TelegramBadRequest):
        error_msg = str(error).lower()
        if "chat not found" in error_msg:
            logger.warning(
                f"Chat not found error (user deleted chat or blocked bot): {error}"
            )
            return True
        elif "bot was blocked" in error_msg:
            logger.warning(f"Bot was blocked by user: {error}")
            return True
        elif "user is deactivated" in error_msg:
            logger.warning(f"User is deactivated: {error}")
            return True
        elif "message is not modified" in error_msg:
            return True
        elif "query is too old" in error_msg or "query id is invalid" in error_msg:
            logger.info(f"Ignoring stale callback query error: {error}")
            return True

    # Логируем другие ошибки
    logger.exception(f"Unhandled error: {error}")
    return True

def setup_dispatcher() -> Dispatcher:
    """Настройка диспетчера с роутерами"""
    dp = Dispatcher(storage=_build_dispatcher_storage())

    # Регистрируем глобальный обработчик ошибок
    dp.errors.register(errors_handler)
    access_guard = AccessGuardMiddleware()
    dp.message.outer_middleware(access_guard)
    dp.callback_query.outer_middleware(access_guard)

    # ⭐ КРИТИЧЕСКИ ВАЖНО: Порядок роутеров в aiogram 3.x
    # Первый зарегистрированный роутер имеет НАИВЫСШИЙ приоритет!
    # Сообщение передаётся ВСЕМ роутерам одновременно, но обрабатывается
    # тем, у кого более специфичный фильтр (например, StateFilter)
    #
    # Правильный порядок:
    # 1. generation_router (FSM состояния - самые специфичные)
    # 2. admin_router (админ команды)
    # 3. payments_router (платежи)
    # 4. batch_generation_router (пакетная генерация)
    # 5. common_router (общие команды /start /help - самые общие)

    dp.include_router(generation_router)  # FSM состояния - ПЕРВЫЙ!
    dp.include_router(image_analyzer_router)  # Анализ фото в промпт
    dp.include_router(admin_router)  # Админ-команды
    dp.include_router(payments_router)  # Платежи
    dp.include_router(batch_generation_router)  # Пакетная генерация
    dp.include_router(common_router)  # Общие команды - ПОСЛЕДНИЙ!

    return dp

async def handle_telegram_webhook(
    request: web.Request, bot: Bot, dp: Dispatcher
) -> web.Response:
    """Обработчик вебхука от Telegram"""
    try:
        raw_body = await request.read()
        if not raw_body:
            logger.warning("Telegram webhook received empty body")
            return web.Response(text="OK", status=200)

        try:
            update_data = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as decode_error:
            logger.warning(f"Telegram webhook received invalid JSON: {decode_error}")
            return web.Response(text="OK", status=200)

        # Создаём объект Update
        update = Update(**update_data)

        async def _process_update():
            try:
                async with _TELEGRAM_WEBHOOK_SEMAPHORE:
                    await dp.feed_update(bot, update)
            except TelegramBadRequest as e:
                error_msg = str(e).lower()
                if (
                    "chat not found" in error_msg
                    or "bot was blocked" in error_msg
                    or "user is deactivated" in error_msg
                ):
                    logger.warning(f"Chat error (safe to ignore): {e}")
                    return
                if "query is too old" in error_msg or "query id is invalid" in error_msg:
                    logger.info(f"Ignoring stale callback query in background task: {e}")
                    return
                logger.exception(f"Telegram API error in background task: {e}")
            except Exception as e:
                logger.exception(f"Webhook background task error: {e}")

        # Сразу отвечаем Telegram, а обработку уводим в фон,
        # чтобы длинные операции не вызывали повторную доставку update.
        task = asyncio.create_task(_process_update())
        _TELEGRAM_WEBHOOK_TASKS.add(task)
        task.add_done_callback(_TELEGRAM_WEBHOOK_TASKS.discard)

        return web.Response(text="OK", status=200)
    except TelegramBadRequest as e:
        # Ошибки Telegram API (chat not found, user blocked bot, etc.)
        # Возвращаем 200, чтобы Telegram не повторял запрос
        error_msg = str(e).lower()
        if (
            "chat not found" in error_msg
            or "bot was blocked" in error_msg
            or "user is deactivated" in error_msg
        ):
            logger.warning(f"Chat error (safe to ignore): {e}")
            return web.Response(text="OK", status=200)
        logger.exception(f"Telegram API error: {e}")
        return web.Response(text="Bad Request", status=200)
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        # Возвращаем 200 даже при ошибках, чтобы Telegram не спамил
        return web.Response(text="OK", status=200)

async def handle_kling_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Kling/PiAPI/Replicate/Kie.ai"""
    try:
        # Verify Replicate webhook signature if configured
        from bot.config import config as _config

        def _verify_replicate_signature(
            secret: str, body: bytes, headers: dict
        ) -> bool:
            """Verify HMAC SHA256 signature using common header names."""
            if not secret:
                return True
            import hashlib
            import hmac

            body_bytes = (
                body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
            )

            candidates = [
                headers.get("x-replicate-signature"),
                headers.get("x-signature"),
                headers.get("replicate-signature"),
                headers.get("signature"),
                headers.get("webhook-signature"),
            ]

            secret_bytes = secret.encode("utf-8")

            for sig in candidates:
                if not sig:
                    continue

                sig_str = sig if isinstance(sig, str) else str(sig)
                parts = [p.strip() for p in sig_str.split(",") if p.strip()]
                sig_candidate = parts[-1]

                if sig_candidate.startswith("sha256="):
                    sig_val = sig_candidate.split("=", 1)[1]
                elif sig_candidate.startswith("v1="):
                    sig_val = sig_candidate.split("=", 1)[1]
                else:
                    sig_val = sig_candidate

                try:
                    computed_hex = hmac.new(
                        secret_bytes, body_bytes, hashlib.sha256
                    ).hexdigest()
                    if hmac.compare_digest(computed_hex, sig_val):
                        return True
                except Exception as e:
                    pass

            return False

        # Read raw body for verification
        raw_body = await request.read()
        if not _verify_replicate_signature(
            _config.REPLICATE_WEBHOOK_SECRET, raw_body, dict(request.headers)
        ):
            logger.warning(
                "Rejected Kling webhook: replicate signature verification failed"
            )
            return web.Response(status=200)

        logger.info("Kling webhook headers: %s", _preview_log_headers(request.headers))

        # Проверяем, есть ли данные в теле запроса
        if not raw_body:
            logger.warning("Kling webhook received empty body")
            return web.Response(status=200)

        try:
            body_text = raw_body.decode("utf-8")
            logger.info("Kling webhook raw body received: %s bytes", len(raw_body))
            data = json.loads(body_text)
        except Exception as e:
            logger.warning(f"Kling webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info("Kling webhook parsed data: %s", _preview_log_payload(data))

        # Kling specific format: {'code': 200, 'data': {'result_video_url': '...'}, 'msg': '...', 'taskId': '...'}
        if "code" in data and data.get("code") == 200 and "taskId" in data:
            task_id = data["taskId"]
            video_url = data["data"].get("result_video_url")
            if task_id and video_url:
                from bot.database import (
                    complete_video_task,
                    get_task_by_id,
                )
                from bot.keyboards import get_video_result_keyboard

                task = await get_task_by_id(task_id)
                # P1-04: Idempotency — skip if already completed
                if task and task.status == "completed":
                    logger.info(f"Webhook: task {task_id} already completed, skipping")
                    return web.Response(status=200)
                model_display = task.model if task and task.model else "Kling"
                if model_display == "aleph":
                    model_display = "Aleph Video"
                elif model_display == "glow":
                    model_display = "Kling Glow"
                logger.info(
                    f"{model_display} success webhook: task {task_id}, video {video_url[:50]}..."
                )
                if task:
                    reference_preview_urls = _extract_reference_image_urls(task, data.get("data"))
                    telegram_id = await _resolve_task_telegram_id(
                        task, context="kling_success_code200"
                    )
                    if telegram_id:
                        video_url = await _persist_result_url_if_needed(
                            video_url,
                            task_type=task.type if task else "video",
                        )
                        bot_instance = request.app["bot"]
                        try:
                            caption = f"✅ <b>Видео ({_html_fragment(model_display)}) готово!</b>\\n\\nID: <code>{_html_fragment(task_id)}</code>"
                            if task.duration:
                                caption += f"\\n⏱ <code>{_html_fragment(task.duration)}с</code>"
                            if task.aspect_ratio:
                                caption += f"\\n📐 <code>{_html_fragment(task.aspect_ratio)}</code>"
                            if task.cost:
                                caption += f"\\n💰 <code>{_html_fragment(task.cost)}🍌</code>"
                            if getattr(task, 'source_feed_gen_id', None):
                                caption += f"\\n\\n🎯 Промпт скрыт"
                            elif task.preset_id == "no_preset" and task.prompt:
                                prompt_preview = _html_fragment(
                                    f"{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}"
                                )
                                caption += f"\\n\\n🎯 Промпт: <code>{prompt_preview}</code>"
                            else:
                                caption += f"\\n\\n🎯 Пресет: {_html_fragment(task.preset_id)}"
                            video_kb = get_video_result_keyboard(
                                video_url,
                                task_id=_task_callback_id(task, task_id),
                                model=task.model if task else model_display,
                                is_public_feed=task.is_public_feed if task else False,
                            )

                            delivered = False
                            media_caption = _build_single_result_caption(
                                _with_original_link(caption, video_url),
                                task,
                                reference_preview_urls,
                            )
                            try:
                                await bot_instance.send_video(
                                    chat_id=telegram_id,
                                    video=video_url,
                                    caption=media_caption,
                                    parse_mode="HTML",
                                    supports_streaming=True,
                                    reply_markup=video_kb,
                                )
                                delivered = True
                            except Exception as send_e:
                                logger.error(
                                    f"Failed to send {model_display} video media to {telegram_id}: {send_e}"
                                )
                                delivered = await _send_video_file_from_url(
                                    bot_instance,
                                    telegram_id,
                                    video_url,
                                    caption=media_caption,
                                    reply_markup=video_kb,
                                )
                            if not delivered:
                                try:
                                    await _send_plain_result_link(
                                        bot_instance,
                                        telegram_id,
                                        media_label="Видео",
                                        model_label=model_display,
                                        task_id=task_id,
                                        result_url=video_url,
                                        reply_markup=video_kb,
                                    )
                                    delivered = True
                                except Exception as link_e:
                                    logger.error(
                                        f"Failed to send {model_display} video link to {telegram_id}: {link_e}"
                                    )
                            await complete_video_task(task_id, video_url)
                            if delivered:
                                logger.info(f"{model_display} video sent to {telegram_id}")
                            else:
                                logger.warning(
                                    f"{model_display} result stored but Telegram delivery failed for {telegram_id}"
                                )
                        except Exception as e:
                            logger.error(
                                f"Failed to notify {model_display} user {telegram_id}: {e}"
                            )
                return web.Response(status=200)

        # Detect Kie.ai format (code:200/501, data.taskId, data.resultJson or failMsg)
        if "code" in data and "data" in data:
            kie_data = data["data"]
            task_id = kie_data.get("taskId")
            status = kie_data.get("state", "").lower()
            result_json_str = kie_data.get("resultJson", "{}")
            fail_code = kie_data.get("failCode")
            fail_msg = kie_data.get("failMsg", "")
            try:
                result_json = json.loads(result_json_str)
                video_url = result_json.get("resultUrls", [None])[0]
            except (json.JSONDecodeError, KeyError):
                video_url = None

            if task_id:
                from bot.database import (
                    add_credits,
                    complete_video_task,
                    get_task_by_id,
                )

                task = await get_task_by_id(task_id)
                # P1-04: Idempotency — skip if already completed
                if task and task.status == "completed":
                    logger.info(f"Webhook: task {task_id} already completed, skipping")
                    return web.Response(status=200)
                model_display = _get_task_model_label(
                    task.model if task else None,
                    task.type if task else None,
                )
                logger.info(
                    f"{model_display} webhook: task {task_id}, status {status}, "
                    + f"video {video_url[:50] if video_url else None}..., "
                    + f"fail: {fail_code}/{fail_msg[:50]}..."
                )
                if task:
                    reference_preview_urls = _extract_reference_image_urls(task, kie_data)
                    telegram_id = await _resolve_task_telegram_id(
                        task, context="kie_legacy"
                    )
                    if telegram_id:
                        video_url = await _persist_result_url_if_needed(
                            video_url,
                            task_type=task.type if task else "video",
                        )
                        bot_instance = request.app["bot"]
                        try:
                            if status in {"success", "completed"} and video_url:
                                # Success case
                                model_display = _get_task_model_label(
                                    task.model, task.type
                                )
                                caption = (
                                    f"✅ <b>{'Видео' if task.type == 'video' else 'Изображение'} готово</b>\n"
                                    f"• Модель: <code>{_html_fragment(model_display)}</code>\n"
                                    f"• ID: <code>{_html_fragment(task_id)}</code>"
                                )
                                if task.duration:
                                    caption += f"\n• Длительность: <code>{_html_fragment(task.duration)}с</code>"
                                if task.aspect_ratio:
                                    caption += f"\n• Формат: <code>{_html_fragment(str(task.aspect_ratio).replace(':', '∶'))}</code>"
                                if task.cost:
                                    caption += (
                                        f"\n• Стоимость: <code>{_html_fragment(task.cost)}🍌</code>"
                                    )
                                if getattr(task, 'source_feed_gen_id', None):
                                    caption += f"\n\n🎯 <b>Промпт скрыт</b>"
                                elif task.preset_id == "no_preset" and task.prompt:
                                    prompt_preview = _html_fragment(
                                        f"{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}"
                                    )
                                    caption += (
                                        f"\n\n🎯 <b>Промпт</b>\n"
                                        f"<code>{prompt_preview}</code>"
                                    )
                                else:
                                    caption += f"\n\n🎯 <b>Пресет</b>\n<code>{_html_fragment(task.preset_id)}</code>"
                                import os

                                # Отправляем видео - всегда скачиваем для Kie.ai
                                import tempfile

                                import aiohttp
                                from aiogram.types import FSInputFile

                                from bot.keyboards import get_video_result_keyboard

                                video_kb = get_video_result_keyboard(
                                    video_url,
                                    task_id=_task_callback_id(task, task_id),
                                    model=task.model if task else model_display,
                                    is_public_feed=task.is_public_feed if task else False,
                                )
                                delivered = False
                                tmp_file = None
                                try:
                                    async with aiohttp.ClientSession() as sess:
                                        headers = {
                                            "User-Agent": "Mozilla/5.0 (compatible; Telegram Bot SDK/1.0)",
                                            "Accept": "*/*",
                                        }
                                        async with sess.get(
                                            video_url,
                                            headers=headers,
                                            timeout=aiohttp.ClientTimeout(total=120),
                                        ) as resp:
                                            if resp.status != 200:
                                                raise RuntimeError(
                                                    f"Download failed: status {resp.status}"
                                                )
                                            tmp = tempfile.NamedTemporaryFile(
                                                delete=False, suffix=".mp4"
                                            )
                                            tmp_file = tmp.name
                                            with open(tmp_file, "wb") as f:
                                                async for (
                                                    chunk
                                                ) in resp.content.iter_chunked(
                                                    1024 * 64
                                                ):
                                                    if chunk:
                                                        f.write(chunk)
                                    video_file = FSInputFile(tmp_file)
                                    await bot_instance.send_video(
                                        chat_id=telegram_id,
                                        video=video_file,
                                        caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                                        parse_mode="HTML",
                                        supports_streaming=True,
                                        reply_markup=video_kb,
                                    )
                                    delivered = True
                                    logger.info(
                                        f"Kie.ai video downloaded and sent to {telegram_id}"
                                    )
                                except Exception as dl_e:
                                    logger.error(
                                        f"Kie.ai video download failed: {dl_e}"
                                    )
                                    # Fallback to URL
                                    try:
                                        await bot_instance.send_video(
                                            chat_id=telegram_id,
                                            video=video_url,
                                            caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                                            parse_mode="HTML",
                                            supports_streaming=True,
                                            reply_markup=video_kb,
                                        )
                                        delivered = True
                                        logger.info(
                                            f"Kie.ai video sent via URL to {telegram_id}"
                                        )
                                    except Exception as url_e:
                                        logger.error(
                                            f"Kie.ai video URL send failed: {url_e}"
                                        )
                                        try:
                                            await _send_plain_result_link(
                                                bot_instance,
                                                telegram_id,
                                                media_label="Видео",
                                                model_label=model_display,
                                                task_id=task_id,
                                                result_url=video_url,
                                                reply_markup=video_kb,
                                                notice=(
                                                    "Telegram не смог прикрепить видео файлом "
                                                    "из-за ограничения размера."
                                                ),
                                            )
                                            delivered = True
                                            logger.info(
                                                f"Kie.ai video link sent to {telegram_id}"
                                            )
                                        except Exception as link_e:
                                            logger.error(
                                                f"Kie.ai video link fallback failed: {link_e}"
                                            )
                                finally:
                                    if tmp_file and os.path.exists(tmp_file):
                                        try:
                                            os.remove(tmp_file)
                                        except Exception:
                                            pass
                                await complete_video_task(task_id, video_url)
                                if delivered:
                                    logger.info(f"Kie.ai result sent to {telegram_id}")
                                else:
                                    logger.warning(
                                        f"Kie.ai result stored but Telegram delivery failed for {telegram_id}"
                                    )
                            else:
                                # Fail case
                                policy_violation = "Prohibited Use policy" in fail_msg
                                error_msg = (
                                    "Запрос не прошёл проверку политики безопасности из-за чувствительного контента."
                                    if policy_violation
                                    else fail_msg[:100]
                                )
                                await add_credits(telegram_id, task.cost or 0)
                                refund_text = "\n\nБананы за эту попытку уже возвращены."
                                await bot_instance.send_message(
                                    chat_id=telegram_id,
                                    text=_build_failure_notification_text(
                                        service_name=model_display,
                                        task_id=task_id,
                                        reason=error_msg,
                                        media_kind=(
                                            "видео"
                                            if task.type == "video"
                                            else "результата"
                                        ),
                                        refund_text=refund_text,
                                    ),
                                    parse_mode="HTML",
                                )
                                await complete_video_task(task_id, None)
                                logger.info(
                                    f"Kie.ai fail notified to {telegram_id}, credits returned"
                                )
                        except Exception as e:
                            logger.error(f"Failed to notify user {telegram_id}: {e}")
                return web.Response(status=200)

        # Fallback to PiAPI/Replicate parsing
        webhook_data = data
        task_id = _extract_first(
            webhook_data, ("taskId", "task_id", "id", "prediction_id", "predictionId")
        )
        status = _extract_first(
            webhook_data, ("status", "state", "result", "prediction_status")
        )

        if not task_id:
            logger.error(
                f"Kling webhook missing task id. Top-level keys: {list(data.keys())}, "
                + f"payload: {_preview_log_payload(webhook_data)}"
            )
            return web.Response(status=200)

        logger.info(f"Processing Kling task {task_id} with status {status}")

        normalized_status = str(status).lower() if status else ""

        if normalized_status in {"completed", "succeeded", "success", "finished"}:
            # Replicate can return either a direct URL/string or a nested object.
            output = (
                webhook_data.get("output", {}) if isinstance(webhook_data, dict) else {}
            )
            video_url = (
                (output.get("video_url") if isinstance(output, dict) else None)
                or (output.get("video") if isinstance(output, dict) else None)
                or (output if isinstance(output, str) else None)
                or (
                    output.get("works")
                    and output["works"][0]
                    .get("video", {})
                    .get("resource_without_watermark")
                    if isinstance(output, dict)
                    else None
                )
            )

            if not video_url:
                logger.error(f"No video URL in completed task: {webhook_data}")
                return web.Response(status=200)

            logger.info(f"Extracted video URL: {video_url[:50]}...")

            # Находим задачу в БД
            from bot.database import (
                complete_video_task,
                get_task_by_id,
            )

            task = await get_task_by_id(task_id)
            # P1-04: Idempotency — skip if already completed
            if task and task.status == "completed":
                logger.info(f"Webhook: task {task_id} already completed, skipping")
                return web.Response(status=200)

            if not task:
                logger.info(
                    "Ignoring orphan webhook for Kling task %s: task not found in database",
                    task_id,
                )
                return web.Response(status=200)

            telegram_id = await _resolve_task_telegram_id(
                task, context="kling_fallback_success"
            )

            if not telegram_id:
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, "
                + f"preset: {task.preset_id}"
            )

            model_display = task.model or task.preset_id or "Kling"
            reference_preview_urls = _extract_reference_image_urls(task, webhook_data)
            caption = f"✅ <b>Видео ({_html_fragment(model_display)}) готово!</b>\\n\\nID: <code>{_html_fragment(task_id)}</code>"
            if task.duration:
                caption += f"\\n⏱ <code>{_html_fragment(task.duration)}с</code>"
            if task.aspect_ratio:
                caption += f"\\n📐 <code>{_html_fragment(task.aspect_ratio)}</code>"
            if task.cost:
                caption += f"\\n💰 <code>{_html_fragment(task.cost)}🍌</code>"
            if getattr(task, 'source_feed_gen_id', None):
                caption += f"\\n\\n🎯 Промпт скрыт"
            elif task.preset_id == "no_preset" and task.prompt:
                prompt_preview = _html_fragment(
                    f"{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}"
                )
                caption += f"\\n\\n🎯 Промпт: <code>{prompt_preview}</code>"
            else:
                caption += f"\\n\\n🎯 Пресет: {_html_fragment(task.preset_id)}"

            video_url = await _persist_result_url_if_needed(
                video_url,
                task_type=task.type if task else "video",
            )

            # Отправляем видео пользователю
            bot_instance = request.app["bot"]
            video_kb = None

            try:
                from bot.keyboards import get_video_result_keyboard

                video_kb = get_video_result_keyboard(
                    video_url,
                    task_id=_task_callback_id(task, task_id),
                    model=task.model if task else model_display,
                    is_public_feed=task.is_public_feed if task else False,
                )
                await bot_instance.send_video(
                    chat_id=telegram_id,
                    video=video_url,
                    caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=video_kb,
                )

                await complete_video_task(task_id, video_url)
                logger.info(f"Video sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send video via URL: {e}")
                # If sending by URL failed (Telegram can't fetch remote file),
                # try to download the file locally and upload it to Telegram.
                try:
                    # Only attempt download for http(s) URLs
                    if isinstance(video_url, str) and video_url.lower().startswith(
                        "http"
                    ):
                        import os
                        import tempfile

                        import aiohttp as _aiohttp

                        logger.info(
                            "Attempting to download video and upload to Telegram as file"
                        )
                        tmp_file = None
                        try:
                            async with _aiohttp.ClientSession() as sess:
                                async with sess.get(video_url, timeout=60) as resp:
                                    if resp.status != 200:
                                        raise RuntimeError(
                                            f"Failed to download video, status={resp.status}"
                                        )
                                    # Create temporary file
                                    tmp = tempfile.NamedTemporaryFile(delete=False)
                                    tmp_file = tmp.name
                                    # Stream write
                                    with open(tmp_file, "wb") as f:
                                        async for chunk in resp.content.iter_chunked(
                                            1024 * 64
                                        ):
                                            if chunk:
                                                f.write(chunk)

                            # Send downloaded file
                            from aiogram.types import FSInputFile

                            video_file = FSInputFile(tmp_file)
                            await bot_instance.send_video(
                                chat_id=telegram_id,
                                video=video_file,
                                caption=_build_single_result_caption(_with_original_link(caption, video_url), task, reference_preview_urls),
                                parse_mode="HTML",
                                supports_streaming=True,
                                reply_markup=video_kb,
                            )

                            await complete_video_task(task_id, video_url)
                            logger.info(
                                f"Video downloaded and sent to user {telegram_id}"
                            )
                        finally:
                            if tmp_file and os.path.exists(tmp_file):
                                try:
                                    os.remove(tmp_file)
                                except Exception as e:
                                    logger.exception(
                                        "Failed to remove temporary video file"
                                    )
                    else:
                        # Fallback — отправляем как ссылка
                        await _send_plain_result_link(
                            bot_instance,
                            telegram_id,
                            media_label="Видео",
                            model_label=model_display,
                            task_id=task_id,
                            result_url=video_url,
                            reply_markup=video_kb,
                        )
                except Exception as fallback_error:
                    logger.error(
                        f"Failed to send fallback message or upload video: {fallback_error}"
                    )
                    try:
                        await _send_plain_result_link(
                            bot_instance,
                            telegram_id,
                            media_label="Видео",
                            model_label=model_display,
                            task_id=task_id,
                            result_url=video_url,
                            reply_markup=video_kb,
                            notice="Telegram не смог прикрепить видео автоматически.",
                        )
                        logger.info(f"Video link sent to user {telegram_id}")
                    except Exception as link_error:
                        logger.error(
                            f"Failed to send fallback video link to {telegram_id}: {link_error}"
                        )
            finally:
                try:
                    await complete_video_task(task_id, video_url)
                except Exception as complete_error:
                    logger.error(f"Failed to store completed video task {task_id}: {complete_error}")
        else:
            logger.error(f"Kling task {task_id} failed with status: {status}")

            from bot.database import (
                add_credits,
                complete_video_task,
                get_task_by_id,
            )

            task = await get_task_by_id(task_id)
            # P1-04: Idempotency — skip if already completed
            if task and task.status == "completed":
                logger.info(f"Webhook: task {task_id} already completed, skipping")
                return web.Response(status=200)
            if task and task.cost:
                telegram_id = await _resolve_task_telegram_id(
                    task, context="kling_failure"
                )
                if telegram_id:
                    bot_instance = request.app["bot"]
                    try:
                        fail_msg = data.get(
                            "msg", str(status) if status else "Unknown error"
                        )
                        await add_credits(telegram_id, task.cost)
                        refund_text = "\n\nКредиты возвращены."
                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=_build_failure_notification_text(
                                service_name="Kling",
                                task_id=task_id,
                                reason=fail_msg,
                                media_kind="видео",
                                refund_text=refund_text,
                            ),
                            parse_mode="HTML",
                        )
                        await complete_video_task(task_id, None)
                        logger.info(f"Kling failure notified to {telegram_id}")
                    except Exception as e:
                        logger.error(
                            f"Failed to notify Kling failure to {telegram_id}: {e}"
                        )

            # Check for sensitive content error
            # webhook_data['error'] or webhook_data['logs'] may be dicts (or other types)
            # so convert them to strings safely before concatenation to avoid TypeError
            def _to_str(value):
                if value is None:
                    return ""
                if isinstance(value, (str, int, float)):
                    return str(value)
                try:
                    return json.dumps(value, ensure_ascii=False)
                except Exception:
                    return str(value)

            # Safely stringify possible dict/complex types in webhook error/logs
            error_msg = (
                _to_str(webhook_data.get("error"))
                + " "
                + _to_str(webhook_data.get("logs"))
            ).lower()
            if "sensitive" in error_msg or "e005" in error_msg:
                from bot.database import (
                    add_credits,
                    get_task_by_id,
                )

                task = await get_task_by_id(task_id)
                # P1-04: Idempotency — skip if already completed
                if task and task.status == "completed":
                    logger.info(f"Webhook: task {task_id} already completed, skipping")
                    return web.Response(status=200)
                if task:
                    telegram_id = await _resolve_task_telegram_id(
                        task, context="kling_sensitive_failure"
                    )
                    if telegram_id:
                        bot_instance = request.app["bot"]
                        try:
                            # Try to get preset cost from preset manager (presets.json)
                            preset = preset_manager.get_preset(task.preset_id)
                            preset_cost = preset.cost if preset else 0
                            await add_credits(telegram_id, preset_cost)
                            await bot_instance.send_message(
                                chat_id=telegram_id,
                                text=(
                                    "❌ <b>Ваш промпт был помечен как чувствительный контент</b>"
                                    "Пожалуйста, попробуйте другой промпт без чувствительного контента."
                                    "🍌 Кредиты возвращены на счёт."
                                ),
                                parse_mode="HTML",
                            )
                            logger.info(
                                f"Sent sensitive content notification to {telegram_id}, returned {preset_cost} credits"
                            )
                        except Exception as notify_error:
                            logger.error(
                                f"Failed to notify user about sensitive content: {notify_error}"
                            )

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kling webhook error: {e}")
        # Return 200 even on unexpected errors to avoid webhook relayers
        # repeatedly retrying the same payload. The error is logged above
        # for investigation.
        return web.Response(status=200)

async def handle_seedream_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Novita AI (Seedream) API

    Novita AI webhook format (ASYNC_TASK_RESULT event):
    {
        "event_type": "ASYNC_TASK_RESULT",
        "payload": {
            "task": {
                "task_id": "...",
                "status": "TASK_STATUS_SUCCEED",
                "task_type": "TXT_TO_IMG"
            },
            "images": [{"image_url": "https://..."}],
            "extra": {...}
        }
    }
    """
    try:
        logger.info("Seedream webhook headers: %s", _preview_log_headers(request.headers))

        body = await request.text()
        logger.info("Seedream webhook raw body received: %s chars", len(body))

        if not body:
            logger.warning("Seedream webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"Seedream webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info("Seedream webhook parsed data: %s", _preview_log_payload(data))

        # Check event type - Novita AI sends ASYNC_TASK_RESULT
        event_type = data.get("event_type")
        if event_type != "ASYNC_TASK_RESULT":
            logger.warning(f"Unexpected event_type: {event_type}, ignoring")
            return web.Response(status=200)

        # Get payload
        payload = data.get("payload", {})

        # Get task info from payload.task
        task_info = payload.get("task", {})
        task_id = task_info.get("task_id")
        status = task_info.get("status")

        if not task_id:
            logger.warning(f"No task_id in Seedream webhook: {data}")
            return web.Response(status=200)

        logger.info(f"Seedream task {task_id} status: {status}")

        # Novita AI status: TASK_STATUS_SUCCEED, TASK_STATUS_FAILED
        if status == "TASK_STATUS_SUCCEED":
            # Get images from payload.images array
            images = payload.get("images", [])

            if not images:
                logger.error(f"No images in completed task: {data}")
                return web.Response(status=200)

            # Novita returns images as objects with image_url field
            image_url = None
            if isinstance(images[0], dict):
                image_url = images[0].get("image_url")
            elif isinstance(images[0], str):
                image_url = images[0]

            if not image_url:
                logger.error(f"Invalid images format: {images}")
                return web.Response(status=200)

            logger.info(f"Extracted image URL: {image_url[:50]}...")

            # Находим задачу в БД по task_id
            from bot.database import complete_video_task, get_task_by_id

            task = await get_task_by_id(task_id)
            # P1-04: Idempotency — skip if already completed
            if task and task.status == "completed":
                logger.info(f"Webhook: task {task_id} already completed, skipping")
                return web.Response(status=200)

            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return web.Response(status=200)

            telegram_id = await _resolve_task_telegram_id(
                task, context="seedream_success"
            )

            if not telegram_id:
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )
            request_data = _extract_task_request_data(task)
            selected_model = request_data.get("img_service") or task.model
            provider_model = request_data.get("provider_model")
            webhook_model = task_info.get("model") or payload.get("model")
            logger.info(
                "Seedream webhook route: task_id=%s selected_model=%s stored_model=%s provider_model=%s webhook_model=%s preset=%s",
                task_id,
                selected_model,
                task.model,
                provider_model,
                webhook_model,
                task.preset_id,
            )
            if webhook_model and task.model and webhook_model != task.model:
                logger.warning(
                    "Seedream webhook model mismatch: task_id=%s selected_model=%s stored_model=%s webhook_model=%s provider_model=%s",
                    task_id,
                    selected_model,
                    task.model,
                    webhook_model,
                    provider_model,
                )

            model_display = task.model or task.preset_id or "Seedream"
            caption = f"✅ <b>Изображение ({model_display}) готово!</b>\\n\\nID: <code>{task_id}</code>"
            if task.aspect_ratio:
                caption += f"\\n📐 <code>{task.aspect_ratio}</code>"
            if task.cost:
                caption += f"\\n💰 <code>{task.cost}🍌</code>"
            if getattr(task, 'source_feed_gen_id', None):
                caption += f"\\n\\n🎯 Промпт скрыт"
            elif task.preset_id == "no_preset" and task.prompt:
                caption += f"\\n\\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption += f"\\n\\n🎯 Пресет: {task.preset_id}"

            from bot.keyboards import get_image_result_keyboard
            reference_preview_urls = _extract_reference_image_urls(task)
            image_url = await _persist_result_url_if_needed(image_url, task_type="image")

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = request.app["bot"]

            try:
                image_bytes = None
                try:
                    import aiohttp

                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, timeout=30) as resp:
                            if resp.status == 200:
                                image_bytes = await resp.read()
                except Exception as download_error:
                    logger.error(
                        f"Failed to download seedream result image bytes: {download_error}"
                    )

                if image_bytes:
                    await bot_instance.send_document(
                        chat_id=telegram_id,
                        document=types.BufferedInputFile(
                            image_bytes, filename=_guess_result_filename(image_url, fallback_base="generated")
                        ),
                        caption=_build_single_result_caption(_with_original_link(caption, image_url), task, reference_preview_urls),
                        parse_mode="HTML",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=_task_callback_id(task, task_id)
                        ),
                    )
                else:
                    await bot_instance.send_document(
                        chat_id=telegram_id,
                        document=image_url,
                        caption=_build_single_result_caption(_with_original_link(caption, image_url), task, reference_preview_urls),
                        parse_mode="HTML",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=_task_callback_id(task, task_id)
                        ),
                    )

                logger.info(f"Image original sent as document to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send image: {e}")
                # Fallback — отправляем как ссылку
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🖼️ Ваше изображение готово!{image_url}",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=_task_callback_id(task, task_id)
                        ),
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")

        elif status == "TASK_STATUS_FAILED":
            reason = task_info.get("reason", "Unknown error")
            logger.error(f"Seedream task {task_id} failed: {reason}")

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Seedream webhook error: {e}")
        return web.Response(status=500)

async def handle_novita_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Novita AI (FLUX.2 Pro) API

    Novita AI webhook format (ASYNC_TASK_RESULT event):
    {
        "event_type": "ASYNC_TASK_RESULT",
        "payload": {
            "task": {
                "task_id": "...",
                "status": "TASK_STATUS_SUCCEED",
                "task_type": "TXT_TO_IMG"
            },
            "images": [{"image_url": "https://..."}],
            "extra": {...}
        }
    }
    """
    try:
        logger.info("Novita FLUX webhook headers: %s", _preview_log_headers(request.headers))

        body = await request.text()
        logger.info("Novita FLUX webhook raw body received: %s chars", len(body))

        if not body:
            logger.warning("Novita FLUX webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"Novita FLUX webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info("Novita FLUX webhook parsed data: %s", _preview_log_payload(data))

        # Check event type - Novita AI sends ASYNC_TASK_RESULT
        event_type = data.get("event_type")
        if event_type != "ASYNC_TASK_RESULT":
            logger.warning(f"Unexpected event_type: {event_type}, ignoring")
            return web.Response(status=200)

        # Get payload
        payload = data.get("payload", {})

        # Get task info from payload.task
        task_info = payload.get("task", {})
        task_id = task_info.get("task_id")
        status = task_info.get("status")

        if not task_id:
            logger.warning(f"No task_id in Novita FLUX webhook: {data}")
            return web.Response(status=200)

        logger.info(f"Novita FLUX task {task_id} status: {status}")

        # Novita AI status: TASK_STATUS_SUCCEED, TASK_STATUS_FAILED
        if status == "TASK_STATUS_SUCCEED":
            # Get images from payload.images array
            images = payload.get("images", [])

            if not images:
                logger.error(f"No images in completed task: {data}")
                return web.Response(status=200)

            # Novita returns images as objects with image_url field
            image_url = None
            if isinstance(images[0], dict):
                image_url = images[0].get("image_url")
            elif isinstance(images[0], str):
                image_url = images[0]

            if not image_url:
                logger.error(f"Invalid images format: {images}")
                return web.Response(status=200)

            logger.info(f"Extracted image URL: {image_url[:50]}...")

            # Находим задачу в БД по task_id
            from bot.database import complete_video_task, get_task_by_id

            task = await get_task_by_id(task_id)
            # P1-04: Idempotency — skip if already completed
            if task and task.status == "completed":
                logger.info(f"Webhook: task {task_id} already completed, skipping")
                return web.Response(status=200)

            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return web.Response(status=200)

            telegram_id = await _resolve_task_telegram_id(
                task, context="novita_success"
            )

            if not telegram_id:
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )

            # Determine caption based on preset
            if getattr(task, 'source_feed_gen_id', None):
                caption = f"✅ <b>Ваше изображение (FLUX.2 Pro) готово!</b>🎯 Промпт скрыт"
            elif task.preset_id == "no_preset" and task.prompt:
                caption = f"✅ <b>Ваше изображение (FLUX.2 Pro) готово!</b>🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption = f"✅ <b>Ваше изображение (FLUX.2 Pro) готово!</b>🎯 Пресет: {task.preset_id}"

            from bot.keyboards import get_image_result_keyboard
            reference_preview_urls = _extract_reference_image_urls(task)
            image_url = await _persist_result_url_if_needed(image_url, task_type="image")

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = request.app["bot"]

            try:
                image_bytes = None
                try:
                    import aiohttp

                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, timeout=30) as resp:
                            if resp.status == 200:
                                image_bytes = await resp.read()
                except Exception as download_error:
                    logger.error(
                        f"Failed to download novita result image bytes: {download_error}"
                    )

                if image_bytes:
                    await bot_instance.send_document(
                        chat_id=telegram_id,
                        document=types.BufferedInputFile(
                            image_bytes, filename=_guess_result_filename(image_url, fallback_base="generated")
                        ),
                        caption=_build_single_result_caption(_with_original_link(caption, image_url), task, reference_preview_urls),
                        parse_mode="HTML",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=_task_callback_id(task, task_id)
                        ),
                    )
                else:
                    await bot_instance.send_document(
                        chat_id=telegram_id,
                        document=image_url,
                        caption=_build_single_result_caption(_with_original_link(caption, image_url), task, reference_preview_urls),
                        parse_mode="HTML",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=_task_callback_id(task, task_id)
                        ),
                    )

                logger.info(f"Novita original sent as document to user {telegram_id}")

                logger.info(f"Image sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send image: {e}")
                # Fallback — отправляем как ссылку
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🖼️ Ваше изображение (FLUX.2 Pro) готово!{image_url}",
                        reply_markup=get_image_result_keyboard(
                            image_url, task_id=_task_callback_id(task, task_id)
                        ),
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")

        elif status == "TASK_STATUS_FAILED":
            reason = task_info.get("reason", "Unknown error")
            logger.error(f"Novita FLUX task {task_id} failed: {reason}")

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Novita FLUX webhook error: {e}")
        return web.Response(status=500)

async def handle_wanx_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от PiAPI WanX API"""
    try:
        logger.info("WanX webhook headers: %s", _preview_log_headers(request.headers))

        body = await request.text()
        logger.info("WanX webhook raw body received: %s chars", len(body))

        if not body:
            logger.warning("WanX webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"WanX webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info("WanX webhook parsed data: %s", _preview_log_payload(data))

        webhook_data = data.get("data") or data.get("payload") or data
        task_id = webhook_data.get("task_id")
        status = webhook_data.get("status")

        if not task_id:
            logger.warning(f"No task_id in WanX webhook: {data}")
            return web.Response(status=200)

        normalized_status = str(status).lower() if status else ""
        logger.info(f"WanX task {task_id} status: {status}")

        if normalized_status in (
            "completed",
            "succeeded",
            "success",
            "task_status_succeed",
        ):
            output = webhook_data.get("output", {})
            video_url = (
                output.get("video_url")
                or output.get("video")
                or (
                    output.get("works")
                    and output["works"][0]
                    .get("video", {})
                    .get("resource_without_watermark")
                )
            )

            if not video_url:
                logger.error(f"No video URL in WanX completed task: {webhook_data}")
                return web.Response(status=200)

            from bot.database import (
                complete_video_task,
                get_task_by_id,
            )

            task = await get_task_by_id(task_id)
            # P1-04: Idempotency — skip if already completed
            if task and task.status == "completed":
                logger.info(f"Webhook: task {task_id} already completed, skipping")
                return web.Response(status=200)
            if not task:
                logger.info(f"Ignoring orphan webhook for WanX task {task_id}: task not found in database")
                return web.Response(status=200)

            telegram_id = await _resolve_task_telegram_id(
                task, context="wanx_success"
            )
            if not telegram_id:
                return web.Response(status=200)

            reference_preview_urls = _extract_reference_image_urls(task, webhook_data)
            if getattr(task, 'source_feed_gen_id', None):
                caption = f"✅ <b>Ваше видео WanX готово!</b>🎯 Промпт скрыт"
            else:
                caption = (
                    f"✅ <b>Ваше видео WanX готово!</b>🎯 Промпт: <code>{task.prompt[:100]}{'...' if task.prompt and len(task.prompt) > 100 else ''}</code>"
                    if task.preset_id == "no_preset" and task.prompt
                    else f"✅ <b>Ваше видео WanX готово!</b>🎯 Пресет: {task.preset_id}"
                )

            video_url = await _persist_result_url_if_needed(video_url, task_type="video")

            bot_instance = request.app["bot"]
            try:
                from bot.keyboards import get_video_result_keyboard

                reply_markup = get_video_result_keyboard(
                    video_url,
                    task_id=_task_callback_id(task, task_id),
                    model=task.model if task else None,
                    is_public_feed=task.is_public_feed if task else False,
                )
                media_caption = _build_single_result_caption(
                    _with_original_link(caption, video_url),
                    task,
                    reference_preview_urls,
                )
                await bot_instance.send_video(
                    chat_id=telegram_id,
                    video=video_url,
                    caption=media_caption,
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=reply_markup,
                )
                await complete_video_task(task_id, video_url)
                logger.info(f"WanX video sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send WanX video: {e}")
                try:
                    delivered = await _send_video_file_from_url(
                        bot_instance,
                        telegram_id,
                        video_url,
                        caption=media_caption,
                        reply_markup=reply_markup,
                    )
                    if delivered:
                        await complete_video_task(task_id, video_url)
                        logger.info(f"WanX video downloaded and sent to user {telegram_id}")
                    else:
                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=f"🎬 Ваше видео WanX готово!\n{video_url}",
                            reply_markup=reply_markup,
                            parse_mode="HTML",
                        )
                except Exception as fallback_error:
                    logger.error(
                        f"Failed to send WanX fallback message: {fallback_error}"
                    )

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"WanX webhook error: {e}")
        return web.Response(status=500)

async def handle_kie_ai_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Kie.ai (Nano Banana 2) API"""
    try:
        logger.info("Kie.ai webhook headers: %s", _preview_log_headers(request.headers))

        # Verify webhook secret if configured (passed as ?secret= in callback URL)
        try:
            skip_secret_check = False
            try:
                skip_secret_check = bool(request.get("skip_kie_ai_secret_check"))
            except Exception:
                skip_secret_check = False

            if skip_secret_check:
                logger.info("Kie.ai webhook secret check skipped for verified KIE Market relay")
            else:
                secret = config.KIE_AI_WEBHOOK_SECRET
                if secret:
                    query_secret = request.query.get("secret", "")
                    if not hmac.compare_digest(query_secret, secret):
                        logger.warning(
                            "Kie.ai webhook rejected: invalid or missing secret param (len=%s)",
                            len(query_secret),
                        )
                        return web.Response(status=403)
        except Exception:
            logger.exception("Error while checking Kie.ai webhook secret")
            return web.Response(status=403)

        raw_body = await request.read()
        if not raw_body:
            logger.warning("Kie.ai webhook received empty body")
            return web.Response(status=200)

        try:
            body_text = raw_body.decode("utf-8")
            logger.info("Kie.ai webhook raw body received: %s bytes", len(raw_body))
            data = json.loads(body_text)
        except Exception as e:
            logger.warning(f"Kie.ai webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info("Kie.ai webhook parsed data: %s", _preview_log_payload(data))

        from bot.database import (
            add_credits,
            complete_video_task,
            get_task_by_id,
        )
        from bot.keyboards import (
            get_gemini_omni_result_keyboard,
            get_video_result_keyboard,
        )

        # Flexible extraction for task_id, status, image_url
        webhook_data = data.get("data") if isinstance(data.get("data"), dict) else data
        task_id = (
            webhook_data.get("taskId")
            or webhook_data.get("task_id")
            or webhook_data.get("id")
        )
        status = webhook_data.get("state") or webhook_data.get("status")
        normalized_status = str(status).lower() if status else ""
        response_code = data.get("code")
        veo_info = webhook_data.get("info") if isinstance(webhook_data, dict) else None
        is_veo_payload = bool(veo_info) or str(task_id).startswith("veo_")

        model = webhook_data.get("model", "")
        model_lower = model.lower()
        if "gpt-image-2" in model_lower:
            service_name = "GPT Image 2"
        elif "seedream" in model_lower:
            service_name = "Seedream"
            if "4.5-edit" in model_lower:
                service_name += " 4.5 Edit"
            elif "lite" in model_lower:
                service_name += " Lite"
        elif "nano-banana" in model_lower or "nano_banana" in model_lower:
            service_name = "Nano Banana"
            if "pro" in model_lower:
                service_name += " Pro"
            else:
                service_name += " 2"
        elif "kling/ai-avatar-standard" in model_lower:
            service_name = "Kling AI Avatar Standard"
        elif "kling/ai-avatar-pro" in model_lower:
            service_name = "Kling AI Avatar Pro"
        elif "kling/v2-5-turbo" in model_lower:
            service_name = "Kling 2.5 Turbo Pro"
        elif "seedance" in model_lower:
            service_name = "Bytedance Seedance 2.0"
        elif "veo" in model_lower or is_veo_payload:
            service_name = "Veo 3.1"
        elif "gemini-omni-video" in model_lower:
            service_name = "Gemini Omni Video"
        elif "gemini-omni-audio" in model_lower:
            service_name = "Gemini Omni Audio"
        elif "gemini-omni-character" in model_lower:
            service_name = "Gemini Omni Character"
        else:
            service_name = model or "AI"

        logger.info(
            f"Processing {service_name} task {task_id} with status {status} (normalized: {normalized_status})"
        )

        if not task_id:
            logger.error(f"Kie.ai webhook missing task id. Payload: {webhook_data}")
            return web.Response(status=200)

        # Find task in DB early for both success and failure
        task = await get_task_by_id(task_id)
        # P1-04: Idempotency — skip if already completed
        if task and task.status == "completed":
            logger.info(f"Webhook: task {task_id} already completed, skipping")
            return web.Response(status=200)
        telegram_id = None
        if task:
            telegram_id = await _resolve_task_telegram_id(
                task, context="kie_ai"
            )

        if is_veo_payload and not normalized_status:
            if response_code == 200:
                normalized_status = "success"
            elif response_code in {400, 422, 500, 501}:
                normalized_status = "failed"

        if normalized_status in {"success", "completed", "succeeded", "finished"}:
            # Parse resultJson for Kie.ai specific format
            result_json_str = webhook_data.get("resultJson", "{}")
            result_url = None
            if is_veo_payload:
                from bot.services.veo_service import veo_service

                veo_urls = veo_service.extract_result_urls(data)
                result_url = veo_urls[0] if veo_urls else None
            else:
                try:
                    result_json = json.loads(result_json_str)
                    result_urls = result_json.get("resultUrls", [])
                    result_url = result_urls[0] if result_urls else None
                except (json.JSONDecodeError, KeyError, IndexError):
                    logger.warning(
                        f"Failed to parse Kie.ai resultJson: {result_json_str}"
                    )
                if not result_url:
                    direct_result = _extract_first(
                        webhook_data,
                        (
                            "resultUrl",
                            "result_url",
                            "videoUrl",
                            "imageUrl",
                            "url",
                        ),
                    )
                    if isinstance(direct_result, list) and direct_result:
                        direct_result = direct_result[0]
                    if isinstance(direct_result, str) and direct_result.startswith("http"):
                        result_url = direct_result

            if result_url:
                logger.info(
                    f"Extracted {service_name} result URL: {result_url[:50]}..."
                )
            else:
                asset_kind = None
                if task and task.type in {"audio", "character"}:
                    asset_kind = task.type
                elif "gemini-omni-audio" in model_lower:
                    asset_kind = "audio"
                elif "gemini-omni-character" in model_lower:
                    asset_kind = "character"

                asset_id = (
                    _extract_gemini_omni_asset_id(webhook_data, asset_kind)
                    if asset_kind
                    else None
                )
                if asset_id:
                    if not task:
                        logger.info(
                            "Ignoring orphan webhook for %s task %s: task not found in database",
                            service_name,
                            task_id,
                        )
                        return web.Response(status=200)
                    if not telegram_id:
                        logger.error(
                            "Cannot find telegram_id for user_id %s",
                            task.user_id,
                        )
                        return web.Response(status=200)

                    model_label = _get_task_model_label(task.model, task.type)
                    title = (
                        "Audio ID готов"
                        if asset_kind == "audio"
                        else "Character ID готов"
                    )
                    bot_instance = request.app["bot"]
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=(
                            f"✅ <b>{title}</b>\n"
                            f"• Модель: <code>{html.escape(model_label)}</code>\n"
                            f"• ID: <code>{html.escape(asset_id)}</code>\n\n"
                            "Этот ID можно использовать в Gemini Omni Video."
                        ),
                        parse_mode="HTML",
                        reply_markup=get_gemini_omni_result_keyboard(),
                    )

                    await complete_video_task(task_id, asset_id)
                    logger.info(
                        "%s asset id %s sent to user %s",
                        service_name,
                        asset_id,
                        telegram_id,
                    )
                    return web.Response(status=200)

                logger.error(
                    f"No result URL found in {service_name} result: {webhook_data.get('resultJson', 'N/A')}"
                )
                if telegram_id:
                    bot_instance = request.app["bot"]
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=(
                            "Не получилось завершить генерацию.\n"
                            f"• Модель: <code>{service_name}</code>\n"
                            f"• ID: <code>{task_id}</code>\n\n"
                            "Мы не получили готовый файл от сервиса.\n"
                            "Попробуйте повторить запуск немного позже."
                        ),
                        parse_mode="HTML",
                    )
                return web.Response(status=200)

            if not task:
                logger.info(f"Ignoring orphan webhook for {service_name} task {task_id}: task not found in database")
                return web.Response(status=200)
            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            logger.info(
                f"Found {service_name} task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )

            result_url = await _persist_result_url_if_needed(
                result_url,
                task_type=task.type if task else ("video" if is_video else "image"),
            )

            reference_preview_urls = _extract_reference_image_urls(
                task,
                webhook_data=webhook_data,
            )
            source_links = _format_reference_links(reference_preview_urls)

            is_video = False
            if result_url:
                url_lower = result_url.lower()
                video_exts = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp", ".flv"]
                if task and task.type == "video":
                    is_video = True
                elif task and (task.model or "").startswith("veo3"):
                    is_video = True
                elif any(ext in url_lower.split("?", 1)[0] for ext in video_exts):
                    is_video = True
                elif "video" in model_lower:
                    is_video = True

            # Build ultra-compact caption with minimal line breaks
            info_lines = []
            prompt_or_preset, label = _get_result_prompt_caption(task)
            model_label = _get_task_model_label(
                task.model if task else None, task.type if task else None
            )
            display_task_id = _public_task_id(task, task_id)
            full_caption = (
                f"✅ <b>{'Видео' if is_video else 'Изображение'} готово</b>\n"
                f"• Модель: <code>{_html_fragment(model_label)}</code>\n"
                f"• ID: <code>{_html_fragment(display_task_id)}</code>"
                f"{_provider_task_id_line(task, task_id)}"
            )
            if task.cost:
                full_caption += f"\n• Стоимость: <code>{_html_fragment(task.cost)}🍌</code>"
            if task.duration:
                full_caption += f"\n• Длительность: <code>{_html_fragment(task.duration)}с</code>"
            if task.aspect_ratio:
                full_caption += (
                    f"\n• Формат: <code>{_html_fragment(str(task.aspect_ratio).replace(':', '∶'))}</code>"
                )
            if is_video:
                if source_links:
                    full_caption += source_links
                full_caption += (
                    f"\n\n🔗 <a href='{html.escape(str(result_url), quote=True)}'>"
                    "Открыть оригинал</a>"
                )
            if len(full_caption) > 980:
                full_caption = full_caption[:977] + "..."

            from bot.keyboards import get_image_result_keyboard

            kb_link = (
                get_video_result_keyboard(
                    result_url,
                    task_id=_task_callback_id(task, task_id),
                    model=task.model if task else None,
                    is_public_feed=task.is_public_feed if task else False,
                )
                if is_video
                else get_image_result_keyboard(result_url, task_id=_task_callback_id(task, task_id))
            )

            bot_instance = request.app["bot"]
            try:
                sent_media = False
                if is_video:
                    video_kb = get_video_result_keyboard(
                        result_url,
                        task_id=_task_callback_id(task, task_id),
                        model=task.model if task else None,
                        is_public_feed=task.is_public_feed if task else False,
                    )
                    try:
                        await bot_instance.send_video(
                            chat_id=telegram_id,
                            video=result_url,
                            caption=_build_single_result_caption(_with_original_link(full_caption, result_url), task, reference_preview_urls),
                            parse_mode="HTML",
                            supports_streaming=True,
                            reply_markup=video_kb,
                        )
                        logger.info(
                            "%s video sent via URL to user %s",
                            service_name,
                            telegram_id,
                        )
                        sent_media = True
                    except Exception as e:
                        logger.warning(
                            "Video URL send failed (%s), trying file upload",
                            e,
                        )
                        tmp_file = None
                        try:
                            import os
                            import tempfile

                            import aiohttp

                            async with aiohttp.ClientSession() as session:
                                async with session.get(result_url, timeout=60) as resp:
                                    if resp.status != 200:
                                        raise RuntimeError(
                                            f"Download failed: {resp.status}"
                                        )
                                    tmp = tempfile.NamedTemporaryFile(
                                        delete=False, suffix=".mp4"
                                    )
                                    tmp_file = tmp.name
                                    with open(tmp_file, "wb") as f:
                                        async for chunk in resp.content.iter_chunked(
                                            1024 * 64
                                        ):
                                            if chunk:
                                                f.write(chunk)
                            from aiogram.types import FSInputFile

                            video_file = FSInputFile(tmp_file)
                            await bot_instance.send_video(
                                chat_id=telegram_id,
                                video=video_file,
                                caption=_build_single_result_caption(_with_original_link(full_caption, result_url), task, reference_preview_urls),
                                parse_mode="HTML",
                                supports_streaming=True,
                                reply_markup=video_kb,
                            )
                            logger.info(
                                f"{service_name} video sent as file to user {telegram_id}"
                            )
                            sent_media = True
                        except Exception as dl_e:
                            logger.error(f"Video file upload failed: {dl_e}")
                        finally:
                            if tmp_file and os.path.exists(tmp_file):
                                try:
                                    os.remove(tmp_file)
                                except Exception:
                                    pass
                else:
                    # Image
                    image_bytes = await _download_remote_bytes(result_url, timeout_seconds=30)
                    preview_sent = False
                    preview_caption = _build_single_result_caption(_with_original_link(full_caption, result_url), task, reference_preview_urls)
                    if image_bytes:
                        preview_bytes = _build_preview_photo_bytes(image_bytes)
                        if preview_bytes:
                            try:
                                photo = types.BufferedInputFile(
                                    preview_bytes, filename="generated_preview.jpg"
                                )
                                await bot_instance.send_photo(
                                    chat_id=telegram_id,
                                    photo=photo,
                                    caption=preview_caption,
                                    parse_mode="HTML",
                                    reply_markup=kb_link,
                                )
                                logger.info(
                                    f"{service_name} image preview sent as file-photo to user {telegram_id}"
                                )
                                preview_sent = True
                            except Exception as preview_file_e:
                                logger.info(
                                    f"Preview file-photo send failed ({preview_file_e}), trying URL photo"
                                )
                    if not preview_sent:
                        try:
                            await bot_instance.send_photo(
                                chat_id=telegram_id,
                                photo=result_url,
                                caption=preview_caption,
                                parse_mode="HTML",
                                reply_markup=kb_link,
                            )
                            logger.info(
                                f"{service_name} image preview sent via URL to user {telegram_id}"
                            )
                            preview_sent = True
                        except Exception as url_send_e:
                            logger.info(
                                f"Image URL send failed ({url_send_e})"
                            )

                    original_sent = await _send_original_file(bot_instance, telegram_id, result_url, image_bytes)

                    if preview_sent:
                        await complete_video_task(task_id, result_url)
                        sent_media = True
                    elif original_sent:
                        await complete_video_task(task_id, result_url)
                        sent_media = True
                    else:
                        logger.warning(f"No image preview or original sent for {service_name}")

                if sent_media:
                    if is_video:
                        await complete_video_task(task_id, result_url)
                    elif _should_send_prompt_followup(task):
                        try:
                            await _send_used_prompt_message(bot_instance, telegram_id, task, result_url)
                        except Exception as prompt_e:
                            logger.error(
                                f"Failed to send prompt follow-up to {telegram_id}: {prompt_e}"
                            )
                else:
                    await _send_plain_result_link(
                        bot_instance,
                        telegram_id,
                        media_label="Видео" if is_video else "Изображение",
                        model_label=model_label,
                        task_id=task_id,
                        result_url=result_url,
                        reply_markup=kb_link,
                    )
                    await complete_video_task(task_id, result_url)
                    logger.info(
                        f"{service_name} fallback text sent to user {telegram_id}"
                    )
            except Exception as send_e:
                logger.error(
                    f"Failed to send {service_name} result to {telegram_id}: {send_e}"
                )
                try:
                    await complete_video_task(task_id, result_url)
                    logger.warning(
                        f"{service_name} result stored but Telegram delivery failed for {telegram_id}"
                    )
                except Exception as complete_e:
                    logger.error(
                        f"Failed to store completed {service_name} task {task_id}: {complete_e}"
                    )
        else:
            # Enhanced failure logging and user notification
            fail_code = (
                webhook_data.get("failCode")
                or webhook_data.get("errorCode")
                or data.get("code")
                or "unknown"
            )
            fail_msg = (
                webhook_data.get("failMsg")
                or webhook_data.get("errorMessage")
                or data.get("msg")
                or "No details"
            )
            user_fail_msg = fail_msg
            fail_msg_lower = str(fail_msg).lower()
            if "generative ai prohibited use policy" in fail_msg_lower:
                user_fail_msg = (
                    "внешний safety-фильтр провайдера не пропустил результат. "
                    "Это не обязательно значит, что запрос запрещён, но текущая модель "
                    "не вернула картинку."
                )
            logger.error(
                "%s task %s FAILED: failCode=%s, failMsg=%s, data=%s",
                service_name,
                task_id,
                fail_code,
                fail_msg,
                _preview_log_payload(webhook_data),
            )

            if task and (
                _is_retryable_kie_blank_task_failure(fail_code, fail_msg)
                or _is_retryable_kie_timeout_failure(task, fail_code, fail_msg)
            ):
                try:
                    retried_task_id = await _retry_transient_kie_image_failure(task, task_id)
                    if retried_task_id:
                        logger.info(
                            "%s task %s requeued automatically as %s after transient KIE upstream failure",
                            service_name,
                            task_id,
                            retried_task_id,
                        )
                        return web.Response(status=200)
                except Exception as retry_error:
                    logger.exception(
                        "Automatic retry failed for transient KIE image task %s: %s",
                        task_id,
                        retry_error,
                    )

            if task and _is_retryable_wan_timeout_failure(task, fail_code, fail_msg):
                try:
                    retried_task_id = await _retry_transient_wan_timeout_failure(task, task_id)
                    if retried_task_id:
                        logger.info(
                            "%s task %s requeued automatically as %s after WAN timeout",
                            service_name,
                            task_id,
                            retried_task_id,
                        )
                        return web.Response(status=200)
                except Exception as retry_error:
                    logger.exception(
                        "Automatic retry failed for transient WAN image task %s: %s",
                        task_id,
                        retry_error,
                    )

            if task and _is_retryable_seedance_real_person_failure(task, fail_msg):
                try:
                    retried_task_id = (
                        await _retry_transient_seedance_real_person_failure(
                            task,
                            task_id,
                        )
                    )
                    if retried_task_id:
                        logger.info(
                            "Seedance task %s requeued automatically as %s after real-person false positive",
                            task_id,
                            retried_task_id,
                        )
                        return web.Response(status=200)
                except Exception as retry_error:
                    logger.exception(
                        "Automatic retry failed for Seedance task %s: %s",
                        task_id,
                        retry_error,
                    )

            if task and task.cost and task.cost > 0:
                await add_credits(telegram_id, task.cost)

            await complete_video_task(task_id, None)

            if telegram_id:
                bot_instance = request.app["bot"]
                try:
                    refund_text = (
                        "\n\nБананы за эту попытку уже возвращены."
                        if task and task.cost and task.cost > 0
                        else "\n\nПопробуйте упростить промпт или повторить попытку немного позже."
                    )
                    error_msg = _build_failure_notification_text(
                        service_name=service_name,
                        task_id=task_id,
                        reason=user_fail_msg,
                        media_kind=(
                            "видео"
                            if task and task.type == "video"
                            else "результата"
                        ),
                        refund_text=refund_text,
                    )
                    reply_markup = None
                    if task and task.type == "image":
                        from bot.keyboards import get_failed_image_retry_keyboard

                        reply_markup = get_failed_image_retry_keyboard(
                            _task_callback_id(task, task_id)
                        )
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=error_msg,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                    logger.info(f"Failure notification sent to {telegram_id}")
                except Exception as notify_e:
                    logger.error(f"Failed to notify user {telegram_id}: {notify_e}")
            else:
                logger.warning(
                    f"No telegram_id for failed task {task_id} (user_id: {task.user_id if task else 'unknown'})"
                )

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kie.ai webhook error: {e}")
        return web.Response(status=200)

async def handle_kie_market_webhook(request: web.Request) -> web.Response:
    """Webhook for KIE Market models such as nano-banana-2-lite."""
    try:
        raw_body = await request.read()
        if not raw_body:
            logger.warning("KIE Market webhook received empty body")
            return web.Response(status=200)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            logger.warning("KIE Market webhook received invalid JSON: %s", exc)
            return web.Response(status=200)

        from bot.services.kie_market_service import kie_market_service

        if not kie_market_service.verify_webhook_signature(
            payload=payload,
            headers=request.headers,
        ):
            return web.json_response(
                {"ok": False, "error": "bad signature"},
                status=401,
            )

        request["skip_kie_ai_secret_check"] = True
        request._read_bytes = raw_body
        return await handle_kie_ai_webhook(request)
    except Exception as exc:
        logger.exception("KIE Market webhook error: %s", exc)
        return web.Response(status=200)

def setup_web_server(dp: Dispatcher, bot: Bot) -> web.Application:
    """Настройка aiohttp сервера для вебхуков"""

    def _normalize_path(path: str, fallback: str) -> str:
        raw = (path or "").strip()
        if not raw:
            return fallback
        return raw if raw.startswith("/") else f"/{raw}"

    app = web.Application(client_max_size=220 * 1024 * 1024)

    # Rate limiter middleware — applies to all routes except /health GET
    from bot.services.rate_limiter import rate_limiter_middleware
    app.middlewares.append(rate_limiter_middleware)

    app["bot"] = bot
    app["dp"] = dp

    # Serve static uploads directory to fix 404 errors for Novita image downloads
    app.router.add_static(
        "/uploads/", path="static/uploads", show_index=False, name="uploads"
    )
    setup_browser_auth_routes(app)
    setup_feed_reference_media_routes(app)
    setup_miniapp_routes(app)

    # Вебхук Telegram
    async def telegram_webhook_handler(request: web.Request) -> web.Response:
        return await handle_telegram_webhook(request, bot, dp)

    app.router.add_post(
        _normalize_path(config.WEBHOOK_PATH, "/telegram/webhook"),
        telegram_webhook_handler,
    )

    # Вебхук CryptoBot
    app.router.add_post(
        _normalize_path(config.CRYPTOBOT_WEBHOOK_PATH, "/cryptobot/webhook"),
        handle_cryptobot_webhook,
    )

    # Вебхук Lava
    app.router.add_post(
        _normalize_path(config.LAVA_WEBHOOK_PATH, "/lava/webhook"),
        handle_lava_webhook,
    )

    # Вебхук YooKassa
    app.router.add_post("/yookassa/webhook", handle_yookassa_webhook)
    # Alternative path (matches provided URL https://.../webhook/yookassa)
    app.router.add_post("/webhook/yookassa", handle_yookassa_webhook)

    # Вебхук Kling
    app.router.add_post("/webhook/kling", handle_kling_webhook)

    # Вебхук Kie.ai (Nano Banana 2)
    app.router.add_post(
        _normalize_path(config.KIE_AI_WEBHOOK_PATH, "/webhook/kie_ai"),
        handle_kie_ai_webhook,
    )

    # Вебхук KIE Market (nano-banana-2-lite + future models)
    app.router.add_post(
        _normalize_path(config.KIE_MARKET_WEBHOOK_PATH, "/webhooks/kie"),
        handle_kie_market_webhook,
    )

    # Health check endpoint (restricted by secret header)
    HEALTH_SECRET = config.HEALTH_CHECK_SECRET or ""

    async def health_check(request: web.Request) -> web.Response:
        if HEALTH_SECRET:
            auth = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if auth != HEALTH_SECRET:
                return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({"status": "ok", "service": "tanya-bot"})

    app.router.add_get("/health", health_check)

    # Internal API for admin panel
    setup_internal_api(app, secret=config.INTERNAL_API_SECRET, version="1.0.0")
    setup_internal_admin_routes(app)

    return app

async def main():
    """Главная функция"""
    # Создаём директорию для логов если её нет
    os.makedirs("logs", exist_ok=True)

    # Проверяем наличие токена
    if not config.BOT_TOKEN:
        logger.error(
            "BOT_TOKEN is not set! Please set the BOT_TOKEN environment variable."
        )
        sys.exit(1)

    # Инициализируем базу данных ДО создания бота
    logger.info("Initializing database before bot startup...")
    await init_db()
    logger.info("Database initialized successfully")

    # Запускаем Task Watchdog для зависших задач генерации
    try:
        from bot.services.task_watchdog import watchdog_loop
        asyncio.create_task(watchdog_loop())
        logger.info("Task watchdog started")
    except Exception:
        logger.exception("Failed to start task watchdog")

    # Запускаем очистку rate limiter'а
    from bot.services.rate_limiter import start_cleanup_task
    start_cleanup_task()

    # Создаём бота
    bot = Bot(
        token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    try:
        asyncio.create_task(_nexus_image_poller_loop(bot))
        logger.info("Nexus image poller started")
    except Exception:
        logger.exception("Failed to start Nexus image poller")

    # Настраиваем диспатчер
    dp = setup_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    if config.WEBHOOK_HOST:
        # Webhook mode (для production)
        logger.info("Starting in webhook mode...")
        app = setup_web_server(dp, bot)
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, config.WEBHOOK_BIND_HOST, config.WEBHOOK_PORT)
        await site.start()

        logger.info(
            "Server started on %s:%s",
            config.WEBHOOK_BIND_HOST,
            config.WEBHOOK_PORT,
        )
        await on_startup(bot, dispatcher=dp)
        try:
            # Держим бота запущенным
            await asyncio.Event().wait()
        finally:
            await on_shutdown(bot)
            await runner.cleanup()
    else:
        # Polling mode (для разработки)
        logger.info("Starting in polling mode...")
        await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
