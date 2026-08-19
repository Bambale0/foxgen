# Gemini-Compatible Image Notes

Этот файл больше не описывает отдельный внешний пример. В контексте `Banano Kling` он фиксирует, как Gemini-compatible image flows представлены внутри проекта.

## Где это живёт в коде

- `bot/services/gemini_service.py`
- `bot/services/nano_banana_pro_service.py`
- `bot/services/nano_banana_2_service.py`
- fallback env keys из `bot/config.py`

## Что важно понимать

- пользовательский слой не оперирует сырыми Gemini model names
- в UI и pricing используются project model ids:
  - `banana_pro`
  - `banana_2`
  - `nano-banana-2-lite`
- canonical alias mapping определён в `bot/services/preset_manager.py`

## Почему этот файл короткий

Источником истины по image generation сейчас являются:

1. сервисы в `bot/services/`
2. keyboard/model labels
3. `data/price.json`
4. tests

Подробные архитектурные шаги смотри в [architecture.md](architecture.md) и [../tracemap_generation.md](../tracemap_generation.md).
