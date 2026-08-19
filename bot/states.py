#!/usr/bin/env python3

from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    """Состояния для процесса генерации"""

    waiting_for_input = State()  # Ожидание пользовательского ввода
    waiting_for_repeat_prompt = State()  # Ожидание нового prompt для повтора
    waiting_for_image = State()  # Ожидание загрузки фото
    waiting_for_video = State()  # Ожидание загрузки видео
    waiting_for_video_prompt = State()  # Ожидание ввода промпта для видео
    waiting_for_reference_video = State()  # Ожидание референсного видео для video+text
    waiting_for_motion_character_image = (
        State()
    )  # Ожидание изображения персонажа для motion control
    waiting_for_motion_video = State()  # Ожидание видео движения для motion control
    waiting_for_video_start_image = (
        State()
    )  # Ожидание загрузки стартового изображения для imgtxt
    confirming_generation = State()  # Подтверждение перед запуском
    selecting_batch_count = (
        State()
    )  # Выбор количества изображений для пакетной генерации

    # Состояния для загрузки референсных изображений (до 14 шт)
    uploading_reference_images = State()  # Загрузка референсных изображений
    uploading_reference_videos = State()  # Загрузка референсных видео для video+text
    confirming_reference_images = State()  # Подтверждение референсов перед генерацией

    # Состояния для пакетного редактирования
    waiting_for_batch_image = State()  # Ожидание загрузки фото
    waiting_for_batch_prompt = State()  # Ожидание ввода промпта
    waiting_for_batch_aspect_ratio = State()  # Ожидание выбора aspect ratio

    # Состояния для видео-опций
    selecting_duration = State()  # Выбор длительности видео
    selecting_aspect_ratio = State()  # Выбор формата видео
    selecting_quality = State()  # Выбор качества видео
    waiting_for_veo_seed = State()  # Ввод seed для Veo
    waiting_for_veo_watermark = State()  # Ввод watermark для Veo
    waiting_for_veo_extend_prompt = State()  # Промпт для продления Veo
    waiting_for_kling_negative_prompt = State()  # Negative prompt для Kling 2.5
    waiting_for_kling_cfg_scale = State()  # CFG scale для Kling 2.5
    waiting_for_avatar_audio = State()  # Аудио для Kling AI Avatar
    waiting_for_omni_seed = State()  # Seed для Gemini Omni Video
    waiting_for_omni_audio_ids = State()  # Audio IDs для Gemini Omni Audio
    waiting_for_omni_character_ids = State()  # Character IDs для Gemini Omni Character
    waiting_for_omni_voice_base = State()  # Базовый голос Gemini Omni Audio
    waiting_for_omni_voice_name = State()  # Имя Gemini Omni Audio
    waiting_for_omni_voice_description = State()  # Описание голоса
    waiting_for_omni_example_dialogue = State()  # Пример диалога
    waiting_for_omni_character_name = State()  # Имя Gemini Omni Character
    waiting_for_omni_character_audio_ids = State()  # Audio IDs для Character


class PaymentStates(StatesGroup):
    """Состояния для процесса оплаты"""

    selecting_package = State()  # Выбор пакета
    waiting_promo_code = State()  # Ввод промокода на пополнение
    confirming_payment = State()  # Подтверждение оплаты
    waiting_payment = State()  # Ожидание оплаты
    waiting_lava_email = State()  # Реальная почта покупателя для Lava
    waiting_partner_withdraw_requisites = State()  # Реквизиты для вывода партнёру
    waiting_partner_withdraw_amount = State()  # Сумма вывода партнёру
    waiting_partner_exchange_amount = State()  # Сумма обмена партнёрского баланса в бананы


class AdminStates(StatesGroup):
    """Состояния для админ-панели"""

    waiting_broadcast_text = State()  # Ввод текста рассылки
    confirming_broadcast = State()  # Подтверждение рассылки
    waiting_user_id = State()  # Ввод ID пользователя
    waiting_partner_user_id = State()  # Ввод ID партнёра для статистики
    waiting_credits_amount = State()  # Ввод количества кредитов
    waiting_price_value = State()  # Ввод нового значения цены
    waiting_prompt_id = State()  # Ввод промпта для модерации
    waiting_prompt_reject_reason = State()  # Причина отклонения промпта
    waiting_promo_code_value = State()  # Создание/поиск промокода
    waiting_ai_request = State()  # Ввод задачи для ИИ-админа
    confirming_ai_action = State()  # Подтверждение действия ИИ
    waiting_nano_banana2_prompt = State()  # Тест Nano Banana 2 (api.apiyi.com)


class BatchGenerationStates(StatesGroup):
    """Состояния для пакетной генерации"""

    selecting_mode = State()  # Выбор режима: pro или standard
    selecting_preset = State()  # Выбор пресета
    entering_prompts = State()  # Ввод промптов (один или несколько)
    uploading_references = State()  # Загрузка референсных изображений
    confirming_batch = State()  # Подтверждение перед запуском
    selecting_batch_count = State()  # Количество изображений для одиночного промпта


class ImageAnalyzerStates(StatesGroup):
    """Состояния для анализа медиа в промпт"""

    waiting_for_photo = State()
    waiting_for_video_prompt = State()
    waiting_for_photo_vk = State()


class SeedreamVideoStates(StatesGroup):
    """Состояния для генерации фото по видео референсам Seedream 5.0 Lite"""

    waiting_for_video = State()
    waiting_for_prompt = State()
