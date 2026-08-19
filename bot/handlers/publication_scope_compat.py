from __future__ import annotations

import importlib.abc
import importlib.machinery
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import database, keyboards
from bot import db as db_backend

logger = logging.getLogger(__name__)
router = Router(name="publication_scope_compat")

_SCHEMA_READY_PATHS: set[str] = set()
_INSTALLED = False
_MINIAPP_HOOK_INSTALLED = False
_COMMON_PATCHED = False

_ORIGINAL_SHARE_TO_FEED = database.share_to_feed
_ORIGINAL_GENERATION_ROW_TO_CARD = database._generation_row_to_card
_ORIGINAL_IMAGE_RESULT_KEYBOARD = keyboards.get_image_result_keyboard
_ORIGINAL_VIDEO_RESULT_KEYBOARD = keyboards.get_video_result_keyboard


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        if hasattr(row, "keys") and key not in row.keys():  # noqa: SIM118 - Row membership checks values
            return default
        return row[key]
    except (AttributeError, IndexError, KeyError, TypeError):
        return getattr(row, key, default)


def _publication_scope_from_row(row: Any) -> str:
    if bool(_row_value(row, "is_public_feed", False)):
        return "feed"
    if bool(_row_value(row, "is_profile_visible", False)):
        return "profile"
    return "private"


def _with_publication_scope(card: dict[str, Any] | None, row: Any) -> dict[str, Any] | None:
    if not card:
        return card
    scope = _publication_scope_from_row(row)
    card["is_public_feed"] = scope == "feed"
    card["is_profile_visible"] = scope in {"feed", "profile"}
    card["publication_scope"] = scope
    card["feed_interactions_enabled"] = scope == "feed"
    return card


def _generation_row_to_card_scoped(*args, **kwargs):
    row = args[0] if args else kwargs.get("row")
    return _with_publication_scope(_ORIGINAL_GENERATION_ROW_TO_CARD(*args, **kwargs), row)


async def _ensure_publication_scope_schema() -> None:
    database_path = str(database.DATABASE_PATH)
    if database_path in _SCHEMA_READY_PATHS:
        return

    async with db_backend.connect(database.DATABASE_PATH, timeout=15) as db:
        migrations = (
            "ALTER TABLE generation_tasks ADD COLUMN is_profile_visible BOOLEAN DEFAULT FALSE",
            "ALTER TABLE generation_tasks ADD COLUMN profile_published_at TIMESTAMP",
        )
        for statement in migrations:
            try:
                await db.execute(statement)
            except db_backend.OperationalError:
                # The compatibility layer is loaded on every start. Existing columns are expected.
                logger.debug("Publication scope column already exists: %s", statement)

        await db.execute(
            """
            UPDATE generation_tasks
            SET is_profile_visible = 1,
                profile_published_at = COALESCE(profile_published_at, feed_published_at, created_at)
            WHERE is_public_feed = 1
              AND COALESCE(is_profile_visible, 0) = 0
            """
        )
        try:
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_generation_tasks_profile "
                "ON generation_tasks(is_profile_visible, user_id, profile_published_at DESC, created_at DESC)"
            )
        except db_backend.OperationalError:
            logger.debug("Could not create publication profile index", exc_info=True)
        await db.commit()

    _SCHEMA_READY_PATHS.add(database_path)


def _generation_identifier(identifier: int | str) -> tuple[str, Any]:
    value = str(identifier or "").strip()
    if value.isdigit():
        return "gt.id = ?", int(value)
    return "gt.task_id = ?", value


async def _fetch_generation_with_author(
    identifier: int | str,
    *,
    user_id: int | None = None,
    require_profile_visible: bool = False,
) -> Any:
    await _ensure_publication_scope_schema()
    clause, value = _generation_identifier(identifier)
    where = [clause]
    params: list[Any] = [value]
    if user_id is not None:
        where.append("gt.user_id = ?")
        params.append(user_id)
    if require_profile_visible:
        where.append("(COALESCE(gt.is_profile_visible, 0) = 1 OR gt.is_public_feed = 1)")

    async with db_backend.connect(database.DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT gt.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code,
                   u.photo_url AS author_photo_url,
                   (
                       SELECT COUNT(*)
                       FROM generation_tasks child
                       WHERE child.parent_generation_id = gt.id
                         AND child.status = 'completed'
                   ) AS remix_count,
                   (
                       SELECT COUNT(*)
                       FROM feed_comments fc
                       WHERE fc.generation_id = gt.id
                   ) AS comments_count
            FROM generation_tasks gt
            LEFT JOIN users u ON u.id = gt.user_id
            WHERE {' AND '.join(where)}
            LIMIT 1
            """,
            params,
        )
        return await cursor.fetchone()


async def get_publication_scope(identifier: int | str, user_id: int | None = None) -> str:
    row = await _fetch_generation_with_author(identifier, user_id=user_id)
    return _publication_scope_from_row(row)


async def _profile_card(
    identifier: int | str,
    *,
    viewer_user_id: int | None = None,
    require_visible: bool = True,
) -> dict[str, Any] | None:
    row = await _fetch_generation_with_author(
        identifier,
        require_profile_visible=require_visible,
    )
    if not row:
        return None
    card = database._generation_row_to_card(
        row,
        viewer_user_id=viewer_user_id,
        include_unavailable=True,
    )
    return _with_publication_scope(card, row)


async def get_user_profile_generations(
    user_id: int,
    limit: int = 120,
    offset: int = 0,
    *,
    include_unpublished_owned: bool = False,
    profile_visible_only: bool = True,
    include_unavailable: bool = False,
) -> list[dict[str, Any]]:
    await _ensure_publication_scope_schema()
    safe_limit = max(0, int(limit or 0))
    safe_offset = max(0, int(offset or 0))

    visibility_clause = "gt.is_public_feed = 1"
    if profile_visible_only:
        visibility_clause = "(COALESCE(gt.is_profile_visible, 0) = 1 OR gt.is_public_feed = 1)"
    if include_unpublished_owned:
        visibility_clause = "gt.source_feed_gen_id IS NULL"

    async with db_backend.connect(database.DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        query = f"""
            SELECT gt.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code,
                   u.photo_url AS author_photo_url,
                   (
                       SELECT COUNT(*)
                       FROM generation_tasks child
                       WHERE child.parent_generation_id = gt.id
                         AND child.status = 'completed'
                   ) AS remix_count,
                   (
                       SELECT COUNT(*)
                       FROM feed_comments fc
                       WHERE fc.generation_id = gt.id
                   ) AS comments_count
            FROM generation_tasks gt
            LEFT JOIN users u ON u.id = gt.user_id
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND {visibility_clause}
            ORDER BY COALESCE(
                gt.profile_published_at,
                gt.feed_published_at,
                gt.created_at
            ) DESC, gt.created_at DESC
            {"LIMIT ? OFFSET ?" if safe_limit else ""}
        """
        params: tuple[Any, ...] = (
            (user_id, safe_limit, safe_offset) if safe_limit else (user_id,)
        )
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    cards: list[dict[str, Any]] = []
    for row in rows:
        card = database._generation_row_to_card(
            row,
            viewer_user_id=user_id,
            include_unavailable=include_unavailable,
        )
        card = _with_publication_scope(card, row)
        if card:
            cards.append(card)
    return cards


async def share_to_feed_scoped(
    gen_id: int | str,
    user_id: int,
    *,
    prompt_visible: bool = False,
    references_visible: bool = False,
    blurred: bool | None = None,
    publication_scope: str = "feed",
    adult_content: bool = False,
) -> dict[str, Any] | None:
    await _ensure_publication_scope_schema()
    legacy_card = await _ORIGINAL_SHARE_TO_FEED(
        gen_id,
        user_id,
        prompt_visible=prompt_visible,
        references_visible=references_visible,
        blurred=blurred,
        publication_scope=publication_scope,
        adult_content=adult_content,
    )
    if not legacy_card:
        return legacy_card

    # The underlying database write still returns the pre-scope card shape.
    # Re-read the row after publication so every caller receives authoritative
    # profile/feed flags regardless of import order or compatibility wrappers.
    identifier = legacy_card.get("id") or gen_id
    scoped_card = await _profile_card(
        identifier,
        viewer_user_id=user_id,
        require_visible=True,
    )
    return scoped_card or legacy_card


async def share_to_profile(
    gen_id: int | str,
    user_id: int,
    *,
    prompt_visible: bool = False,
    references_visible: bool = False,
    blurred: bool | None = None,
) -> dict[str, Any] | None:
    await _ensure_publication_scope_schema()
    async with db_backend.connect(database.DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await database._fetch_generation_row(db, gen_id, user_id=user_id)
        if (
            not row
            or row["type"] not in database.FEED_PUBLIC_TYPES
            or row["status"] != "completed"
            or not row["result_url"]
            or row["source_feed_gen_id"] is not None
            or not database._feed_result_urls(row)
        ):
            return None

        result_urls = database._generation_result_urls(row)
        result_url = row["result_url"]
        result_urls_json = None
        if result_urls:
            from bot.services.feed_persist import persist_feed_result_urls

            persisted = await persist_feed_result_urls(result_urls)
            if persisted:
                import json

                result_url = persisted[0]
                result_urls_json = json.dumps(persisted, ensure_ascii=False)

        next_blurred = database.generation_feed_blurred(row) if blurred is None else bool(blurred)
        published_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(
            sep=" ", timespec="microseconds"
        )
        await db.execute(
            """
            UPDATE generation_tasks
            SET is_profile_visible = 1,
                is_public_feed = 0,
                profile_published_at = ?,
                feed_published_at = NULL,
                feed_prompt_visible = ?,
                feed_references_visible = ?,
                feed_blurred = ?,
                result_url = ?,
                result_urls = COALESCE(?, result_urls),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                published_at,
                int(bool(prompt_visible)),
                int(bool(references_visible)),
                int(next_blurred),
                result_url,
                result_urls_json,
                row["id"],
            ),
        )
        await db.commit()
        internal_id = row["id"]

    return await _profile_card(internal_id, viewer_user_id=user_id)


async def remove_from_feed_scoped(
    gen_id: int | str,
    user_id: int,
    *,
    allow_any_user: bool = False,
) -> bool:
    """Remove from discovery feed; owner keeps it in the profile, admin hides it fully."""
    await _ensure_publication_scope_schema()
    async with db_backend.connect(database.DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await database._fetch_generation_row(
            db,
            gen_id,
            user_id=None if allow_any_user else user_id,
        )
        if not row:
            return False

        if allow_any_user:
            await db.execute(
                """
                UPDATE generation_tasks
                SET is_public_feed = 0,
                    is_profile_visible = 0,
                    feed_published_at = NULL,
                    profile_published_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
        else:
            await db.execute(
                """
                UPDATE generation_tasks
                SET is_public_feed = 0,
                    is_profile_visible = 1,
                    feed_published_at = NULL,
                    profile_published_at = COALESCE(profile_published_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
        await db.commit()
        return True


async def remove_publication(gen_id: int | str, user_id: int) -> bool:
    await _ensure_publication_scope_schema()
    async with db_backend.connect(database.DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await database._fetch_generation_row(db, gen_id, user_id=user_id)
        if not row:
            return False
        await db.execute(
            """
            UPDATE generation_tasks
            SET is_public_feed = 0,
                is_profile_visible = 0,
                feed_published_at = NULL,
                profile_published_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )
        await db.commit()
        return True


def _replace_publication_button(
    markup: InlineKeyboardMarkup,
    task_id: str | None,
    *,
    scope: str,
) -> InlineKeyboardMarkup:
    if not task_id:
        return markup
    # Publication state is edited through one stable action.  Showing the
    # current scope as a second action made the result keyboard look as if it
    # could create another publication instead of updating the existing one.
    label = "📤 Опубликовать"

    rows: list[list[InlineKeyboardButton]] = []
    replaced = False
    for row in markup.inline_keyboard:
        next_row: list[InlineKeyboardButton] = []
        for button in row:
            callback_data = str(button.callback_data or "")
            if callback_data.startswith(("feedpub_", "feedrm_", "pubscope_")):
                if not replaced:
                    next_row.append(
                        InlineKeyboardButton(
                            text=label,
                            callback_data=f"pubscope_{task_id}",
                        )
                    )
                    replaced = True
                # Drop every later legacy or already-normalized publication
                # action. The result markup may pass through this adapter more
                # than once while a message is refreshed.
            else:
                next_row.append(button)
        if next_row:
            rows.append(next_row)

    if not replaced:
        rows.insert(
            1 if rows else 0,
            [InlineKeyboardButton(text=label, callback_data=f"pubscope_{task_id}")],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_image_result_keyboard_scoped(
    image_url: str,
    task_id: str | None = None,
    is_public_feed: bool = False,
    is_prompt_library: bool = False,
):
    markup = _ORIGINAL_IMAGE_RESULT_KEYBOARD(
        image_url,
        task_id=task_id,
        is_public_feed=is_public_feed,
        is_prompt_library=is_prompt_library,
    )
    return _replace_publication_button(
        markup,
        task_id,
        scope="feed" if is_public_feed else "private",
    )


def get_video_result_keyboard_scoped(
    video_url: str,
    user_credits: int = 0,
    task_id: str | None = None,
    model: str | None = None,
    is_public_feed: bool = False,
):
    markup = _ORIGINAL_VIDEO_RESULT_KEYBOARD(
        video_url,
        user_credits=user_credits,
        task_id=task_id,
        model=model,
        is_public_feed=is_public_feed,
    )
    return _replace_publication_button(
        markup,
        task_id,
        scope="feed" if is_public_feed else "private",
    )


async def _task_and_user(callback: types.CallbackQuery, task_id: str):
    user = await database.get_or_create_user(callback.from_user.id)
    task = await database.get_generation_task_payload(task_id, user_id=user.id)
    return user, task


def _task_result_markup(task: dict[str, Any], scope: str) -> InlineKeyboardMarkup:
    task_id = str(task.get("task_id") or "")
    is_public = scope == "feed"
    if str(task.get("type") or "") == "video":
        markup = get_video_result_keyboard_scoped(
            str(task.get("result_url") or ""),
            task_id=task_id,
            model=str(task.get("model") or ""),
            is_public_feed=is_public,
        )
    else:
        markup = get_image_result_keyboard_scoped(
            str(task.get("result_url") or ""),
            task_id=task_id,
            is_public_feed=is_public,
            is_prompt_library=bool(task.get("is_prompt_library")),
        )
    return _replace_publication_button(markup, task_id, scope=scope)


async def _refresh_result_markup(callback: types.CallbackQuery, task: dict[str, Any], scope: str) -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=_task_result_markup(task, scope))
    except (AttributeError, TelegramBadRequest, TypeError):
        logger.debug("Could not refresh publication result keyboard", exc_info=True)


def _invalidate_publication_caches() -> None:
    common_module = sys.modules.get("bot.handlers.common")
    if not common_module:
        return
    invalidator = getattr(common_module, "_invalidate_feed_and_profile_caches", None)
    if callable(invalidator):
        invalidator()


def _profile_blur_keyboard(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👁 Без blur",
                    callback_data=f"profileblur_0_{task_id}",
                ),
                InlineKeyboardButton(
                    text="🙈 С blur",
                    callback_data=f"profileblur_1_{task_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"pubscope_{task_id}",
                )
            ],
        ]
    )


def _feed_confirmation_components(
    task_id: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build the mandatory feed privacy confirmation with safe defaults."""
    from bot.handlers.generation import (
        _feed_publication_keyboard,
        _feed_publication_text,
    )

    return _feed_publication_text(), _feed_publication_keyboard(
        task_id,
        prompt_visible=False,
        references_visible=False,
        blurred=False,
    )


@router.callback_query(F.data.startswith("pubscope_"))
async def choose_publication_scope(callback: types.CallbackQuery):
    task_id = (callback.data or "").replace("pubscope_", "", 1)
    user, task = await _task_and_user(callback, task_id)
    if not task:
        await callback.answer("Генерация не найдена", show_alert=True)
        return
    scope = await get_publication_scope(task_id, user.id)

    rows: list[list[InlineKeyboardButton]] = []
    if scope != "feed":
        rows.append([InlineKeyboardButton(text="🌐 В общую ленту", callback_data=f"feedpub_{task_id}")])
    rows.append([InlineKeyboardButton(text="👤 Только в мой профиль", callback_data=f"profilepub_{task_id}")])
    if scope != "private":
        rows.append([InlineKeyboardButton(text="🗑 Убрать публикацию", callback_data=f"profilehide_{task_id}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"pubcancel_{task_id}")])

    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("feedpub_"))
async def publish_to_public_feed(callback: types.CallbackQuery):
    task_id = (callback.data or "").replace("feedpub_", "", 1)
    user, task = await _task_and_user(callback, task_id)
    if not task:
        await callback.answer("Генерация не найдена", show_alert=True)
        return
    text, markup = _feed_confirmation_components(task_id)
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=markup,
    )
    await callback.answer("Настройте видимость и подтвердите публикацию")


@router.callback_query(F.data.startswith("profilepub_"))
async def publish_only_to_profile(callback: types.CallbackQuery):
    task_id = (callback.data or "").replace("profilepub_", "", 1)
    user, task = await _task_and_user(callback, task_id)
    if not task:
        await callback.answer("Генерация не найдена", show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=_profile_blur_keyboard(task_id)
    )
    await callback.answer("Выберите, блюрить публикацию или нет")


@router.callback_query(F.data.startswith("profileblur_"))
async def publish_only_to_profile_with_blur(callback: types.CallbackQuery):
    payload = (callback.data or "").replace("profileblur_", "", 1)
    blur_value, separator, task_id = payload.partition("_")
    if not separator or blur_value not in {"0", "1"} or not task_id:
        await callback.answer("Некорректный выбор blur", show_alert=True)
        return
    user, task = await _task_and_user(callback, task_id)
    if not task:
        await callback.answer("Генерация не найдена", show_alert=True)
        return
    blurred = blur_value == "1"
    card = await share_to_profile(task_id, user.id, blurred=blurred)
    if not card:
        await callback.answer("Не удалось добавить в профиль", show_alert=True)
        return
    _invalidate_publication_caches()
    task["is_public_feed"] = False
    task["is_profile_visible"] = True
    await _refresh_result_markup(callback, task, "profile")
    from bot.handlers.generation import (
        _published_feed_bot_link,
        _published_feed_link,
        _published_feed_link_keyboard,
    )

    me = await callback.bot.get_me()
    publication_url = _published_feed_link(me.username, card)
    publication_bot_url = _published_feed_bot_link(me.username, card)
    await callback.message.answer(
        "✅ Работа добавлена в ваш профиль.\n\n"
        f"🔗 Ссылка на работу:\n{publication_url}",
        reply_markup=_published_feed_link_keyboard(
            publication_url,
            publication_bot_url,
        ),
        disable_web_page_preview=True,
    )
    await callback.answer(
        "Добавлено в профиль с blur — ссылка отправлена"
        if blurred
        else "Добавлено в профиль — ссылка отправлена"
    )


@router.callback_query(F.data.startswith("feedrm_"))
async def downgrade_feed_to_profile(callback: types.CallbackQuery):
    task_id = (callback.data or "").replace("feedrm_", "", 1)
    user, task = await _task_and_user(callback, task_id)
    if not task:
        await callback.answer("Генерация не найдена", show_alert=True)
        return
    removed = await remove_from_feed_scoped(task_id, user.id)
    if not removed:
        await callback.answer("Публикация не найдена", show_alert=True)
        return
    _invalidate_publication_caches()
    task["is_public_feed"] = False
    task["is_profile_visible"] = True
    await _refresh_result_markup(callback, task, "profile")
    await callback.answer("Убрано из ленты, оставлено в профиле")


@router.callback_query(F.data.startswith("profilehide_"))
async def hide_publication(callback: types.CallbackQuery):
    task_id = (callback.data or "").replace("profilehide_", "", 1)
    user, task = await _task_and_user(callback, task_id)
    if not task:
        await callback.answer("Генерация не найдена", show_alert=True)
        return
    removed = await remove_publication(task_id, user.id)
    if not removed:
        await callback.answer("Публикация не найдена", show_alert=True)
        return
    _invalidate_publication_caches()
    task["is_public_feed"] = False
    task["is_profile_visible"] = False
    await _refresh_result_markup(callback, task, "private")
    await callback.answer("Публикация скрыта")


@router.callback_query(F.data.startswith("pubcancel_"))
async def cancel_publication_scope(callback: types.CallbackQuery):
    task_id = (callback.data or "").replace("pubcancel_", "", 1)
    user, task = await _task_and_user(callback, task_id)
    if not task:
        await callback.answer("Генерация не найдена", show_alert=True)
        return
    scope = await get_publication_scope(task_id, user.id)
    await _refresh_result_markup(callback, task, scope)
    await callback.answer()


def install_common_publication_scope_compat(common_module) -> None:
    global _COMMON_PATCHED
    if _COMMON_PATCHED:
        return
    original_builder = getattr(common_module, "_build_feed_keyboard", None)
    if not callable(original_builder):
        return

    async def scoped_builder(*args, **kwargs):
        card = kwargs.get("card")
        if card is None and len(args) > 1:
            card = args[1]
        markup = await original_builder(*args, **kwargs)
        if not card or str(card.get("publication_scope") or "feed") == "feed":
            return markup

        filtered_rows: list[list[InlineKeyboardButton]] = []
        for row in markup.inline_keyboard:
            filtered: list[InlineKeyboardButton] = []
            for button in row:
                callback_data = str(button.callback_data or "")
                text = str(button.text or "")
                if callback_data.startswith(("bfl:", "bflp:", "bfs:", "bfr:", "repeat_image_")):
                    continue
                if "Повторить" in text or "Ссылка на пост" in text or text.startswith("❤️"):
                    continue
                filtered.append(button)
            if filtered:
                filtered_rows.append(filtered)
        return InlineKeyboardMarkup(inline_keyboard=filtered_rows)

    common_module._build_feed_keyboard = scoped_builder
    _COMMON_PATCHED = True


async def _miniapp_generation_share_scoped(module, request):
    try:
        body = await module._miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id") or body.get("feed_id")
        scope = str(body.get("publication_scope") or body.get("scope") or "feed").strip().lower()
        prompt_visible = module._payload_bool(
            body.get("prompt_visible", body.get("feed_prompt_visible")),
            False,
        )
        references_visible = module._payload_bool(
            body.get("references_visible", body.get("feed_references_visible")),
            False,
        )
        blurred = None
        if "blurred" in body or "feed_blurred" in body:
            blurred = module._payload_bool(
                body.get("blurred", body.get("feed_blurred")),
                False,
            )

        _telegram_id, ctx = await module._get_user_context(
            request.app,
            init_data,
            body.get("start_param_fallback"),
        )
        user_id = ctx["user"].id

        async def with_publication_link(card):
            me = await request.app["bot"].get_me()
            referral_code = str(card.get("author_referral_code") or "").strip().upper()
            card["publication_link"] = (
                module.build_feed_link(me.username, card["id"], referral_code)
                if me.username
                else module.config.mini_app_url
            )
            return card

        if scope == "profile":
            card = await share_to_profile(
                gen_id,
                user_id,
                prompt_visible=prompt_visible,
                references_visible=references_visible,
                blurred=blurred,
            )
            if not card:
                return module.web.json_response(
                    {"ok": False, "error": "Нельзя добавить эту генерацию в профиль"},
                    status=403,
                )
            card = await with_publication_link(card)
            _invalidate_publication_caches()
            return module.web.json_response(
                {"ok": True, "feed_item": card, "publication_scope": "profile"}
            )

        if scope in {"private", "none", "hidden"}:
            removed = await remove_publication(gen_id, user_id)
            _invalidate_publication_caches()
            return module.web.json_response(
                {"ok": True, "removed": removed, "publication_scope": "private"}
            )

        card = await share_to_feed_scoped(
            gen_id,
            user_id,
            prompt_visible=prompt_visible,
            references_visible=references_visible,
            blurred=blurred,
        )
        if not card:
            return module.web.json_response(
                {"ok": False, "error": "Нельзя опубликовать эту генерацию в ленту"},
                status=403,
            )
        card = await with_publication_link(card)
        _invalidate_publication_caches()
        return module.web.json_response(
            {"ok": True, "feed_item": card, "publication_scope": "feed"}
        )
    except Exception as error:  # noqa: BLE001 - API boundary converts unexpected failures to JSON
        return module._miniapp_error_response(
            error,
            log_message="Mini App scoped generation publication failed",
        )


def _patch_miniapp_module(module) -> None:
    async def scoped_generation_share(request):
        return await _miniapp_generation_share_scoped(module, request)

    module.miniapp_generation_share = scoped_generation_share


class _MiniappPatchLoader(importlib.abc.Loader):
    def __init__(self, original_loader):
        self.original_loader = original_loader

    def create_module(self, spec):
        creator = getattr(self.original_loader, "create_module", None)
        return creator(spec) if callable(creator) else None

    def exec_module(self, module):
        self.original_loader.exec_module(module)
        _patch_miniapp_module(module)


class _MiniappPatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "bot.miniapp":
            return None
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = _MiniappPatchLoader(spec.loader)
        return spec


def _install_miniapp_import_hook() -> None:
    global _MINIAPP_HOOK_INSTALLED
    if _MINIAPP_HOOK_INSTALLED:
        return
    loaded = sys.modules.get("bot.miniapp")
    if loaded is not None:
        _patch_miniapp_module(loaded)
    else:
        sys.meta_path.insert(0, _MiniappPatchFinder())
    _MINIAPP_HOOK_INSTALLED = True


def install_publication_scope_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    database._generation_row_to_card = _generation_row_to_card_scoped
    database.share_to_feed = share_to_feed_scoped
    database.remove_from_feed = remove_from_feed_scoped
    database.get_user_feed_generations = get_user_profile_generations

    keyboards.get_image_result_keyboard = get_image_result_keyboard_scoped
    keyboards.get_video_result_keyboard = get_video_result_keyboard_scoped

    _install_miniapp_import_hook()
    _INSTALLED = True
