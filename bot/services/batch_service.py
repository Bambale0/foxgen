import asyncio
import io
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from bot.config import config
from bot.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


def _is_binary_image_payload(result) -> bool:
    return isinstance(result, (bytes, bytearray))


class BatchStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BatchItem:
    index: int
    image: bytes  # Исходное изображение (bytes для галереи/превью)
    prompt: str  # Промпт пользователя
    image_url: Optional[str] = None  # Публичный URL исходного изображения
    status: BatchStatus = BatchStatus.PENDING
    result: Optional[bytes] = None
    result_url: Optional[str] = None  # Публичный URL результата
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None


@dataclass
class BatchJob:
    id: str
    user_id: int
    images: List[bytes]  # Список исходных изображений
    prompt: str  # Промпт от пользователя
    aspect_ratio: str  # Соотношение сторон (1:1, 16:9 и т.д.)
    total_cost: int
    items: List[BatchItem] = field(default_factory=list)
    status: BatchStatus = BatchStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    progress_callback: Optional[Callable] = None

    @property
    def progress_percent(self) -> int:
        if not self.items:
            return 0
        completed = sum(1 for i in self.items if i.status == BatchStatus.COMPLETED)
        return int(completed / len(self.items) * 100)

    @property
    def is_complete(self) -> bool:
        return all(
            i.status in (BatchStatus.COMPLETED, BatchStatus.FAILED) for i in self.items
        )


class BatchEditingService:
    """Сервис пакетного редактирования изображений"""

    MAX_CONCURRENT = 3
    COST_PER_IMAGE = 2  # 2 банана за изображение

    def __init__(self):
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._active_jobs: Dict[str, BatchJob] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _save_result_file(
        self, file_bytes: bytes, file_ext: str = "png"
    ) -> Optional[str]:
        """
        Сохраняет результат в папку static/uploads и возвращает публичный URL.
        """
        try:
            if not _is_binary_image_payload(file_bytes):
                logger.error(
                    "Batch _save_result_file expected bytes, got %s",
                    type(file_bytes).__name__,
                )
                return None

            # Создаём поддиректорию по дате
            date_str = datetime.now().strftime("%Y%m%d")
            upload_dir = os.path.join("static", "uploads", date_str)
            os.makedirs(upload_dir, exist_ok=True)

            # Генерируем уникальное имя файла
            file_id = str(uuid.uuid4())[:8]
            filename = f"{file_id}.{file_ext}"
            filepath = os.path.join(upload_dir, filename)

            # Сохраняем файл
            with open(filepath, "wb") as f:
                f.write(bytes(file_bytes))

            # Формируем публичный URL
            base_url = config.static_base_url
            public_url = f"{base_url}/uploads/{date_str}/{filename}"

            logger.info(f"Saved batch result: {public_url}")
            return public_url

        except Exception as e:
            logger.exception(f"Error saving batch result file: {e}")
            return None

    async def create_batch_job(
        self,
        user_id: int,
        images: List[bytes],
        prompt: str,
        aspect_ratio: str = "1:1",
        image_urls: List[str] = None,
    ) -> Optional[BatchJob]:
        """Создаёт задачу пакетного редактирования"""

        if not images or not prompt:
            return None

        # Рассчитываем стоимость (Pro модель = 3 банана)
        total_cost = len(images) * 3

        # Генерируем ID задачи
        job_id = f"batch_{user_id}_{int(time.time())}"

        # Создаём элементы - каждое изображение с одним промптом
        items = []
        for i, image in enumerate(images):
            image_url = image_urls[i] if image_urls and i < len(image_urls) else None
            items.append(
                BatchItem(index=i, image=image, prompt=prompt, image_url=image_url)
            )

        job = BatchJob(
            id=job_id,
            user_id=user_id,
            images=images,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            total_cost=total_cost,
            items=items,
        )

        self._active_jobs[job_id] = job
        return job

    async def execute_batch(
        self,
        job: BatchJob,
        progress_callback: Optional[Callable[[BatchJob], Any]] = None,
    ) -> BatchJob:
        """Выполняет пакетное редактирование с прогрессом"""

        job.status = BatchStatus.RUNNING
        job.progress_callback = progress_callback

        # Используем Pro модель с высоким качеством
        model = "gemini-3-pro-image-preview"

        # Пакетное редактирование — параллельная обработка
        await self._execute_parallel_editing(job, model)

        # Финальная сборка
        await self._finalize_job(job)

        return job

    async def _execute_parallel_editing(self, job: BatchJob, model: str):
        """Параллельное редактирование с ограничением конкурентности"""

        async def edit_item(item: BatchItem):
            async with self._semaphore:
                item.status = BatchStatus.RUNNING
                item.started_at = time.time()

                try:
                    # Редактирование изображения через Gemini с Pro моделью, 4K качеством
                    # Используем публичный URL если доступен, иначе bytes
                    result = await gemini_service.generate_image(
                        prompt=item.prompt,
                        model=model,
                        aspect_ratio=job.aspect_ratio,
                        image_input=item.image if not item.image_url else None,
                        image_input_url=item.image_url,
                        resolution="4K",
                    )

                    if _is_binary_image_payload(result):
                        result_bytes = bytes(result)
                        item.result = result_bytes
                        # Сохраняем результат в файл и получаем публичный URL
                        result_url = self._save_result_file(result_bytes, "png")
                        if result_url:
                            item.result_url = result_url
                        item.status = BatchStatus.COMPLETED
                    else:
                        item.status = BatchStatus.FAILED
                        item.error = (
                            f"Unexpected response type: {type(result).__name__}"
                            if result
                            else "Empty response"
                        )
                        if result:
                            logger.error(
                                "Batch item %s returned non-binary payload: %s",
                                item.index,
                                type(result).__name__,
                            )

                except Exception as e:
                    logger.exception(f"Item {item.index} failed: {e}")
                    item.status = BatchStatus.FAILED
                    item.error = str(e)
                finally:
                    item.completed_at = time.time()

                    # Уведомляем о прогрессе
                    if job.progress_callback:
                        await job.progress_callback(job)

        # Запускаем все задачи параллельно (семафор ограничит)
        await asyncio.gather(*[edit_item(item) for item in job.items])

    async def _finalize_job(self, job: BatchJob):
        """Финализирует задачу — сборка галереи, метрики"""

        job.completed_at = time.time()

        successful = [i for i in job.items if i.status == BatchStatus.COMPLETED]

        if len(successful) == len(job.items):
            job.status = BatchStatus.COMPLETED
        elif successful:
            job.status = BatchStatus.PARTIAL
        else:
            job.status = BatchStatus.FAILED

        # Сохраняем в БД для истории
        await self._save_job_results(job)

    async def _save_job_results(self, job: BatchJob):
        """Сохраняет результаты в базу данных"""
        try:
            from bot.database import save_batch_job

            await save_batch_job(
                job_id=job.id,
                user_id=job.user_id,
                mode="batch_edit",
                total_cost=job.total_cost,
                results_count=sum(
                    1 for i in job.items if i.status == BatchStatus.COMPLETED
                ),
                duration=(
                    job.completed_at - job.created_at if job.completed_at else None
                ),
            )
        except Exception as e:
            logger.error(f"Failed to save batch job: {e}")

    async def create_gallery_preview(self, job: BatchJob) -> Optional[bytes]:
        """Создаёт превью-галерею из результатов"""

        successful = [i for i in job.items if i.result]
        if not successful:
            return None

        def _create_gallery():
            from PIL import Image, ImageDraw, ImageFont

            # Определяем разметку
            count = len(successful)
            if count <= 2:
                cols, rows = count, 1
            elif count <= 4:
                cols, rows = 2, 2
            else:
                cols, rows = 3, 2

            # Размер превью
            thumb_size = 512
            gallery_width = cols * thumb_size
            gallery_height = rows * thumb_size

            gallery = Image.new("RGB", (gallery_width, gallery_height), (240, 240, 240))

            for idx, item in enumerate(successful):
                if idx >= cols * rows:
                    break

                img = Image.open(io.BytesIO(item.result))
                img.thumbnail(
                    (thumb_size - 20, thumb_size - 20), Image.Resampling.LANCZOS
                )

                row = idx // cols
                col = idx % cols

                x = col * thumb_size + 10
                y = row * thumb_size + 10

                # Вставляем
                gallery.paste(img, (x, y))

                # Номер
                draw = ImageDraw.Draw(gallery)
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20
                    )
                except Exception:
                    font = ImageFont.load_default()

                draw.text((x + 5, y + 5), str(idx + 1), fill=(255, 255, 255), font=font)

            # Сохраняем
            buf = io.BytesIO()
            gallery.save(buf, format="JPEG", quality=85)
            return buf.getvalue()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _create_gallery)

    async def upscale_selected(
        self, job_id: str, item_index: int, target_resolution: str = "4K"
    ) -> Optional[bytes]:
        """Апскейл выбранного изображения до высокого разрешения"""

        job = self._active_jobs.get(job_id)
        if not job:
            return None

        if item_index >= len(job.items):
            return None

        item = job.items[item_index]
        if not item.result:
            return None

        # Используем Gemini 3 Pro для апскейла
        upscale_prompt = (
            f"Faithfully upscale and enhance this image to {target_resolution} quality. "
            f"Preserve all details, enhance sharpness, add fine texture where appropriate. "
            f"Professional photo restoration and enhancement."
        )

        # Отправляем изображение на улучшение
        result = await gemini_service.generate_image(
            prompt=upscale_prompt,
            model="gemini-3-pro-image-preview",
            image_input=item.result,
        )

        if _is_binary_image_payload(result):
            return bytes(result)
        if result:
            logger.error(
                "Batch upscale returned non-binary payload for job %s item %s: %s",
                job_id,
                item_index,
                type(result).__name__,
            )
        return None

    def get_job(self, job_id: str) -> Optional[BatchJob]:
        """Получает активную задачу"""
        return self._active_jobs.get(job_id)

    def get_batch_modes(self) -> Dict[str, Dict]:
        """Получает все доступные режимы пакетного редактирования"""
        try:
            presets_path = Path("data/presets.json")
            with open(presets_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("batch_edit_modes", {})
        except Exception:
            return {}

    async def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Очищает старые задачи из памяти"""
        cutoff = time.time() - (max_age_hours * 3600)

        to_remove = [
            jid
            for jid, job in self._active_jobs.items()
            if job.completed_at and job.completed_at < cutoff
        ]

        for jid in to_remove:
            del self._active_jobs[jid]

        return len(to_remove)


# Глобальный сервис
batch_service = BatchEditingService()
