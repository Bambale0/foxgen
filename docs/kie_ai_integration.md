# Полная карта интеграции AI-моделей через kie.ai

> **Дата:** 29.06.2026  
> **Назначение:** Документация по всем AI-моделям, их маппингу, маршрутизации и полноценной интеграции в проект  
> **Основной провайдер:** `https://api.kie.ai` (KIE = Kie.ai)

---

## 1. АРХИТЕКТУРА ИНТЕГРАЦИИ

### 1.1. Роль kie.ai

**kie.ai** выступает как **роутер/прокси/Market API** ко множеству моделей. Почти все сервисы отправляют POST на единый эндпоинт с полем `model`, которое выбирает конкретную модель внутри KIE.

### 1.2. Основные эндпоинты KIE

| Эндпоинт | Назначение | Используется в |
|---|---|---|
| `POST /api/v1/jobs/createTask` | Создание задачи генерации | Kling, Grok, GPT Image, Seedream, Seedance, Wan 2.7, Nano Banana Pro/2 |
| `GET /api/v1/jobs/recordInfo` | Получение статуса задачи | Все сервисы-наследники KlingService |
| `POST /api/file-stream-upload` | Загрузка файлов (refs) | KieFileUploadService |
| `POST /codex/v1/responses` | Responses API (GPT-5.5) | Photo/Video Prompt Service |
| `/gpt-5-2/v1/chat/completions` | Chat Completions | AI Assistant, Admin AI |
| `/claude/v1/messages` | Claude API | Admin AI |
| `/api/v1/veo/generate` | Veo 3.1 Video | VeoService |

### 1.3. API-ключи (из config.py)

| Переменная | Назначение |
|---|---|
| `KIE_AI_API_KEY` | **Основной ключ** для всех kie.ai запросов |
| `NANOBANANA_API_KEY` | Legacy ключ (используется как fallback для KIE) |
| `GEMINI_API_KEY` | Нативный Gemini API (fallback) |
| `KLING_API_KEY` / `PIAPI_API_KEY` | Legacy Kling ключи |
| `NANOBANANA2_FALLBACK_API_KEY` | Fallback для Nano Banana 2 (Gemini-compat) |
| `NANO_BANANA_PRO_FALLBACK_API_KEY` | Fallback для Nano Banana Pro (Gemini-compat) |
| `REPLICATE_API_TOKEN` | Replicate API (старая интеграция) |

### 1.4. Базовые URL

```python
KIE_BASE_URL = "https://api.kie.ai"
NANOBANANA_BASE_URL = "https://api.nanobanana.com/v1"
PIAPI_BASE_URL = "https://api.piapi.ai"
NOVITA_BASE_URL = "https://api.novita.ai"
FREEPIK_BASE_URL = "https://api.freepik.com/v1"
```

---

## 2. ПОЛНАЯ КАРТА МОДЕЛЕЙ

### 2.1. Видео-модели (Video)

#### 2.1.1. Kling 3.0 (v3_std, v3_pro)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `v3_std`, `v3_pro`, `kling_v3`, `kling_3`, `kling_3_pro` |
| **Модель Kie.ai** | `kling-3.0/video` |
| **Сервис** | `KlingService.generate_kling_3_video()` |
| **Параметры** | prompt, mode (std/pro), duration (3-15), aspect_ratio (16:9/9:16/1:1), image_urls, sound (bool), multi_shots, kling_elements, callBackUrl |
| **Длительность** | 3-15 секунд |
| **Особенности** | Поддержка multi-shots, Kling Elements (до 3 элементов), звук |
| **Цена** | `KlingService` — базовая |

#### 2.1.2. Kling 2.5 Turbo Pro (v26_pro)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `v26_pro`, `kling_25_turbo_pro` |
| **Модели Kie.ai** | `kling/v2-5-turbo-text-to-video-pro` (текст→видео), `kling/v2-5-turbo-image-to-video-pro` (изображ→видео) |
| **Сервис** | `KlingService.generate_kling_25_turbo_video()` |
| **Параметры** | prompt, duration (5/10), aspect_ratio, image_url (опц.), negative_prompt, cfg_scale (0.0-1.0), callBackUrl |
| **Длительность** | 5 или 10 секунд |
| **Цена** | Базовая через `pricing_final` |

#### 2.1.3. Kling AI Avatar (avatar_std, avatar_pro)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `avatar_std`, `avatar_pro`, `kling_avatar_std`, `kling_avatar_pro` |
| **Модели Kie.ai** | `kling/ai-avatar-standard`, `kling/ai-avatar-pro` |
| **Сервис** | `KlingService.generate_kling_ai_avatar()` |
| **Вход** | image_url (фото персонажа), audio_url (аудио), prompt |
| **Особенности** | Генерация говорящего аватара |

#### 2.1.4. Kling Motion Control (motion_control)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `motion_control_v26`, `motion_control_v30`, `kling-2.6/motion-control`, `kling-3.0/motion-control` |
| **Модели Kie.ai** | `kling-2.6/motion-control`, `kling-3.0/motion-control` |
| **Сервис** | `KlingService.generate_motion_control()` |
| **Вход** | image_url (фото персонажа), video_urls (видео движения), preset_motion, prompt, motion_direction, mode (720p/1080p) |

#### 2.1.5. Kling Glow (glow)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `glow` |
| **Модель Kie.ai** | Специальная (Motion Control c glow) |
| **Сервис** | `KlingService.generate_video()` → `generate_motion_control()` |
| **Особенности** | Перенос glow-стиля на референсного персонажа |

#### 2.1.6. Grok Imagine (grok_imagine)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `grok_imagine` |
| **Модель Kie.ai** | `grok-imagine/image-to-video` |
| **Сервис** | `GrokService.generate_image_to_video()` |
| **Вход** | image_urls (до 7), prompt, mode, duration, resolution, aspect_ratio |
| **Особенности** | Превращает изображения в видео |
| **Цена** | 6🍌 (по умолчанию) |

#### 2.1.7. Grok Imagine 1.5 (grok_imagine_v15)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `grok_imagine_v15` |
| **Модель Kie.ai** | `grok-imagine-video-1-5-preview` |
| **Сервис** | `GrokService.generate_image_to_video_v15()` |
| **Вход** | 1 image_url, prompt, duration (1-15), resolution (480p/720p), aspect_ratio |
| **Особенности** | **NEW** — улучшенное качество, поддержка resolution/aspect_ratio |
| **Цена** | 8🍌 (по умолчанию) |

#### 2.1.8. Grok Imagine i2i (grok_imagine_i2i)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `grok_imagine_i2i` |
| **Модель Kie.ai** | `grok-imagine/image-to-image` |
| **Сервис** | `GrokService.generate_image_to_image()` |
| **Вход** | image_urls, prompt |
| **Особенности** | Генерация изображения из изображения + промпта |

#### 2.1.9. Bytedance Seedance 2.0 (seedance_2)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `seedance_2` |
| **Модель Kie.ai** | `bytedance/seedance-2` |
| **Сервис** | `SeedanceService.generate_video()` |
| **Вход** | prompt, duration (5-15), aspect_ratio (16:9/9:16/1:1), resolution (480p/720p/1080p), first_frame_url, last_frame_url, reference_image_urls (до 9), reference_video_urls (до 3), reference_audio_urls (1), return_last_frame, generate_audio, web_search |
| **Особенности** | first/last-frame НЕ совместимы с multimodal references |
| **Цена** | 5🍌 (по умолчанию) |

#### 2.1.10. Veo 3.1 (veo3, veo3_fast, veo3_lite)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `veo3`, `veo3_fast`, `veo3_lite` |
| **Эндпоинт** | `POST https://api.kie.ai/api/v1/veo/generate` |
| **Сервис** | `VeoService` (отдельный, не наследник KlingService) |
| **Модели** | Google Veo 3.1 — Quality / Fast / Lite |
| **Цена** | 6🍌 (по умолчанию) |

#### 2.1.11. Gemini Omni (gemini_omni)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `gemini_omni`, `gemini_omni_video`, `gemini_omni_audio`, `gemini_omni_character` |
| **Сервис** | `GeminiOmniService` |
| **Особенности** | Поддержка аудио и character ID |
| **Под-типы** | video (фото→видео), audio (аудио→видео), character (персонаж→видео) |
| **Цена** | от 6🍌 |

---

### 2.2. Изображения (Image Models)

#### 2.2.1. Nano Banana Pro (banana_pro / nano_banana_pro)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `banana_pro`, `nano_banana_pro`, `nanobanana` |
| **Модель Kie.ai** | `nano-banana-pro` |
| **Сервис** | `NanoBananaProService.create_task()` |
| **Параметры** | prompt, image_input, aspect_ratio, resolution (1K/2K/4K), output_format |
| **Primary** | `KIE_AI_API_KEY` → `https://api.kie.ai` |
| **Fallback** | `NANO_BANANA_PRO_FALLBACK_API_KEY` → `api.apiyi.com` (Gemini-compat, модель `gemini-3-pro-image-preview`) |
| **Эндпоинт KIE** | `POST /api/v1/jobs/createTask` |
| **Загрузка файлов** | Через `KieFileUploadService` → `/api/file-stream-upload` |
| **Цена** | 5🍌 |

#### 2.2.2. Nano Banana 2 (banana_2 / nano_banana_2)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `banana_2`, `nano_banana_2` |
| **Модель Kie.ai** | `nano-banana-2` |
| **Сервис** | `NanoBanana2Service.create_task()` |
| **Primary** | `KIE_AI_API_KEY` → `https://api.kie.ai` |
| **Fallback** | `NANOBANANA2_FALLBACK_API_KEY` → `api.apiyi.com` (Gemini-compat, модель `gemini-3.1-flash-image-preview`) |
| **Цена** | 5🍌 |

#### 2.2.3. GPT Image 2 (flux_pro)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `flux_pro`, `gpt_image`, `gpt_image_2` |
| **Модели Kie.ai** | `gpt-image-2-text-to-image` (text→img), `gpt-image-2-image-to-image` (img→img) |
| **Сервис** | `GPTImageService` (наследует `KlingService`) |
| **Параметры** | prompt, aspect_ratio (auto/1:1/9:16/16:9/4:3/3:4), nsfw_checker, input_urls (для i2i), callBackUrl |
| **Ограничения** | prompt ≤ 20000 символов, input_urls ≤ 16 |
| **Эндпоинт** | `POST /api/v1/jobs/createTask` |
| **Цена** | 5🍌 |

#### 2.2.4. Seedream 4.5 Edit (seedream_edit)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `seedream_edit`, `seedream` |
| **Модель Kie.ai** | `seedream/4.5-edit` |
| **Сервис** | `SeedreamService` (наследует `KlingService`) |
| **Параметры** | prompt, image_urls (до 5), aspect_ratio, quality (basic/high), nsfw_checker, callBackUrl |
| **Поддержка AR** | 1:1, 4:3, 3:4, 16:9, 9:16, 2:3, 3:2, 21:9 |
| **Цена** | 4🍌 |

#### 2.2.5. Seedream 5 Pro (seedream_5_pro)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `seedream_5_pro` |
| **Модели Kie.ai** | `seedream/5-pro-text-to-image` (text→img), `seedream/5-pro-image-to-image` (img→img) |
| **Сервис** | `SeedreamService` |
| **Параметры** | prompt, aspect_ratio, quality (basic/high), image_urls (опц. для i2i), callBackUrl |
| **Роутинг** | Без `image_urls` → text-to-image, с `image_urls` → image-to-image |
| **Поддержка AR** | 1:1, 4:3, 3:4, 16:9, 9:16, 2:3, 3:2, 21:9 |
| **Цена** | Временно тот же tier, что и `seedream_edit` |

#### 2.2.6. Wan 2.7 Image (wan_27)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `wan_27`, `wan` |
| **Модели Kie.ai** | `wan/2-7-image-pro` (по умолч.), `wan/2-7-image` |
| **Сервис** | `Wan27Service` (наследует `KlingService`) |
| **Параметры** | prompt, aspect_ratio, input_urls (до 9), n (1-4 / 1-12 sequential), resolution, pro, enable_sequential, thinking_mode, watermark, seed, callBackUrl |
| **Особенности** | thinking_mode только для text-to-image; sequential → до 12 изображений |
| **Цена** | 5🍌 |

#### 2.2.7. Gemini Image (banana_api legacy)

| Параметр | Значение |
|---|---|
| **Внутренний ID** | `flash`, `pro` (legacy) |
| **Модели** | `google/gemini-2.5-flash-image`, `google/gemini-3-pro-image-preview` |
| **Сервис** | `GeminiService` (отдельный, не через KIE) |
| **Эндпоинт** | `https://api.nanobanana.com/v1/chat/completions` (Nano Banana) или нативный Gemini API |
| **Параметры** | prompt, model, image_input, aspect_ratio, resolution (1K/2K/4K), enable_search, reference_images (до 14), preserve_faces |
| **Особенности** | Multi-turn chat, edit image, style transfer, composite, search grounding, thinking mode |
| **Статус** | **Устаревшая интеграция** — заменена на Nano Banana Pro/2 через KIE |

---

### 2.3. Текстовые / Чат-модели (Text/Chat)

#### 2.3.1. GPT-5.5 + Responses API

| Параметр | Значение |
|---|---|
| **Эндпоинт** | `POST /codex/v1/responses` |
| **Используется** | PhotoPromptService, VideoPromptService (анализ изображений/видео) |
| **Модель** | `gpt-5-5` (переменная `PHOTO_PROMPT_MODEL`) |
| **Дополнительно** | Поддержка аудио-входа (max 10MB), видео-входа (max 30MB / 60s) |

#### 2.3.2. AI Assistant + Admin AI

| Параметр | Значение |
|---|---|
| **Эндпоинт** | `/gpt-5-2/v1/chat/completions` |
| **Альтернатива** | `/claude/v1/messages` (Claude API) |
| **Сервисы** | `ai_assistant_service.py`, `admin_ai_service.py` |
| **Используется** | Помощник для пользователей, AI-админ |

---

## 3. МАППИНГ: ВНУТРЕННИЙ ID → MODEL KIE.AI

### 3.1. Полный маппинг видео-моделей

| internal_id | kie.ai model | service_class | endpoint |
|---|---|---|---|
| `v3_std` | `kling-3.0/video` | `KlingService` | createTask |
| `v3_pro` | `kling-3.0/video` (mode=pro) | `KlingService` | createTask |
| `v26_pro` | `kling/v2-5-turbo-text-to-video-pro` / `kling/v2-5-turbo-image-to-video-pro` | `KlingService` | createTask |
| `avatar_std` | `kling/ai-avatar-standard` | `KlingService` | createTask |
| `avatar_pro` | `kling/ai-avatar-pro` | `KlingService` | createTask |
| `motion_control_v26` | `kling-2.6/motion-control` | `KlingService` | createTask |
| `motion_control_v30` | `kling-3.0/motion-control` | `KlingService` | createTask |
| `glow` | (Motion Control c glow-style) | `KlingService` | createTask |
| `grok_imagine` | `grok-imagine/image-to-video` | `GrokService` | createTask |
| `grok_imagine_v15` | `grok-imagine-video-1-5-preview` | `GrokService` | createTask |
| `grok_imagine_i2i` | `grok-imagine/image-to-image` | `GrokService` | createTask |
| `seedance_2` | `bytedance/seedance-2` | `SeedanceService` | createTask |
| `veo3` / `veo3_fast` / `veo3_lite` | (Veo API) | `VeoService` | `/api/v1/veo/generate` |
| `gemini_omni` | (Gemini Omni) | `GeminiOmniService` | createTask |
| `gemini_omni_video` | (Gemini Omni Video) | `GeminiOmniService` | createTask |
| `gemini_omni_audio` | (Gemini Omni Audio) | `GeminiOmniService` | createTask |
| `gemini_omni_character` | (Gemini Omni Character) | `GeminiOmniService` | createTask |

### 3.2. Полный маппинг изображений

| internal_id | kie.ai model | service_class | загрузка refs |
|---|---|---|---|
| `banana_pro` / `nano_banana_pro` | `nano-banana-pro` | `NanoBananaProService` | KieFileUploadService |
| `banana_2` / `nano_banana_2` | `nano-banana-2` | `NanoBanana2Service` | KieFileUploadService |
| `flux_pro` / `gpt_image_2` | `gpt-image-2-text-to-image` / `gpt-image-2-image-to-image` | `GPTImageService` | — |
| `seedream_edit` | `seedream/4.5-edit` | `SeedreamService` | KieFileUploadService |
| `seedream_5_pro` | `seedream/5-pro-text-to-image` / `seedream/5-pro-image-to-image` | `SeedreamService` | KieFileUploadService |
| `wan_27` / `wan` | `wan/2-7-image-pro` / `wan/2-7-image` | `Wan27Service` | — |
| `flash` / `pro` (legacy) | `google/gemini-2.5-flash-image` / `google/gemini-3-pro-image-preview` | `GeminiService` | — |

### 3.3. Отображение для пользователя (keyboards.py)

#### VIDEO_MODEL_LABELS

```python
{
    "v3_std": "Kling v3",
    "v3_pro": "Kling 3.0",
    "v26_pro": "Kling 2.5 Turbo Pro",
    "avatar_std": "Kling AI Avatar Standard",
    "avatar_pro": "Kling AI Avatar Pro",
    "motion_control_v26": "Kling 2.6 Motion Control",
    "grok_imagine": "Grok Imagine",
    "grok_imagine_v15": "Grok Imagine 1.5",
    "seedance_2": "Bytedance Seedance 2.0",
    "glow": "Kling Glow",
    "veo3": "Veo 3.1 Quality",
    "veo3_fast": "Veo 3.1 Fast",
    "veo3_lite": "Veo 3.1 Lite",
    "gemini_omni": "Gemini Omni",
    "gemini_omni_video": "Gemini Omni Video",
    "gemini_omni_audio": "Gemini Omni Audio",
    "gemini_omni_character": "Gemini Omni Character",
}
```

#### IMAGE_MODEL_LABELS

```python
{
    "flux_pro": "GPT Image 2",
    "banana_pro": "Nano Banana Pro",
    "banana_2": "Nano Banana 2",
    "seedream_edit": "Seedream 4.5",
    "seedream_5_pro": "Seedream 5 Pro",
    "grok_imagine_i2i": "Grok Imagine",
    "wan_27": "Wan 2.7 Pro",
    "nanobanana": "Nano Banana Pro",
}
```

---

## 4. СТРУКТУРА ЗАПРОСА KIE

### 4.1. Единый формат createTask

```python
payload = {
    "model": "kling-3.0/video",        # Идентификатор модели в KIE
    "input": {
        # Параметры зависят от модели
        "prompt": "...",
        "aspect_ratio": "16:9",
        ...
    },
    "callBackUrl": "https://..."        # Опционально: вебхук для уведомлений
}
```

### 4.2. Формат ответа createTask

```python
{
    "code": 200,
    "data": {
        "taskId": "uuid-задачи"
    },
    "msg": "success"
}
```

### 4.3. Формат статуса задачи

```python
# GET /api/v1/jobs/recordInfo?taskId=...
{
    "data": {
        "status": "succeeded",          # или "pending", "running", "failed"
        "output": "https://result.url", # URL результата
        "taskId": "uuid-задачи"
    }
}
```

---

## 5. МАРШРУТИЗАЦИЯ (ROUTING)

### 5.1. Видео-маршрутизация

В `KlingService.generate_video()`:

1. **Проверка на NON_KLING_MODELS** — если модель в этом списке, возвращается ошибка (предотвращает случайную отправку image-моделей в Kling)
2. **Motion Control** → `generate_motion_control()`
3. **Kling 3.0** (v3, omni) → `generate_kling_3_video()`
4. **Kling 2.5 Turbo** (v26_pro) → `generate_kling_25_turbo_video()`
5. **Avatar** → `generate_kling_ai_avatar()`
6. **Glow** → `generate_motion_control()` (с glow-style)
7. **Остальное** → ошибка unsupported_model

### 5.2. Изображения — маршрутизация

В `handlers/generation.py` через `img_service`:

- `banana_pro` / `nano_banana_pro` → `NanoBananaProService`
- `banana_2` / `nano_banana_2` → `NanoBanana2Service`
- `flux_pro` / `gpt_image_2` → `GPTImageService`
- `seedream_edit` → `SeedreamService`
- `seedream_5_pro` → `SeedreamService`
- `wan_27` → `Wan27Service`
- `grok_imagine_i2i` → `GrokService`
- `flash` / `pro` (legacy) → `GeminiService`

### 5.3. NON_KLING_MODELS (защита от неверной маршрутизации)

```python
NON_KLING_MODELS = {
    "grok_imagine", "grok_imagine_v15", "seedance_2",
    "grok_imagine_i2i", "banana_pro", "banana_2",
    "seedream_edit", "flux_pro", "gpt_image_2",
    "nano_banana_pro", "nano_banana_2",
}
```

---

## 6. СТОИМОСТЬ (pricing_final.py)

### 6.1. Image модели

| internal_id | стоимость (🍌) |
|---|---|
| `nanobanana`, `banana_pro`, `banana_2` | 5 |
| `nano_banana`, `nano_banana_pro`, `nano_banana_2` | 5 |
| `seedream`, `seedream_edit` | 4 |
| `grok_imagine_i2i`, `grok` | 3 |
| `gpt_image_2`, `gpt_image` | 5 |
| `wan_27`, `wan` | 5 |

### 6.2. Видео модели

Цена рассчитывается через `preset_manager.get_video_cost_per_second()`.

---

## 7. FALLBACK-ПРОВАЙДЕРЫ

### 7.1. Nano Banana Pro / Nano Banana 2

Оба сервиса поддерживают двухуровневую архитектуру:

1. **Primary:** `KIE_AI_API_KEY` → `https://api.kie.ai`
2. **Fallback:** `NANO_BANANA_PRO_FALLBACK_API_KEY` / `NANOBANANA2_FALLBACK_API_KEY` → `api.apiyi.com`

При отказе primary, запрос автоматически перенаправляется на Gemini-совместимый fallback:
- **Pro:** модель `gemini-3-pro-image-preview` + проприетарный `imageConfig`
- **Banana 2:** модель `gemini-3.1-flash-image-preview` + проприетарный `imageConfig`

### 7.2. GeminiService (legacy)

Многоуровневый fallback:
1. Nano Banana API (`api.nanobanana.com/v1/chat/completions`)
2. Нативный Gemini API (`google-genai` SDK)

---

## 8. ЗАГРУЗКА ФАЙЛОВ (KieFileUploadService)

**Базовый URL:** `https://kieai.redpandaai.co`

### 8.1. Процесс

1. Получает локальный путь к файлу из `static/uploads/`
2. Проверяет кэш (48h TTL)
3. Если файл имеет стабильный публичный URL → использует его
4. Иначе → POST `multipart/form-data` на `/api/file-stream-upload`
5. Возвращает временный URL для использования в `image_urls`

### 8.2. Используется в

- `NanoBananaProService` (загрузка референсов)
- `NanoBanana2Service` (загрузка референсов)
- `SeedreamService` (загрузка референсов)
- `SeedanceService` (загрузка first/last frame + reference images)
- `GrokService` (загрузка референсов)

### 8.3. Кэширование

- Ключ: `{local_path}:{st_size}:{st_mtime_ns}`
- TTL: 48 часов

---

## 9. ОБРАБОТКА ВЕБХУКОВ (Callbacks)

Все сервисы поддерживают опциональный `callBackUrl` для асинхронного получения результата.

### 9.1. KIE Webhook

- **Путь:** `/webhook/kie_ai` (настраивается через `KIE_AI_WEBHOOK_PATH`)
- **Полный URL:** `config.kie_notification_url`
- **Обработчик:** `KIE_AI_WEBHOOK_PATH`

### 9.2. Другие вебхуки

| Сервис | Путь | Свойство config |
|---|---|---|
| Kling (legacy) | `/webhook/kling` | `kling_notification_url` |
| Replicate | `/webhook/replicate` | `replicate_notification_url` |
| Z Image Turbo | `/webhook/z-image-turbo` | `z_image_turbo_notification_url` |
| Wanx | `/webhook/wanx` | `wanx_notification_url` |

---

## 10. НЕОБХОДИМЫЕ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (полный список)

### 10.1. Обязательные

```bash
# Telegram
BOT_TOKEN=

# Основной ключ AI (kie.ai)
KIE_AI_API_KEY=

# Вебхуки
WEBHOOK_HOST=
```

### 10.2. Опциональные / Fallback

```bash
# Nano Banana
NANOBANANA_API_KEY=                # Для GeminiService + fallback для KIE
NANOBANANA2_FALLBACK_API_KEY=      # Fallback для Nano Banana 2
NANO_BANANA_PRO_FALLBACK_API_KEY=  # Fallback для Nano Banana Pro
NANOBANANA2_FALLBACK_BASE_URL=     # Обычно https://api.apiyi.com
NANO_BANANA_PRO_FALLBACK_BASE_URL= # Обычно https://api.apiyi.com

# Gemini (legacy)
GEMINI_API_KEY=

# Kling (legacy)
KLING_API_KEY=
PIAPI_API_KEY=

# Другие провайдеры
FREEPIK_API_KEY=
NOVITA_API_KEY=
REPLICATE_API_TOKEN=
REPLICATE_WEBHOOK_SECRET=

# Prompt analysis
PHOTO_PROMPT_MODEL=gpt-5-5
PHOTO_PROMPT_MAX_AUDIO_BYTES=10485760
VIDEO_PROMPT_MAX_VIDEO_BYTES=31457280
VIDEO_PROMPT_MAX_DURATION_SECONDS=60
```

### 10.3. Платёжные провайдеры

```bash
PAYMENT_PROVIDER=cryptobot  # или yookassa, lava, tbank, telegram_stars
CRYPTOBOT_API_TOKEN=
LAVA_API_KEY=
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
TBANK_TERMINAL_KEY=
TBANK_SECRET_KEY=
TELEGRAM_STARS_ENABLED=1
```

---

## 11. ДИАГРАММА ВЗАИМОДЕЙСТВИЯ

```
Пользователь (Telegram)
       |
       v
  generation.py (handlers)
       |
       +---> img_service выбора
       |       |--- banana_pro → NanoBananaProService → kie.ai POST createTask (model=nano-banana-pro)
       |       |--- banana_2  → NanoBanana2Service  → kie.ai POST createTask (model=nano-banana-2)
       |       |--- flux_pro  → GPTImageService     → kie.ai POST createTask (model=gpt-image-2-*)
       |       |--- seedream  → SeedreamService     → kie.ai POST createTask (model=seedream/4.5-edit)
       |       |--- wan_27    → Wan27Service        → kie.ai POST createTask (model=wan/2-7-image-*)
       |       |--- legacy    → GeminiService        → api.nanobanana.com / native Gemini
       |
       +---> v_model выбора
               |--- v3_std/pro             → KlingService     → kie.ai POST createTask (model=kling-3.0/video)
               |--- v26_pro                → KlingService     → kie.ai POST createTask (model=kling/v2-5-turbo-*)
               |--- grok_imagine(v15)      → GrokService      → kie.ai POST createTask (model=grok-imagine-*)
               |--- seedance_2             → SeedanceService  → kie.ai POST createTask (model=bytedance/seedance-2)
               |--- veo3*                  → VeoService       → kie.ai POST /api/v1/veo/generate
               |--- gemini_omni*           → GeminiOmniService→ kie.ai POST createTask
               |--- avatar*                → KlingService     → kie.ai POST createTask (model=kling/ai-avatar-*)
               |--- motion_control*        → KlingService     → kie.ai POST createTask (model=kling-*-/motion-control)
               |--- glow                   → KlingService     → kie.ai POST createTask (motion control)
```

---

## 12. ЗАМЕЧАНИЯ

1. **GeminiService** (legacy) — использует `NANOBANANA_API_KEY` для запросов к `api.nanobanana.com/v1/chat/completions` или нативный Google Gemini SDK. **Заменяется** на Nano Banana Pro/2 через KIE.
2. **KieFileUploadService** — использует `KIE_AI_API_KEY || NANOBANANA_API_KEY` для аутентификации при загрузке файлов.
3. **NON_KLING_MODELS** — критический защитный механизм, предотвращающий отправку image-запросов в Kling видео-сервис.
4. **pricing_final.py** — содержит только image-модели. Видео-цены рассчитываются динамически через `preset_manager`.
5. **VeoService** и **GeminiOmniService** — единственные сервисы, которые **НЕ наследуют** `KlingService` и имеют собственные эндпоинты.
6. **Кэш KieFileUploadService** — 48 часов. При перезапуске бота кэш сбрасывается.
