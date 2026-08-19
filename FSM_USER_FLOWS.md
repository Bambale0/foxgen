# FSM, экраны, callback-контракт и пользовательские флоу

Этот документ описывает обязательную FSM-архитектуру, экраны, callback-контракты и пользовательские сценарии для Telegram Bot + Mini App.

Нельзя делать просто набор команд. Продукт должен работать как пошаговый Telegram Bot + Mini App с понятными экранами, состояниями, callback-кнопками и сохранением промежуточных параметров в FSM.

---

## 1. Обязательная FSM-структура

Файл: `bot/states.py`

Группы состояний:
- `GenerationStates` — всё создание фото/видео
- `PaymentStates` — пополнение баланса
- `AdminStates` — админка
- `BatchGenerationStates` — батч-генерация
- `ImageAnalyzerStates` — промпт по фото

Правило: новые экраны **не хранят данные в глобальных переменных**. Все временные параметры — в `FSMContext`.

---

## 2. Базовая структура FSM data

### Фото-флоу
```python
def default_image_flow_data():
    return {
        "generation_type": "image",
        "img_service": "banana_pro",
        "img_ratio": "1:1",
        "img_count": 1,
        "img_quality": "2K",
        "img_nsfw_checker": False,
        "nsfw_enabled": False,
        "reference_images": [],
        "img_flow_step": "select_model",
        "preset_id": "new",
        "user_prompt": "",
    }
```

### Видео-флоу
```python
def default_video_flow_data():
    return {
        "generation_type": "video",
        "video_flow_step": "select_model",
        "v_type": "text", "v_model": "v3_pro",
        "v_duration": 5, "v_ratio": "16:9",
        "v_image_url": None,
        "reference_images": [],
        "v_reference_videos": [],
        "avatar_audio_url": None,
        "user_prompt": "",
        "grok_mode": "normal", "grok_resolution": "480p",
        "veo_generation_type": "TEXT_2_VIDEO",
        "veo_translation": True, "veo_resolution": "720p",
        "veo_seed": None, "veo_watermark": "",
        "kling_negative_prompt": "", "kling_cfg_scale": 0.5,
        "omni_resolution": "720p", "omni_seed": None,
        "omni_audio_ids": [], "omni_character_ids": [],
        "omni_base_voice": "achernar",
        "omni_voice_name": "", "omni_voice_description": "",
        "omni_example_dialogue": "", "omni_character_name": "",
        "omni_character_audio_ids": [],
    }
```

---

## 3. Главный экран

Обязательные кнопки:
- 🚀 Открыть Mini App
- 🖼 Создать фото
- 🎬 Создать видео
- 🎯 Motion Control
- 📸 Промпт по фото
- 🎞 Промпт по видео
- 🖼 Лента
- 📚 Библиотека промптов
- 🤖 AI-помощник
- 🍌 Баланс
- 💬 Поддержка
- 🤝 Партнёрам
- ⋯ Ещё

---

## 4. Фото-флоу

```
Главное меню → Создать фото
→ выбор модели
→ загрузка/пропуск референсов
→ экран настроек (ratio/quality/count)
→ ввод prompt
→ проверка баланса → списание
→ generation_task → provider → webhook → результат
→ кнопки: повторить / опубликовать / в библиотеку / анимировать
```

### Callback-контракт:
```
create_image_text_new    image_change_model
model_banana_pro         model_banana_2
model_nano_banana_2_lite model_seedream_edit
model_grok_i2i           model_flux_pro
model_wan_27
img_ref_continue_new     ref_skip_new
ref_saved_library
img_ratio_1_1            img_ratio_16_9
img_ratio_9_16           img_ratio_4_3
img_ratio_3_4
img_quality_2k           img_quality_4k
img_quality_basic        img_quality_high
img_count_1              img_count_2
img_count_4              img_count_6
```

---

## 5. Видео-флоу

Типы: `text | imgtxt | video | avatar | motion | audio | character`

### Callback-контракт:
```
create_video_new          video_change_model
video_change_media        video_media_continue
video_media_skip
v_model_v3_pro            v_model_v3_std
v_model_v26_pro           v_model_grok_imagine
v_model_grok_imagine_v15  v_model_seedance_2
v_model_gemini_omni       v_model_veo3
v_model_veo3_fast         v_model_veo3_lite
v_model_glow
v_type_text               v_type_imgtxt
v_type_video              v_type_avatar
v_type_motion
ratio_16_9                ratio_9_16
ratio_1_1
video_dur_4/5/6/8/10/15
kling_negative_prompt_edit  kling_cfg_scale_edit
veo_translation_toggle      veo_resolution_720p/1080p/4k
veo_seed_edit               veo_watermark_edit
omni_mode_video/audio/character  omni_resolution_720p/1080p/4k
omni_seed_edit              omni_audio_ids_edit
omni_character_ids_edit
```

---

## 6. Референсы

Загрузка photo/document (JPEG, PNG, WEBP), видео. Публичный URL. Лимит по модели. Библиотека сохранённых.

Callback'и:
```
ref_skip_new        img_ref_continue_new
vid_ref_continue_new  ref_saved_library
savedref_nav_{index}  savedref_use_{reference_id}
savedref_delete_{reference_id}_{index}  savedref_close
```

---

## 7. Оплаты и баланс

```
Главное меню → Баланс
→ Пополнить → выбор пакета → промокод → способ оплаты
→ pending transaction → payment URL
→ webhook провайдера → проверка подписи → начисление → уведомление
```

Callback'и:
```
menu_balance     menu_topup
choose_pay_{package_id}  topup_enter_promo
topup_remove_promo
buy_stars_{package_id}   buy_crypto_{package_id}
buy_yookassa_{package_id}  buy_lava_{package_id}
check_payment_{transaction_id}
```

---

## 8. Админка

Разделы: Статистика, Пользователи, Партнёры, Финансы/рефы, Цены, Промокоды, Промпты, ИИ-админ, Рассылка, Подписка на канал

Callback'и: `admin_stats, admin_users, admin_partners, admin_finance, admin_prices, admin_promocodes, admin_prompts, admin_ai, admin_broadcast, admin_required_subscription_toggle, admin_back`

---

## 9. Экранный контракт

Каждый экран: `render() + keyboard() + callback handler + state transition`

### Паттерн:
```python
async def show_some_screen(callback, state):
    data = await state.get_data()
    text = build_some_screen_text(data)
    keyboard = get_some_screen_keyboard(data)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(SomeStates.some_state)

@router.callback_query(F.data == "some_continue")
async def some_continue(callback, state):
    await state.update_data(some_step_completed=True)
    await show_next_screen(callback, state)
    await callback.answer()
```

---

## 10. Router order

Специфичные роутеры → общие:
```python
dp.include_router(generation_router)
dp.include_router(image_analyzer_router)
dp.include_router(admin_router)
dp.include_router(payments_router)
dp.include_router(batch_generation_router)
dp.include_router(common_router)  # последним!
```

---

## 11. Feed, repeat, remix

После результата: Повторить, Новый prompt, Анимировать, В ленту, В библиотеку, Показать prompt/референсы

Repeat восстанавливает request_data из generation_tasks в FSM.

---

## 12. Критерий готовности UX

Пользователь проходит без ручных команд:
1. /start → Создать фото → модель → референсы → настройки → prompt → результат
2. /start → Создать видео → модель → тип → файлы → настройки → prompt → результат
3. /start → Баланс → Пополнить → пакет → оплата → бананы
4. /start → Лента → открыть → повторить/ремикснуть
5. /admin → статистика → цены → промокоды → рассылка
