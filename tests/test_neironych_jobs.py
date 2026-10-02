import json

import httpx
import pytest


@pytest.fixture
async def prepared_db(tmp_path, monkeypatch):
    from bot import database
    from bot.services import neironych_jobs as jobs
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'bot.db'))
    monkeypatch.setattr(database, 'DATABASE_PATH', str(tmp_path / 'bot.db'))
    await database.init_db()
    user = await database.get_or_create_user(501)
    async with database.db_backend.connect() as conn:
        await conn.execute('UPDATE users SET credits = 7 WHERE telegram_id = 501')
        await conn.commit()
    monkeypatch.setattr(jobs, 'ARTIFACT_ROOT', tmp_path / 'results')
    monkeypatch.setattr(jobs.config, 'STATIC_BASE_URL', 'https://media.example')
    monkeypatch.setattr(jobs.config, 'ADMIN_IDS_STR', '')
    return user


class Bot:
    def __init__(self):
        self.messages = []
    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return type('Message', (), {'message_id': len(self.messages)})()
    async def send_document(self, **kwargs):
        self.messages.append(kwargs)
        return type('Message', (), {'message_id': len(self.messages)})()
    async def send_video(self, **kwargs):
        self.messages.append(kwargs)
        return type('Message', (), {'message_id': len(self.messages)})()


def provider(handler):
    from happyfox_neironych import Client, Settings
    return Client(Settings(api_key='test', enabled=True, base_url='https://api.example.test'), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_confirmed_rejection_refunds_once_without_creating_another_task(prepared_db, monkeypatch):
    from bot import database
    from bot.services import neironych_jobs as jobs, neironych_routing as routing
    from happyfox_neironych import image_request
    seen = []
    def handler(r):
        seen.append(r)
        return httpx.Response(422, json={'detail': 'invalid_request_contract'})
    monkeypatch.setattr(routing, 'client', provider(handler))
    req = image_request('nano-banana-2', 'photo', key='happyfox-job-123')
    task_id = await jobs.enqueue_telegram(prepared_db, 501, req, product='banana_2', cost=3)
    bot = Bot()
    await jobs.process_telegram_task(bot, task_id)
    await jobs.process_telegram_task(bot, task_id)
    user = await database.get_or_create_user(501)
    assert user.credits == 10
    assert len(seen) == 1
    assert len(bot.messages) == 1
    assert (await database.get_task_by_id(task_id)).status == 'failed'


@pytest.mark.asyncio
async def test_unknown_image_outcome_is_held_with_original_request_and_no_refund(prepared_db, monkeypatch):
    from bot import database
    from bot.services import neironych_jobs as jobs, neironych_routing as routing
    from happyfox_neironych import image_request
    seen = []
    def handler(r):
        seen.append(r)
        raise httpx.ReadTimeout('timeout', request=r)
    monkeypatch.setattr(routing, 'client', provider(handler))
    req = image_request('nano-banana-pro', 'photo', key='happyfox-job-456')
    task_id = await jobs.enqueue_telegram(prepared_db, 501, req, product='banana_pro', cost=3)
    bot = Bot()
    await jobs.process_telegram_task(bot, task_id)
    await jobs.process_telegram_task(bot, task_id)
    task = await database.get_task_by_id(task_id)
    assert (await database.get_or_create_user(501)).credits == 7
    assert len(seen) == 1
    assert task.status != 'failed'
    metadata = json.loads(task.request_data)
    assert metadata['native_operation']['phase'] == 'held'
    assert metadata['native_operation']['request'] == req.to_dict()
    assert len(bot.messages) == 1


@pytest.mark.asyncio
async def test_text_result_is_delivered_once_as_plain_text(prepared_db, monkeypatch):
    from bot import database
    from bot.services import neironych_jobs as jobs, neironych_routing as routing
    from happyfox_neironych import text_request
    monkeypatch.setattr(routing, 'client', provider(lambda r: httpx.Response(200, json={'choices': [{'message': {'content': '<b>not HTML</b>'}, 'finish_reason': 'stop'}]})))
    req = text_request('glm-5.3-flash', 'answer', key='happyfox-text-123')
    task_id = await jobs.enqueue_telegram(prepared_db, 501, req, product='glm-5.3-flash', cost=0)
    bot = Bot()
    await jobs.process_telegram_task(bot, task_id)
    await jobs.process_telegram_task(bot, task_id)
    assert len(bot.messages) == 1
    assert '<b>not HTML</b>' in bot.messages[0]['text']
    assert bot.messages[0]['parse_mode'] is None
    assert (await database.get_task_by_id(task_id)).status == 'completed'
