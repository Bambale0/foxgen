"""
Примеры использования Kling 3 API Service

Этот файл содержит подробные примеры использования всех методов KlingService.

Документация API: https://docs.freepik.com/apis/freepik/ai/kling-v3
"""

import asyncio
import os

from bot.config import config

# Способ 1: Использовать готовый инстанс (рекомендуется)
# kling_service уже инициализирован в kling_service.py
# Импорт сервиса
from bot.services.kling_service import KlingService, kling_service

# =============================================================================
# Инициализация сервиса
# =============================================================================


# Способ 2: Создать свой инстанс
# kling_service = KlingService(
#     api_key="ВАШ_API_KEY",  # FREEPIK_API_KEY из .env
#     base_url="https://api.freepik.com/v1"
# )


# =============================================================================
# ПРИМЕР 1: Текст в видео (Text-to-Video)
# =============================================================================


async def example_text_to_video():
    """
    Генерация видео из текстового описания (T2V)

    Поддерживаемые параметры:
    - prompt: текстовое описание (до 2500 символов)
    - duration: длительность видео (3-15 секунд)
    - aspect_ratio: формат видео ("16:9", "9:16", "1:1")
    - quality: качество ("pro" - лучше, "std" - быстрее)
    """
    print("\n=== ПРИМЕР 1: Text-to-Video ===")

    # Простой вызов
    result = await kling_service.text_to_video(
        prompt="A futuristic city with flying cars and neon lights at sunset",
        duration=5,
        aspect_ratio="16:9",
        quality="std",  # или "pro"
    )

    if result:
        print(f"✅ Задача создана! Task ID: {result['task_id']}")
        print(f"   Статус: {result['status']}")

        # Ожидание результата
        final_result = await kling_service.wait_for_completion(
            task_id=result["task_id"],
            max_attempts=60,  # Максимум 60 попыток
            delay=5,  # Пауза 5 секунд между попытками
        )

        if final_result:
            print(f"✅ Видео готово!")
            print(f"   Результат: {final_result}")
    else:
        print("❌ Ошибка создания задачи")


# =============================================================================
# ПРИМЕР 2: Изображение в видео (Image-to-Video)
# =============================================================================


async def example_image_to_video():
    """
    Генерация видео из изображения (I2V)

    Параметры:
    - image_url: URL изображения (мин 300x300, макс 10MB, JPG/PNG)
    - prompt: текстовое описание (что сделать с изображением)
    - duration: длительность (3-15 сек)
    - aspect_ratio: формат видео
    - quality: "pro" или "std"
    """
    print("\n=== ПРИМЕР 2: Image-to-Video ===")

    result = await kling_service.image_to_video(
        image_url="https://example.com/photo.jpg",
        prompt="Animate this person walking through the city",
        duration=5,
        aspect_ratio="16:9",
        quality="std",
    )

    if result:
        print(f"✅ Задача создана! Task ID: {result['task_id']}")
    else:
        print("❌ Ошибка создания задачи")


# =============================================================================
# ПРИМЕР 3: Видео в видео (Video-to-Video / Reference-to-Video)
# =============================================================================


async def example_video_to_video():
    """
    Генерация видео с использованием референсного видео (R2V)

    Параметры:
    - video_url: URL референсного видео (3-10 сек, 720-2160px, макс 200MB, mp4/mov)
    - prompt: описание с @Video1 для ссылки на видео
    - duration: длительность (3-15 сек)
    - aspect_ratio: формат видео
    - quality: "pro" или "std"
    """
    print("\n=== ПРИМЕР 3: Video-to-Video ===")

    result = await kling_service.video_to_video(
        video_url="https://example.com/reference.mp4",
        prompt="@Video1 A person dancing in a futuristic setting with neon lights",
        duration=5,
        aspect_ratio="16:9",
        quality="std",
    )

    if result:
        print(f"✅ Задача создана! Task ID: {result['task_id']}")
    else:
        print("❌ Ошибка создания задачи")


# =============================================================================
# ПРИМЕР 4: Продвинутые методы - Kling 3 Pro
# =============================================================================


async def example_kling_pro():
    """
    Использование Kling 3 Pro с расши

    Дренными параметрамиополнительные параметры:
    - negative_prompt: что исключить из видео
    - cfg_scale: adherence to prompt (0-2, где 0 - креативно, 2 - строго)
    - generate_audio: генерировать ли звук (по умолчанию True)
    - voice_ids: ID голосов для озвучивания (макс 2)
    - elements: элементы для консистентности персонажей
    - multi_prompt: несколько сцен (до 6)
    """
    print("\n=== ПРИМЕР 4: Kling 3 Pro ===")

    result = await kling_service.generate_video_pro(
        prompt="A majestic dragon flying over mountains at sunrise",
        duration=5,
        aspect_ratio="16:9",
        # Дополнительные параметры
        negative_prompt="blur, distortion, low quality, watermark",
        cfg_scale=0.7,  # Баланс между креативностью и точностью
        generate_audio=True,  # Генерировать звук
        voice_ids=None,  # Можно добавить ID голосов
        # Для I2V
        # start_image_url="https://example.com/start.jpg",
        # end_image_url="https://example.com/end.jpg",
    )

    if result:
        print(f"✅ Задача создана! Task ID: {result['task_id']}")
    else:
        print("❌ Ошибка создания задачи")


# =============================================================================
# ПРИМЕР 5: Kling 3 Omni Pro с элементами
# =============================================================================


async def example_omni_with_elements():
    """
    Использование Kling 3 Omni с элементами для консистентности

    Elements позволяют сохранять одного персонажа/объект между видео
    """
    print("\n=== ПРИМЕР 5: Omni с элементами ===")

    # Определение элемента (персонаж)
    elements = [
        {
            "reference_image_urls": [
                "https://example.com/face1.jpg",
                "https://example.com/face2.jpg",
            ],
            "frontal_image_url": "https://example.com/face_front.jpg",
        }
    ]

    result = await kling_service.generate_video_omni_pro(
        prompt="@Element1 walking in a modern city",
        duration=5,
        aspect_ratio="16:9",
        elements=elements,
    )

    if result:
        print(f"✅ Задача создана! Task ID: {result['task_id']}")
    else:
        print("❌ Ошибка создания задачи")


# =============================================================================
# ПРИМЕР 6: Multi-shot (несколько сцен)
# =============================================================================


async def example_multishot():
    """
    Создание видео из нескольких сцен (до 6, макс 15 сек всего)
    """
    print("\n=== ПРИМЕР 6: Multi-shot ===")

    # Определение сцен
    multi_prompt = [
        {"prompt": "A car driving through a forest road", "duration": "3"},
        {"prompt": "The car arrives at a futuristic city", "duration": "4"},
        {"prompt": "The car parks in front of a tall building", "duration": "3"},
    ]

    result = await kling_service.generate_video_std(
        prompt="",  # Не используется при multi_prompt
        duration=10,  # Общая длительность (сумма duration в multi_prompt)
        aspect_ratio="16:9",
        multi_prompt=multi_prompt,
        shot_type="customize",
    )

    if result:
        print(f"✅ Задача создана! Task ID: {result['task_id']}")
    else:
        print("❌ Ошибка создания задачи")


# =============================================================================
# ПРИМЕР 7: Проверка статуса задачи
# =============================================================================


async def example_check_status():
    """
    Проверка статуса конкретной задачи
    """
    print("\n=== ПРИМЕР 7: Проверка статуса ===")

    task_id = "YOUR_TASK_ID_HERE"

    # Способ 1: Прямой вызов
    status = await kling_service.get_v3_task_status(task_id)

    # Способ 2: Через универсальный метод
    status = await kling_service.get_task_status(task_id)

    if status:
        data = status.get("data", {})
        print(f"   Task ID: {data.get('task_id')}")
        print(f"   Статус: {data.get('status')}")

        # Если видео готово
        if data.get("status") == "COMPLETED":
            print(f"   Результат: {data.get('generated')}")
    else:
        print("❌ Ошибка получения статуса")


# =============================================================================
# ПРИМЕР 8: Список всех задач
# =============================================================================


async def example_list_tasks():
    """
    Получение списка всех задач с пагинацией
    """
    print("\n=== ПРИМЕР 8: Список задач ===")

    # Список задач Kling 3
    tasks = await kling_service.list_v3_tasks(page=1, page_size=20)

    if tasks:
        for task in tasks.get("data", []):
            print(f"   Task: {task.get('task_id')} - Status: {task.get('status')}")

    # Список задач Kling 3 Omni
    omni_tasks = await kling_service.list_omni_tasks(page=1, page_size=10)

    # Список задач Reference-to-Video
    r2v_tasks = await kling_service.list_r2v_tasks(page=1, page_size=10)


# =============================================================================
# ПРИМЕР 9: Использование webhook
# =============================================================================


async def example_with_webhook():
    """
    Использование webhook для уведомления о завершении
    """
    print("\n=== ПРИМЕР 9: Webhook ===")

    webhook_url = "https://your-domain.com/webhook/kling"

    result = await kling_service.generate_video_std(
        prompt="A beautiful sunset over the ocean",
        duration=5,
        webhook_url=webhook_url,  # URL для уведомления
    )

    if result:
        print(f"✅ Задача создана с webhook!")
        print(f"   При завершении придёт уведомление на: {webhook_url}")
    else:
        print("❌ Ошибка")


# =============================================================================
# Универсальный метод generate_video()
# =============================================================================


async def example_universal():
    """
    Универсальный метод generate_video() для обратной совместимости
    """
    print("\n=== ПРИМЕР 10: Универсальный метод ===")

    # Доступные модели:
    # - "v3_pro"       : Kling 3 Pro
    # - "v3_std"       : Kling 3 Standard
    # - "v3_omni_pro"  : Kling 3 Omni Pro
    # - "v3_omni_std"  : Kling 3 Omni Standard
    # - "v3_omni_pro_r2v" : Kling 3 Omni Pro Video-to-Video
    # - "v3_omni_std_r2v" : Kling 3 Omni Standard Video-to-Video

    result = await kling_service.generate_video(
        prompt="A cat playing with a ball of yarn",
        model="v3_std",  # Какая модель использовать
        duration=5,
        aspect_ratio="16:9",
        cfg_scale=0.5,
    )

    if result:
        print(f"✅ Задача создана! Task ID: {result['task_id']}")
    else:
        print("❌ Ошибка")


# =============================================================================
# Запуск всех примеров
# =============================================================================


async def main():
    """Запуск всех примеров"""
    print("🚀 Запуск примеров использования Kling 3 API")
    print("=" * 50)

    # Примечание: Для запуска нужно добавить API ключ в .env
    # FREEPIK_API_KEY=your_api_key

    # Раскомментируйте нужный пример для тестирования:

    # await example_text_to_video()
    # await example_image_to_video()
    # await example_video_to_video()
    # await example_kling_pro()
    # await example_omni_with_elements()
    # await example_multishot()
    # await example_check_status()
    # await example_list_tasks()
    # await example_with_webhook()
    # await example_universal()

    print("\n✅ Все примеры готовы к использованию!")
    print("   Раскомментируйте нужный пример в функции main()")


if __name__ == "__main__":
    asyncio.run(main())


# =============================================================================
# КРАТКАЯ ШПАРГАЛКА
# =============================================================================

"""
КРАТКАЯ ШПАРГАЛКА ПО ИСПОЛЬЗОВАНИЮ:

1. Импорт:
   from bot.services.kling_service import kling_service

2. Текст в видео:
   result = await kling_service.text_to_video(
       prompt="описание видео",
       duration=5,
       aspect_ratio="16:9",
       quality="std"  # или "pro"
   )

3. Изображение в видео:
   result = await kling_service.image_to_video(
       image_url="URL_изображения",
       prompt="что сделать",
       duration=5,
       quality="std"
   )

4. Видео в видео:
   result = await kling_service.video_to_video(
       video_url="URL_видео",
       prompt="@Video1 описание",
       duration=5,
       quality="std"
   )

5. Ожидание результата:
   final = await kling_service.wait_for_completion(task_id)

6. Проверка статуса:
   status = await kling_service.get_task_status(task_id)

ПАРАМЕТРЫ:
- duration: 3-15 секунд
- aspect_ratio: "16:9", "9:16", "1:1"
- quality: "pro" (лучше качество), "std" (быстрее)
- cfg_scale: 0-2 (0 - креативно, 2 - строго следует промпту)
"""
