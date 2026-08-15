from __future__ import annotations

import re
from html import escape
from urllib.parse import quote
from uuid import UUID, uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError
from foxgen.bot.callbacks import safe_edit_callback_message
from foxgen.bot.catalog import GenerationMode, product_for_mode
from foxgen.bot.keyboards import main_menu, model_keyboard
from foxgen.bot.states import FeedStates, GenerationStates

router = Router(name="foxgen-feed")
_PROFILE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,55}$")
_FEED_SORTS = {"recent", "top_day", "top"}


def parse_start_payload(value: str | None) -> tuple[str, str] | None:
    raw = (value or "").strip()
    if raw.startswith("post_"):
        identifier = raw.removeprefix("post_")
        try:
            UUID(identifier)
        except ValueError:
            return None
        return "post", identifier
    if raw.startswith("remix_"):
        identifier = raw.removeprefix("remix_")
        try:
            UUID(identifier)
        except ValueError:
            return None
        return "remix", identifier
    if raw.startswith("profile_"):
        slug = raw.removeprefix("profile_").lower()
        if not _PROFILE_SLUG_RE.fullmatch(slug):
            return None
        return "profile", slug
    return None


def telegram_deep_link(bot_username: str, payload: str) -> str:
    username = bot_username.strip().lstrip("@")
    if not username:
        raise ValueError("bot username is required")
    if len(payload) > 64:
        raise ValueError("Telegram start payload exceeds 64 characters")
    return f"https://t.me/{username}?start={quote(payload, safe='_-')}"


async def handle_start_payload(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
    payload: str | None,
) -> bool:
    parsed = parse_start_payload(payload)
    if parsed is None:
        return False
    kind, value = parsed
    try:
        if kind == "post":
            item = await api_client.publication(
                user_id=message.from_user.id if message.from_user else 0,
                publication_id=value,
            )
            await _answer_publication(message, api_client, item)
            return True
        if kind == "profile":
            await state.update_data(feed_profile_slug=value)
            await _answer_profile(message, api_client, value)
            return True
        await _begin_remix_message(message, state, api_client, value)
        return True
    except FoxGenApiError as exc:
        await message.answer(
            f"⚠️ {escape(exc.message)}",
            reply_markup=main_menu(),
        )
        return True


@router.callback_query(F.data == "feed:open")
async def open_feed(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    await _show_feed_page(callback, api_client, sort="recent", offset=0)


@router.callback_query(F.data.startswith("feed:page:"))
async def feed_page(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[2] not in _FEED_SORTS:
        await callback.answer("Некорректная страница ленты.", show_alert=True)
        return
    try:
        offset = max(int(parts[3]), 0)
    except ValueError:
        await callback.answer("Некорректная страница ленты.", show_alert=True)
        return
    await _show_feed_page(callback, api_client, sort=parts[2], offset=offset)


@router.callback_query(F.data == "feed:profile:me")
async def own_profile(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    try:
        profile = await api_client.own_profile(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await state.update_data(feed_profile_slug=str(profile.get("slug") or ""))
    await safe_edit_callback_message(
        callback,
        _profile_text(profile),
        _profile_keyboard(str(profile.get("slug") or ""), own=True),
    )


@router.callback_query(F.data.startswith("feed:p:"))
async def public_profile(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    slug = (callback.data or "").removeprefix("feed:p:").strip().lower()
    if not _PROFILE_SLUG_RE.fullmatch(slug):
        await callback.answer("Некорректный профиль.", show_alert=True)
        return
    try:
        profile = await api_client.profile(user_id=callback.from_user.id, slug=slug)
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await state.update_data(feed_profile_slug=slug)
    await safe_edit_callback_message(
        callback,
        _profile_text(profile),
        _profile_keyboard(slug, own=False),
    )


@router.callback_query(F.data.startswith("feed:profile:page:"))
async def profile_publication_page(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    try:
        offset = max(int((callback.data or "").rsplit(":", 1)[1]), 0)
    except (IndexError, ValueError):
        await callback.answer("Некорректная страница профиля.", show_alert=True)
        return
    data = await state.get_data()
    slug = str(data.get("feed_profile_slug") or "")
    if not _PROFILE_SLUG_RE.fullmatch(slug):
        await callback.answer("Откройте профиль заново.", show_alert=True)
        return
    try:
        payload = await api_client.profile_publications(
            user_id=callback.from_user.id,
            slug=slug,
            limit=1,
            offset=offset,
        )
        item = _first_item(payload)
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if item is None:
        await callback.answer("В профиле больше нет публикаций.", show_alert=True)
        return
    await _edit_publication(
        callback,
        api_client,
        item,
        navigation=("profile", offset),
    )


@router.callback_query(F.data == "feed:mine")
async def own_publications(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    await _show_own_publication(callback, api_client, offset=0)


@router.callback_query(F.data.startswith("feed:mine:"))
async def own_publication_page(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    try:
        offset = max(int((callback.data or "").rsplit(":", 1)[1]), 0)
    except (IndexError, ValueError):
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    await _show_own_publication(callback, api_client, offset=offset)


@router.callback_query(F.data.startswith("feed:l:"))
async def set_like(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[3] not in {"0", "1"}:
        await callback.answer("Некорректная реакция.", show_alert=True)
        return
    publication_id = parts[2]
    try:
        UUID(publication_id)
        result = await api_client.set_like(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            publication_id=publication_id,
            liked=parts[3] == "1",
        )
    except (ValueError, FoxGenApiError) as exc:
        message = exc.message if isinstance(exc, FoxGenApiError) else "Некорректная публикация."
        await callback.answer(message, show_alert=True)
        return
    await callback.answer(
        f"Нравится: {int(result.get('likes_count') or 0)}",
    )
    try:
        item = await api_client.publication(
            user_id=callback.from_user.id,
            publication_id=publication_id,
        )
    except FoxGenApiError:
        return
    await _edit_publication(callback, api_client, item, answer_callback=False)


@router.callback_query(F.data.startswith("feed:c:"))
async def show_comments(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[2] not in {"f", "p"}:
        await callback.answer("Некорректный раздел комментариев.", show_alert=True)
        return
    publication_id = parts[3]
    surface = "feed" if parts[2] == "f" else "profile"
    try:
        payload = await api_client.comments(
            user_id=callback.from_user.id,
            publication_id=publication_id,
            surface=surface,
            limit=20,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    items = payload.get("items")
    comments = items if isinstance(items, list) else []
    lines = ["<b>Комментарии</b>"]
    for raw in comments[-10:]:
        if not isinstance(raw, dict):
            continue
        author = raw.get("author")
        author_name = "Пользователь"
        if isinstance(author, dict):
            author_name = str(author.get("display_name") or author.get("slug") or author_name)
        lines.append(f"\n<b>{escape(author_name)}</b>: {escape(str(raw.get('body') or ''))}")
    if not comments:
        lines.append("\nПока комментариев нет.")
    await safe_edit_callback_message(
        callback,
        "".join(lines),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✍️ Написать",
                        callback_data=f"feed:ca:{parts[2]}:{publication_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ К публикации", callback_data=f"feed:post:{publication_id}"
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data.startswith("feed:ca:"))
async def begin_comment(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[2] not in {"f", "p"}:
        await callback.answer("Некорректная публикация.", show_alert=True)
        return
    try:
        UUID(parts[3])
    except ValueError:
        await callback.answer("Некорректная публикация.", show_alert=True)
        return
    await state.update_data(
        comment_publication_id=parts[3],
        comment_surface="feed" if parts[2] == "f" else "profile",
    )
    await state.set_state(FeedStates.waiting_comment)
    await safe_edit_callback_message(
        callback,
        "Напишите комментарий одним сообщением (до 1000 символов). /start отменит ввод.",
    )


@router.message(FeedStates.waiting_comment, F.text)
async def save_comment(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    body = (message.text or "").strip()
    if not 1 <= len(body) <= 1000:
        await message.answer("Комментарий должен содержать от 1 до 1000 символов.")
        return
    data = await state.get_data()
    publication_id = str(data.get("comment_publication_id") or "")
    surface = str(data.get("comment_surface") or "")
    try:
        await api_client.add_comment(
            user_id=message.from_user.id if message.from_user else 0,
            username=message.from_user.username if message.from_user else None,
            publication_id=publication_id,
            surface=surface,
            body=body,
        )
    except FoxGenApiError as exc:
        await message.answer(f"⚠️ {escape(exc.message)}")
        return
    await state.clear()
    await message.answer(
        "✅ Комментарий добавлен.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="К публикации", callback_data=f"feed:post:{publication_id}"
                    )
                ],
                [InlineKeyboardButton(text="Лента", callback_data="feed:open")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("feed:post:"))
async def open_publication(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    publication_id = (callback.data or "").removeprefix("feed:post:")
    try:
        item = await api_client.publication(
            user_id=callback.from_user.id,
            publication_id=publication_id,
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await _edit_publication(callback, api_client, item)


@router.callback_query(F.data.startswith("feed:r:"))
async def begin_remix(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    publication_id = (callback.data or "").removeprefix("feed:r:")
    try:
        await _begin_remix_callback(callback, state, api_client, publication_id)
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)


@router.callback_query(F.data.startswith("feed:publish:"))
async def publish_generation(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[2] not in {"feed", "profile"}:
        await callback.answer("Некорректная публикация.", show_alert=True)
        return
    try:
        item = await api_client.publish_generation(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            generation_id=parts[3],
            scope=parts[2],
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await callback.answer("Опубликовано ✅", show_alert=True)
    await _edit_publication(callback, api_client, item, answer_callback=False)


@router.callback_query(F.data.startswith("feed:unpublish:"))
async def unpublish_generation(callback: CallbackQuery, api_client: FoxGenApiClient) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[2] not in {"feed", "profile"}:
        await callback.answer("Некорректная публикация.", show_alert=True)
        return
    try:
        await api_client.unpublish_generation(
            user_id=callback.from_user.id,
            generation_id=parts[3],
            scope=parts[2],
        )
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await callback.answer("Публикация скрыта.", show_alert=True)
    await _show_own_publication(callback, api_client, offset=0, answer_callback=False)


@router.callback_query(F.data == "feed:profile:edit")
async def begin_profile_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedStates.editing_profile_slug)
    await safe_edit_callback_message(
        callback,
        (
            "Введите новый короткий адрес профиля: 3–56 символов a-z, 0-9, _ или -. "
            "/start отменит редактирование."
        ),
    )


@router.message(FeedStates.editing_profile_slug, F.text)
async def profile_slug(message: Message, state: FSMContext) -> None:
    slug = (message.text or "").strip().lower()
    if not _PROFILE_SLUG_RE.fullmatch(slug):
        await message.answer("Нужно 3–56 символов: a-z, 0-9, _ или -.")
        return
    await state.update_data(profile_edit_slug=slug)
    await state.set_state(FeedStates.editing_profile_name)
    await message.answer(
        "Введите отображаемое имя до 128 символов или отправьте - чтобы скрыть его."
    )


@router.message(FeedStates.editing_profile_name, F.text)
async def profile_name(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if len(value) > 128:
        await message.answer("Имя длиннее 128 символов.")
        return
    await state.update_data(profile_edit_name=None if value == "-" else value)
    await state.set_state(FeedStates.editing_profile_bio)
    await message.answer(
        "Введите описание профиля до 500 символов или отправьте - чтобы оставить пустым."
    )


@router.message(FeedStates.editing_profile_bio, F.text)
async def profile_bio(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
) -> None:
    value = (message.text or "").strip()
    if len(value) > 500:
        await message.answer("Описание длиннее 500 символов.")
        return
    data = await state.get_data()
    try:
        profile = await api_client.update_profile(
            user_id=message.from_user.id if message.from_user else 0,
            username=message.from_user.username if message.from_user else None,
            slug=str(data.get("profile_edit_slug") or ""),
            display_name=(
                str(data.get("profile_edit_name"))
                if data.get("profile_edit_name") is not None
                else None
            ),
            bio=None if value == "-" else value,
        )
    except FoxGenApiError as exc:
        await message.answer(f"⚠️ {escape(exc.message)}")
        return
    await state.clear()
    await message.answer(
        "✅ Профиль обновлён.\n\n" + _profile_text(profile),
        reply_markup=_profile_keyboard(str(profile.get("slug") or ""), own=True),
    )


async def _show_feed_page(
    callback: CallbackQuery,
    api_client: FoxGenApiClient,
    *,
    sort: str,
    offset: int,
) -> None:
    try:
        payload = await api_client.feed(
            user_id=callback.from_user.id,
            sort=sort,
            limit=1,
            offset=offset,
        )
        item = _first_item(payload)
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if item is None:
        text = "В ленте пока нет публикаций." if offset == 0 else "Публикации закончились."
        await safe_edit_callback_message(
            callback,
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")]]
            ),
        )
        return
    await _edit_publication(
        callback,
        api_client,
        item,
        navigation=(sort, offset),
    )


async def _show_own_publication(
    callback: CallbackQuery,
    api_client: FoxGenApiClient,
    *,
    offset: int,
    answer_callback: bool = True,
) -> None:
    try:
        payload = await api_client.own_publications(
            user_id=callback.from_user.id,
            limit=1,
            offset=offset,
        )
        item = _first_item(payload)
    except FoxGenApiError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    if item is None:
        await safe_edit_callback_message(
            callback,
            "У вас пока нет публикаций.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Лента", callback_data="feed:open")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
                ]
            ),
            answer_callback=answer_callback,
        )
        return
    await _edit_publication(
        callback,
        api_client,
        item,
        navigation=("mine", offset),
        own_management=True,
        answer_callback=answer_callback,
    )


async def _edit_publication(
    callback: CallbackQuery,
    api_client: FoxGenApiClient,
    item: dict[str, object],
    *,
    navigation: tuple[str, int] | None = None,
    own_management: bool = False,
    answer_callback: bool = True,
) -> None:
    media_url = await _first_media_url(api_client, callback.from_user.id, item)
    await safe_edit_callback_message(
        callback,
        _publication_text(item, media_url),
        _publication_keyboard(
            item,
            navigation=navigation,
            own_management=own_management,
        ),
        answer_callback=answer_callback,
    )


async def _answer_publication(
    message: Message,
    api_client: FoxGenApiClient,
    item: dict[str, object],
) -> None:
    user_id = message.from_user.id if message.from_user else 0
    media_url = await _first_media_url(api_client, user_id, item)
    await message.answer(
        _publication_text(item, media_url),
        reply_markup=_publication_keyboard(item),
    )


async def _answer_profile(message: Message, api_client: FoxGenApiClient, slug: str) -> None:
    user_id = message.from_user.id if message.from_user else 0
    profile = await api_client.profile(user_id=user_id, slug=slug)
    await message.answer(
        _profile_text(profile),
        reply_markup=_profile_keyboard(slug, own=False),
    )


async def _first_media_url(
    api_client: FoxGenApiClient,
    user_id: int,
    item: dict[str, object],
) -> str | None:
    publication_id = str(item.get("id") or "")
    if not publication_id or not bool(item.get("active", True)):
        return None
    try:
        payload = await api_client.publication_media(
            user_id=user_id,
            publication_id=publication_id,
        )
    except FoxGenApiError:
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    url = items[0].get("url")
    return str(url) if isinstance(url, str) and url.startswith("https://") else None


async def _begin_remix_message(
    message: Message,
    state: FSMContext,
    api_client: FoxGenApiClient,
    publication_id: str,
) -> None:
    source = await api_client.remix_source(
        user_id=message.from_user.id if message.from_user else 0,
        publication_id=publication_id,
    )
    mode = _remix_mode(str(source.get("media_kind") or ""))
    await _prepare_remix_state(state, source, mode)
    await message.answer(
        (
            "<b>Ремикс</b>\n\nИсточник сохранён. Выберите модель — промпт исходной "
            "публикации уже подставлен и его можно изменить перед запуском."
        ),
        reply_markup=model_keyboard(mode),
    )


async def _begin_remix_callback(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: FoxGenApiClient,
    publication_id: str,
) -> None:
    source = await api_client.remix_source(
        user_id=callback.from_user.id,
        publication_id=publication_id,
    )
    mode = _remix_mode(str(source.get("media_kind") or ""))
    await _prepare_remix_state(state, source, mode)
    await safe_edit_callback_message(
        callback,
        "<b>Ремикс</b>\n\nИсточник сохранён. Выберите модель — исходный промпт уже подставлен.",
        model_keyboard(mode),
    )


async def _prepare_remix_state(
    state: FSMContext,
    source: dict[str, object],
    mode: GenerationMode,
) -> None:
    publication_id = str(source.get("publication_id") or "")
    prompt = str(source.get("prompt") or "").strip()
    if not publication_id or len(prompt) < 3:
        raise FoxGenApiError("Источник ремикса повреждён.", status_code=502)
    await state.clear()
    await state.update_data(
        entrypoint="remix",
        source_publication_id=publication_id,
        source_prompt=prompt,
        prompt=prompt,
        mode=mode.value,
        product=product_for_mode(mode).value,
        media=[],
        idempotency_key=f"generation:remix:{publication_id}:{uuid4().hex}",
        can_submit=False,
    )
    await state.set_state(GenerationStates.choosing_model)


def _remix_mode(media_kind: str) -> GenerationMode:
    normalized = media_kind.lower().split(".")[-1]
    if normalized == "image":
        return GenerationMode.IMAGE_EDIT
    if normalized == "video":
        return GenerationMode.VIDEO_REFERENCE
    raise FoxGenApiError("Для этого типа результата ремикс пока недоступен.", status_code=422)


def _first_item(payload: dict[str, object]) -> dict[str, object] | None:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    item = items[0]
    return item if isinstance(item, dict) else None


def _profile_text(profile: dict[str, object]) -> str:
    slug = escape(str(profile.get("slug") or ""))
    name = escape(str(profile.get("display_name") or slug))
    bio = escape(str(profile.get("bio") or "Пока без описания."))
    return f"<b>{name}</b>\n@{slug}\n\n{bio}"


def _profile_keyboard(slug: str, *, own: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🖼 Публикации", callback_data="feed:profile:page:0")],
    ]
    if own:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="✏️ Изменить профиль", callback_data="feed:profile:edit"
                    )
                ],
                [InlineKeyboardButton(text="⚙️ Мои публикации", callback_data="feed:mine")],
            ]
        )
    elif _PROFILE_SLUG_RE.fullmatch(slug):
        rows.append([InlineKeyboardButton(text="🔗 Профиль", callback_data=f"feed:p:{slug}")])
    rows.extend(
        [
            [InlineKeyboardButton(text="🌐 Лента", callback_data="feed:open")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _publication_text(item: dict[str, object], media_url: str | None) -> str:
    author = item.get("author")
    author_name = "Пользователь"
    if isinstance(author, dict):
        author_name = str(author.get("display_name") or author.get("slug") or author_name)
    prompt = item.get("prompt")
    prompt_line = (
        f"\n\n<b>Промпт</b>\n{escape(str(prompt))}" if isinstance(prompt, str) and prompt else ""
    )
    media_line = (
        f'\n\n<a href="{escape(media_url, quote=True)}">Открыть результат</a>' if media_url else ""
    )
    return (
        f"<b>{escape(author_name)}</b> · {escape(str(item.get('model_slug') or 'model'))}\n"
        f"❤️ {int(item.get('likes_count') or 0)}"
        + f" · 💬 {int(item.get('comments_count') or 0)}"
        + f" · 🔁 {int(item.get('remix_count') or 0)}"
        f"{prompt_line}{media_line}"
    )


def _publication_keyboard(
    item: dict[str, object],
    *,
    navigation: tuple[str, int] | None = None,
    own_management: bool = False,
) -> InlineKeyboardMarkup:
    publication_id = str(item.get("id") or "")
    generation_id = str(item.get("generation_id") or "")
    scope = str(item.get("scope") or "feed")
    surface_code = "p" if scope == "profile" else "f"
    liked = bool(item.get("liked_by_viewer"))
    author = item.get("author")
    author_slug = str(author.get("slug") or "") if isinstance(author, dict) else ""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="💔 Убрать лайк" if liked else "❤️ Нравится",
                callback_data=f"feed:l:{publication_id}:{'0' if liked else '1'}",
            ),
            InlineKeyboardButton(
                text="💬 Комментарии",
                callback_data=f"feed:c:{surface_code}:{publication_id}",
            ),
        ]
    ]
    if bool(item.get("prompt_actions_allowed")):
        rows.append(
            [InlineKeyboardButton(text="🔁 Ремикс", callback_data=f"feed:r:{publication_id}")]
        )
    if _PROFILE_SLUG_RE.fullmatch(author_slug):
        rows.append([InlineKeyboardButton(text="👤 Автор", callback_data=f"feed:p:{author_slug}")])
    if own_management and generation_id:
        if bool(item.get("active", True)):
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🙈 Снять публикацию",
                        callback_data=f"feed:unpublish:{scope}:{generation_id}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="📣 Опубликовать снова",
                        callback_data=f"feed:publish:{scope}:{generation_id}",
                    )
                ]
            )
    if navigation is not None:
        mode, offset = navigation
        previous = max(offset - 1, 0)
        next_offset = offset + 1
        if mode in _FEED_SORTS:
            rows.append(
                [
                    InlineKeyboardButton(text="⬅️", callback_data=f"feed:page:{mode}:{previous}"),
                    InlineKeyboardButton(text="➡️", callback_data=f"feed:page:{mode}:{next_offset}"),
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton(text="Новые", callback_data="feed:page:recent:0"),
                    InlineKeyboardButton(text="Топ дня", callback_data="feed:page:top_day:0"),
                    InlineKeyboardButton(text="Топ", callback_data="feed:page:top:0"),
                ]
            )
        elif mode == "profile":
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⬅️",
                        callback_data=f"feed:profile:page:{previous}",
                    ),
                    InlineKeyboardButton(
                        text="➡️",
                        callback_data=f"feed:profile:page:{next_offset}",
                    ),
                ]
            )
        elif mode == "mine":
            rows.append(
                [
                    InlineKeyboardButton(text="⬅️", callback_data=f"feed:mine:{previous}"),
                    InlineKeyboardButton(text="➡️", callback_data=f"feed:mine:{next_offset}"),
                ]
            )
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
