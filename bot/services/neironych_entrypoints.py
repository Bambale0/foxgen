"""Translate existing product inputs before durable native submission."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from happyfox_neironych import ContractError, image_request, video_request
from . import neironych_jobs as jobs, neironych_routing as routing

logger = logging.getLogger(__name__)


async def image(
    *, user: Any, telegram_id: int, product: str, prompt: str, ratio: str,
    references: list[str], quality: str, cost: float,
    metadata: dict[str, Any] | None = None, **lineage: Any,
) -> dict[str, Any] | None:
    provider_model = await routing.media_model(product)
    if provider_model is None:
        return None
    if provider_model == 'nano-banana-2' and (
        len(references) > 3
        or ratio not in {'1:1', '16:9', '9:16', '4:3', '3:4'}
        or str(quality).casefold() not in {'1k', '2k', '4k'}
    ):
        logger.info(
            'neironych_capability_fallback product=%s provider_model=%s reason=banana2_input_contract',
            product,
            provider_model,
        )
        return None
    key = f'happyfox-image-{uuid.uuid4().hex}'
    options: dict[str, Any] = {'images': references, 'ratio': ratio}
    quality_lower = str(quality or "").lower()
    if quality_lower in {'1k', '2k', '4k'}:
        options['resolution'] = quality_lower
    elif (
        provider_model == 'gpt-image-2.5-sunburst'
        and quality_lower in {'basic', 'auto', 'low', 'medium', 'high'}
    ):
        # GPT image quality and geometry are independent. Preserve the chosen
        # aspect ratio; "basic" is the HappyFox label for provider auto quality.
        options['quality'] = 'auto' if quality_lower == 'basic' else quality_lower
    else:
        raise ContractError('Choose a supported image resolution')
    request = image_request(provider_model, prompt, key=key, **options)
    task_id = await jobs.enqueue_telegram(user, telegram_id, request, product=product, cost=cost,
        metadata=metadata, original_prompt=prompt, **lineage)
    return {'status': 'queued', 'task_id': task_id, 'local_task_id': task_id,
            'runtime_img_service': product, 'model_label': request.model.label, 'provider': 'neironych'}


def video_options(
    *, product: str, generation_type: str, duration: int, ratio: str, resolution: str,
    images: list[str] | None = None, videos: list[str] | None = None,
    audios: list[str] | None = None, start: str | None = None, end: str | None = None,
    mode: str = 'auto', generate_audio: bool | None = None,
) -> dict[str, Any]:
    images, videos, audios = list(images or []), list(videos or []), list(audios or [])
    # Preserve additional references instead of silently dropping them. A lone
    # photo is a start frame; reference mode never mixes frame fields.
    if start and (generation_type != 'imgtxt' or images or videos or audios) and not end:
        if start not in images:
            images.insert(0, start)
        start = None
    if product == 'seedance_2_5' and (start or mode == 'edit'):
        ratio = 'adaptive'
    result = {'duration': duration, 'ratio': ratio, 'resolution': resolution,
              'images': images, 'videos': videos, 'audios': audios,
              'start_image': start, 'end_image': end, 'mode': mode}
    if product.startswith('seedance_') and generate_audio is None:
        generate_audio = True
    if generate_audio is not None:
        result['generate_audio'] = generate_audio
    return result


def seedance25_native_options(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Translate the existing Seedance 2.5 UX only when partner semantics match."""
    if (
        bool(payload.get('return_last_frame'))
        or str(payload.get('output_format') or 'mp4').lower() != 'mp4'
        or bool(payload.get('web_search'))
        or bool(payload.get('nsfw_checker'))
        or payload.get('generate_audio') is False
    ):
        return None

    scenario = str(payload.get('scenario') or 'text')
    ratio = str(payload.get('ratio') or '16:9')
    if scenario in {'text', 'multimodal'} and ratio == 'adaptive':
        # Current partner contract explicitly forbids adaptive for text/ref mode.
        return None
    generation_type = (
        'text'
        if scenario == 'text'
        else 'imgtxt'
        if scenario in {'first_frame', 'first_last'}
        else 'video'
    )
    return video_options(
        product='seedance_2_5',
        generation_type=generation_type,
        duration=int(payload.get('duration', 5)),
        ratio=ratio,
        resolution=str(payload.get('resolution') or '720p'),
        images=list(payload.get('image_urls') or []),
        videos=list(payload.get('video_urls') or []),
        audios=list(payload.get('audio_urls') or []),
        start=payload.get('first_frame'),
        end=payload.get('last_frame'),
        mode='reference' if scenario == 'multimodal' else 'auto',
        generate_audio=True,
    )


async def video(
    *, user: Any, telegram_id: int, product: str, prompt: str, cost: float,
    options: dict[str, Any], metadata: dict[str, Any] | None = None, **lineage: Any,
) -> dict[str, Any] | None:
    provider_model = await routing.media_model(product)
    if provider_model is None:
        return None
    if product == 'grok_imagine_v15':
        if not options.get('start_image') and not options.get('images'):
            # Preserve the existing HappyFox Grok product contract: image-to-video.
            return None
        if str(options.get('resolution') or '').lower() == '1080p':
            logger.info(
                'neironych_capability_fallback product=%s provider_model=%s reason=grok_i2v_1080p',
                product,
                provider_model,
            )
            return None
    request = video_request(
        provider_model,
        prompt,
        key=f'happyfox-video-{uuid.uuid4().hex}',
        **options,
    )
    task_id = await jobs.enqueue_telegram(user, telegram_id, request, product=product, cost=cost,
        metadata=metadata, original_prompt=prompt, **lineage)
    return {'status': 'queued', 'task_id': task_id, 'cost': cost, 'task_type': 'video',
            'provider': 'neironych', 'model_label': request.model.label}
