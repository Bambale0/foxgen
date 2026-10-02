"""HappyFox operational routing; prices and wallet ownership stay unchanged."""
from __future__ import annotations

import json
import time
from typing import Any

from happyfox_neironych import Client, ContractError, MODELS, ProviderError

SETTING_KEY = 'neironych_provider'
# Technical compatibility IDs, not a failover policy. A Pro request never maps to NB2.
MEDIA_ALIASES = {
    'banana_2': 'nano-banana-2',
    'banana_pro': 'nano-banana-pro',
    'nanobanana': 'nano-banana-pro',
    'flux_pro': 'gpt-image-2.5-sunburst',
    'grok_imagine_v15': 'grok-imagine-video-1.5',
    'seedance_2': 'seedance-2.0',
    'seedance_2_5': 'seedance-2.5',
}
TEXT_MODELS = tuple(key for key, spec in MODELS.items() if spec.kind == 'text')
client = Client()
_catalog: set[str] | None = None
_catalog_until = 0.0
_snapshot: dict[str, Any] = {}


def invalidate_catalog() -> None:
    global _catalog, _catalog_until
    _catalog, _catalog_until = None, 0.0


async def live_models() -> set[str]:
    global _catalog, _catalog_until
    if _catalog is None or _catalog_until <= time.monotonic():
        _catalog = await client.list_models()
        _catalog_until = time.monotonic() + 60
    return set(_catalog)


async def configuration() -> dict[str, Any]:
    from bot.database import get_bot_setting

    raw = await get_bot_setting(SETTING_KEY, None)
    settings: dict[str, Any] = {
        'version': 1, 'media_enabled': False, 'text_enabled': False,
        'text_model': 'glm-5.3-flash',
    }
    if raw is not None:
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            raise ContractError('Invalid Neironych routing configuration') from None
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ContractError('Unknown Neironych routing configuration version')
        settings.update(value)
    if any(type(settings[key]) is not bool for key in ('media_enabled', 'text_enabled')):
        raise ContractError('Provider enable flags must be booleans')
    if settings['text_model'] not in TEXT_MODELS:
        raise ContractError('Unsupported text model setting')
    global _snapshot
    _snapshot = settings
    return dict(settings)


async def _require(model: str) -> str:
    if not client.settings.ready:
        raise ProviderError('provider_not_configured')
    if model not in await live_models():
        raise ProviderError('model_not_available')
    return model


async def media_model(product: str) -> str | None:
    model = MEDIA_ALIASES.get(product)
    if not model or not (await configuration())['media_enabled']:
        return None
    # A configured route fails closed. Catalog/key failure is not a KIE fallback.
    return await _require(model)


async def text_model(selected: str | None = None) -> str | None:
    settings = await configuration()
    if not settings['text_enabled']:
        return None
    model = selected or settings['text_model']
    if model not in TEXT_MODELS:
        raise ContractError('Unsupported text model selection')
    return await _require(model)


def text_picker_enabled() -> bool:
    return bool(_snapshot.get('text_enabled') and client.settings.ready)


def media_label(product: str, fallback: str) -> str:
    """Selection screens only. Historical results use their persisted provider ID."""
    if _snapshot.get('media_enabled') and client.settings.ready and product in MEDIA_ALIASES:
        return MODELS[MEDIA_ALIASES[product]].label
    return fallback


async def configure(section: str, value: bool | str, *, actor: int) -> dict[str, Any]:
    from bot.database import set_bot_setting

    settings = await configuration()
    if section == 'model':
        if value not in TEXT_MODELS:
            raise ContractError('Unsupported text model')
        settings['text_model'] = value
    elif section in ('media', 'text') and type(value) is bool:
        if value:
            if not client.settings.ready:
                raise ProviderError('provider_not_configured')
            invalidate_catalog()
            required = set(MEDIA_ALIASES.values()) if section == 'media' else set(TEXT_MODELS)
            if required - await live_models():
                raise ProviderError('required_models_not_available')
        settings[section + '_enabled'] = value
    else:
        raise ContractError('Use media/text on/off or model <model ID>')
    settings['updated_by'] = int(actor)
    if not await set_bot_setting(SETTING_KEY, json.dumps(settings, ensure_ascii=False, sort_keys=True), updated_by_telegram_id=actor):
        raise RuntimeError('Provider configuration was not saved')
    global _snapshot
    _snapshot = settings
    return dict(settings)
