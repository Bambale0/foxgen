"""
Скрипт для скачивания всех существующих публикаций ленты с эфемерных хостов
на сервер, чтобы они не исчезали по TTL.

Запуск: source venv/bin/activate && python scripts/persist_existing_feed.py
"""

import asyncio
import json
import logging
import os
import sys

# Путь к корню проекта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    # Вручную ставим DATABASE_URL из .env.postgres
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env.postgres")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    os.environ["DATABASE_URL"] = line.split("=", 1)[1]
                    break

    import bot.db as db_backend
    db_backend.DATABASE_URL = os.environ.get("DATABASE_URL", "")
    db_backend.DATABASE_PATH = os.environ["DATABASE_URL"]

    from bot.services.feed_persist import download_to_local
    from bot.database import (
        DATABASE_PATH,
        _generation_result_urls,
        _is_ephemeral_feed_result_url,
        FEED_EPHEMERAL_RESULT_HOSTS,
        _feed_result_host,
    )

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        # Выбираем все публичные записи, у которых хотя бы один URL эфемерный
        cur = await db.execute(
            """
            SELECT id, result_url, result_urls, completed_at, created_at
            FROM generation_tasks
            WHERE is_public_feed IS TRUE
              AND status = 'completed'
            ORDER BY completed_at DESC
            """
        )
        rows = await cur.fetchall()
        logger.info("Всего публичных записей: %s", len(rows))

        updated_count = 0
        skipped_count = 0
        failed_count = 0

        for row in rows:
            gen_id = row["id"]
            result_urls = _generation_result_urls(row)

            # Проверяем, есть ли среди URL эфемерные
            has_ephemeral = any(
                _is_ephemeral_feed_result_url(url)
                for url in result_urls
            )
            if not has_ephemeral:
                skipped_count += 1
                continue

            logger.info("Обрабатываю запись %s (%s URL)...", gen_id, len(result_urls))

            # Скачиваем эфемерные URL
            persisted = []
            for url in result_urls:
                if _is_ephemeral_feed_result_url(url):
                    local = await download_to_local(url)
                    if local:
                        persisted.append(local)
                    else:
                        persisted.append(url)
                else:
                    persisted.append(url)

            if persisted == result_urls:
                # Ничего не изменилось
                skipped_count += 1
                continue

            # Сохраняем новые URL в БД
            new_result_url = persisted[0] if persisted else row["result_url"]
            result_urls_json = json.dumps(persisted, ensure_ascii=False)

            try:
                await db.execute(
                    """
                    UPDATE generation_tasks
                    SET result_url = ?,
                        result_urls = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_result_url, result_urls_json, gen_id),
                )
                updated_count += 1
                logger.info(
                    "  Обновлено: %s -> %s",
                    gen_id,
                    new_result_url[:60] + "...",
                )
            except Exception as e:
                logger.exception("  Ошибка обновления записи %s: %s", gen_id, e)
                failed_count += 1

        await db.commit()

    logger.info(
        "\nГотово! Обновлено: %s, пропущено: %s, ошибок: %s",
        updated_count,
        skipped_count,
        failed_count,
    )


if __name__ == "__main__":
    asyncio.run(main())