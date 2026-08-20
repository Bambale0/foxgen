# Prompt Guide

Этот документ описывает, как в текущем проекте понимать и сопровождать prompt-related сценарии.

## 1. Где prompt используется

### Генерация изображений

- Telegram flow в `bot/handlers/generation.py`
- Mini App image generation в `bot/miniapp.py`
- provider services в `bot/services/*`

### Генерация видео

- text-to-video
- image/video-assisted video generation
- avatar/motion/Gemini Omni branches

### Prompt extraction / assistance

- `photo-to-prompt`
- `video-to-prompt`
- `AI assistant`

## 2. Источники prompt-related логики

- `bot/handlers/generation.py`
- `bot/handlers/image_analyzer.py`
- `bot/handlers/common.py`
- `bot/services/photo_prompt_service.py`
- `bot/services/video_prompt_service.py`
- `bot/services/ai_assistant_service.py`
- `bot/utils/user_facing_errors.py`
- `bot/utils/validators.py`

## 3. Практические правила

- не документировать prompt format, которого нет в коде
- не обещать universal support одинаковых параметров для всех моделей
- помнить, что часть моделей принимает только текст, часть требует media input
- помнить, что prompt может скрываться в feed/repeat/remix сценариях по правилам приватности

## 4. Что важно для UX

- prompt должен объясняться пользователю человеческим языком
- model-specific advanced params не должны подменять собой основной prompt
- ошибки prompt validation должны быть user-facing, а не провайдерским raw dump

## 5. Что важно для сопровождения

- при изменении model family сверять:
  - UI labels
  - service payload assembly
  - tracemap generation docs
  - pricing/availability assumptions

Для архитектурного контекста смотри [architecture.md](architecture.md) и [../tracemap_generation.md](../tracemap_generation.md).
