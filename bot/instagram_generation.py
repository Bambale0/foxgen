from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from bot import database
from bot import db as db_backend
from bot.channel_identity import ChannelIdentity, ensure_channel_identity_schema
from bot.channel_promotions import (
    consume_instagram_first_image,
    ensure_channel_promotion_schema,
    ensure_instagram_first_image_promotion,
    release_instagram_first_image,
    reserve_instagram_first_image,
)
from bot.config import config
from bot.database import add_credits, add_generation_history, deduct_credits
from bot.instagram_api import InstagramClient, InstagramEvent, InstagramSettings
from bot.services.kie_market_service import kie_market_service
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)

INSTAGRAM_IMAGE_MODEL = "banana_2"
INSTAGRAM_PROVIDER_MODEL = "nano-banana-2"
INSTAGRAM_IMAGE_RESOLUTION = "2K"
INSTAGRAM_IMAGE_OUTPUT_FORMAT = "png"
_WORKER_CONCURRENCY = 4
_WORKER_POLL_SECONDS = 1.0
_JOB_LEASE_SECONDS = 20 * 60
_RETRY_DELAY_SECONDS = 30
_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY: set[str] = set()

_CONFIRM_WORDS = {
    "да",
    "yes",
    "ок",
    "ok",
    "запускай",
    "запустить",
    "готово",
    "продолжить",
}
_CANCEL_WORDS = {"нет", "no", "отмена", "отменить", "стоп", "cancel"}

AccountLinkFactory = Callable[[ChannelIdentity], Awaitable[str]]
ImageGenerator = Callable[[str, str], Awaitable[str]]


@dataclass(frozen=True)
class InstagramDraft:
    identity_id: int
    image_url: str
    prompt: str
    state: str


@dataclass(frozen=True)
class InstagramGenerationJob:
    id: str
    identity_id: int
    account_id: str
    recipient_id: str
    image_url: str
    prompt: str
    model: str
    cost: float
    billing_mode: str
    telegram_id: int | None
    promotion_reservation_key: str | None
    status: str
    provider_task_id: str | None
    result_url: str | None
    delivered_at_epoch: int | None
    attempt_count: int


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


def _schema_key() -> str:
    if db_backend.is_postgres():
        return f"postgres:{db_backend.DATABASE_URL}"
    return f"sqlite:{database.DATABASE_PATH}"


def _use_mapping_rows(db: db_backend.Connection) -> None:
    db.row_factory = db_backend.Row


def _sqlite_schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS instagram_generation_sessions (
            identity_id INTEGER PRIMARY KEY,
            image_url TEXT NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'idle',
            updated_at_epoch INTEGER NOT NULL,
            FOREIGN KEY (identity_id) REFERENCES channel_identities (id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS instagram_generation_jobs (
            id TEXT PRIMARY KEY,
            identity_id INTEGER NOT NULL,
            account_id TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            image_url TEXT NOT NULL,
            prompt TEXT NOT NULL,
            model TEXT NOT NULL,
            cost REAL NOT NULL DEFAULT 0,
            billing_mode TEXT NOT NULL,
            telegram_id INTEGER,
            promotion_reservation_key TEXT,
            status TEXT NOT NULL,
            provider_task_id TEXT,
            result_url TEXT,
            delivered_at_epoch INTEGER,
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at_epoch INTEGER NOT NULL DEFAULT 0,
            lease_expires_at_epoch INTEGER,
            created_at_epoch INTEGER NOT NULL,
            updated_at_epoch INTEGER NOT NULL,
            completed_at_epoch INTEGER,
            FOREIGN KEY (identity_id) REFERENCES channel_identities (id) ON DELETE CASCADE
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_instagram_jobs_worker "
            "ON instagram_generation_jobs(status, next_attempt_at_epoch, created_at_epoch)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_instagram_jobs_identity "
            "ON instagram_generation_jobs(identity_id, created_at_epoch)"
        ),
    )


def _postgres_schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS instagram_generation_sessions (
            identity_id BIGINT PRIMARY KEY,
            image_url TEXT NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'idle',
            updated_at_epoch BIGINT NOT NULL,
            FOREIGN KEY (identity_id) REFERENCES channel_identities (id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS instagram_generation_jobs (
            id TEXT PRIMARY KEY,
            identity_id BIGINT NOT NULL,
            account_id TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            image_url TEXT NOT NULL,
            prompt TEXT NOT NULL,
            model TEXT NOT NULL,
            cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            billing_mode TEXT NOT NULL,
            telegram_id BIGINT,
            promotion_reservation_key TEXT,
            status TEXT NOT NULL,
            provider_task_id TEXT,
            result_url TEXT,
            delivered_at_epoch BIGINT,
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at_epoch BIGINT NOT NULL DEFAULT 0,
            lease_expires_at_epoch BIGINT,
            created_at_epoch BIGINT NOT NULL,
            updated_at_epoch BIGINT NOT NULL,
            completed_at_epoch BIGINT,
            FOREIGN KEY (identity_id) REFERENCES channel_identities (id) ON DELETE CASCADE
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_instagram_jobs_worker "
            "ON instagram_generation_jobs(status, next_attempt_at_epoch, created_at_epoch)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_instagram_jobs_identity "
            "ON instagram_generation_jobs(identity_id, created_at_epoch)"
        ),
    )


async def _create_postgres_schema(db: db_backend.Connection) -> None:
    raw_connection = getattr(db, "_conn", None)
    if raw_connection is None:
        raise RuntimeError("PostgreSQL connection does not expose its migration handle")
    async with raw_connection.cursor() as cursor:
        for statement in _postgres_schema_statements():
            await cursor.execute(statement)
    await raw_connection.commit()


async def ensure_instagram_generation_schema() -> None:
    await ensure_channel_identity_schema()
    await ensure_channel_promotion_schema()
    key = _schema_key()
    if key in _SCHEMA_READY:
        return

    async with _schema_lock():
        if key in _SCHEMA_READY:
            return
        async with db_backend.connect() as db:
            if db_backend.is_postgres():
                await _create_postgres_schema(db)
            else:
                for statement in _sqlite_schema_statements():
                    await db.execute(statement)
                await db.commit()
        _SCHEMA_READY.add(key)


def _row_to_draft(row: db_backend.Row | None) -> InstagramDraft | None:
    if row is None:
        return None
    return InstagramDraft(
        identity_id=int(row["identity_id"]),
        image_url=str(row["image_url"] or ""),
        prompt=str(row["prompt"] or ""),
        state=str(row["state"] or "idle"),
    )


def _row_to_job(row: db_backend.Row | None) -> InstagramGenerationJob | None:
    if row is None:
        return None
    return InstagramGenerationJob(
        id=str(row["id"]),
        identity_id=int(row["identity_id"]),
        account_id=str(row["account_id"]),
        recipient_id=str(row["recipient_id"]),
        image_url=str(row["image_url"]),
        prompt=str(row["prompt"]),
        model=str(row["model"]),
        cost=float(row["cost"] or 0),
        billing_mode=str(row["billing_mode"]),
        telegram_id=(
            int(row["telegram_id"]) if row["telegram_id"] is not None else None
        ),
        promotion_reservation_key=(
            str(row["promotion_reservation_key"])
            if row["promotion_reservation_key"] is not None
            else None
        ),
        status=str(row["status"]),
        provider_task_id=(
            str(row["provider_task_id"])
            if row["provider_task_id"] is not None
            else None
        ),
        result_url=(
            str(row["result_url"]) if row["result_url"] is not None else None
        ),
        delivered_at_epoch=(
            int(row["delivered_at_epoch"])
            if row["delivered_at_epoch"] is not None
            else None
        ),
        attempt_count=int(row["attempt_count"] or 0),
    )


async def save_instagram_image_draft(identity_id: int, image_url: str) -> None:
    await ensure_instagram_generation_schema()
    url = str(image_url or "").strip()
    if identity_id <= 0 or not url:
        raise ValueError("identity_id and image_url are required")
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO instagram_generation_sessions (
                identity_id, image_url, prompt, state, updated_at_epoch
            ) VALUES (?, ?, '', 'waiting_prompt', ?)
            ON CONFLICT(identity_id) DO UPDATE SET
                image_url = excluded.image_url,
                prompt = '',
                state = 'waiting_prompt',
                updated_at_epoch = excluded.updated_at_epoch
            """,
            (identity_id, url, now),
        )
        await db.commit()


async def get_instagram_draft(identity_id: int) -> InstagramDraft | None:
    await ensure_instagram_generation_schema()
    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        cursor = await db.execute(
            """
            SELECT identity_id, image_url, prompt, state
            FROM instagram_generation_sessions
            WHERE identity_id = ?
            """,
            (identity_id,),
        )
        return _row_to_draft(await cursor.fetchone())


async def update_instagram_draft(
    identity_id: int,
    *,
    prompt: str | None = None,
    state: str | None = None,
    clear_image: bool = False,
) -> None:
    await ensure_instagram_generation_schema()
    draft = await get_instagram_draft(identity_id)
    if draft is None:
        raise ValueError("Instagram image draft does not exist")
    next_prompt = draft.prompt if prompt is None else str(prompt).strip()
    next_state = draft.state if state is None else str(state).strip()
    next_image = "" if clear_image else draft.image_url
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE instagram_generation_sessions
            SET image_url = ?, prompt = ?, state = ?, updated_at_epoch = ?
            WHERE identity_id = ?
            """,
            (next_image, next_prompt, next_state, int(time.time()), identity_id),
        )
        await db.commit()


async def _linked_billing_user(identity_id: int) -> tuple[int, int, float] | None:
    await ensure_instagram_generation_schema()
    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        cursor = await db.execute(
            """
            SELECT u.id AS user_id, u.telegram_id, u.credits
            FROM channel_identities AS i
            JOIN users AS u ON u.id = i.user_id
            WHERE i.id = ? AND i.user_id IS NOT NULL
            """,
            (identity_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return int(row["user_id"]), int(row["telegram_id"]), float(row["credits"] or 0)


async def _insert_job(job: InstagramGenerationJob, *, status: str) -> None:
    await ensure_instagram_generation_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO instagram_generation_jobs (
                id, identity_id, account_id, recipient_id, image_url, prompt,
                model, cost, billing_mode, telegram_id,
                promotion_reservation_key, status, provider_task_id, result_url,
                delivered_at_epoch, error, attempt_count, next_attempt_at_epoch,
                lease_expires_at_epoch, created_at_epoch, updated_at_epoch,
                completed_at_epoch
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL,
                NULL, NULL, 0, 0, NULL, ?, ?, NULL
            )
            """,
            (
                job.id,
                job.identity_id,
                job.account_id,
                job.recipient_id,
                job.image_url,
                job.prompt,
                job.model,
                job.cost,
                job.billing_mode,
                job.telegram_id,
                job.promotion_reservation_key,
                status,
                now,
                now,
            ),
        )
        await db.commit()


async def _activate_job(job_id: str) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE instagram_generation_jobs
            SET status = 'queued', next_attempt_at_epoch = 0,
                updated_at_epoch = ?
            WHERE id = ? AND status = 'prepared'
            """,
            (int(time.time()), job_id),
        )
        await db.commit()


async def _claim_next_job() -> InstagramGenerationJob | None:
    await ensure_instagram_generation_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        _use_mapping_rows(db)
        cursor = await db.execute(
            """
            SELECT *
            FROM instagram_generation_jobs
            WHERE (
                    status = 'queued'
                    OR (
                        status = 'processing'
                        AND lease_expires_at_epoch IS NOT NULL
                        AND lease_expires_at_epoch < ?
                    )
                  )
              AND next_attempt_at_epoch <= ?
            ORDER BY created_at_epoch ASC
            LIMIT 1
            """,
            (now, now),
        )
        row = await cursor.fetchone()
        job = _row_to_job(row)
        if job is None:
            return None
        claim = await db.execute(
            """
            UPDATE instagram_generation_jobs
            SET status = 'processing',
                lease_expires_at_epoch = ?,
                attempt_count = attempt_count + 1,
                updated_at_epoch = ?
            WHERE id = ?
              AND (
                    status = 'queued'
                    OR (
                        status = 'processing'
                        AND lease_expires_at_epoch IS NOT NULL
                        AND lease_expires_at_epoch < ?
                    )
                  )
            """,
            (now + _JOB_LEASE_SECONDS, now, job.id, now),
        )
        if int(getattr(claim, "rowcount", 0) or 0) != 1:
            await db.rollback()
            return None
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM instagram_generation_jobs WHERE id = ?",
            (job.id,),
        )
        return _row_to_job(await cursor.fetchone())


async def _mark_job_result(
    job_id: str,
    result_url: str,
    provider_task_id: str | None,
) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE instagram_generation_jobs
            SET result_url = ?, provider_task_id = ?, updated_at_epoch = ?
            WHERE id = ?
            """,
            (result_url, provider_task_id, int(time.time()), job_id),
        )
        await db.commit()


async def _mark_job_delivered(job_id: str) -> int:
    delivered_at = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE instagram_generation_jobs
            SET delivered_at_epoch = ?, updated_at_epoch = ?
            WHERE id = ? AND delivered_at_epoch IS NULL
            """,
            (delivered_at, delivered_at, job_id),
        )
        await db.commit()
    return delivered_at


async def _mark_job_succeeded(job_id: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE instagram_generation_jobs
            SET status = 'succeeded', error = NULL, lease_expires_at_epoch = NULL,
                updated_at_epoch = ?, completed_at_epoch = ?
            WHERE id = ?
            """,
            (now, now, job_id),
        )
        await db.commit()


async def _mark_job_failed(job_id: str, error: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE instagram_generation_jobs
            SET status = 'failed', error = ?, lease_expires_at_epoch = NULL,
                updated_at_epoch = ?, completed_at_epoch = ?
            WHERE id = ?
            """,
            (str(error)[:1000], now, now, job_id),
        )
        await db.commit()


async def _retry_job(job_id: str, error: str) -> None:
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE instagram_generation_jobs
            SET status = 'queued', error = ?, lease_expires_at_epoch = NULL,
                next_attempt_at_epoch = ?, updated_at_epoch = ?
            WHERE id = ?
            """,
            (str(error)[:1000], now + _RETRY_DELAY_SECONDS, now, job_id),
        )
        await db.commit()


async def _persist_inline_result(image_bytes: bytes, mime_type: str | None) -> str:
    host = str(config.WEBHOOK_HOST or "").strip().rstrip("/")
    if not host.startswith("https://"):
        raise RuntimeError(
            "A public HTTPS WEBHOOK_HOST is required for Instagram media delivery"
        )
    ext = {
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/png": "png",
    }.get(str(mime_type or "").lower(), "png")
    directory = Path("static/uploads/instagram/results")
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = directory / filename
    await asyncio.to_thread(path.write_bytes, bytes(image_bytes))
    return f"{host}/uploads/instagram/results/{filename}"


async def _default_image_generator(prompt: str, image_url: str) -> str:
    result = await nano_banana_2_service.generate_image(
        prompt=prompt,
        aspect_ratio="auto",
        resolution=INSTAGRAM_IMAGE_RESOLUTION,
        image_input=[image_url],
        output_format=INSTAGRAM_IMAGE_OUTPUT_FORMAT,
        callback_url=None,
        model=INSTAGRAM_PROVIDER_MODEL,
    )
    if not isinstance(result, dict):
        raise RuntimeError("Image provider did not accept the generation")
    if result.get("image_bytes"):
        return await _persist_inline_result(
            bytes(result["image_bytes"]),
            str(result.get("mime_type") or "image/png"),
        )
    task_id = str(result.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(
            str(result.get("error") or "Image provider returned no task")
        )
    completed = await nano_banana_2_service.wait_for_completion(task_id)
    if not isinstance(completed, dict):
        raise RuntimeError("Image generation failed or timed out")
    urls = kie_market_service.parse_result_urls(completed)
    if not urls:
        raise RuntimeError("Image provider completed without a result URL")
    return str(urls[0])


def _attachment_image_url(event: InstagramEvent) -> str:
    message = event.payload.get("message")
    if not isinstance(message, dict):
        return ""
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return ""
    for item in attachments:
        if (
            not isinstance(item, dict)
            or str(item.get("type") or "").lower() != "image"
        ):
            continue
        payload = (
            item.get("payload") if isinstance(item.get("payload"), dict) else {}
        )
        url = str(payload.get("url") or "").strip()
        if url:
            return url
    return ""


def _normalized_reply(value: str) -> str:
    return " ".join(str(value or "").casefold().strip().split())


class InstagramGenerationService:
    def __init__(
        self,
        *,
        settings: InstagramSettings,
        client: InstagramClient | Any | None = None,
        account_link_factory: AccountLinkFactory | None = None,
        generator: ImageGenerator = _default_image_generator,
    ) -> None:
        self.settings = settings
        self.client = client or InstagramClient.from_settings(settings)
        self.account_link_factory = account_link_factory
        self.generator = generator
        self._stop_event = asyncio.Event()
        self._active: set[asyncio.Task] = set()

    async def _send_account_link(
        self,
        identity: ChannelIdentity,
        account_id: str,
        recipient_id: str,
    ) -> None:
        link = ""
        if self.account_link_factory is not None:
            link = str(await self.account_link_factory(identity)).strip()
        suffix = f"\n\n{link}" if link else ""
        await self.client.send_text(
            account_id,
            recipient_id,
            "Первая генерация уже использована ✅ Следующие фото оплачиваются "
            "по обычным ценам HappyFox. Привяжи Instagram к своему аккаунту, "
            "чтобы использовать общий баланс и историю."
            + suffix,
        )

    async def _offer_paid_generation(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        prompt: str,
        account_id: str,
        recipient_id: str,
    ) -> None:
        billing = await _linked_billing_user(identity.id)
        if billing is None:
            await update_instagram_draft(
                identity.id,
                prompt=prompt,
                state="awaiting_link",
            )
            await self._send_account_link(identity, account_id, recipient_id)
            return

        _user_id, _telegram_id, credits = billing
        cost = float(preset_manager.get_generation_cost(INSTAGRAM_IMAGE_MODEL))
        await update_instagram_draft(
            identity.id,
            prompt=prompt,
            state="awaiting_confirmation",
        )
        rub_value = float(preset_manager.get_credit_rub_value())
        price_rub = round(cost * rub_value, 2)
        balance_line = f"Баланс: {credits:g} 🐾."
        if credits < cost:
            action = (
                " Баланса не хватает — пополни HappyFox в Telegram, "
                "затем вернись и ответь ДА."
            )
        else:
            action = " Ответь ДА для запуска или НЕТ для отмены."
        await self.client.send_text(
            account_id,
            recipient_id,
            f"Стоимость следующей генерации: {cost:g} 🐾 "
            f"({price_rub:g} ₽). {balance_line}{action}",
        )

    async def _enqueue_free(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        prompt: str,
        account_id: str,
        recipient_id: str,
    ) -> bool:
        job_id = uuid.uuid4().hex
        if not await reserve_instagram_first_image(identity.id, job_id):
            return False
        job = InstagramGenerationJob(
            id=job_id,
            identity_id=identity.id,
            account_id=account_id,
            recipient_id=recipient_id,
            image_url=draft.image_url,
            prompt=prompt,
            model=INSTAGRAM_IMAGE_MODEL,
            cost=0,
            billing_mode="free",
            telegram_id=None,
            promotion_reservation_key=job_id,
            status="prepared",
            provider_task_id=None,
            result_url=None,
            delivered_at_epoch=None,
            attempt_count=0,
        )
        try:
            await _insert_job(job, status="prepared")
            await _activate_job(job.id)
        except Exception:
            await release_instagram_first_image(job_id)
            raise
        await update_instagram_draft(
            identity.id,
            prompt=prompt,
            state="generating",
        )
        await self.client.send_text(
            account_id,
            recipient_id,
            "Запускаю первую генерацию бесплатно 🎁 Результат пришлю сюда, "
            "как только он будет готов.",
        )
        return True

    async def _enqueue_paid(
        self,
        identity: ChannelIdentity,
        draft: InstagramDraft,
        account_id: str,
        recipient_id: str,
    ) -> None:
        billing = await _linked_billing_user(identity.id)
        if billing is None:
            await update_instagram_draft(identity.id, state="awaiting_link")
            await self._send_account_link(identity, account_id, recipient_id)
            return
        user_id, telegram_id, _credits = billing
        cost = float(preset_manager.get_generation_cost(INSTAGRAM_IMAGE_MODEL))
        job = InstagramGenerationJob(
            id=uuid.uuid4().hex,
            identity_id=identity.id,
            account_id=account_id,
            recipient_id=recipient_id,
            image_url=draft.image_url,
            prompt=draft.prompt,
            model=INSTAGRAM_IMAGE_MODEL,
            cost=cost,
            billing_mode="credits",
            telegram_id=telegram_id,
            promotion_reservation_key=None,
            status="prepared",
            provider_task_id=None,
            result_url=None,
            delivered_at_epoch=None,
            attempt_count=0,
        )
        await _insert_job(job, status="prepared")
        deducted = await deduct_credits(telegram_id, cost)
        if not deducted:
            await _mark_job_failed(job.id, "insufficient_balance")
            await self.client.send_text(
                account_id,
                recipient_id,
                f"Не хватает баланса для запуска. Нужно {cost:g} 🐾. "
                "Пополни HappyFox в Telegram и попробуй ещё раз.",
            )
            return
        try:
            await _activate_job(job.id)
        except Exception:
            await add_credits(telegram_id, cost)
            await _mark_job_failed(job.id, "activation_failed")
            raise
        await update_instagram_draft(identity.id, state="generating")
        await self.client.send_text(
            account_id,
            recipient_id,
            f"Оплата {cost:g} 🐾 принята ✅ Запускаю генерацию "
            "и пришлю результат сюда.",
        )
        if user_id > 0:
            logger.info(
                "Instagram paid generation queued: job=%s user=%s",
                job.id,
                user_id,
            )

    async def handle_message(
        self,
        identity: ChannelIdentity,
        event: InstagramEvent,
    ) -> bool:
        image_url = _attachment_image_url(event)
        if image_url:
            draft = await get_instagram_draft(identity.id)
            if draft and draft.state == "generating":
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Я уже делаю предыдущую генерацию. Сначала пришлю результат, "
                    "потом можно отправить новое фото.",
                )
                return True
            await save_instagram_image_draft(identity.id, image_url)
            promotion = await ensure_instagram_first_image_promotion(identity.id)
            free_line = (
                " Первая генерация будет бесплатно 🎁"
                if promotion.status != "consumed"
                else ""
            )
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Фото получил 📸"
                + free_line
                + " Теперь одним сообщением напиши, что хочешь получить.",
            )
            return True

        text = str(event.text or "").strip()
        if not text:
            return False
        draft = await get_instagram_draft(identity.id)
        if draft is None or not draft.image_url:
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Сначала пришли фото 📸, а следующим сообщением — "
                "что хочешь с ним сделать.",
            )
            return True

        normalized = _normalized_reply(text)
        if draft.state == "generating":
            await self.client.send_text(
                event.account_id,
                event.sender_id,
                "Генерация уже идёт. Результат пришлю сюда автоматически.",
            )
            return True

        if draft.state == "awaiting_confirmation":
            if normalized in _CANCEL_WORDS:
                await update_instagram_draft(
                    identity.id,
                    prompt="",
                    state="waiting_prompt",
                )
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Отменил. Фото сохранил — можешь написать новый запрос.",
                )
                return True
            if normalized not in _CONFIRM_WORDS:
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Ответь ДА, чтобы запустить платную генерацию, "
                    "или НЕТ, чтобы отменить.",
                )
                return True
            await self._enqueue_paid(
                identity,
                draft,
                event.account_id,
                event.sender_id,
            )
            return True

        if draft.state == "awaiting_link":
            if identity.user_id is None:
                await self._send_account_link(
                    identity,
                    event.account_id,
                    event.sender_id,
                )
                return True
            await self._offer_paid_generation(
                identity,
                draft,
                draft.prompt or text,
                event.account_id,
                event.sender_id,
            )
            return True

        promotion = await ensure_instagram_first_image_promotion(identity.id)
        if promotion.status != "consumed":
            if await self._enqueue_free(
                identity,
                draft,
                text,
                event.account_id,
                event.sender_id,
            ):
                return True
            promotion = await ensure_instagram_first_image_promotion(identity.id)
            if promotion.status != "consumed":
                await self.client.send_text(
                    event.account_id,
                    event.sender_id,
                    "Бесплатная генерация уже запускается. "
                    "Результат пришлю сюда автоматически.",
                )
                return True

        await self._offer_paid_generation(
            identity,
            draft,
            text,
            event.account_id,
            event.sender_id,
        )
        return True

    async def _finalize_failure(
        self,
        job: InstagramGenerationJob,
        error: Exception,
    ) -> None:
        if job.billing_mode == "free" and job.promotion_reservation_key:
            await release_instagram_first_image(job.promotion_reservation_key)
        elif job.billing_mode == "credits" and job.telegram_id and job.cost > 0:
            await add_credits(job.telegram_id, job.cost)
        await _mark_job_failed(job.id, str(error))
        with contextlib.suppress(Exception):
            await update_instagram_draft(job.identity_id, state="waiting_prompt")
        with contextlib.suppress(Exception):
            retry_note = (
                " Бесплатная попытка сохранена."
                if job.billing_mode == "free"
                else " Списанные 🐾 уже возвращены."
            )
            await self.client.send_text(
                job.account_id,
                job.recipient_id,
                "Не получилось завершить генерацию 😕 Попробуй ещё раз "
                "с тем же фото."
                + retry_note,
            )

    async def _finalize_success(self, job: InstagramGenerationJob) -> None:
        if job.billing_mode == "free" and job.promotion_reservation_key:
            consumed = await consume_instagram_first_image(
                job.promotion_reservation_key
            )
            if not consumed:
                raise RuntimeError(
                    "Failed to consume Instagram free-image entitlement"
                )

        await _mark_job_succeeded(job.id)
        with contextlib.suppress(Exception):
            await update_instagram_draft(
                job.identity_id,
                prompt="",
                state="idle",
                clear_image=True,
            )

        if job.billing_mode == "credits":
            billing = await _linked_billing_user(job.identity_id)
            if billing is not None:
                user_id, _telegram_id, _credits = billing
                with contextlib.suppress(Exception):
                    await add_generation_history(
                        user_id,
                        "instagram_banana_2",
                        job.prompt,
                        job.cost,
                    )
            with contextlib.suppress(Exception):
                await self.client.send_text(
                    job.account_id,
                    job.recipient_id,
                    "Готово ✨ Можешь прислать следующее фото — "
                    "цена будет показана до запуска.",
                )
            return

        with contextlib.suppress(Exception):
            await self.client.send_text(
                job.account_id,
                job.recipient_id,
                "Готово 🎁 Это была бесплатная первая генерация. "
                "Следующие фото — по обычной цене HappyFox; "
                "перед запуском всегда покажу стоимость.",
            )

    async def _process_job(self, job: InstagramGenerationJob) -> None:
        result_url = str(job.result_url or "").strip()
        if not result_url:
            try:
                result_url = await self.generator(job.prompt, job.image_url)
                if not result_url:
                    raise RuntimeError("Image generator returned an empty URL")
                await _mark_job_result(job.id, result_url, job.provider_task_id)
            except Exception as error:
                logger.exception(
                    "Instagram image generation failed: job=%s",
                    job.id,
                )
                await self._finalize_failure(job, error)
                return

        delivered_at_epoch = job.delivered_at_epoch
        if delivered_at_epoch is None:
            try:
                await self.client.send_media(
                    job.account_id,
                    job.recipient_id,
                    "image",
                    result_url,
                )
                delivered_at_epoch = await _mark_job_delivered(job.id)
            except Exception as error:
                logger.exception(
                    "Instagram result delivery failed: job=%s",
                    job.id,
                )
                await _retry_job(job.id, str(error))
                return

        try:
            await self._finalize_success(job)
        except Exception as error:
            logger.exception(
                "Instagram result finalization failed after delivery: job=%s delivered_at=%s",
                job.id,
                delivered_at_epoch,
            )
            await _retry_job(job.id, str(error))

    async def run_worker(self) -> None:
        await ensure_instagram_generation_schema()
        self._stop_event.clear()
        while not self._stop_event.is_set():
            self._active = {task for task in self._active if not task.done()}
            while len(self._active) < _WORKER_CONCURRENCY:
                job = await _claim_next_job()
                if job is None:
                    break
                task = asyncio.create_task(self._process_job(job))
                self._active.add(task)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=_WORKER_POLL_SECONDS,
                )
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop_event.set()
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)


def install_instagram_generation_worker(
    app: web.Application,
    service: InstagramGenerationService,
) -> None:
    async def worker_context(_app: web.Application):
        task = asyncio.create_task(service.run_worker())
        try:
            yield
        finally:
            await service.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app["instagram_generation_service"] = service
    app.cleanup_ctx.append(worker_context)
