import json
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_disabled_route_preserves_kie_but_enabled_route_never_silently_falls_back(monkeypatch):
    from bot.services import neironych_routing as routing
    from happyfox_neironych import ProviderError
    config = {'version': 1, 'media_enabled': False, 'text_enabled': False, 'text_model': 'glm-5.3-flash'}
    async def get_setting(key, default=None):
        return json.dumps(config)
    monkeypatch.setattr('bot.database.get_bot_setting', get_setting)
    monkeypatch.setattr(routing, 'client', SimpleNamespace(settings=SimpleNamespace(ready=False)))
    assert await routing.media_model('banana_pro') is None
    config['media_enabled'] = True
    with pytest.raises(ProviderError, match='provider_not_configured'):
        await routing.media_model('banana_pro')
    assert await routing.media_model('wan_27') is None


@pytest.mark.asyncio
async def test_missing_live_model_does_not_switch_to_another_provider(monkeypatch):
    from bot.services import neironych_routing as routing
    from happyfox_neironych import ProviderError
    async def get_setting(key, default=None):
        return json.dumps({'version': 1, 'media_enabled': True})
    async def models():
        return {'nano-banana-2'}
    monkeypatch.setattr('bot.database.get_bot_setting', get_setting)
    monkeypatch.setattr(routing, 'client', SimpleNamespace(settings=SimpleNamespace(ready=True), list_models=models))
    routing.invalidate_catalog()
    assert await routing.media_model('banana_2') == 'nano-banana-2'
    with pytest.raises(ProviderError, match='model_not_available'):
        await routing.media_model('banana_pro')


@pytest.mark.asyncio
async def test_operator_enable_is_audited_and_checks_live_contracts(monkeypatch):
    from bot.services import neironych_routing as routing
    from happyfox_neironych import MODELS
    writes = []
    async def get_setting(key, default=None):
        return None
    async def set_setting(key, value, **kwargs):
        writes.append((key, json.loads(value), kwargs))
        return True
    async def models():
        return set(MODELS)
    monkeypatch.setattr('bot.database.get_bot_setting', get_setting)
    monkeypatch.setattr('bot.database.set_bot_setting', set_setting)
    monkeypatch.setattr(routing, 'client', SimpleNamespace(settings=SimpleNamespace(ready=True), list_models=models))
    routing.invalidate_catalog()
    await routing.configure('media', True, actor=42)
    assert writes[0][1]['media_enabled'] is True
    assert writes[0][2]['updated_by_telegram_id'] == 42


def test_dynamic_gpt_image_label_tracks_provider_enable(monkeypatch):
    from bot.services import neironych_routing as routing
    from bot.keyboards import get_image_model_label

    monkeypatch.setattr(routing, "_snapshot", {"media_enabled": False})
    monkeypatch.setattr(routing.client, "settings", SimpleNamespace(ready=True))
    assert get_image_model_label("flux_pro") == "GPT Image 2"

    monkeypatch.setattr(routing, "_snapshot", {"media_enabled": True})
    assert get_image_model_label("flux_pro") == "GPT Image 2.5 Sunburst"


@pytest.mark.asyncio
async def test_capability_mismatch_keeps_existing_provider_without_truncating(monkeypatch):
    from bot.services import neironych_entrypoints as entry

    async def route(product):
        return {
            "banana_2": "nano-banana-2",
            "grok_imagine_v15": "grok-imagine-video-1.5",
        }[product]

    monkeypatch.setattr(entry.routing, "media_model", route)

    image = await entry.image(
        user=SimpleNamespace(id=1, telegram_id=1),
        telegram_id=1,
        product="banana_2",
        prompt="keep every reference",
        ratio="1:1",
        references=[
            "https://media.example/1.png",
            "https://media.example/2.png",
            "https://media.example/3.png",
            "https://media.example/4.png",
        ],
        quality="2K",
        cost=2,
    )
    assert image is None

    video = await entry.video(
        user=SimpleNamespace(id=1, telegram_id=1),
        telegram_id=1,
        product="grok_imagine_v15",
        prompt="animate",
        cost=3,
        options=entry.video_options(
            product="grok_imagine_v15",
            generation_type="imgtxt",
            duration=5,
            ratio="16:9",
            resolution="1080p",
            start="https://media.example/start.png",
        ),
    )
    assert video is None


@pytest.mark.asyncio
async def test_gpt_image_quality_preserves_requested_ratio(monkeypatch):
    from bot.services import neironych_entrypoints as entry

    captured = {}

    async def route(product):
        assert product == "flux_pro"
        return "gpt-image-2.5-sunburst"

    async def enqueue(user, telegram_id, request, **kwargs):
        captured["request"] = request
        return "nr-test"

    monkeypatch.setattr(entry.routing, "media_model", route)
    monkeypatch.setattr(entry.jobs, "enqueue_telegram", enqueue)

    result = await entry.image(
        user=SimpleNamespace(id=1, telegram_id=1),
        telegram_id=1,
        product="flux_pro",
        prompt="wide banner",
        ratio="16:9",
        references=[],
        quality="basic",
        cost=2,
    )

    assert result is not None
    assert captured["request"].payload["size"] == "2048x1152"
    assert captured["request"].payload["quality"] == "auto"
