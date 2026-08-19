#!/usr/bin/env python3
"""Переотправляет результаты completed-задач, которые не дошли до пользователей из-за падения бота."""

import asyncio
import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.env import load_project_env
load_project_env()

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from bot.config import config
from bot.database import init_db
from bot import db as db_backend
from bot.keyboards import get_image_result_keyboard, get_video_result_keyboard
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("redeliver")

# Окно нестабильности (UTC): бот циклично падал
WINDOW_START = "2026-07-06 17:17:00"
WINDOW_END = "2026-07-06 17:45:00"


def _get_model_label(model: str | None, task_type: str | None = None) -> str:
    if not model:
        return "AI"
    mapping = {
        "banana_pro": "Banana Pro",
        "banana_2": "Banana 2",
        "nanobanana": "Nano Banana",
        "nano-banana-2-lite": "Nano Banana 2 Lite 🔥",
        "seedream_edit": "Seedream 4.5",
        "flux_pro": "GPT Image 2",
        "grok_imagine": "Grok Imagine",
        "grok_imagine_v15": "Grok Imagine 1.5 NEW🔥🔥🔥",
        "wan_27": "Wan 2.7",
        "v3_std": "Kling 3 Std",
        "v3_pro": "Kling 3 Pro",
        "veo3": "Veo 3.1 Quality",
        "veo3_fast": "Veo 3.1 Fast",
        "veo3_lite": "Veo 3.1 Lite",
    }
    return mapping.get(model, model.replace("_", " ").title() if model else "AI")


def _build_caption(task, result_url: str) -> str:
    model_label = _get_model_label(task.model, task.type)
    is_video = task.type == "video"
    media_label = "Видео" if is_video else "Изображение"

    lines = [
        f"✅ <b>{media_label} готово!</b>",
        "",
        f"🆔 ID: <code>{html.escape(task.task_id)}</code>",
        f"🎨 Модель: <b>{html.escape(model_label)}</b>",
    ]
    if task.aspect_ratio:
        lines.append(f"📐 Формат: {html.escape(str(task.aspect_ratio).replace(':', '∶'))}")
    if task.cost:
        lines.append(f"💰 Списано: <b>{html.escape(str(task.cost))} 🍌</b>")

    caption = "\n".join(lines)

    if result_url:
        safe_url = html.escape(result_url, quote=True)
        caption += f"\n\n🔗 <a href='{safe_url}'>Открыть оригинал</a>"

    return caption[:980]


async def redeliver():
    await init_db()

    async with db_backend.connect() as conn:
        cursor = await conn.execute(
            """
            SELECT id, task_id, user_id, telegram_id, type, model, result_url, preset_id, aspect_ratio, cost
            FROM generation_tasks
            WHERE status = 'completed' AND result_url IS NOT NULL
            AND completed_at BETWEEN ? AND ?
            ORDER BY completed_at ASC
            """,
            (WINDOW_START, WINDOW_END),
        )
        tasks = await cursor.fetchall()

    if not tasks:
        logger.info("No tasks to redeliver.")
        return

    logger.info(f"Found {len(tasks)} tasks to redeliver")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    delivered = 0
    failed = 0

    for row in tasks:
        # row: (id, task_id, user_id, telegram_id, type, model, result_url, preset_id, aspect_ratio, cost)
        class TaskRow:
            id = row[0]
            task_id = row[1]
            user_id = row[2]
            telegram_id = row[3]
            type = row[4]
            model = row[5]
            result_url = row[6]
            preset_id = row[7]
            aspect_ratio = row[8]
            cost = row[9]

        task = TaskRow()
        tg_id = task.telegram_id

        if not tg_id:
            logger.warning(f"Task {task.task_id}: no telegram_id, skipping")
            failed += 1
            continue

        caption = _build_caption(task, task.result_url)
        is_video = task.type == "video"

        try:
            if is_video:
                kb = get_video_result_keyboard(
                    task.result_url,
                    task_id=str(task.id),
                    model=task.model,
                )
                try:
                    await bot.send_video(
                        chat_id=tg_id,
                        video=task.result_url,
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                        reply_markup=kb,
                    )
                except Exception:
                    # fallback: send as link
                    await bot.send_message(
                        chat_id=tg_id,
                        text=f"{caption}\n\n{task.result_url}",
                        parse_mode="HTML",
                        reply_markup=kb,
                        disable_web_page_preview=False,
                    )
            else:
                kb = get_image_result_keyboard(task.result_url, task_id=str(task.id))
                try:
                    await bot.send_photo(
                        chat_id=tg_id,
                        photo=task.result_url,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=kb,
                    )
                except Exception:
                    # fallback: send as document
                    try:
                        await bot.send_document(
                            chat_id=tg_id,
                            document=task.result_url,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=kb,
                        )
                    except Exception:
                        await bot.send_message(
                            chat_id=tg_id,
                            text=f"{caption}\n\n📎 {task.result_url}",
                            parse_mode="HTML",
                            reply_markup=kb,
                            disable_web_page_preview=False,
                        )

            delivered += 1
            logger.info(f"✓ Delivered {task.task_id} (id={task.id}) to tg_id={tg_id}")

        except Exception as e:
            failed += 1
            logger.error(f"✗ Failed {task.task_id} to tg_id={tg_id}: {e}")

    await bot.session.close()
    logger.info(f"Done. Delivered: {delivered}, Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(redeliver())