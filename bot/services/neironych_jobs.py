"""Native operations on the existing HappyFox task rows and wallet.

Telegram/Mini App use generation_tasks; MAX uses max_generation_jobs. The
shared provider state machine never creates a second ledger or fake identity.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Callable

from bot import database, db as db_backend
from bot.config import config
from happyfox_neironych import ContractError, PreparedRequest
from happyfox_neironych.lifecycle import Artifacts, advance, encoded, new_operation
from . import neironych_routing as routing

logger = logging.getLogger(__name__)
ARTIFACT_ROOT = Path('static/uploads/neironych')
_worker: asyncio.Task | None = None


def artifacts() -> Artifacts:
    return Artifacts(ARTIFACT_ROOT, config.static_base_url.rstrip('/') + '/uploads/neironych')


class TaskJournal:
    """Compare-and-swap nested journal while preserving unrelated task metadata."""
    def __init__(self, task_id: str, *, channel: str = 'telegram'):
        self.task_id = task_id
        if channel == 'telegram':
            self.table, self.key, self.column = 'generation_tasks', 'task_id', 'request_data'
            self.clock = 'updated_at = CURRENT_TIMESTAMP'
        elif channel == 'max':
            self.table, self.key, self.column = 'max_generation_jobs', 'id', 'options_json'
            self.clock = f'updated_at_epoch = {int(time.time())}'
        else:
            raise ValueError('Unsupported native journal channel')

    async def _read(self, *, require_operation: bool = True) -> tuple[str, dict[str, Any]]:
        async with db_backend.connect() as db:
            cursor = await db.execute(
                f'SELECT {self.column} FROM {self.table} WHERE {self.key} = ?',
                (self.task_id,),
            )
            row = await cursor.fetchone()
        if not row:
            raise LookupError('Native task not found')
        raw = row[0]
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Native task metadata is invalid')
        if require_operation and not isinstance(value.get('native_operation'), dict):
            raise ValueError('Native task journal is missing')
        return raw, value

    async def metadata(self) -> dict[str, Any]:
        return (await self._read())[1]

    async def load(self) -> str:
        return encoded((await self.metadata())['native_operation'])

    async def _cas(self, old: str, value: dict[str, Any]) -> bool:
        async with db_backend.connect() as db:
            cursor = await db.execute(
                f'UPDATE {self.table} SET {self.column} = ?, {self.clock} WHERE {self.key} = ? AND {self.column} = ?',
                (encoded(value), self.task_id, old),
            )
            await db.commit()
            return int(cursor.rowcount or 0) == 1

    async def replace(self, expected: str, value: str) -> bool:
        old, parent = await self._read()
        if encoded(parent['native_operation']) != expected:
            return False
        parent['native_operation'] = json.loads(value)
        return await self._cas(old, parent)

    async def update(self, mutate: Callable[[dict[str, Any]], bool]) -> bool:
        for _ in range(3):
            old, parent = await self._read()
            if not mutate(parent):
                return False
            if await self._cas(old, parent):
                return True
        return False


async def ensure_max_operation(job_id: str, request: PreparedRequest) -> TaskJournal:
    """Persist the exact provider request before any MAX external side effect."""
    journal = TaskJournal(job_id, channel='max')
    for _ in range(3):
        old, parent = await journal._read(require_operation=False)
        existing = parent.get('native_operation')
        if isinstance(existing, dict):
            restored = PreparedRequest.from_dict(existing['request'])
            if restored.to_dict() != request.to_dict():
                raise ContractError('MAX job already has a different provider request')
            return journal
        parent['native_operation'] = new_operation(request)
        parent['native_provider'] = 'neironych'
        parent['native_provider_model'] = request.model.id
        if await journal._cas(old, parent):
            logger.info(
                'neironych_max_journal_created job_id=%s provider_model=%s',
                job_id,
                request.model.id,
            )
            return journal
    raise RuntimeError('MAX native journal could not be persisted')


async def advance_max_operation(
    job_id: str,
    request: PreparedRequest,
) -> dict[str, Any]:
    journal = await ensure_max_operation(job_id, request)
    return await advance(journal, routing.client, artifacts())


async def enqueue_telegram(
    user: Any, telegram_id: int, request: PreparedRequest, *, product: str,
    cost: float, metadata: dict[str, Any] | None = None,
    original_prompt: str | None = None,
    source_feed_gen_id: int | None = None, parent_generation_id: int | None = None,
    action_type: str | None = None,
) -> str:
    if getattr(user, 'telegram_id', telegram_id) != telegram_id:
        raise ContractError('Task owner mismatch')
    if not math.isfinite(float(cost)) or cost < 0:
        raise ContractError('Invalid generation price')
    task_id = 'nr_' + hashlib.sha256(f'{telegram_id}:{request.key}'.encode()).hexdigest()[:32]
    payload = request.payload
    parent = {
        **(metadata or {}),
        'provider': 'neironych', 'provider_model': request.model.id,
        'native_operation': new_operation(request), 'native_delivered': False,
        # Record actual debit exemption at launch, not the user's later role.
        'charged_cost': 0 if config.is_admin(telegram_id) else float(cost),
    }
    inserted = await database.add_generation_task(
        user.id, telegram_id, task_id, request.model.kind, 'neironych',
        model=product, duration=payload.get('duration'), aspect_ratio=payload.get('aspect_ratio'),
        prompt=original_prompt if original_prompt is not None else str(payload.get('prompt') or ''),
        cost=cost, request_data=parent, source_feed_gen_id=source_feed_gen_id,
        parent_generation_id=parent_generation_id, action_type=action_type,
    )
    if not inserted:
        existing = await TaskJournal(task_id).metadata()
        if existing['native_operation']['request'] != request.to_dict():
            raise ContractError('Same logical task has a different provider payload')
    logger.info('neironych_enqueued task_id=%s user_id=%s provider_model=%s kind=%s', task_id, user.id, request.model.id, request.model.kind)
    return task_id


async def _refund_failed(task_id: str) -> None:
    """One transaction claims the failed task and returns the recorded debit."""
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute('SELECT user_id, status, request_data FROM generation_tasks WHERE task_id = ?', (task_id,))
        row = await cursor.fetchone()
        if not row:
            return
        parent = json.loads(row['request_data'])
        if parent.get('native_refund_applied') or parent['native_operation']['phase'] != 'failed':
            return
        amount = float(parent.get('charged_cost') or 0)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError('Invalid recorded debit')
        parent['native_refund_applied'] = True
        cursor = await db.execute(
            "UPDATE generation_tasks SET status = 'failed', request_data = ?, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND request_data = ? AND status IN ('pending', 'processing')",
            (encoded(parent), task_id, row['request_data']),
        )
        if int(cursor.rowcount or 0) != 1:
            await db.rollback()
            return
        if amount:
            refund = await db.execute('UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (amount, row['user_id']))
            if int(refund.rowcount or 0) != 1:
                raise RuntimeError('Refund owner is missing')
        await db.commit()
    logger.info('neironych_refund_applied task_id=%s credits=%s', task_id, amount)


async def _claim_delivery(journal: TaskJournal, *, held: bool) -> bool:
    now = time.time()
    def claim(parent: dict[str, Any]) -> bool:
        if parent.get('native_delivered') or (held and parent.get('native_hold_notified')):
            return False
        if parent.get('native_delivery_until', 0) > now or parent.get('native_delivery_after', 0) > now:
            return False
        parent['native_delivery_until'] = now + 120
        return True
    return await journal.update(claim)


async def process_telegram_task(bot: Any, task_id: str) -> None:
    journal = TaskJournal(task_id)
    parent = await journal.metadata()
    if parent.get('native_delivered'):
        return
    operation = await advance(journal, routing.client, artifacts())
    phase = operation['phase']
    if phase not in {'ready', 'failed', 'held'}:
        return
    task = await database.get_task_by_id(task_id)
    if task is None:
        return
    if phase == 'failed':
        await _refund_failed(task_id)
    if phase == 'ready':
        result_assets = operation.get('assets') or []
        result_url = result_assets[0].get('url') if result_assets else None
        async with db_backend.connect() as db:
            await db.execute(
                "UPDATE generation_tasks SET status = 'completed', result_url = ?, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
                (result_url, task_id),
            )
            await db.commit()
    if not await _claim_delivery(journal, held=phase == 'held'):
        return
    completed = False
    try:
        if phase == 'failed':
            metadata = await journal.metadata()
            refunded = float(metadata.get('charged_cost') or 0)
            await bot.send_message(chat_id=task.telegram_id,
                text=f'Не удалось завершить запрос. ID: {task_id}. ' + (f'Возвращено {refunded:g} лапок.' if refunded else 'Списания не было.'),
                parse_mode=None)
        elif phase == 'held':
            await bot.send_message(chat_id=task.telegram_id,
                text=f'Уточняю результат запроса {task_id}. Провайдер не подтвердил итог; повторно платный запрос не отправляю. Номер сохранён для проверки поддержкой.',
                parse_mode=None)
        else:
            request = PreparedRequest.from_dict(operation['request'])
            if request.model.kind == 'text':
                text = f'{request.model.label}\n\n' + str(operation['text'])
                parts = [text[i:i + 3500] for i in range(0, len(text), 3500)]
                index = int((await journal.metadata()).get('native_delivery_index', 0))
                for pos in range(index, len(parts)):
                    await bot.send_message(chat_id=task.telegram_id, text=parts[pos], parse_mode=None)
                    if not await journal.update(lambda data, n=pos + 1: _set(data, native_delivery_index=n)):
                        raise RuntimeError('Delivery checkpoint was not saved')
            else:
                asset = operation['assets'][0]
                url = asset['url']
                caption = f'{request.model.label} — готово.\nID: {task_id}'
                from bot.keyboards import get_image_result_keyboard, get_video_result_keyboard
                if request.model.kind == 'image':
                    await bot.send_document(chat_id=task.telegram_id, document=url, caption=caption, parse_mode=None,
                        reply_markup=get_image_result_keyboard(url, task_id=task_id))
                else:
                    await bot.send_video(chat_id=task.telegram_id, video=url, caption=caption, parse_mode=None, supports_streaming=True,
                        reply_markup=get_video_result_keyboard(url, task_id=task_id, model=task.model))
        completed = True
    finally:
        await journal.update(lambda data: _set(data,
            native_delivery_until=0,
            native_delivery_after=0 if completed else time.time() + 60,
            **({'native_hold_notified': True} if completed and phase == 'held' else {'native_delivered': True} if completed else {})))
        logger.info('neironych_delivery task_id=%s phase=%s delivered=%s', task_id, phase, completed)


def _set(value: dict[str, Any], **changes: Any) -> bool:
    value.update(changes)
    return True


async def _loop(bot: Any) -> None:
    while True:
        try:
            async with db_backend.connect() as db:
                cursor = await db.execute(
                    """SELECT task_id FROM generation_tasks
                       WHERE task_id LIKE 'nr_%'
                         AND request_data NOT LIKE ?
                         AND NOT (request_data LIKE ? AND request_data LIKE ?)
                       ORDER BY updated_at ASC LIMIT 25""",
                    ('%"native_delivered":true%', '%"phase":"held"%', '%"native_hold_notified":true%'),
                )
                rows = await cursor.fetchall()
            semaphore = asyncio.Semaphore(4)
            async def process(row: Any) -> None:
                async with semaphore:
                    try:
                        await process_telegram_task(bot, row[0])
                    except Exception as exc:
                        logger.error('neironych_task_step_failed task_id=%s error_type=%s', row[0], type(exc).__name__)
            await asyncio.gather(*(process(row) for row in rows))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error('neironych_worker_failed error_type=%s', type(exc).__name__)
        await asyncio.sleep(routing.client.settings.poll_interval)


async def start(bot: Any) -> None:
    global _worker
    await routing.configuration()
    if routing.client.settings.ready and (_worker is None or _worker.done()):
        _worker = asyncio.create_task(_loop(bot), name='happyfox-neironych-worker')
        logger.info('neironych_worker_started')


async def stop() -> None:
    global _worker
    if _worker is not None:
        _worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _worker
        _worker = None
