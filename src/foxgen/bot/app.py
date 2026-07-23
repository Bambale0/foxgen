import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import CallbackQuery, ErrorEvent, Message

from foxgen.bot.api_client import FoxGenApiClient
from foxgen.bot.flows import router as generation_router
from foxgen.bot.keyboards import main_menu
from foxgen.bot.uploads import TelegramInputMediaStorage
from foxgen.core.config import Settings, get_settings
from foxgen.infra.media import S3MediaStorage


logger = logging.getLogger(__name__)
router = Router(name="foxgen-shell")


@router.message(CommandStart())
@router.message(Command("menu"))
async def show_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "<b>FoxGen</b>\n\nВыберите раздел.",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "nav:menu")
async def return_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        try:
            await callback.message.edit_text("Главное меню", reply_markup=main_menu())
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
    await callback.answer()


@router.callback_query(F.data == "nav:cancel")
async def cancel_flow(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            "Действие отменено. Главное меню:",
            reply_markup=main_menu(),
        )
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("planned:"))
async def planned_section(callback: CallbackQuery) -> None:
    if callback.message:
        try:
            await callback.message.edit_text(
                "Раздел уже включён в дорожную карту и будет подключён отдельным PR.",
                reply_markup=main_menu(),
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
    await callback.answer()


@router.callback_query()
async def stale_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Эта кнопка устарела. Открыл главное меню.", show_alert=True)
    if callback.message:
        try:
            await callback.message.edit_text("Главное меню", reply_markup=main_menu())
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise


@router.message()
async def fallback_message(message: Message) -> None:
    await message.answer(
        "Не понял действие. Выберите нужный раздел кнопкой.",
        reply_markup=main_menu(),
    )


@router.error()
async def global_error(event: ErrorEvent) -> bool:
    logger.exception("Unhandled Telegram update", exc_info=event.exception)
    update_message = event.update.message
    if update_message:
        await update_message.answer(
            "Что-то пошло не так. Откройте /menu и повторите шаг."
        )
        return True
    update_callback = event.update.callback_query
    if update_callback:
        await update_callback.answer(
            "Что-то пошло не так. Откройте /menu и повторите шаг.",
            show_alert=True,
        )
    return True


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
    media_storage = S3MediaStorage(
        bucket=resolved.s3_bucket,
        region=resolved.s3_region,
        endpoint_url=(
            str(resolved.s3_endpoint_url)
            if resolved.s3_endpoint_url is not None
            else None
        ),
        access_key_id=(
            resolved.s3_access_key_id.get_secret_value()
            if resolved.s3_access_key_id is not None
            else None
        ),
        secret_access_key=(
            resolved.s3_secret_access_key.get_secret_value()
            if resolved.s3_secret_access_key is not None
            else None
        ),
        force_path_style=resolved.s3_force_path_style,
        presigned_url_ttl_seconds=resolved.telegram_input_presigned_url_ttl_seconds,
    )
    input_media = TelegramInputMediaStorage(
        storage=media_storage,
        max_bytes=resolved.telegram_input_max_bytes,
    )
    dispatcher = Dispatcher(
        storage=storage,
        api_client=api_client,
        input_media=input_media,
    )
    dispatcher.include_router(generation_router)
    dispatcher.include_router(router)
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
        await api_client.aclose()
        await bot.session.close()
        await storage.close()


def run_sync() -> None:
    asyncio.run(run())
