import asyncio
import json

import httpx
import pytest


class Journal:
    def __init__(self, request):
        from happyfox_neironych.lifecycle import new_operation
        self.value = json.dumps(new_operation(request))

    async def load(self):
        return self.value

    async def replace(self, expected, value):
        if self.value != expected:
            return False
        self.value = value
        return True


def client(handler):
    from happyfox_neironych import Client, Settings
    return Client(Settings(api_key='synthetic', enabled=True, base_url='https://api.example.test'), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_video_restart_reconciles_same_saved_id_without_another_post(tmp_path):
    from happyfox_neironych import video_request
    from happyfox_neironych.lifecycle import Artifacts, advance
    calls = []
    def handler(r):
        calls.append(r)
        if r.method == 'POST':
            return httpx.Response(202, json={'request_id': 'original-id'})
        if r.url.path.endswith('/content'):
            return httpx.Response(200, headers={'content-type': 'video/mp4'}, content=b'\0\0\0\x20ftypisom' + b'x' * 64)
        return httpx.Response(200, json={'request_id': 'original-id', 'status': 'done'})
    req = video_request('seedance-2.0', 'scene', key='stable-operation-123', duration=4)
    journal = Journal(req)
    artifacts = Artifacts(tmp_path, 'https://media.example/results')
    assert (await advance(journal, client(handler), artifacts, now=1000))['phase'] == 'waiting'
    result = await advance(journal, client(handler), artifacts, now=1020)
    assert result['phase'] == 'ready'
    assert result['assets'][0]['url'].startswith('https://media.example/results/')
    assert sum(r.method == 'POST' for r in calls) == 1


@pytest.mark.asyncio
async def test_unknown_video_post_replays_exact_original_body_and_key(tmp_path):
    from happyfox_neironych import video_request
    from happyfox_neironych.lifecycle import Artifacts, advance
    calls = []
    def handler(r):
        calls.append(r)
        if len(calls) == 1:
            raise httpx.ReadTimeout('synthetic', request=r)
        return httpx.Response(202, json={'request_id': 'original-id'})
    req = video_request('seedance-2.5', 'scene', key='stable-operation-123', duration=4)
    journal = Journal(req)
    artifacts = Artifacts(tmp_path)
    first = await advance(journal, client(handler), artifacts, now=1000)
    assert first['phase'] == 'sending'
    second = await advance(journal, client(handler), artifacts, now=1020)
    assert second['phase'] == 'waiting'
    assert calls[0].content == calls[1].content == req.body.encode()
    assert calls[0].headers['idempotency-key'] == calls[1].headers['idempotency-key']


@pytest.mark.asyncio
async def test_unknown_image_or_text_is_held_not_refunded_or_regenerated(tmp_path):
    from happyfox_neironych import image_request, text_request
    from happyfox_neironych.lifecycle import Artifacts, advance
    for req in (image_request('nano-banana-2', 'photo', key='image-key-123'), text_request('glm-5.3-flash', 'text', key='text-key-123')):
        calls = []
        def handler(r):
            calls.append(r)
            raise httpx.ReadTimeout('synthetic', request=r)
        journal = Journal(req)
        result = await advance(journal, client(handler), Artifacts(tmp_path), now=1000)
        assert result['phase'] == 'held'
        assert (await advance(journal, client(handler), Artifacts(tmp_path), now=99999))['phase'] == 'held'
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_expired_sync_submission_lease_does_not_trigger_second_post(tmp_path):
    from happyfox_neironych import image_request
    from happyfox_neironych.lifecycle import Artifacts, advance
    journal = Journal(image_request('nano-banana-pro', 'photo', key='image-key-123'))
    value = json.loads(journal.value)
    value.update(phase='sending', lease_until=999)
    journal.value = json.dumps(value)
    calls = []
    def handler(r):
        calls.append(r)
        raise AssertionError('must not resubmit')
    assert (await advance(journal, client(handler), Artifacts(tmp_path), now=1000))['phase'] == 'held'
    assert calls == []


@pytest.mark.asyncio
async def test_two_workers_claim_one_submission_and_terminal_failure_is_explicit(tmp_path):
    from happyfox_neironych import video_request
    from happyfox_neironych.lifecycle import Artifacts, advance
    calls = []
    async def handler(r):
        calls.append(r)
        await asyncio.sleep(0.01)
        return httpx.Response(422, json={'detail': 'invalid_request_contract'})
    journal = Journal(video_request('seedance-2.0', 'scene', key='video-key-123', duration=4))
    c = client(handler)
    await asyncio.gather(advance(journal, c, Artifacts(tmp_path), now=1000), advance(journal, c, Artifacts(tmp_path), now=1000))
    assert json.loads(journal.value)['phase'] == 'failed'
    assert len(calls) == 1
