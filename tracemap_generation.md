# Trace Map: Generation

## 1. Основные entrypoints

### Telegram

- `create_image_text_new`
- `create_image_refs_new`
- `create_video_new`
- `motion_control`
- `photo_to_prompt`
- `video_to_prompt`
- batch-generation callbacks

### Mini App

- `POST /mini-app/api/generate-image`
- `POST /mini-app/api/generate-video`
- `POST /mini-app/api/generate-motion`
- `POST /mini-app/api/photo-to-prompt`

## 2. Image generation trace

`user input`
-> `bot/handlers/generation.py`
-> selected image model in FSM
-> reference uploads optional
-> prompt + aspect ratio + other options captured
-> balance precheck
-> `generation_tasks` row created
-> one of services:
  - `nano_banana_pro_service.py`
  - `nano_banana_2_service.py`
  - `gpt_image_service.py`
  - `seedream_service.py`
  - `grok_service.py`
  - `wan27_service.py`
-> provider returns direct result or async task id
-> if async: webhook completion updates DB
-> result surfaced to bot/Mini App

## 3. Video generation trace

`user input`
-> model selection in `bot/keyboards.py`
-> media step:
  - text
  - image + text
  - video + text
  - avatar + audio
  - Gemini Omni audio/character branches
  - motion branch
-> settings step:
  - ratio
  - duration
  - quality/resolution
  - model-specific advanced params
-> balance precheck
-> `add_generation_task`
-> provider service dispatch
-> async completion via webhook
-> `complete_video_task` / failed task path
-> post-result actions: publish/remix/repeat/share

## 4. Provider routing map

### Image-side

- `banana_pro` -> Nano Banana Pro service
- `banana_2` -> Nano Banana 2 service
- `nano-banana-2-lite` -> Lite Banana path
- `flux_pro` -> GPT Image 2 / flux-compatible path
- `seedream_edit`, `seedream_5_pro` -> Seedream/Kie path
- `grok_imagine_i2i` -> Grok image service
- `wan_27` -> Wan 2.7 image service

### Video-side

- `v3_pro`, `v3_std`, `v26_pro`, `glow`, avatar/motion variants -> Kling family
- `grok_imagine`, `grok_imagine_v15` -> Grok video path
- `seedance_2` -> Seedance path
- `veo3`, `veo3_fast`, `veo3_lite` -> Veo/Kie path
- `gemini_omni_*` -> Gemini Omni path

## 5. Async completion map

### Webhook handlers

- `/webhook/kling` -> `handle_kling_webhook`
- Kie AI path -> `handle_kie_ai_webhook`
- Kie Market path -> `handle_kie_market_webhook`
- Seedream/Novita/Wan legacy-specific handlers stay in `bot/main.py`

### Completion side effects

- resolve stored task
- reject orphan payload if task is unknown
- parse provider status/result URL
- store result URLs / metadata
- move task to `completed` or `failed`
- send Telegram result when relevant
- expose updated task state to Mini App polling

## 6. Shared validation points

- prompt policy / explicit content checks
- media type/size validation
- reference count limits
- model-specific ratio/duration constraints
- user balance checks
- access guard / subscription gate

## 7. DB tables touched

- `generation_tasks`
- `generation_history`
- `saved_references`
- `batch_jobs`
- feed/prompt tables if user publishes result later

## 8. Important risks

- alias mismatch between UI model ids and pricing canonical ids
- provider webhook status shape drift
- reference asset path/public URL mismatch
- duplicate provider callbacks
- user retries after partial task creation
