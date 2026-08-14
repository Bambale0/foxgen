import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseEventIsolation
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import CallbackQuery, ErrorEvent, Message

from foxgen.bot.admin import router as admin_router
from foxgen.bot.admin_api_client import AdminApiClient
from foxgen.bot.admin_extras import router as admin_extras_router
from foxgen.bot.api_client import FoxGenApiClient
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.flows import router as generation_router
from foxgen.bot.fsm_contract import contract_for
from foxgen.bot.keyboards import main_menu
from foxgen.bot.quick_start import router as quick_start_router
from foxgen.bot.uploads import TelegramInputMediaStorage, stored_input_keys
from foxgen.core.config import Settings, get_settings
from foxgen.infra.input_media import LocalInputMediaStorage

logger = logging.getLogger(__name__)
global_commands_router = Router(name="foxgen-global-commands")
router = Router(name="foxgen-shell")
FSM_EVENT_LOCK_TIMEOUT_SECONDS = 180


async def clear_state_with_inputs(
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    data = await state.get_data()
    cleanup = await input_media.delete_many(stored_input_keys(data))
    if cleanup.failed:
        logger.warning(
            "telegram_input_cleanup_failed",
            extra={"failed_count": len(cleanup.failed)},
        )
    await state.clear()


@global_commands_router.message(CommandStart())
@global_commands_router.message(Command("menu"))
async def show_menu(
    message: Message,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    """Interrupt any active FSM draft and return to the canonical entrypoint."""

    await clear_state_with_inputs(state, input_media)
    await message.answer(
        "<b>FoxGen</b>\n\nВыберите раздел.",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "nav:menu")
async def return_to_menu(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    await clear_state_with_inputs(state, input_media)
    await safe_edit_callback_message(callback, "Главное меню", main_menu())


@router.callback_query(F.data == "nav:cancel")
async def cancel_flow(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    await clear_state_with_inputs(state, input_media)
    await safe_edit_callback_message(
        callback,
        "Действие отменено. Главное меню:",
        main_menu(),
        answer_text="Отменено",
    )


@router.callback_query(F.data.startswith("planned:"))
async def planned_section(callback: CallbackQuery) -> None:
    await safe_edit_callback_message(
        callback,
        "Раздел уже включён в дорожную карту и будет подключён отдельным PR.",
        main_menu(),
    )


@router.callback_query()
async def stale_callback(
    callback: CallbackQuery,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    current = await state.get_state()
    if contract_for(current) is not None:
        await callback.answer(
            "Эта кнопка не относится к текущему шагу. Используйте кнопки в последнем сообщении или /menu.",
            show_alert=True,
        )
        return

    await clear_state_with_inputs(state, input_media)
    await callback.answer(
        "Срок действия кнопки истёк. Открыл главное меню.",
        show_alert=True,
    )
    if callback.message:
        await safe_edit_callback_message(
            callback,
            "Черновик уже недоступен. Главное меню:",
            main_menu(),
            answer_callback=False,
        )


@router.message()
async def fallback_message(
    message: Message,
    state: FSMContext,
    input_media: TelegramInputMediaStorage,
) -> None:
    current = await state.get_state()
    if contract_for(current) is not None:
        await message.answer(
            "Сейчас открыт незавершённый шаг. Используйте кнопки или формат ввода из последнего сообщения. "
            "Команда /menu отменит черновик и вернёт в главное меню."
        )
        return
    if current is not None:
        await clear_state_with_inputs(state, input_media)
        await message.answer(
            "Черновик относится к старой версии и был безопасно сброшен.",
            reply_markup=main_menu(),
        )
        return
    await message.answer(
        "Не понял действие. Выберите нужный раздел кнопкой.",
        reply_markup=main_menu(),
    )


@router.error()
async def global_error(event: ErrorEvent) -> bool:
    logger.exception("Unhandled Telegram update", exc_info=event.exception)
    update_message = event.update.message
    if update_message:
        await update_message.answer("Что-то пошло не так. Откройте /menu и повторите шаг.")
        return True
    update_callback = event.update.callback_query
    if update_callback:
        await update_callback.answer(
            "Что-то пошло не так. Откройте /menu и повторите шаг.",
            show_alert=True,
        )
    return True


def create_event_isolation(storage: RedisStorage) -> BaseEventIsolation:
    """Serialize updates for one FSM key across polling tasks and bot replicas."""

    return storage.create_isolation(lock_kwargs={"timeout": FSM_EVENT_LOCK_TIMEOUT_SECONDS})


def register_runtime_routers(dispatcher: Dispatcher) -> None:
    """Register interrupt commands first, then privileged/product routers and fallbacks."""

    # /start and /menu are hard interrupts: they must run before any state-specific
    # text handler (and before admin/product routers) so an active FSM can never
    # swallow the command as ordinary user input.
    dispatcher.include_router(global_commands_router)
    # Extension callbacks re-authorize through the signed Admin API on every action.
    # Keep them before the shell's catch-all callback handler so stale recovery cannot
    # swallow a valid privileged action.
    dispatcher.include_router(admin_extras_router)
    dispatcher.include_router(admin_router)
    dispatcher.include_router(quick_start_router)
    dispatcher.include_router(generation_router)
    dispatcher.include_router(router)


async def run(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    telegram_token = resolved.telegram_bot_token
    internal_token = resolved.internal_api_token
    if telegram_token is None:
        raise RuntimeError("FOXGEN_TELEGRAM_BOT_TOKEN is required")
    if internal_token is None:
        raise RuntimeError("FOXGEN_INTERNAL_API_TOKEN is required for Telegram submissions")

    storage = RedisStorage.from_url(
        resolved.redis_url,
        state_ttl=resolved.telegram_fsm_ttl_seconds,
        data_ttl=resolved.telegram_fsm_ttl_seconds,
    )
    api_client = FoxGenApiClient(
        base_url=str(resolved.internal_api_base_url),
        internal_token=internal_token.get_secret_value(),
        timeout_seconds=resolved.internal_api_timeout_seconds,
    )
    admin_api_client: AdminApiClient | None = None
    if resolved.admin_api_enabled and resolved.admin_hmac_key is not None:
        admin_api_client = AdminApiClient(
            base_url=str(resolved.internal_api_base_url),
            hmac_key=resolved.admin_hmac_key.get_secret_value(),
            timeout_seconds=resolved.internal_api_timeout_seconds,
        )
    media_storage = LocalInputMediaStorage(
        root=resolved.telegram_input_storage_root,
        public_base_url=resolved.telegram_input_public_base_url,
        signing_secret=internal_token.get_secret_value(),
        presigned_url_ttl_seconds=resolved.telegram_input_presigned_url_ttl_seconds,
        retention_seconds=resolved.telegram_input_retention_seconds,
    )
    input_media = TelegramInputMediaStorage(
        storage=media_storage,
        max_bytes=resolved.telegram_input_max_bytes,
    )
    dispatcher = Dispatcher(
        storage=storage,
        events_isolation=create_event_isolation(storage),
        api_client=api_client,
        admin_api_client=admin_api_client,
        input_media=input_media,
    )
    register_runtime_routers(dispatcher)
    bot = Bot(
        token=telegram_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        if admin_api_client is not None:
            await admin_api_client.aclose()
        await api_client.aclose()
        await bot.session.close()
        await storage.close()


def run_sync() -> None:
    asyncio.run(run())
