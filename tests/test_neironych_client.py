import base64
import io

import httpx
import pytest
from PIL import Image


def configured(handler, **kwargs):
    from happyfox_neironych import Client, Settings
    return Client(Settings(api_key='never-print-this-key', enabled=True, base_url='https://api.example.test', **kwargs), transport=httpx.MockTransport(handler))


def jpeg():
    out = io.BytesIO()
    Image.new('RGB', (8, 8)).save(out, 'JPEG')
    return out.getvalue()


@pytest.mark.asyncio
async def test_image_edit_sends_same_body_and_returns_actual_jpeg_format():
    from happyfox_neironych import image_request
    req = image_request('nano-banana-pro', 'Change "label"\nonly', key='logical-task-123', images=['https://media.example/r.png'])
    def handler(request):
        assert request.headers['authorization'] == 'Bearer never-print-this-key'
        assert request.headers['idempotency-key'] == 'logical-task-123'
        assert request.content == req.body.encode()
        assert request.url.path == '/v1/images/edits'
        return httpx.Response(200, headers={'X-Request-Id': 'image-123'}, json={'data': [{'b64_json': base64.b64encode(jpeg()).decode()}]})
    result = await configured(handler).submit(req)
    assert result.request_id == 'image-123'
    assert result.images[0].content_type == 'image/jpeg'
    assert result.images[0].extension == 'jpg'
    assert result.images[0].data == jpeg()


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['glm-5.3-flash', 'gpt-5.6-luna', 'grok-4.5'])
async def test_each_text_protocol_extracts_all_text_blocks(model):
    from happyfox_neironych import text_request
    req = text_request(model, 'Ready?', key='logical-text-123')
    def handler(request):
        assert request.url.path == req.endpoint
        if req.endpoint.endswith('/chat/completions'):
            return httpx.Response(200, json={'choices': [{'message': {'content': 'Ready.'}, 'finish_reason': 'stop'}]})
        return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'reasoning'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Ready.'}]}]})
    assert (await configured(handler).submit(req)).text == 'Ready.'


@pytest.mark.asyncio
async def test_video_keeps_authorization_on_configured_origin(tmp_path):
    from happyfox_neironych import video_request
    seen = []
    mp4 = b'\x00\x00\x00\x20ftypisom' + b'x' * 64
    def handler(request):
        seen.append(request)
        assert request.url.host == 'api.example.test'
        assert request.headers['authorization'] == 'Bearer never-print-this-key'
        if request.method == 'POST':
            return httpx.Response(202, json={'request_id': 'job-123'})
        if request.url.path.endswith('/content'):
            return httpx.Response(200, headers={'Content-Type': 'video/mp4'}, content=mp4)
        return httpx.Response(200, json={'request_id': 'job-123', 'status': 'done', 'video': {'url': 'https://evil.example/steal'}, 'usage': {'billed_seconds': 6}})
    c = configured(handler)
    outcome = await c.submit(video_request('seedance-2.0', 'scene', key='video-logical-123', duration=4))
    state = await c.video_status(outcome.request_id)
    path = await c.download_video(outcome.request_id, tmp_path / 'result.mp4')
    assert state.status == 'done'
    assert state.billed_seconds == 6
    assert path.read_bytes() == mp4
    assert len(seen) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_id', ['../admin', 'https://evil.example', 'id?a=b', ''])
async def test_invalid_video_identifiers_never_become_paths(bad_id):
    from happyfox_neironych import ProviderError, video_request
    c = configured(lambda r: httpx.Response(202, json={'request_id': bad_id}))
    with pytest.raises(ProviderError) as caught:
        await c.submit(video_request('seedance-2.0', 'scene', key='video-logical-123', duration=4))
    assert caught.value.uncertain


@pytest.mark.asyncio
async def test_unknown_sync_submission_is_not_retried_or_echoed():
    from happyfox_neironych import ProviderError, image_request
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(503, json={'error': {'type': 'submission_outcome_unknown', 'message': 'never-print-this-key PRIVATE PROMPT'}, 'request_id': 'request-123'})
    with pytest.raises(ProviderError) as caught:
        await configured(handler).submit(image_request('nano-banana-2', 'PRIVATE PROMPT', key='image-logical-123'))
    assert caught.value.uncertain
    assert caught.value.request_id == 'request-123'
    assert 'never-print-this-key' not in str(caught.value)
    assert 'PRIVATE PROMPT' not in str(caught.value)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_partial_or_malformed_text_is_not_success():
    from happyfox_neironych import ProviderError, text_request
    req = text_request('gpt-5.6-luna', 'text', key='text-logical-123')
    c = configured(lambda r: httpx.Response(200, json={'status': 'incomplete', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'part'}]}]}))
    with pytest.raises(ProviderError, match='incomplete'):
        await c.submit(req)


@pytest.mark.asyncio
async def test_status_identity_retry_after_and_redirect_are_checked(tmp_path):
    from happyfox_neironych import ProviderError
    with pytest.raises(ProviderError):
        await configured(lambda r: httpx.Response(200, json={'request_id': 'not-my-job', 'status': 'done'})).video_status('my-job')
    with pytest.raises(ProviderError) as caught:
        await configured(lambda r: httpx.Response(429, headers={'Retry-After': '15'}, json={'error': {'type': 'provider_rate_limited'}})).video_status('my-job')
    assert caught.value.retryable
    assert caught.value.retry_after == 15
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={'Location': 'https://evil.example/steal'})
    with pytest.raises(ProviderError):
        await configured(handler).download_video('my-job', tmp_path / 'result.mp4')
    assert len(seen) == 1


def test_secret_files_and_disabled_bootstrap(monkeypatch, tmp_path):
    from happyfox_neironych import Settings
    for prefix in ('NEURONYCH_', 'NEIRONYCH_'):
        for suffix in ('API_KEY', 'API_KEY_FILE', 'API_ENABLED'):
            monkeypatch.delenv(prefix + suffix, raising=False)
    monkeypatch.setenv('NEURONYCH_API_KEY_FILE', str(tmp_path / 'absent'))
    assert not Settings.from_env().enabled
    keyfile = tmp_path / 'key'
    keyfile.write_text('never-print-this-key')
    monkeypatch.setenv('NEURONYCH_API_KEY_FILE', str(keyfile))
    monkeypatch.setenv('NEURONYCH_API_ENABLED', 'true')
    settings = Settings.from_env()
    assert settings.ready
    assert 'never-print-this-key' not in repr(settings)


@pytest.mark.asyncio
async def test_models_are_discovered_without_auth_and_malformed_images_are_rejected():
    from happyfox_neironych import ProviderError, image_request
    def handler(request):
        if request.url.path == '/v1/models':
            assert 'authorization' not in request.headers
            return httpx.Response(200, json={'data': [{'id': 'nano-banana-pro'}]})
        return httpx.Response(200, json={'data': [{'b64_json': 'SGVsbG8='}]})
    c = configured(handler)
    assert await c.list_models() == {'nano-banana-pro'}
    with pytest.raises(ProviderError):
        await c.submit(image_request('nano-banana-pro', 'photo', key='image-logical-123'))
