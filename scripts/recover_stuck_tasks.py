#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
from typing import Any

from aiogram import Bot, types

from bot.config import config
from bot.database import add_credits, complete_video_task, get_task_by_id
from bot.keyboards import get_failed_image_retry_keyboard, get_image_result_keyboard
from bot.main import (
    _build_failure_notification_text,
    _build_preview_photo_bytes,
    _build_single_result_caption,
    _download_remote_bytes,
    _extract_reference_image_urls,
    _get_task_model_label,
    _persist_result_url_if_needed,
    _resolve_task_telegram_id,
    _send_original_file,
    _send_plain_result_link,
    _task_callback_id,
    _with_original_link,
)
from bot.services.nano_banana_2_service import nano_banana_2_service
from bot.services.nano_banana_pro_service import nano_banana_pro_service
from bot.services.seedream_service import seedream_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("recover_stuck_tasks")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_ids", nargs="+", help="Provider task ids to recover")
    return parser.parse_args()


def _normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_result_url_from_result_json(value: Any) -> str | None:
    payload = value
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    for key in ("resultUrls", "result_urls", "urls", "images", "videos"):
        urls = payload.get(key)
        if isinstance(urls, list) and urls:
            first = urls[0]
            if isinstance(first, str) and first.startswith("http"):
                return first
    return None


async def _fetch_provider_state(task) -> tuple[str, str | None, str | None]:
    model = str(task.model or "").strip().lower()

    if model in {"banana_pro", "nanobanana", "nano-banana-pro", "nano_banana_pro"}:
        data = await nano_banana_pro_service.get_task_status(task.task_id)
        if not data:
            return "unknown", None, "provider returned no status"
        status = _normalize_status(data.get("state") or data.get("status"))
        result_url = (
            data.get("resultUrl")
            or data.get("result_url")
            or _extract_result_url_from_result_json(data.get("resultJson"))
        )
        reason = data.get("failMsg") or data.get("error") or data.get("message")
        return status, result_url, reason

    if model in {"banana_2", "nano-banana-2", "nano_banana_2", "nano-banana-2-lite", "nano_banana_2_lite"}:
        data = await nano_banana_2_service.get_task_status(task.task_id)
        if not data:
            return "unknown", None, "provider returned no status"
        status = _normalize_status(data.get("state") or data.get("status"))
        result_url = (
            data.get("resultUrl")
            or data.get("result_url")
            or _extract_result_url_from_result_json(data.get("resultJson"))
        )
        reason = data.get("failMsg") or data.get("error") or data.get("message")
        return status, result_url, reason

    if model in {"seedream_5_pro", "seedream_edit"} or "seedream" in model:
        payload = await seedream_service.get_task_status(task.task_id)
        if not payload:
            return "unknown", None, "provider returned no status"
        data = payload.get("data") or {}
        status = _normalize_status(data.get("status"))
        output = data.get("output")
        result_url = output if isinstance(output, str) else None
        reason = None
        raw_data = (payload.get("raw") or {}).get("data") or {}
        if not result_url:
            result_url = _extract_result_url_from_result_json(raw_data.get("resultJson"))
        reason = raw_data.get("failMsg") or raw_data.get("error") or raw_data.get("message")
        return status, result_url, reason

    return "unsupported", None, f"unsupported model {task.model}"


async def _send_image_result(bot: Bot, task, result_url: str) -> None:
    telegram_id = await _resolve_task_telegram_id(task, context="manual_recover")
    if not telegram_id:
        raise RuntimeError(f"telegram_id not resolved for task {task.task_id}")

    result_url = await _persist_result_url_if_needed(result_url, task_type="image")
    model_label = _get_task_model_label(task.model, task.type)
    caption = (
        f"✅ <b>Изображение готово</b>\n"
        f"• Модель: <code>{model_label}</code>\n"
        f"• ID: <code>{task.task_id}</code>"
    )
    reference_preview_urls = _extract_reference_image_urls(task)
    preview_caption = _build_single_result_caption(
        _with_original_link(caption, result_url),
        task,
        reference_preview_urls,
    )
    reply_markup = get_image_result_keyboard(
        result_url,
        task_id=_task_callback_id(task, task.task_id),
    )

    image_bytes = await _download_remote_bytes(result_url, timeout_seconds=30)
    preview_sent = False

    if image_bytes:
        preview_bytes = _build_preview_photo_bytes(image_bytes)
        if preview_bytes:
            try:
                await bot.send_photo(
                    chat_id=telegram_id,
                    photo=types.BufferedInputFile(preview_bytes, filename="generated_preview.jpg"),
                    caption=preview_caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                preview_sent = True
            except Exception as exc:
                logger.warning("preview file-photo send failed task_id=%s error=%s", task.task_id, exc)

    if not preview_sent:
        try:
            await bot.send_photo(
                chat_id=telegram_id,
                photo=result_url,
                caption=preview_caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            preview_sent = True
        except Exception as exc:
            logger.warning("preview url-photo send failed task_id=%s error=%s", task.task_id, exc)

    if preview_sent:
        await complete_video_task(task.task_id, result_url)
    else:
        original_sent = await _send_original_file(bot, telegram_id, result_url, image_bytes)
        if original_sent:
            await complete_video_task(task.task_id, result_url)
        else:
            await _send_plain_result_link(
                bot,
                telegram_id,
                media_label="Изображение",
                model_label=model_label,
                task_id=task.task_id,
                result_url=result_url,
                reply_markup=reply_markup,
                notice="Результат восстановлен вручную.",
            )
            await complete_video_task(task.task_id, result_url)


async def _send_failure(bot: Bot, task, reason: str | None) -> None:
    telegram_id = await _resolve_task_telegram_id(task, context="manual_recover")
    if not telegram_id:
        raise RuntimeError(f"telegram_id not resolved for task {task.task_id}")

    if task.cost and task.cost > 0:
        await add_credits(telegram_id, task.cost)

    await complete_video_task(task.task_id, None)

    reply_markup = None
    if task.type == "image":
        reply_markup = get_failed_image_retry_keyboard(_task_callback_id(task, task.task_id))

    await bot.send_message(
        chat_id=telegram_id,
        text=_build_failure_notification_text(
            service_name=_get_task_model_label(task.model, task.type),
            task_id=task.task_id,
            reason=reason,
            media_kind="результата",
            refund_text="\n\nБананы за эту попытку уже возвращены." if task.cost and task.cost > 0 else "",
        ),
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def _recover_one(bot: Bot, task_id: str) -> str:
    task = await get_task_by_id(task_id)
    if not task:
        return f"{task_id}: missing in db"
    if task.status != "pending":
        return f"{task_id}: skip status={task.status}"

    status, result_url, reason = await _fetch_provider_state(task)
    if status in {"success", "completed", "succeeded", "done"} and result_url:
        await _send_image_result(bot, task, result_url)
        return f"{task_id}: delivered success"
    if status in {"fail", "failed", "error", "rejected"}:
        await _send_failure(bot, task, reason)
        return f"{task_id}: delivered failure"
    return f"{task_id}: still pending upstream status={status}"


async def main() -> int:
    args = _parse_args()
    bot = Bot(token=config.BOT_TOKEN)
    try:
        for task_id in args.task_ids:
            try:
                result = await _recover_one(bot, task_id)
                logger.info(result)
            except Exception as exc:
                logger.exception("task recovery failed task_id=%s error=%s", task_id, exc)
        return 0
    finally:
        await bot.session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
