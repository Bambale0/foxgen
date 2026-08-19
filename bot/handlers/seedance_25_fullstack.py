"""Full-stack Seedance 2.5 runtime for the experimental feature branch.

This layer intentionally avoids changing the established generic Mini App and
Kie webhook flows. It patches only the Seedance 2.5 seams:

* admin-only Mini App bootstrap metadata and generation launch;
* dedicated Kie callback capable of video + returned last frame and MOV;
* polling reconciliation if the callback is delayed/lost;
* real ffprobe validation for Telegram video/audio references;
* support for advanced ``asset://`` inputs for admin testing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, FSInputFile
from PIL import Image

from bot import db as db_backend
from bot.config import config
from bot.services.kie_market_service import kie_market_service
from bot.services.media_input_utils import resolve_local_upload_path
from bot.services.preset_manager import preset_manager
from bot.services.seedance_25_service import (
    get_seedance25_callback_url,
    seedance_25_service,
)

from . import generation as generation_module
from . import seedance_25_preview as preview_module

logger = logging.getLogger(__name__)
router = Router(name="seedance_25_fullstack")

MODEL_KEY = "seedance_2_5"
MODEL_LABEL = "Seedance 2.5"

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "gif"}
VIDEO_EXTS = {"mp4", "mov"}
AUDIO_EXTS = {"wav", "mp3"}

MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MIN_SIDE = 300
MAX_SIDE = 6000
MIN_RATIO = 0.4
MAX_RATIO = 2.5
MIN_VIDEO_PIXELS = 640 * 640
MAX_VIDEO_PIXELS = 834 * 1112
MIN_MEDIA_DURATION = 2.0
MAX_MEDIA_DURATION = 30.0
MAX_TOTAL_VIDEO_DURATION = 30.0
MIN_FPS = 24.0
MAX_FPS = 60.0

_RECONCILE_TASK_KEY = "seedance25_reconcile_task"


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and config.is_admin(int(user_id)))


def _clean_urls(values: Iterable[Any] | None, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    if limit is not None and len(result) > limit:
        raise ValueError(f"Слишком много референсов: максимум {limit}")
    return result


def _is_provider_source(value: str) -> bool:
    candidate = str(value or "").strip()
    return candidate.startswith("asset://") or candidate.startswith(("https://", "http://"))


def _validate_provider_sources(values: Iterable[str]) -> None:
    for value in values:
        if not _is_provider_source(value):
            raise ValueError(f"Некорректный URL/asset: {value[:120]}")


def _extension_from_url(value: str) -> str:
    path = urlsplit(str(value or "")).path
    return Path(path).suffix.lower().lstrip(".")


def _float_fraction(value: Any) -> float:
    text = str(value or "0").strip()
    if not text or text in {"0/0", "N/A"}:
        return 0.0
    try:
        return float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        try:
            return float(text)
        except (TypeError, ValueError):
            return 0.0


async def _ffprobe(path: str) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name,size:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration",
        "-of",
        "json",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise ValueError(
            "Не удалось прочитать медиа через ffprobe: "
            + stderr.decode("utf-8", errors="ignore")[:300]
        )
    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe вернул некорректные метаданные") from exc


def _probe_duration(meta: dict[str, Any], kind: str) -> float:
    streams = meta.get("streams") or []
    for stream in streams:
        if str(stream.get("codec_type") or "") == kind:
            try:
                duration = float(stream.get("duration") or 0)
            except (TypeError, ValueError):
                duration = 0.0
            if duration > 0:
                return duration
    try:
        return float((meta.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def _probe_video_stream(meta: dict[str, Any]) -> dict[str, Any]:
    for stream in meta.get("streams") or []:
        if str(stream.get("codec_type") or "") == "video":
            return stream
    raise ValueError("Видео-поток не найден")


def _validate_dimensions(width: int, height: int, *, video: bool) -> None:
    if width < MIN_SIDE or height < MIN_SIDE or width > MAX_SIDE or height > MAX_SIDE:
        raise ValueError("Размеры должны быть 300–6000 px по каждой стороне")
    ratio = width / height
    if not MIN_RATIO <= ratio <= MAX_RATIO:
        raise ValueError("Соотношение сторон должно быть в диапазоне 0.4–2.5")
    if video:
        pixels = width * height
        if not MIN_VIDEO_PIXELS <= pixels <= MAX_VIDEO_PIXELS:
            raise ValueError(
                f"Видео содержит {pixels} пикселей на кадр; допустимо {MIN_VIDEO_PIXELS}–{MAX_VIDEO_PIXELS}"
            )


def _validate_image_path(path: str) -> None:
    size = os.path.getsize(path)
    if size > MAX_IMAGE_BYTES:
        raise ValueError("Изображение должно быть меньше 30 MB")
    ext = Path(path).suffix.lower().lstrip(".")
    if ext and ext not in IMAGE_EXTS:
        raise ValueError("Формат изображения: jpeg/png/webp/bmp/tiff/gif")
    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:
        raise ValueError("Не удалось прочитать изображение") from exc
    _validate_dimensions(int(width), int(height), video=False)


async def _validate_video_path(path: str) -> float:
    if os.path.getsize(path) > MAX_VIDEO_BYTES:
        raise ValueError("Видео-референс не должен превышать 200 MB")
    ext = Path(path).suffix.lower().lstrip(".")
    if ext not in VIDEO_EXTS:
        raise ValueError("Видео-референс должен быть MP4 или MOV")

    meta = await _ffprobe(path)
    stream = _probe_video_stream(meta)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    _validate_dimensions(width, height, video=True)

    fps = _float_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    if not MIN_FPS <= fps <= MAX_FPS:
        raise ValueError(f"FPS видео должен быть 24–60; получено {fps:g}")

    duration = _probe_duration(meta, "video")
    if not MIN_MEDIA_DURATION <= duration <= MAX_MEDIA_DURATION:
        raise ValueError(f"Длительность видео должна быть 2–30 секунд; получено {duration:.2f}")
    return duration


async def _validate_audio_path(path: str) -> float:
    if os.path.getsize(path) > MAX_AUDIO_BYTES:
        raise ValueError("Аудио-референс не должен превышать 15 MB")
    ext = Path(path).suffix.lower().lstrip(".")
    if ext not in AUDIO_EXTS:
        raise ValueError("Аудио-референс должен быть WAV или MP3")
    meta = await _ffprobe(path)
    duration = _probe_duration(meta, "audio")
    if not MIN_MEDIA_DURATION <= duration <= MAX_MEDIA_DURATION:
        raise ValueError(f"Длительность аудио должна быть 2–30 секунд; получено {duration:.2f}")
    return duration


async def _validate_local_source(source: str, kind: str) -> float | None:
    path = resolve_local_upload_path(source)
    if not path:
        return None
    if kind == "image":
        _validate_image_path(path)
        return None
    if kind == "video":
        return await _validate_video_path(path)
    if kind == "audio":
        return await _validate_audio_path(path)
    raise ValueError(f"Unknown media kind: {kind}")


async def _validate_seedance_sources(
    *,
    first_frame_url: str | None,
    last_frame_url: str | None,
    image_urls: list[str],
    video_urls: list[str],
    audio_urls: list[str],
) -> None:
    all_sources = [
        *([first_frame_url] if first_frame_url else []),
        *([last_frame_url] if last_frame_url else []),
        *image_urls,
        *video_urls,
        *audio_urls,
    ]
    _validate_provider_sources(all_sources)

    if first_frame_url:
        await _validate_local_source(first_frame_url, "image")
    if last_frame_url:
        await _validate_local_source(last_frame_url, "image")
    for source in image_urls:
        await _validate_local_source(source, "image")

    local_video_duration = 0.0
    for source in video_urls:
        duration = await _validate_local_source(source, "video")
        if duration:
            local_video_duration += duration
    if local_video_duration > MAX_TOTAL_VIDEO_DURATION + 0.01:
        raise ValueError(
            f"Суммарная длительность видео-референсов — максимум 30 секунд; получено {local_video_duration:.2f}"
        )

    for source in audio_urls:
        await _validate_local_source(source, "audio")


def _seedance25_model_meta() -> dict[str, Any]:
    durations = [-1, *range(4, 31)]
    quality_costs = preset_manager.get_video_quality_costs(MODEL_KEY)
    return {
        "id": MODEL_KEY,
        "label": "🧪 Seedance 2.5 (admin)",
        "description": "Полный admin-preview Bytedance: first/last frame, мультимодальные фото/видео/аудио референсы, audio generation и web search",
        "durations": durations,
        "ratios": ["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
        "supports": ["text", "imgtxt", "video"],
        "costs": {
            str(duration): preset_manager.get_video_cost_with_quality(
                MODEL_KEY,
                5 if duration == -1 else duration,
                "720p",
            )
            for duration in durations
        },
        "quality_costs": quality_costs,
        "seedance25_resolutions": ["480p", "720p"],
        "seedance25_output_formats": ["mp4", "mov"],
        "seedance25_scenarios": ["text", "first_frame", "first_last", "multimodal"],
        "supports_generate_audio": True,
        "supports_return_last_frame": True,
        "supports_web_search": True,
        "supports_nsfw_checker": True,
        "supports_auto_duration": True,
        "camera_control_via_prompt": True,
        "max_image_references": 30,
        "max_video_references": 10,
        "max_audio_references": 10,
        "admin_only": True,
    }


def _json_response_payload(response: web.StreamResponse) -> dict[str, Any] | None:
    body = getattr(response, "body", None)
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None


async def _miniapp_seedance25_generate(request: web.Request, body: dict[str, Any]) -> web.Response:
    miniapp_module = __import__("bot.miniapp", fromlist=["*"])
    telegram_id, ctx = await miniapp_module._get_user_context(
        request.app,
        str(body.get("init_data") or ""),
        body.get("start_param_fallback"),
    )
    if not _is_admin(telegram_id):
        return web.json_response(
            {"ok": False, "error": "Seedance 2.5 сейчас доступна только администраторам"},
            status=403,
        )

    user = ctx["user"]
    prompt = str(body.get("prompt") or "").strip()
    scenario = str(body.get("seedance25_scenario") or "text").strip().lower()
    if scenario not in {"text", "first_frame", "first_last", "multimodal"}:
        return web.json_response({"ok": False, "error": "Некорректный сценарий Seedance 2.5"}, status=400)

    try:
        duration = int(body.get("v_duration", 5))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "Некорректная длительность"}, status=400)

    ratio = str(body.get("v_ratio") or "adaptive").strip().lower()
    resolution = str(body.get("seedance25_resolution") or "720p").strip().lower()
    output_format = str(body.get("seedance25_output_format") or "mp4").strip().lower()
    generate_audio = bool(body.get("seedance25_generate_audio", True))
    return_last_frame = bool(body.get("seedance25_return_last_frame", False))
    web_search = bool(body.get("seedance25_web_search", False))
    nsfw_checker = bool(body.get("seedance25_nsfw_checker", False))

    first_frame = str(body.get("seedance25_first_frame_url") or "").strip() or None
    last_frame = str(body.get("seedance25_last_frame_url") or "").strip() or None
    try:
        image_urls = _clean_urls(body.get("reference_images") or [], 30)
        video_urls = _clean_urls(body.get("v_reference_videos") or [], 10)
        audio_urls = _clean_urls(body.get("seedance25_reference_audio_urls") or [], 10)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    # Scenario itself is the authoritative source of media routing.
    if scenario == "text":
        first_frame = last_frame = None
        image_urls = []
        video_urls = []
        audio_urls = []
        if not prompt:
            return web.json_response({"ok": False, "error": "Для Text-to-Video нужен промпт"}, status=400)
    elif scenario == "first_frame":
        last_frame = None
        image_urls = []
        video_urls = []
        audio_urls = []
        if not first_frame:
            return web.json_response({"ok": False, "error": "Загрузите первый кадр"}, status=400)
    elif scenario == "first_last":
        image_urls = []
        video_urls = []
        audio_urls = []
        if not first_frame or not last_frame:
            return web.json_response({"ok": False, "error": "Загрузите первый и последний кадры"}, status=400)
    else:
        first_frame = last_frame = None
        if not (image_urls or video_urls or audio_urls):
            return web.json_response({"ok": False, "error": "Добавьте хотя бы один мультимодальный референс"}, status=400)

    try:
        await _validate_seedance_sources(
            first_frame_url=first_frame,
            last_frame_url=last_frame,
            image_urls=image_urls,
            video_urls=video_urls,
            audio_urls=audio_urls,
        )
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    # Keep saved-reference freshness consistent with the established Mini App.
    try:
        if first_frame:
            await miniapp_module.touch_saved_references(telegram_id, [first_frame], kind="image")
        if last_frame:
            await miniapp_module.touch_saved_references(telegram_id, [last_frame], kind="image")
        if image_urls:
            await miniapp_module.touch_saved_references(telegram_id, image_urls, kind="image")
        if video_urls:
            await miniapp_module.touch_saved_references(telegram_id, video_urls, kind="video")
        if audio_urls:
            await miniapp_module.touch_saved_references(telegram_id, audio_urls, kind="audio")
    except Exception:
        logger.exception("Seedance 2.5: failed to touch saved references")

    pricing_duration = 5 if duration == -1 else duration
    quote = preset_manager.get_video_cost_with_quality(
        MODEL_KEY,
        pricing_duration,
        resolution,
    )

    result = await seedance_25_service.generate_video(
        prompt=prompt,
        duration=duration,
        aspect_ratio=ratio,
        resolution=resolution,
        first_frame_url=first_frame,
        last_frame_url=last_frame,
        reference_image_urls=image_urls or None,
        reference_video_urls=video_urls or None,
        reference_audio_urls=audio_urls or None,
        return_last_frame=return_last_frame,
        generate_audio=generate_audio,
        output_format=output_format,
        web_search=web_search,
        nsfw_checker=nsfw_checker,
        callBackUrl=get_seedance25_callback_url(),
    )
    if not result or not result.get("task_id"):
        error = result.get("error") if isinstance(result, dict) else "provider response has no task_id"
        return web.json_response({"ok": False, "error": str(error)}, status=502)

    task_id = str(result["task_id"])
    await generation_module.add_generation_task(
        user.id,
        telegram_id,
        task_id,
        "video",
        "no_preset_video",
        model=MODEL_KEY,
        duration=duration,
        aspect_ratio=ratio,
        prompt=prompt,
        cost=quote,
        request_data={
            "source": "miniapp",
            "preview": "seedance_2_5_admin",
            "v_model": MODEL_KEY,
            "v_type": "text" if scenario == "text" else "imgtxt" if scenario in {"first_frame", "first_last"} else "video",
            "seedance25_scenario": scenario,
            "first_frame_url": first_frame,
            "last_frame_url": last_frame,
            "reference_images": image_urls,
            "v_reference_videos": video_urls,
            "reference_audios": audio_urls,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "return_last_frame": return_last_frame,
            "output_format": output_format,
            "web_search": web_search,
            "nsfw_checker": nsfw_checker,
            "admin_price_quote": quote,
            "admin_free": True,
            "provider_model": seedance_25_service.MODEL_NAME,
            "callback_url": get_seedance25_callback_url(),
        },
    )

    return web.json_response(
        {
            "ok": True,
            "status": "queued",
            "task_id": task_id,
            "credits": user.credits,
            "cost": quote,
            "model_label": MODEL_LABEL,
            "admin_free": True,
            "resolution": resolution,
            "duration": duration,
            "aspect_ratio": ratio,
            "scenario": scenario,
        }
    )


def _extract_result_urls(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    result_json = data.get("resultJson") if isinstance(data, dict) else None
    parsed: Any = result_json
    if isinstance(result_json, str):
        try:
            parsed = json.loads(result_json)
        except json.JSONDecodeError:
            parsed = None

    urls: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, str):
            candidate = value.strip()
            if candidate.startswith(("https://", "http://")) and candidate not in urls:
                urls.append(candidate)
            return
        if isinstance(value, list):
            for item in value:
                visit(item, key)
            return
        if isinstance(value, dict):
            preferred = (
                "resultUrls",
                "result_urls",
                "videoUrl",
                "video_url",
                "url",
                "lastFrameUrl",
                "last_frame_url",
                "lastFrame",
            )
            for name in preferred:
                if name in value:
                    visit(value.get(name), name)
            for name, item in value.items():
                if name not in preferred:
                    visit(item, name)

    if parsed is not None:
        visit(parsed)
    if isinstance(data, dict):
        for key in ("resultUrls", "result_urls", "videoUrl", "video_url", "lastFrameUrl", "last_frame_url"):
            visit(data.get(key), key)
    return urls


def _classify_results(urls: list[str], request_data: dict[str, Any]) -> tuple[str | None, str | None]:
    if not urls:
        return None, None
    output_format = str(request_data.get("output_format") or "mp4").lower()
    return_last = bool(request_data.get("return_last_frame"))

    video_url = next((u for u in urls if _extension_from_url(u) in {output_format, *VIDEO_EXTS}), None)
    image_url = next((u for u in urls if _extension_from_url(u) in IMAGE_EXTS), None)
    if video_url is None:
        video_url = urls[0]
    if return_last and image_url is None and len(urls) > 1:
        image_url = next((u for u in urls if u != video_url), urls[1])
    return video_url, image_url


async def _download_to_temp(url: str, suffix: str, max_bytes: int = 50 * 1024 * 1024) -> str | None:
    tmp_path: str | None = None
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"}) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                if resp.status != 200:
                    return None
                if resp.content_length and resp.content_length > max_bytes:
                    return None
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp_path = tmp.name
                downloaded = 0
                try:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            raise ValueError("result too large")
                        tmp.write(chunk)
                finally:
                    tmp.close()
        return tmp_path
    except Exception:
        logger.exception("Seedance 2.5 result download failed: %s", url)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return None


async def _send_seedance25_results(
    app: web.Application,
    telegram_id: int,
    task_id: str,
    video_url: str,
    last_frame_url: str | None,
    request_data: dict[str, Any],
) -> None:
    bot = app["bot"]
    output_format = str(request_data.get("output_format") or _extension_from_url(video_url) or "mp4").lower()
    resolution = str(request_data.get("resolution") or "720p")
    duration = request_data.get("duration") or request_data.get("v_duration")
    scenario = str(request_data.get("seedance25_scenario") or "text")
    caption = (
        "✅ <b>Seedance 2.5 готово</b>\n"
        f"• ID: <code>{task_id}</code>\n"
        f"• Сценарий: <code>{scenario}</code>\n"
        f"• Качество: <code>{resolution}</code>\n"
        f"• Формат: <code>{output_format.upper()}</code>"
    )
    if duration is not None:
        caption += f"\n• Длительность: <code>{'Auto' if int(duration) == -1 else str(duration) + 'с'}</code>"
    caption += "\n• Admin preview: <code>без списания</code>"

    delivered = False
    suffix = ".mov" if output_format == "mov" else ".mp4"
    if output_format == "mp4":
        try:
            await bot.send_video(
                telegram_id,
                video=video_url,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
            )
            delivered = True
        except Exception:
            logger.info("Seedance 2.5 URL video delivery failed; trying file upload")

    if not delivered:
        tmp_path = await _download_to_temp(video_url, suffix=suffix)
        if tmp_path:
            try:
                if output_format == "mp4":
                    await bot.send_video(
                        telegram_id,
                        video=FSInputFile(tmp_path),
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                    )
                else:
                    await bot.send_document(
                        telegram_id,
                        document=FSInputFile(tmp_path, filename=f"seedance25-{task_id}.mov"),
                        caption=caption,
                        parse_mode="HTML",
                    )
                delivered = True
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    if not delivered:
        try:
            await bot.send_message(
                telegram_id,
                caption + f"\n\n🔗 Оригинал:\n{video_url}",
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        except Exception:
            logger.exception("Seedance 2.5 result notification failed")

    if last_frame_url:
        frame_caption = f"🖼 <b>Последний кадр Seedance 2.5</b>\nID: <code>{task_id}</code>"
        try:
            await bot.send_photo(
                telegram_id,
                photo=last_frame_url,
                caption=frame_caption,
                parse_mode="HTML",
            )
        except Exception:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(last_frame_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        if resp.status == 200:
                            raw = await resp.read()
                            await bot.send_photo(
                                telegram_id,
                                photo=BufferedInputFile(raw, filename=f"seedance25-{task_id}-last-frame.png"),
                                caption=frame_caption,
                                parse_mode="HTML",
                            )
                            return
                await bot.send_message(telegram_id, frame_caption + f"\n{last_frame_url}", parse_mode="HTML")
            except Exception:
                logger.exception("Seedance 2.5 last-frame delivery failed")


async def _load_task_row(task_id: str):
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT gt.*, u.telegram_id
            FROM generation_tasks gt
            JOIN users u ON u.id = gt.user_id
            WHERE gt.task_id = ?
            LIMIT 1
            """,
            (task_id,),
        )
        return await cursor.fetchone()


async def _store_task_result(task_id: str, video_url: str | None, urls: list[str], *, success: bool) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE generation_tasks
            SET result_url = ?, result_urls = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (
                video_url,
                json.dumps(urls, ensure_ascii=False),
                "completed" if success else "failed",
                task_id,
            ),
        )
        await db.commit()


async def _process_seedance25_payload(app: web.Application, payload: dict[str, Any]) -> bool:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    task_id = str((data or {}).get("taskId") or payload.get("taskId") or "").strip()
    if not task_id:
        return False

    row = await _load_task_row(task_id)
    if not row or str(row["model"] or "") != MODEL_KEY:
        return False
    if str(row["status"] or "").lower() in {"completed", "failed"}:
        return True

    try:
        request_data = json.loads(row["request_data"] or "{}")
    except (TypeError, json.JSONDecodeError):
        request_data = {}
    request_data.setdefault("duration", row["duration"])

    state = str((data or {}).get("state") or payload.get("state") or "").lower()
    code = int(payload.get("code") or 200)
    fail_msg = str((data or {}).get("failMsg") or payload.get("msg") or "")
    telegram_id = int(row["telegram_id"])

    if state in {"fail", "failed", "error"} or code in {501, 500, 422, 402, 429, 455, 505}:
        await _store_task_result(task_id, None, [], success=False)
        try:
            await app["bot"].send_message(
                telegram_id,
                "❌ <b>Seedance 2.5 не завершилась</b>\n"
                f"ID: <code>{task_id}</code>\n"
                f"Причина: <code>{fail_msg[:600] or 'provider error'}</code>\n\n"
                "Admin preview — списаний не было.",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Seedance 2.5 failure notification failed")
        return True

    if state not in {"success", "completed", "succeeded", "finished"}:
        return False

    urls = _extract_result_urls(payload)
    if not urls:
        return False
    video_url, last_frame_url = _classify_results(urls, request_data)
    if not video_url:
        return False

    await _store_task_result(task_id, video_url, urls, success=True)
    await _send_seedance25_results(
        app,
        telegram_id,
        task_id,
        video_url,
        last_frame_url if request_data.get("return_last_frame") else None,
        request_data,
    )
    return True


async def seedance25_webhook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=200)

    if not kie_market_service.verify_webhook_signature(payload, request.headers):
        logger.warning("Rejected Seedance 2.5 webhook with invalid signature")
        return web.Response(status=401)

    try:
        await _process_seedance25_payload(request.app, payload)
    except Exception:
        logger.exception("Seedance 2.5 dedicated webhook failed")
    return web.Response(status=200)


async def _seedance25_reconcile_loop(app: web.Application) -> None:
    await asyncio.sleep(15)
    while True:
        try:
            async with db_backend.connect() as db:
                db.row_factory = db_backend.Row
                cursor = await db.execute(
                    """
                    SELECT task_id
                    FROM generation_tasks
                    WHERE model = ? AND status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT 25
                    """,
                    (MODEL_KEY,),
                )
                rows = await cursor.fetchall()
            for row in rows:
                task_id = str(row["task_id"] or "")
                if not task_id:
                    continue
                task_data = await kie_market_service.get_task_status(task_id)
                if not task_data:
                    continue
                await _process_seedance25_payload(app, {"code": 200, "data": task_data})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Seedance 2.5 reconcile iteration failed")
        await asyncio.sleep(60)


async def _seedance25_startup(app: web.Application) -> None:
    if app.get(_RECONCILE_TASK_KEY):
        return
    app[_RECONCILE_TASK_KEY] = asyncio.create_task(_seedance25_reconcile_loop(app))


async def _seedance25_cleanup(app: web.Application) -> None:
    task = app.get(_RECONCILE_TASK_KEY)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def install_seedance_25_fullstack() -> None:
    """Patch Mini App setup/handlers before ``main`` imports the setup function."""
    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_seedance25_fullstack_installed", False):
        return

    original_bootstrap = miniapp_module.miniapp_bootstrap
    original_generate_video = miniapp_module.miniapp_generate_video
    original_setup = miniapp_module.setup_miniapp_routes

    async def bootstrap_with_seedance25(request: web.Request) -> web.Response:
        response = await original_bootstrap(request)
        if response.status != 200:
            return response
        payload = _json_response_payload(response)
        if not payload or not payload.get("is_admin"):
            return response
        models = list(payload.get("video_models") or [])
        if not any(str(item.get("id")) == MODEL_KEY for item in models if isinstance(item, dict)):
            models.append(_seedance25_model_meta())
        payload["video_models"] = models
        return web.json_response(payload)

    async def generate_video_with_seedance25(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return await original_generate_video(request)
        model = str(body.get("v_model") or "")
        if model != MODEL_KEY:
            return await original_generate_video(request)
        try:
            return await _miniapp_seedance25_generate(request, body)
        except Exception as exc:
            logger.exception("Mini App Seedance 2.5 generation failed")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    def setup_with_seedance25(app: web.Application):
        result = original_setup(app)
        app.router.add_post("/webhook/kie_seedance25", seedance25_webhook)
        app.on_startup.append(_seedance25_startup)
        app.on_cleanup.append(_seedance25_cleanup)
        return result

    miniapp_module.miniapp_bootstrap = bootstrap_with_seedance25
    miniapp_module.miniapp_generate_video = generate_video_with_seedance25
    miniapp_module.setup_miniapp_routes = setup_with_seedance25
    miniapp_module._seedance25_fullstack_installed = True


async def _download_telegram_bytes(message: types.Message, media) -> bytes:
    tg_file = await message.bot.get_file(media.file_id)
    downloaded = await message.bot.download_file(tg_file.file_path)
    return downloaded.read()


async def _validate_temp_bytes(raw: bytes, suffix: str, kind: str) -> float | None:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = tmp.name
    try:
        tmp.write(raw)
        tmp.close()
        if kind == "video":
            return await _validate_video_path(path)
        if kind == "audio":
            return await _validate_audio_path(path)
        _validate_image_path(path)
        return None
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass


async def _store_video_reference(message: types.Message, state: FSMContext, media, ext: str, mime: str) -> None:
    data = await state.get_data()
    if data.get("seedance25_scenario") != "multimodal":
        await message.answer("Видео-референсы доступны только в мультимодальном режиме Seedance 2.5.")
        return
    urls = _clean_urls(data.get("v_reference_videos") or [])
    if len(urls) >= 10:
        await message.answer("❌ Максимум 10 видео-референсов.")
        return
    raw = await _download_telegram_bytes(message, media)
    try:
        duration = float(await _validate_temp_bytes(raw, f".{ext}", "video") or 0)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return
    durations = [float(item or 0) for item in data.get("seedance25_reference_video_durations") or []]
    if sum(durations) + duration > MAX_TOTAL_VIDEO_DURATION + 0.01:
        await message.answer("❌ Суммарная длительность видео-референсов — максимум 30 секунд.")
        return
    url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        raw,
        ext,
        kind="video",
        original_filename=f"seedance25_{media.file_id}.{ext}",
        content_type=mime,
    )
    if not url:
        await message.answer("❌ Не удалось сохранить видео.")
        return
    urls.append(url)
    durations.append(duration)
    await state.update_data(v_reference_videos=urls, seedance25_reference_video_durations=durations)
    await message.answer(f"✅ Видео добавлено: {duration:.2f}с, проверены FPS/размеры/формат.")
    await preview_module._show_seedance_25_screen(message, state, edit=False)


async def _store_audio_reference(message: types.Message, state: FSMContext, media, ext: str, mime: str) -> None:
    data = await state.get_data()
    if data.get("seedance25_scenario") != "multimodal":
        await message.answer("Аудио-референсы доступны только в мультимодальном режиме Seedance 2.5.")
        return
    urls = _clean_urls(data.get("seedance25_reference_audio_urls") or [])
    if len(urls) >= 10:
        await message.answer("❌ Максимум 10 аудио-референсов.")
        return
    raw = await _download_telegram_bytes(message, media)
    try:
        duration = float(await _validate_temp_bytes(raw, f".{ext}", "audio") or 0)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return
    url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        raw,
        ext,
        kind="audio",
        original_filename=f"seedance25_{media.file_id}.{ext}",
        content_type=mime,
    )
    if not url:
        await message.answer("❌ Не удалось сохранить аудио.")
        return
    urls.append(url)
    await state.update_data(seedance25_reference_audio_urls=urls)
    await message.answer(f"✅ Аудио добавлено: {duration:.2f}с, формат проверен.")
    await preview_module._show_seedance_25_screen(message, state, edit=False)


@router.message(generation_module.GenerationStates.waiting_for_video_prompt, F.video)
async def seedance25_full_video(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    media = message.video
    mime = str(media.mime_type or "video/mp4").lower()
    ext = "mov" if "quicktime" in mime else "mp4"
    await _store_video_reference(message, state, media, ext, mime)


@router.message(generation_module.GenerationStates.waiting_for_video_prompt, F.audio)
async def seedance25_full_audio(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    media = message.audio
    name = str(media.file_name or "").lower()
    mime = str(media.mime_type or "").lower()
    ext = "wav" if name.endswith(".wav") or "wav" in mime else "mp3"
    await _store_audio_reference(message, state, media, ext, mime or f"audio/{ext}")


@router.message(generation_module.GenerationStates.waiting_for_video_prompt, F.voice)
async def seedance25_full_voice(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    await message.answer("❌ Telegram Voice = OGG. По Seedance 2.5 spec используйте WAV или MP3 файлом.")


@router.message(generation_module.GenerationStates.waiting_for_video_prompt, F.document)
async def seedance25_full_document(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    document = message.document
    name = str(document.file_name or "").lower()
    ext = Path(name).suffix.lower().lstrip(".")
    mime = str(document.mime_type or "application/octet-stream").lower()
    if ext in VIDEO_EXTS:
        await _store_video_reference(message, state, document, ext, "video/quicktime" if ext == "mov" else "video/mp4")
        return
    if ext in AUDIO_EXTS:
        await _store_audio_reference(message, state, document, ext, "audio/wav" if ext == "wav" else "audio/mpeg")
        return
    # Image documents are handled by the existing preview router.
    raise SkipHandler


@router.message(
    generation_module.GenerationStates.waiting_for_video_prompt,
    F.text.regexp(r"(?i)^asset:(first|last|image|video|audio|clear)\b"),
)
async def seedance25_asset_command(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    text = str(message.text or "").strip()
    head, _, raw_value = text.partition(" ")
    kind = head.split(":", 1)[1].lower()
    value = raw_value.strip()
    if kind == "clear":
        await state.update_data(
            seedance25_first_frame_url=None,
            seedance25_last_frame_url=None,
            reference_images=[],
            v_reference_videos=[],
            seedance25_reference_audio_urls=[],
            seedance25_reference_video_durations=[],
        )
        await message.answer("✅ Seedance asset inputs очищены.")
        await preview_module._show_seedance_25_screen(message, state, edit=False)
        return
    if not value.startswith("asset://"):
        await message.answer("❌ Формат: <code>asset:image asset://asset-id</code>", parse_mode="HTML")
        return

    scenario = str(data.get("seedance25_scenario") or "text")
    if kind in {"first", "last"}:
        if scenario not in {"first_frame", "first_last"}:
            await message.answer("Сначала выберите сценарий 1-й кадр или 1-й + последний.")
            return
        if kind == "first":
            await state.update_data(seedance25_first_frame_url=value)
        else:
            if scenario != "first_last":
                await message.answer("Последний кадр доступен только в режиме 1-й + последний.")
                return
            await state.update_data(seedance25_last_frame_url=value)
    else:
        if scenario != "multimodal":
            await message.answer("asset:image/video/audio доступны только в мультимодальном сценарии.")
            return
        mapping = {
            "image": ("reference_images", 30),
            "video": ("v_reference_videos", 10),
            "audio": ("seedance25_reference_audio_urls", 10),
        }
        state_key, limit = mapping[kind]
        values = _clean_urls([*(data.get(state_key) or []), value], limit)
        await state.update_data(**{state_key: values})
    await message.answer(f"✅ {kind}: asset добавлен.")
    await preview_module._show_seedance_25_screen(message, state, edit=False)
