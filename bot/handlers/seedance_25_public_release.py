"""Public-release compatibility layer for Seedance 2.5.

The feature branch originally carried Seedance 2.5 as an admin-only preview.
This module flips the already-tested provider/UI seams to a normal user model
without touching tanyapi:

* Seedance 2.5 is visible to every user and is the only model marked NEW;
* admins keep the established free-generation behaviour;
* regular users are balance-checked and charged before provider launch;
* immediate provider launch failures are refunded;
* asynchronous provider failures claim an idempotent refund marker before the
  dedicated webhook marks the task failed;
* public Telegram/Mini App copy no longer says "admin preview".
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import wraps
from typing import Any

from aiohttp import web
from aiogram import types
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.services.preset_manager import preset_manager
from bot.services.seedance_25_service import (
    get_seedance25_callback_url,
    seedance_25_service,
)

from . import generation as generation_module
from . import seedance_25_fullstack as fullstack
from . import seedance_25_preview as preview_module

logger = logging.getLogger(__name__)
MODEL_KEY = "seedance_2_5"

_NEW_MARKERS_RE = re.compile(
    r"(?:\s+NEW(?:🔥+)?|\s+🔥\s*НОВИНКА|\s+НОВИНКА|\s+🆕)",
    flags=re.IGNORECASE,
)


def _public_feature_access(user_id: int | None) -> bool:
    """Seedance feature access is public; authentication still happens upstream."""
    return user_id is not None


def _clean_other_new_markers(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _NEW_MARKERS_RE.sub("", str(text or ""))).strip()


def _copy_button_with_text(button: types.InlineKeyboardButton, text: str):
    try:
        return button.model_copy(update={"text": text})
    except AttributeError:
        button.text = text
        return button


def _public_video_model_keyboard(original):
    @wraps(original)
    def wrapped(current_model: str = "v3_pro", user_id: int | None = None):
        markup = original(current_model, user_id=user_id)
        rows: list[list[types.InlineKeyboardButton]] = []
        has_seedance = False
        insert_after = None

        for row_index, row in enumerate(markup.inline_keyboard):
            cleaned_row: list[types.InlineKeyboardButton] = []
            for button in row:
                callback = str(button.callback_data or "")
                if callback == "v_model_seedance_2_5":
                    has_seedance = True
                    label = _seedance_public_button_text(current_model)
                    cleaned_row.append(_copy_button_with_text(button, label))
                    continue
                cleaned_row.append(
                    _copy_button_with_text(button, _clean_other_new_markers(button.text))
                )
                if callback == "v_model_seedance_2":
                    insert_after = row_index
            rows.append(cleaned_row)

        if not has_seedance:
            seedance_button = types.InlineKeyboardButton(
                text=_seedance_public_button_text(current_model),
                callback_data="v_model_seedance_2_5",
            )
            index = (insert_after + 1) if insert_after is not None else max(len(rows) - 1, 0)
            rows.insert(index, [seedance_button])

        return types.InlineKeyboardMarkup(inline_keyboard=rows)

    return wrapped


def _clean_keyboard_new_markers(original):
    @wraps(original)
    def wrapped(*args, **kwargs):
        markup = original(*args, **kwargs)
        rows = [
            [
                _copy_button_with_text(button, _clean_other_new_markers(button.text))
                for button in row
            ]
            for row in markup.inline_keyboard
        ]
        return types.InlineKeyboardMarkup(inline_keyboard=rows)

    return wrapped


def _seedance_public_button_text(current_model: str) -> str:
    check = "✅ " if current_model == MODEL_KEY else ""
    per_second = preset_manager.get_video_cost_per_second(MODEL_KEY, 5, "720p")
    return f"{check}🆕 Seedance 2.5 NEW • {per_second}🍌/с"


def _public_model_meta() -> dict[str, Any]:
    meta = fullstack._seedance25_model_meta_original()
    meta.update(
        {
            "label": "🆕 Seedance 2.5 NEW",
            "description": "Новая Bytedance video-модель: текст, first/last frame и мультимодальные фото/видео/аудио референсы",
            "admin_only": False,
            "is_new": True,
        }
    )
    return meta


def _duration_label(value: int) -> str:
    return "Auto" if int(value) == -1 else f"{int(value)}с"


async def _public_show_screen(target, state: FSMContext, *, edit: bool = True) -> None:
    data = await state.get_data()
    scenario = data.get("seedance25_scenario", "text")
    first = bool(data.get("seedance25_first_frame_url"))
    last = bool(data.get("seedance25_last_frame_url"))
    images = len(data.get("reference_images") or [])
    videos = len(data.get("v_reference_videos") or [])
    audios = len(data.get("seedance25_reference_audio_urls") or [])
    duration = int(data.get("v_duration", 5))
    quote = preview_module._price_quote(data)
    user_id = getattr(getattr(target, "from_user", None), "id", None)
    is_admin = bool(user_id and config.is_admin(int(user_id)))

    if scenario == "first_frame":
        media_hint = f"Загрузите <b>1 фото</b> как первый кадр. Сейчас: {'✅' if first else '—'}"
    elif scenario == "first_last":
        media_hint = (
            "Загрузите последовательно <b>2 фото</b>: первый и последний кадры. "
            f"Сейчас: первый {'✅' if first else '—'}, последний {'✅' if last else '—'}"
        )
    elif scenario == "multimodal":
        media_hint = (
            "Можно присылать фото / видео / аудио прямо сюда. "
            f"Фото <code>{images}/30</code>, видео <code>{videos}/10</code>, "
            f"аудио <code>{audios}/10</code>. Видео суммарно ≤30с."
        )
    else:
        media_hint = "Медиа не требуется — отправьте текстовый промпт."

    billing_line = (
        f"💰 Цена: <code>{quote}</code>🍌. Для администратора списание отключено."
        if is_admin
        else f"💰 Цена: <code>{quote}</code>🍌 — будет списана при запуске."
    )
    auto_note = (
        "\n⚠️ Auto сейчас доступен только администратору: для пользователей выберите 4–30с."
        if duration == -1 and not is_admin
        else ""
    )
    text = (
        "🆕 <b>Seedance 2.5 · NEW</b>\n\n"
        f"Сценарий: <b>{preview_module._scenario_label(scenario)}</b>\n"
        f"Качество: <code>{data.get('seedance25_resolution', '720p')}</code> · "
        f"Формат кадра: <code>{data.get('v_ratio', 'adaptive')}</code> · "
        f"Длительность: <code>{_duration_label(duration)}</code>\n"
        f"Выход: <code>{data.get('seedance25_output_format', 'mp4')}</code> · "
        f"аудио: <code>{'on' if data.get('seedance25_generate_audio', True) else 'off'}</code>\n"
        f"Web search: <code>{'on' if data.get('seedance25_web_search') else 'off'}</code> · "
        f"NSFW checker: <code>{'on' if data.get('seedance25_nsfw_checker') else 'off'}</code> · "
        f"последний кадр: <code>{'yes' if data.get('seedance25_return_last_frame') else 'no'}</code>\n\n"
        f"{media_hint}\n\n"
        "🎥 Движение камеры и lock объектива задавайте прямо в промпте.\n\n"
        f"{billing_line}{auto_note}\n\n"
        "После настройки отправьте промпт до 5000 символов."
    )
    markup = preview_module._seedance_25_keyboard(data)

    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    elif edit:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")

    await state.set_state(generation_module.GenerationStates.waiting_for_video_prompt)


def _scenario_payload(data: dict[str, Any], prompt: str) -> dict[str, Any]:
    scenario = str(data.get("seedance25_scenario") or "text")
    first = data.get("seedance25_first_frame_url") if scenario in {"first_frame", "first_last"} else None
    last = data.get("seedance25_last_frame_url") if scenario == "first_last" else None
    images = fullstack._clean_urls(data.get("reference_images") or [], 30) if scenario == "multimodal" else []
    videos = fullstack._clean_urls(data.get("v_reference_videos") or [], 10) if scenario == "multimodal" else []
    audios = fullstack._clean_urls(data.get("seedance25_reference_audio_urls") or [], 10) if scenario == "multimodal" else []
    return {
        "scenario": scenario,
        "prompt": str(prompt or "").strip(),
        "duration": int(data.get("v_duration", 5)),
        "ratio": str(data.get("v_ratio") or "adaptive"),
        "resolution": str(data.get("seedance25_resolution") or "720p"),
        "first_frame": str(first or "").strip() or None,
        "last_frame": str(last or "").strip() or None,
        "image_urls": images,
        "video_urls": videos,
        "audio_urls": audios,
        "return_last_frame": bool(data.get("seedance25_return_last_frame", False)),
        "generate_audio": bool(data.get("seedance25_generate_audio", True)),
        "output_format": str(data.get("seedance25_output_format") or "mp4"),
        "web_search": bool(data.get("seedance25_web_search", False)),
        "nsfw_checker": bool(data.get("seedance25_nsfw_checker", False)),
    }


async def _validate_public_payload(payload: dict[str, Any], *, is_admin: bool) -> None:
    scenario = payload["scenario"]
    if len(payload["prompt"]) > seedance_25_service.MAX_PROMPT_LENGTH:
        raise ValueError("Промпт Seedance 2.5 — максимум 5000 символов")
    if scenario == "text" and not payload["prompt"]:
        raise ValueError("Для Text-to-Video нужен промпт")
    if scenario in {"first_frame", "first_last"} and not payload["first_frame"]:
        raise ValueError("Сначала загрузите первый кадр")
    if scenario == "first_last" and not payload["last_frame"]:
        raise ValueError("Для этого режима нужен последний кадр")
    if scenario == "multimodal" and not (
        payload["image_urls"] or payload["video_urls"] or payload["audio_urls"]
    ):
        raise ValueError("Добавьте хотя бы один мультимодальный референс")
    if payload["duration"] == -1 and not is_admin:
        raise ValueError("Auto-длительность пока доступна только администратору; выберите 4–30 секунд")
    await fullstack._validate_seedance_sources(
        first_frame_url=payload["first_frame"],
        last_frame_url=payload["last_frame"],
        image_urls=payload["image_urls"],
        video_urls=payload["video_urls"],
        audio_urls=payload["audio_urls"],
    )


async def _launch_provider(payload: dict[str, Any]) -> dict[str, Any]:
    return await seedance_25_service.generate_video(
        prompt=payload["prompt"],
        duration=payload["duration"],
        aspect_ratio=payload["ratio"],
        resolution=payload["resolution"],
        first_frame_url=payload["first_frame"],
        last_frame_url=payload["last_frame"],
        reference_image_urls=payload["image_urls"] or None,
        reference_video_urls=payload["video_urls"] or None,
        reference_audio_urls=payload["audio_urls"] or None,
        return_last_frame=payload["return_last_frame"],
        generate_audio=payload["generate_audio"],
        output_format=payload["output_format"],
        web_search=payload["web_search"],
        nsfw_checker=payload["nsfw_checker"],
        callBackUrl=get_seedance25_callback_url(),
    )


def _request_data(payload: dict[str, Any], *, is_admin: bool, quote: float, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "release": "seedance_2_5_public",
        "v_model": MODEL_KEY,
        "v_type": "text" if payload["scenario"] == "text" else "imgtxt" if payload["scenario"] in {"first_frame", "first_last"} else "video",
        "seedance25_scenario": payload["scenario"],
        "first_frame_url": payload["first_frame"],
        "last_frame_url": payload["last_frame"],
        "reference_images": payload["image_urls"],
        "v_reference_videos": payload["video_urls"],
        "reference_audios": payload["audio_urls"],
        "resolution": payload["resolution"],
        "generate_audio": payload["generate_audio"],
        "return_last_frame": payload["return_last_frame"],
        "output_format": payload["output_format"],
        "web_search": payload["web_search"],
        "nsfw_checker": payload["nsfw_checker"],
        "charged": not is_admin,
        "charged_cost": float(quote),
        "admin_free": is_admin,
        "refund_on_failure": not is_admin,
        "refund_claimed": False,
        "callback_url": get_seedance25_callback_url(),
        "provider_model": seedance_25_service.MODEL_NAME,
    }


async def _public_message_launch(message: types.Message, state: FSMContext, prompt: str) -> None:
    data = await state.get_data()
    payload = _scenario_payload(data, prompt)
    is_admin = config.is_admin(message.from_user.id)
    try:
        await _validate_public_payload(payload, is_admin=is_admin)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return

    quote = float(preview_module._price_quote(data))
    if not is_admin and not await generation_module.check_can_afford(message.from_user.id, quote):
        credits = await generation_module.get_user_credits(message.from_user.id)
        await message.answer(
            f"❌ Недостаточно бананов. Нужно <b>{quote:g}🍌</b>, на балансе <b>{credits:g}🍌</b>.",
            parse_mode="HTML",
        )
        return

    charged = False
    processing = await message.answer(
        "🆕 <b>Seedance 2.5 · NEW</b>\n"
        f"Цена: <code>{quote:g}</code>🍌 · отправляю задачу в Kie.ai…",
        parse_mode="HTML",
    )
    try:
        if not is_admin:
            await generation_module.deduct_credits(message.from_user.id, quote)
            charged = True

        result = await _launch_provider(payload)
        if not result or not result.get("task_id"):
            if charged:
                await generation_module.add_credits(message.from_user.id, quote)
                charged = False
            error = result.get("error") if isinstance(result, dict) else "provider response has no task_id"
            await processing.delete()
            await message.answer(
                f"❌ Seedance 2.5 не запустилась: <code>{str(error)[:500]}</code>"
                + ("\n🍌 Списание возвращено." if not is_admin else ""),
                parse_mode="HTML",
            )
            return

        user = await generation_module.get_or_create_user(message.from_user.id)
        task_id = str(result["task_id"])
        await generation_module.add_generation_task(
            user.id,
            message.from_user.id,
            task_id,
            "video",
            "no_preset_video",
            model=MODEL_KEY,
            duration=payload["duration"],
            aspect_ratio=payload["ratio"],
            prompt=payload["prompt"],
            cost=quote,
            request_data=_request_data(payload, is_admin=is_admin, quote=quote, source="telegram"),
        )
        await processing.delete()
        billing = "администратору бесплатно" if is_admin else f"списано {quote:g}🍌"
        await message.answer(
            "✅ <b>Seedance 2.5 запущена</b>\n"
            f"🆔 <code>{task_id}</code>\n"
            f"⏱ <code>{_duration_label(payload['duration'])}</code> · "
            f"📐 <code>{payload['ratio']}</code> · 🖥 <code>{payload['resolution']}</code>\n"
            f"💰 {billing}.\n\n"
            "Результат придёт автоматически после завершения.",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("Public Seedance 2.5 Telegram launch failed")
        if charged:
            try:
                await generation_module.add_credits(message.from_user.id, quote)
            except Exception:
                logger.exception("Seedance 2.5 immediate refund failed for %s", message.from_user.id)
        try:
            await processing.delete()
        except Exception:
            pass
        await message.answer(
            f"❌ Seedance 2.5: <code>{str(exc)[:500]}</code>"
            + ("\n🍌 Если списание успело пройти, оно возвращено." if not is_admin else ""),
            parse_mode="HTML",
        )
    finally:
        await state.clear()


async def _public_miniapp_generate(request: web.Request, body: dict[str, Any]) -> web.Response:
    import bot.miniapp as miniapp_module

    telegram_id, ctx = await miniapp_module._get_user_context(
        request.app,
        str(body.get("init_data") or ""),
        body.get("start_param_fallback"),
    )
    user = ctx["user"]
    is_admin = config.is_admin(telegram_id)

    data = {
        "seedance25_scenario": str(body.get("seedance25_scenario") or "text").strip().lower(),
        "v_duration": int(body.get("v_duration", 5)),
        "v_ratio": str(body.get("v_ratio") or "adaptive").strip().lower(),
        "seedance25_resolution": str(body.get("seedance25_resolution") or "720p").strip().lower(),
        "seedance25_first_frame_url": str(body.get("seedance25_first_frame_url") or "").strip() or None,
        "seedance25_last_frame_url": str(body.get("seedance25_last_frame_url") or "").strip() or None,
        "reference_images": fullstack._clean_urls(body.get("reference_images") or [], 30),
        "v_reference_videos": fullstack._clean_urls(body.get("v_reference_videos") or [], 10),
        "seedance25_reference_audio_urls": fullstack._clean_urls(body.get("seedance25_reference_audio_urls") or [], 10),
        "seedance25_return_last_frame": bool(body.get("seedance25_return_last_frame", False)),
        "seedance25_generate_audio": bool(body.get("seedance25_generate_audio", True)),
        "seedance25_output_format": str(body.get("seedance25_output_format") or "mp4").strip().lower(),
        "seedance25_web_search": bool(body.get("seedance25_web_search", False)),
        "seedance25_nsfw_checker": bool(body.get("seedance25_nsfw_checker", False)),
    }
    scenario = data["seedance25_scenario"]
    if scenario not in {"text", "first_frame", "first_last", "multimodal"}:
        return web.json_response({"ok": False, "error": "Некорректный сценарий Seedance 2.5"}, status=400)

    if scenario == "text":
        data.update(
            seedance25_first_frame_url=None,
            seedance25_last_frame_url=None,
            reference_images=[],
            v_reference_videos=[],
            seedance25_reference_audio_urls=[],
        )
    elif scenario == "first_frame":
        data.update(
            seedance25_last_frame_url=None,
            reference_images=[],
            v_reference_videos=[],
            seedance25_reference_audio_urls=[],
        )
    elif scenario == "first_last":
        data.update(reference_images=[], v_reference_videos=[], seedance25_reference_audio_urls=[])
    else:
        data.update(seedance25_first_frame_url=None, seedance25_last_frame_url=None)

    payload = _scenario_payload(data, str(body.get("prompt") or ""))
    try:
        await _validate_public_payload(payload, is_admin=is_admin)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    quote = float(preview_module._price_quote(data))
    if not is_admin and not await miniapp_module.check_can_afford(telegram_id, quote):
        fresh = await miniapp_module.get_or_create_user(telegram_id)
        return web.json_response(
            {"ok": False, "error": f"Недостаточно бананов. Нужно {quote:g}🍌", "credits": fresh.credits},
            status=400,
        )

    charged = False
    try:
        if not is_admin:
            await miniapp_module.deduct_credits(telegram_id, quote)
            charged = True

        result = await _launch_provider(payload)
        if not result or not result.get("task_id"):
            if charged:
                await miniapp_module.add_credits(telegram_id, quote)
                charged = False
            error = result.get("error") if isinstance(result, dict) else "provider response has no task_id"
            return web.json_response(
                {"ok": False, "error": f"Seedance 2.5 не запустилась: {error}. Списание возвращено."},
                status=502,
            )

        task_id = str(result["task_id"])
        await generation_module.add_generation_task(
            user.id,
            telegram_id,
            task_id,
            "video",
            "no_preset_video",
            model=MODEL_KEY,
            duration=payload["duration"],
            aspect_ratio=payload["ratio"],
            prompt=payload["prompt"],
            cost=quote,
            request_data=_request_data(payload, is_admin=is_admin, quote=quote, source="miniapp"),
        )
        fresh_user = await miniapp_module.get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": "queued",
                "task_id": task_id,
                "credits": fresh_user.credits,
                "cost": quote,
                "model_label": "Seedance 2.5",
                "admin_free": is_admin,
                "resolution": payload["resolution"],
                "duration": payload["duration"],
                "aspect_ratio": payload["ratio"],
                "scenario": payload["scenario"],
            }
        )
    except Exception as exc:
        logger.exception("Public Seedance 2.5 Mini App launch failed")
        if charged:
            try:
                await miniapp_module.add_credits(telegram_id, quote)
            except Exception:
                logger.exception("Seedance 2.5 Mini App immediate refund failed for %s", telegram_id)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _claim_async_refund(task_id: str) -> tuple[int, float] | None:
    row = await fullstack._load_task_row(task_id)
    if not row or str(row["status"] or "").lower() != "pending":
        return None
    try:
        request_data = json.loads(row["request_data"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not request_data.get("refund_on_failure") or request_data.get("refund_claimed"):
        return None
    cost = float(request_data.get("charged_cost") or row["cost"] or 0)
    if cost <= 0:
        return None

    old_json = row["request_data"] or "{}"
    request_data["refund_claimed"] = True
    new_json = json.dumps(request_data, ensure_ascii=False, separators=(",", ":"))
    async with fullstack.db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE generation_tasks
            SET request_data = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'pending' AND request_data = ?
            """,
            (new_json, task_id, old_json),
        )
        await db.commit()
        if int(getattr(cursor, "rowcount", 0) or 0) != 1:
            return None
    return int(row["telegram_id"]), cost


async def _public_process_payload(app: web.Application, payload: dict[str, Any]) -> bool:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    task_id = str((data or {}).get("taskId") or payload.get("taskId") or "").strip()
    state = str((data or {}).get("state") or payload.get("state") or "").lower()
    code = int(payload.get("code") or 200)
    is_failure = state in {"fail", "failed", "error"} or code in {501, 500, 422, 402, 429, 455, 505}
    if is_failure and task_id:
        claimed = await _claim_async_refund(task_id)
        if claimed:
            telegram_id, cost = claimed
            try:
                await generation_module.add_credits(telegram_id, cost)
                logger.info("Seedance 2.5 refunded %.2f credits for failed task %s", cost, task_id)
            except Exception:
                logger.exception("Seedance 2.5 async refund failed for task %s", task_id)
    return await fullstack._process_seedance25_payload_original(app, payload)


async def _public_send_results(
    app: web.Application,
    telegram_id: int,
    task_id: str,
    video_url: str,
    last_frame_url: str | None,
    request_data: dict[str, Any],
) -> None:
    bot = app["bot"]
    output_format = str(request_data.get("output_format") or fullstack._extension_from_url(video_url) or "mp4").lower()
    resolution = str(request_data.get("resolution") or "720p")
    duration = request_data.get("duration")
    scenario = str(request_data.get("seedance25_scenario") or "text")
    admin_free = bool(request_data.get("admin_free"))
    cost = float(request_data.get("charged_cost") or 0)
    billing = "без списания для администратора" if admin_free else f"списано {cost:g}🍌"
    caption = (
        "✅ <b>Seedance 2.5 готово</b>\n"
        f"• ID: <code>{task_id}</code>\n"
        f"• Сценарий: <code>{scenario}</code>\n"
        f"• Качество: <code>{resolution}</code>\n"
        f"• Формат: <code>{output_format.upper()}</code>\n"
        f"• Оплата: <code>{billing}</code>"
    )
    if duration is not None:
        caption += f"\n• Длительность: <code>{'Auto' if int(duration) == -1 else str(duration) + 'с'}</code>"

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
            logger.info("Seedance 2.5 URL delivery failed; trying downloaded file")

    if not delivered:
        temp_path = await fullstack._download_to_temp(video_url, suffix=suffix)
        if temp_path:
            try:
                if output_format == "mp4":
                    await bot.send_video(
                        telegram_id,
                        video=types.FSInputFile(temp_path),
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                    )
                else:
                    await bot.send_document(
                        telegram_id,
                        document=types.FSInputFile(temp_path, filename=f"seedance25-{task_id}.mov"),
                        caption=caption,
                        parse_mode="HTML",
                    )
                delivered = True
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    if not delivered:
        await bot.send_message(
            telegram_id,
            caption + f"\n\n🔗 Оригинал:\n{video_url}",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

    if last_frame_url:
        try:
            await bot.send_photo(
                telegram_id,
                photo=last_frame_url,
                caption=f"🖼 <b>Последний кадр Seedance 2.5</b>\nID: <code>{task_id}</code>",
                parse_mode="HTML",
            )
        except Exception:
            await bot.send_message(
                telegram_id,
                f"🖼 Последний кадр Seedance 2.5:\n{last_frame_url}",
                disable_web_page_preview=False,
            )


def install_seedance_25_public_release() -> None:
    """Install public access after preview/fullstack compatibility layers."""
    import bot.keyboards as keyboard_module
    import bot.miniapp as miniapp_module

    if getattr(generation_module, "_seedance_25_public_release_installed", False):
        return

    # Access checks inside the isolated Seedance modules become feature-access
    # checks. Global config.is_admin is still used for billing/admin privileges.
    fullstack._is_admin = _public_feature_access
    preview_module._is_admin = _public_feature_access

    # Preserve originals for public wrappers and tests.
    if not hasattr(fullstack, "_seedance25_model_meta_original"):
        fullstack._seedance25_model_meta_original = fullstack._seedance25_model_meta
    if not hasattr(fullstack, "_process_seedance25_payload_original"):
        fullstack._process_seedance25_payload_original = fullstack._process_seedance25_payload

    fullstack._seedance25_model_meta = _public_model_meta
    fullstack._process_seedance25_payload = _public_process_payload
    fullstack._send_seedance25_results = _public_send_results
    preview_module._show_seedance_25_screen = _public_show_screen

    # Telegram model lists: expose Seedance to everybody and remove NEW/НОВИНКА
    # badges from all other models.
    original_video_keyboard = keyboard_module.get_video_model_selection_keyboard
    original_image_keyboard = keyboard_module.get_image_model_selection_keyboard
    public_video_keyboard = _public_video_model_keyboard(original_video_keyboard)
    public_image_keyboard = _clean_keyboard_new_markers(original_image_keyboard)
    keyboard_module.get_video_model_selection_keyboard = public_video_keyboard
    keyboard_module.get_image_model_selection_keyboard = public_image_keyboard
    generation_module.get_video_model_selection_keyboard = public_video_keyboard
    generation_module.get_image_model_selection_keyboard = public_image_keyboard

    # Mini App bootstrap: the admin-preview wrapper only exposed Seedance to
    # admins. Rebuild the model entry for every authenticated user.
    current_bootstrap = miniapp_module.miniapp_bootstrap

    @wraps(current_bootstrap)
    async def public_bootstrap(request: web.Request) -> web.Response:
        response = await current_bootstrap(request)
        if response.status != 200:
            return response
        payload = fullstack._json_response_payload(response)
        if not payload:
            return response
        models = [
            item for item in list(payload.get("video_models") or [])
            if not (isinstance(item, dict) and str(item.get("id")) == MODEL_KEY)
        ]
        models.append(_public_model_meta())
        payload["video_models"] = models
        return web.json_response(payload)

    miniapp_module.miniapp_bootstrap = public_bootstrap

    # Preserve large-video assembly requests; all real generation requests use
    # the public billed path.
    current_seedance_generate = fullstack._miniapp_seedance25_generate

    async def public_generate(request: web.Request, body: dict[str, Any]) -> web.Response:
        if body.get("seedance25_upload_only"):
            return await current_seedance_generate(request, body)
        return await _public_miniapp_generate(request, body)

    fullstack._miniapp_seedance25_generate = public_generate

    # Replace preview's admin-guard launch wrappers after preview installation.
    current_apply_model = generation_module._apply_video_model_selection
    current_message_launch = generation_module.run_no_preset_video_from_message
    current_callback_launch = generation_module.run_no_preset_video_from_callback

    @wraps(current_apply_model)
    async def public_apply_model(callback, state, model):
        if model != MODEL_KEY:
            return await current_apply_model(callback, state, model)
        await state.clear()
        await state.update_data(**preview_module._defaults())
        await _public_show_screen(callback, state)
        await callback.answer()

    @wraps(current_message_launch)
    async def public_message_launch(message, state, prompt):
        data = await state.get_data()
        if data.get("v_model") != MODEL_KEY:
            return await current_message_launch(message, state, prompt)
        return await _public_message_launch(message, state, prompt)

    @wraps(current_callback_launch)
    async def public_callback_launch(callback, state, prompt, cost, is_admin):
        data = await state.get_data()
        if data.get("v_model") != MODEL_KEY:
            return await current_callback_launch(callback, state, prompt, cost, is_admin)
        await _public_message_launch(callback.message, state, prompt)
        try:
            await callback.answer("Seedance 2.5 запускаю")
        except Exception:
            pass

    generation_module._apply_video_model_selection = public_apply_model
    generation_module.run_no_preset_video_from_message = public_message_launch
    generation_module.run_no_preset_video_from_callback = public_callback_launch
    generation_module._seedance_25_public_release_installed = True
