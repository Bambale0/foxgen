from html import escape
from urllib.parse import quote
from uuid import UUID, uuid4

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import (
    FeedCommentView,
    FeedPublicationView,
    FoxGenApiClient,
    FoxGenApiError,
)
from foxgen.bot.catalog import GenerationMode, Product
from foxgen.bot.keyboards import main_menu, model_keyboard
from foxgen.bot.states import FeedStates, GenerationStates
from foxgen.feed.domain import DeepLinkKind, parse_start_param


router = Router(name="feed")

_SOURCE_CODES = {"r": "recent", "d": "top_day", "t": "top"}
_SOURCE_TITLES = {"recent": "Новые", "top_day": "Топ дня", "top": "Топ"}


@router.message(Command("feed"))
async def feed_command(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await state.clear()
    await _send_feed_page(
        message,
        api_client,
        user_id=_message_user_id(message),
        source="recent",
        offset=0,
    )


@router.callback_query(F.data == "feed:open")
async def open_feed(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await state.clear()
    if callback.message:
        await _send_feed_page(
            callback.message,
            api_client,
            user_id=callback.from_user.id,
            source="recent",
            offset=0,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("feed:src:"))
async def switch_feed_source(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    source = _SOURCE_CODES.get((callback.data or "").rpartition(":")[2])
    if source is None:
        await callback.answer("Неизвестный раздел ленты.", show_alert=True)
        return
    if callback.message:
        await _send_feed_page(
            callback.message,
            api_client,
            user_id=callback.from_user.id,
            source=source,
            offset=0,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("feed:page:"))
async def feed_page(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[2] not in _SOURCE_CODES:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    try:
        offset = max(0, int(parts[3]))
    except ValueError:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    if callback.message:
        await _send_feed_page(
            callback.message,
            api_client,
            user_id=callback.from_user.id,
            source=_SOURCE_CODES[parts[2]],
            offset=offset,
        )
    await callback.answer()


@router.callback_query(F.data == "feed:profile:me")
async def own_profile(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await state.clear()
    try:
        profile = await api_client.own_feed_profile(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            display_name=callback.from_user.full_name,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if callback.message:
        await _send_profile_page(
            callback.message,
            api_client,
            user_id=callback.from_user.id,
            public_slug=profile.public_slug,
            offset=0,
            header=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("feed:profile:"))
async def author_profile(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    slug = (callback.data or "").split(":", 2)[2]
    if slug == "me":
        await callback.answer()
        return
    if callback.message:
        await _send_profile_page(
            callback.message,
            api_client,
            user_id=callback.from_user.id,
            public_slug=slug,
            offset=0,
            header=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("feed:pp:"))
async def profile_page(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    try:
        offset = max(0, int(parts[3]))
    except ValueError:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    if callback.message:
        await _send_profile_page(
            callback.message,
            api_client,
            user_id=callback.from_user.id,
            public_slug=parts[2],
            offset=offset,
            header=False,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("feed:post:"))
async def open_post(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    publication_id = (callback.data or "").rpartition(":")[2]
    try:
        item = await api_client.feed_publication(
            user_id=callback.from_user.id,
            publication_id=publication_id,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if callback.message:
        await _send_publication(callback.message, item)
    await callback.answer()


@router.callback_query(F.data.startswith("feed:like:"))
async def like_publication(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    await _set_like(callback, api_client, liked=True)


@router.callback_query(F.data.startswith("feed:unlike:"))
async def unlike_publication(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    await _set_like(callback, api_client, liked=False)


@router.callback_query(F.data.startswith("feed:comments:"))
async def show_comments(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parsed = _publication_surface_callback(callback.data, "feed:comments:")
    if parsed is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    publication_id, surface = parsed
    try:
        comments = await api_client.feed_comments(
            user_id=callback.from_user.id,
            publication_id=publication_id,
            surface=surface,
            limit=30,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            _comments_text(comments),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Написать комментарий",
                            callback_data=(
                                f"feed:comment:{_uuid_hex(publication_id)}:"
                                f"{_surface_code(surface)}"
                            ),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="К публикации",
                            callback_data=f"feed:post:{_uuid_hex(publication_id)}",
                        )
                    ],
                ]
            ),
        )
    await callback.answer()


@router.callback_query(FeedStates.waiting_comment, F.data == "feed:comment:cancel")
async def cancel_comment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    if callback.message:
        await callback.message.answer("Комментарий не отправлен.")


@router.callback_query(F.data.startswith("feed:comment:"))
async def begin_comment(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _publication_surface_callback(callback.data, "feed:comment:")
    if parsed is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    publication_id, surface = parsed
    await state.set_state(FeedStates.waiting_comment)
    await state.update_data(feed_publication_id=publication_id, feed_surface=surface)
    if callback.message:
        await callback.message.answer(
            "Напишите комментарий одним сообщением (до 300 символов).",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data="feed:comment:cancel")]
                ]
            ),
        )
    await callback.answer()


@router.message(FeedStates.waiting_comment, F.text)
async def receive_comment(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    data = await state.get_data()
    publication_id = data.get("feed_publication_id")
    surface = data.get("feed_surface")
    if not isinstance(publication_id, str) or surface not in {"feed", "profile"}:
        await state.clear()
        await message.answer("Черновик комментария устарел. Откройте публикацию снова.")
        return
    try:
        await api_client.add_feed_comment(
            user_id=_message_user_id(message),
            publication_id=publication_id,
            surface=surface,
            text=(message.text or "").strip(),
        )
    except FoxGenApiError as exc:
        await message.answer(exc.message)
        return
    await state.clear()
    await message.answer(
        "Комментарий опубликован.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="К публикации",
                        callback_data=f"feed:post:{_uuid_hex(publication_id)}",
                    )
                ]
            ]
        ),
    )


@router.message(FeedStates.waiting_comment)
async def invalid_comment(message: Message) -> None:
    await message.answer("Для комментария нужен текст до 300 символов.")


@router.callback_query(F.data.startswith("feed:share:"))
async def share_publication(
    callback: CallbackQuery,
    bot: Bot,
    api_client: FoxGenApiClient,
) -> None:
    parsed = _publication_surface_callback(callback.data, "feed:share:")
    if parsed is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    publication_id, surface = parsed
    try:
        start_param = await api_client.share_feed_publication(
            user_id=callback.from_user.id,
            publication_id=publication_id,
            surface=surface,
        )
        deep_link = await _telegram_deep_link(bot, start_param)
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            f"Ссылка на публикацию:\n<code>{escape(deep_link)}</code>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Поделиться",
                            url="https://t.me/share/url?url=" + quote(deep_link, safe=""),
                        )
                    ]
                ]
            ),
        )
    await callback.answer("Ссылка готова")


@router.callback_query(F.data.startswith("feed:remix:"))
async def remix_publication(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    await _start_remix(
        state=state,
        api_client=api_client,
        user_id=callback.from_user.id,
        publication_id=(callback.data or "").rpartition(":")[2],
        callback=callback,
    )


@router.callback_query(F.data.startswith("feed:publish:"))
async def publish_generation(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[3] not in {"f", "p"}:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    scope = "feed" if parts[3] == "f" else "profile"
    try:
        item = await api_client.publish(
            user_id=callback.from_user.id,
            generation_id=str(UUID(parts[2])),
            scope=scope,
            prompt_visible=True,
        )
    except ValueError:
        await callback.answer("Некорректный ID генерации.", show_alert=True)
        return
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await callback.answer(
        "Опубликовано в ленте." if scope == "feed" else "Добавлено в профиль.",
        show_alert=True,
    )
    if callback.message:
        await _send_publication(callback.message, item)


@router.callback_query(F.data.startswith("feed:unpub:"))
async def unpublish_publication(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    publication_id = (callback.data or "").rpartition(":")[2]
    try:
        await api_client.unpublish(
            user_id=callback.from_user.id,
            publication_id=publication_id,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await callback.answer("Публикация снята.", show_alert=True)
    if callback.message:
        await callback.message.answer("Публикация больше не видна другим пользователям.")


@router.message(CommandStart(deep_link=True))
async def deep_link_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    target = parse_start_param(command.args)
    if target is None:
        await state.clear()
        await message.answer("Главное меню", reply_markup=main_menu())
        return
    user_id = _message_user_id(message)
    await state.clear()
    try:
        if target.kind == DeepLinkKind.POST and target.publication_id is not None:
            item = await api_client.feed_publication(
                user_id=user_id,
                publication_id=str(target.publication_id),
            )
            await _send_publication(message, item)
        elif target.kind == DeepLinkKind.PROFILE and target.profile_slug is not None:
            await _send_profile_page(
                message,
                api_client,
                user_id=user_id,
                public_slug=target.profile_slug,
                offset=0,
                header=True,
            )
        elif target.kind == DeepLinkKind.REMIX and target.publication_id is not None:
            await _start_remix(
                state=state,
                api_client=api_client,
                user_id=user_id,
                publication_id=str(target.publication_id),
                message=message,
            )
    except FoxGenApiError as exc:
        await message.answer(exc.message, reply_markup=main_menu())


async def _send_feed_page(
    message: Message,
    api_client: FoxGenApiClient,
    *,
    user_id: int,
    source: str,
    offset: int,
) -> None:
    try:
        items = await api_client.feed(user_id=user_id, source=source, limit=1, offset=offset)
    except FoxGenApiError as exc:
        await message.answer(exc.message, reply_markup=_feed_root_keyboard())
        return
    if not items:
        await message.answer("В этом разделе пока нет публикаций.", reply_markup=_feed_root_keyboard())
        return
    code = _source_code(source)
    await _send_publication(
        message,
        items[0],
        next_callback=f"feed:page:{code}:{offset + 1}",
        previous_callback=f"feed:page:{code}:{offset - 1}" if offset > 0 else None,
        title=_SOURCE_TITLES.get(source, "Лента"),
    )


async def _send_profile_page(
    message: Message,
    api_client: FoxGenApiClient,
    *,
    user_id: int,
    public_slug: str,
    offset: int,
    header: bool,
) -> None:
    try:
        page = await api_client.feed_profile(
            user_id=user_id,
            public_slug=public_slug,
            limit=1,
            offset=offset,
        )
    except FoxGenApiError as exc:
        await message.answer(exc.message, reply_markup=_feed_root_keyboard())
        return
    if header:
        username = f"@{page.profile.username}" if page.profile.username else ""
        bio = f"\n{escape(page.profile.bio)}" if page.profile.bio else ""
        await message.answer(
            f"<b>{escape(page.profile.display_name)}</b> {escape(username)}{bio}\n"
            f"Публичный код: <code>{escape(page.profile.public_slug)}</code>"
        )
    if not page.items:
        await message.answer("В профиле пока нет опубликованных работ.", reply_markup=_feed_root_keyboard())
        return
    await _send_publication(
        message,
        page.items[0],
        next_callback=f"feed:pp:{page.profile.public_slug}:{offset + 1}",
        previous_callback=(
            f"feed:pp:{page.profile.public_slug}:{offset - 1}" if offset > 0 else None
        ),
        title="Профиль",
    )


async def _send_publication(
    message: Message,
    publication: FeedPublicationView,
    *,
    next_callback: str | None = None,
    previous_callback: str | None = None,
    title: str | None = None,
) -> None:
    caption = _publication_caption(publication, title=title)
    keyboard = _publication_keyboard(
        publication,
        next_callback=next_callback,
        previous_callback=previous_callback,
    )
    if publication.media_urls:
        media_url = publication.media_urls[0]
        if publication.media_kind == "video":
            await message.answer_video(video=media_url, caption=caption, reply_markup=keyboard)
            return
        if publication.media_kind == "image":
            await message.answer_photo(photo=media_url, caption=caption, reply_markup=keyboard)
            return
    await message.answer(caption, reply_markup=keyboard)


async def _set_like(
    callback: CallbackQuery,
    api_client: FoxGenApiClient,
    *,
    liked: bool,
) -> None:
    publication_id = (callback.data or "").rpartition(":")[2]
    try:
        item = await api_client.set_feed_like(
            user_id=callback.from_user.id,
            publication_id=publication_id,
            liked=liked,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _refresh_card(callback, item)
    await callback.answer("Лайк сохранён" if liked else "Лайк снят")


async def _refresh_card(callback: CallbackQuery, item: FeedPublicationView) -> None:
    if callback.message is None:
        return
    caption = _publication_caption(item)
    keyboard = _publication_keyboard(item)
    try:
        if callback.message.photo or callback.message.video or callback.message.document:
            await callback.message.edit_caption(caption=caption, reply_markup=keyboard)
        else:
            await callback.message.edit_text(caption, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def _start_remix(
    *,
    state: FSMContext,
    api_client: FoxGenApiClient,
    user_id: int,
    publication_id: str,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
) -> None:
    try:
        source = await api_client.remix_source(user_id=user_id, publication_id=publication_id)
    except FoxGenApiError as exc:
        await _remix_error(exc.message, callback=callback, message=message)
        return

    if source.media_kind == "image":
        mode = GenerationMode.IMAGE_EDIT
        product = Product.IMAGE
    elif source.media_kind == "video":
        mode = GenerationMode.VIDEO_REFERENCE
        product = Product.VIDEO
    else:
        await _remix_error(
            "Remix для этого типа медиа пока не поддерживается.",
            callback=callback,
            message=message,
        )
        return

    if not source.reference_storage_keys:
        await _remix_error(
            "Исходный файл remix недоступен.",
            callback=callback,
            message=message,
        )
        return

    media = [
        {"kind": source.media_kind, "storage_key": key}
        for key in source.reference_storage_keys[:6]
    ]
    await state.clear()
    await state.update_data(
        entrypoint="feed_remix",
        source_publication_id=source.id,
        source_media_kind=source.media_kind,
        product=product.value,
        mode=mode.value,
        idempotency_key=f"generation:{user_id}:{uuid4().hex}",
        media=media,
        can_submit=False,
    )
    await state.set_state(GenerationStates.choosing_model)
    text = (
        "<b>Remix публикации</b>\n\n"
        "Исходный результат закреплён как референс. Выберите модель и опишите свой вариант. "
        "Производную работу можно опубликовать в профиль, но не в общую ленту; "
        "её prompt не будет раскрыт в публичной карточке."
    )
    if callback is not None:
        if callback.message:
            await callback.message.answer(text, reply_markup=model_keyboard(mode))
        await callback.answer()
    elif message is not None:
        await message.answer(text, reply_markup=model_keyboard(mode))


async def _remix_error(
    text: str,
    *,
    callback: CallbackQuery | None,
    message: Message | None,
) -> None:
    if callback is not None:
        await callback.answer(text, show_alert=True)
    elif message is not None:
        await message.answer(text)


def _publication_caption(publication: FeedPublicationView, *, title: str | None = None) -> str:
    lines: list[str] = []
    if title:
        lines.append(f"<b>{escape(title)}</b>")
    lines.append(f"<b>{escape(publication.author_display_name)}</b>")
    lines.append(f"Модель: {escape(publication.model_slug)}")
    if publication.is_derivative:
        lines.append("↻ Remix / производная работа")
    if publication.prompt is not None:
        lines.append(f"\n{escape(publication.prompt)}")
    lines.append(
        f"\n♡ {publication.likes_count}   💬 {publication.comments_count}   "
        f"↗ {publication.shares_count}   ↻ {publication.remixes_count}"
    )
    return "\n".join(lines)


def _publication_keyboard(
    publication: FeedPublicationView,
    *,
    next_callback: str | None = None,
    previous_callback: str | None = None,
) -> InlineKeyboardMarkup:
    publication_hex = _uuid_hex(publication.id)
    surface_code = _surface_code(publication.scope)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="♥ Убрать лайк" if publication.viewer_liked else "♡ Лайк",
                callback_data=(
                    f"feed:unlike:{publication_hex}"
                    if publication.viewer_liked
                    else f"feed:like:{publication_hex}"
                ),
            ),
            InlineKeyboardButton(
                text=f"Комментарии {publication.comments_count}",
                callback_data=f"feed:comments:{publication_hex}:{surface_code}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Поделиться",
                callback_data=f"feed:share:{publication_hex}:{surface_code}",
            ),
            InlineKeyboardButton(text="Remix", callback_data=f"feed:remix:{publication_hex}"),
        ],
        [
            InlineKeyboardButton(
                text="Профиль автора",
                callback_data=f"feed:profile:{publication.author_slug}",
            )
        ],
    ]
    if publication.is_mine:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Снять публикацию",
                    callback_data=f"feed:unpub:{publication_hex}",
                )
            ]
        )
    navigation: list[InlineKeyboardButton] = []
    if previous_callback:
        navigation.append(InlineKeyboardButton(text="←", callback_data=previous_callback))
    if next_callback:
        navigation.append(InlineKeyboardButton(text="→", callback_data=next_callback))
    if navigation:
        rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton(text="Лента", callback_data="feed:open"),
            InlineKeyboardButton(text="Мой профиль", callback_data="feed:profile:me"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _feed_root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Новые", callback_data="feed:src:r"),
                InlineKeyboardButton(text="Топ дня", callback_data="feed:src:d"),
                InlineKeyboardButton(text="Топ", callback_data="feed:src:t"),
            ],
            [InlineKeyboardButton(text="Мой профиль", callback_data="feed:profile:me")],
            [InlineKeyboardButton(text="Главное меню", callback_data="nav:menu")],
        ]
    )


def _comments_text(comments: tuple[FeedCommentView, ...]) -> str:
    if not comments:
        return "<b>Комментарии</b>\n\nПока никто не написал."
    lines = ["<b>Комментарии</b>"]
    for item in comments:
        lines.append(f"\n<b>{escape(item.author_display_name)}</b>\n{escape(item.text)}")
    return "\n".join(lines)


def _publication_surface_callback(
    value: str | None,
    prefix: str,
) -> tuple[str, str] | None:
    raw = value or ""
    if not raw.startswith(prefix):
        return None
    publication_raw, separator, surface_code = raw[len(prefix) :].rpartition(":")
    if not separator or surface_code not in {"f", "p"}:
        return None
    try:
        publication_id = str(UUID(publication_raw))
    except ValueError:
        return None
    return publication_id, "feed" if surface_code == "f" else "profile"


def _surface_code(surface: str) -> str:
    return "f" if surface == "feed" else "p"


def _source_code(source: str) -> str:
    for code, value in _SOURCE_CODES.items():
        if value == source:
            return code
    return "r"


def _uuid_hex(value: str) -> str:
    try:
        return UUID(value).hex
    except ValueError:
        return value.replace("-", "")


async def _telegram_deep_link(bot: Bot, start_param: str) -> str:
    me = await bot.get_me()
    if not me.username:
        raise FoxGenApiError("У бота не настроено публичное имя.", status_code=503)
    return f"https://t.me/{me.username}?start={start_param}"


def _message_user_id(message: Message) -> int:
    return message.from_user.id if message.from_user is not None else 0
