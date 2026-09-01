import json
import logging
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram import types
from aiogram.types import CopyTextButton, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.subscription_service import (
    REQUIRED_CHANNEL_URL,
    SUBSCRIPTION_CHECK_CALLBACK,
)
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)


def _mini_app_url_with_start_param(start_param: str | None = None, referral_code: str | None = None) -> str:
    base_url = str(config.mini_app_url or "").strip()
    if not base_url:
        return base_url
    code = str(referral_code or "").strip().upper()
    param = str(start_param or "").strip()
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if code:
        query["ref"] = code
    if param:
        query["startapp"] = param
    elif code:
        query.setdefault("startapp", f"ref_{code}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _mini_app_url_with_referral(referral_code: str | None = None) -> str:
    return _mini_app_url_with_start_param(referral_code=referral_code)


def _video_prompt_price_label() -> str:
    value = float(preset_manager.get_video_prompt_cost())
    return f"{value:g}"


def load_prices():
    """Backward-compatible helper for tests and old integrations."""
    price_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "price.json",
    )
    with open(price_path, "r", encoding="utf-8") as f:
        return json.load(f)


try:
    PACKAGES = load_prices().get("packages", [])
except Exception:
    PACKAGES = []


# =============================================================================
# ГЛАВНОЕ МЕНЮ - согласно ux.md
# =============================================================================


def get_main_menu_keyboard(user_credits: int = 0, telegram_id: int | None = None, mini_app_referral_code: str | None = None):
    """Аккуратное главное меню: сценарии сверху, детали моделей внутри разделов."""
    builder = InlineKeyboardBuilder()

    if config.mini_app_url:
        builder.row(
            InlineKeyboardButton(
                text="🚀 Открыть Mini App",
                web_app=WebAppInfo(url=_mini_app_url_with_referral(mini_app_referral_code) or config.mini_app_url),
            )
        )
    builder.row(
        InlineKeyboardButton(text="🖼 Создать фото", callback_data="create_image_text_new"),
        InlineKeyboardButton(text="🎬 Создать видео", callback_data="create_video_new"),
    )
    builder.row(
        InlineKeyboardButton(text="🎯 Motion Control", callback_data="motion_control"),
        InlineKeyboardButton(text="✍️ Промпт по описанию", callback_data="photo_to_prompt"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🎞 Промпт по видео • {_video_prompt_price_label()}🍌", callback_data="video_to_prompt"),
        InlineKeyboardButton(text="🤖 AI-помощник", callback_data="menu_ai_assistant"),
    )
    builder.row(
        InlineKeyboardButton(text="📚 Библиотека промптов", callback_data="menu_prompts"),
        InlineKeyboardButton(text="🖼 Лента", callback_data="menu_feed"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🍌 Баланс: {user_credits}", callback_data="menu_balance"),
        InlineKeyboardButton(text="💬 Поддержка", callback_data="menu_support"),
    )
    builder.row(
        InlineKeyboardButton(text="🤝 Партнёрам", callback_data="menu_partner"),
        InlineKeyboardButton(text="⋯ Ещё", callback_data="ux_more"),
    )

    return builder.as_markup()


def get_create_hub_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 Фото", callback_data="create_image_text_new")
    builder.button(text="🎬 Видео", callback_data="create_video_new")
    builder.button(text="📱 Reels/TikTok", callback_data="quick_reels_video")
    builder.button(text="🛍 Товар/реклама", callback_data="quick_product_image")
    builder.button(text="⚡ Быстрый старт", callback_data="create_image_text_new")
    builder.button(text="⚙️ Свои настройки", callback_data="create_video_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_edit_hub_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎨 Сменить стиль", callback_data="edit_style_image")
    builder.button(text="🖼 Сменить фон", callback_data="edit_background_image")
    builder.button(text="🧩 По референсам", callback_data="create_image_refs_new")
    builder.button(text="🧠 Grok i2i", callback_data="edit_grok_i2i")
    builder.button(text="⚙️ Свои настройки", callback_data="create_image_refs_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def get_animate_hub_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🖼 Фото → Видео", callback_data="quick_image_to_video")
    builder.button(text="🎯 Motion Control", callback_data="motion_control")
    builder.button(text="🎞 Видео-референс", callback_data="quick_video_reference")
    builder.button(text="🎬 Видео с нуля", callback_data="create_video_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def get_motion_control_model_keyboard(current_model: str = "motion_control_v26"):
    builder = InlineKeyboardBuilder()
    options = [
        (
            "motion_control_v26",
            "🎯 Kling 2.6 Motion Control",
            "Стабильный перенос движения",
            preset_manager.get_video_cost("motion_control_v26", 5),
        ),
    ]
    for model_key, title, description, cost in options:
        check = "✅ " if current_model == model_key else ""
        per_second = preset_manager.get_video_cost_per_second(model_key, 5)
        builder.row(
            InlineKeyboardButton(
                text=f"{check}{title} • {per_second}🍌/с",
                callback_data=f"v_model_{model_key}",
            )
        )
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


def get_more_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❓ Как пользоваться", callback_data="menu_help")
    builder.button(text="💬 Поддержка", callback_data="menu_support")
    builder.button(text="💰 Пополнить", callback_data="menu_topup")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def get_admin_keyboard(subscription_required: bool | None = None):
    builder = InlineKeyboardBuilder()
    if subscription_required is None:
        subscription_label = "🔐 Подписка на канал"
    else:
        subscription_label = "🔐 Подписка: ВКЛ" if subscription_required else "🔓 Подписка: ВЫКЛ"
    builder.button(text="🔄 Перезагрузить пресеты", callback_data="admin_reload")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="🤝 Партнёры", callback_data="admin_partners")
    builder.button(text="📒 Финансы/рефы", callback_data="admin_finance")
    builder.button(text="💸 Цены", callback_data="admin_prices")
    builder.button(text="🎟 Промокоды", callback_data="admin_promocodes")
    builder.button(text="📚 Промпты", callback_data="admin_prompts")
    builder.button(text="🤖 ИИ-админ", callback_data="admin_ai")
    builder.button(text="📘 Инструкция ИИ", callback_data="admin_ai_help")
    builder.button(text=subscription_label, callback_data="admin_required_subscription_toggle")
    builder.button(text=f"🎞 Видео → prompt • {_video_prompt_price_label()}🍌", callback_data="video_to_prompt")
    builder.button(text="⚙️ Рассылка", callback_data="admin_broadcast")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 2, 2, 2, 2)
    return builder.as_markup()


def get_required_subscription_keyboard(channel_url: str = REQUIRED_CHANNEL_URL) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Подписаться на канал", url=channel_url)
    builder.button(text="✅ Проверить подписку", callback_data=SUBSCRIPTION_CHECK_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()


SUPPORTED_RATIOS = {
    "v3_std": ["16:9", "9:16", "1:1"],
    "v3_pro": ["16:9", "9:16", "1:1"],
    "v26_pro": ["16:9", "9:16", "1:1"],
    "v3_omni_std": ["16:9", "9:16", "1:1"],
    "v3_omni_pro": ["16:9", "9:16", "1:1"],
    "grok_imagine": ["16:9", "9:16", "1:1", "3:2", "2:3"],
    "grok_imagine_v15": ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
    "seedance_2": ["16:9", "9:16", "1:1"],
    "seedance_2_5": ["16:9", "9:16", "1:1"],
    "motion_control_v26": ["1:1"],
    "glow": ["16:9", "9:16", "1:1"],
    "veo3": ["16:9", "9:16", "Auto"],
    "veo3_fast": ["16:9", "9:16", "Auto"],
    "veo3_lite": ["16:9", "9:16", "Auto"],
    "gemini_omni": ["16:9", "9:16"],
    "gemini_omni_video": ["16:9", "9:16"],
}

VIDEO_MODEL_LABELS = {
    "v3_std": "Kling v3",
    "v3_pro": "Kling 3.0",
    "v26_pro": "Kling 2.5 Turbo Pro",
    "avatar_std": "Kling AI Avatar Standard",
    "avatar_pro": "Kling AI Avatar Pro",
    "motion_control_v26": "Kling 2.6 Motion Control",
    "grok_imagine": "Grok Imagine",
    "grok_imagine_v15": "Grok Imagine 1.5",
    "seedance_2": "Bytedance Seedance 2.0",
    "seedance_2_5": "Bytedance Seedance 2.5",
    "glow": "Kling Glow",
    "veo3": "Veo 3.1 Quality",
    "veo3_fast": "Veo 3.1 Fast",
    "veo3_lite": "Veo 3.1 Lite",
    "gemini_omni": "Gemini Omni",
    "gemini_omni_video": "Gemini Omni Video",
    "gemini_omni_audio": "Gemini Omni Audio",
    "gemini_omni_character": "Gemini Omni Character",
}

IMAGE_MODEL_LABELS = {
    "flux_pro": "GPT Image 2",
    "banana_pro": "Nano Banana Pro",
    "banana_2": "Nano Banana 2",
    "nano-banana-2-lite": "Nano Banana 2 Lite 🔥 НОВИНКА",
    "seedream_edit": "Seedream 4.5",
    "seedream_5_pro": "Seedream 5 Pro 🔥 НОВИНКА",
    "grok_imagine_i2i": "Grok Imagine",
    "wan_27": "Wan 2.7 Pro",
    "nanobanana": "Nano Banana Pro",
}


def get_video_model_label(model: str) -> str:
    return VIDEO_MODEL_LABELS.get(model, model)


def get_video_type_label(v_type: str) -> str:
    mapping = {
        "text": "Текст -> Видео",
        "imgtxt": "Фото + Текст -> Видео",
        "video": "Видео + Текст -> Видео",
        "avatar": "Аватар + Аудио -> Видео",
        "audio": "Gemini Omni Audio ID",
        "character": "Gemini Omni Character ID",
        "motion": "Motion Control",
    }
    return mapping.get(v_type, v_type)


def get_image_model_label(model: str) -> str:
    return IMAGE_MODEL_LABELS.get(model, model)


def _video_pricing_quality(
    model: str,
    veo_resolution: str = "720p",
    omni_resolution: str = "720p",
    motion_quality: str = "720p",
    grok_resolution: str = "480p",
) -> str | None:
    key = preset_manager.normalize_video_model_key(model)
    if key == "grok_imagine_v15":
        return grok_resolution
    if key.startswith("veo3"):
        return veo_resolution
    if key == "gemini_omni_video":
        return omni_resolution
    if key.startswith("motion_control"):
        return motion_quality
    return None


def get_video_model_selection_keyboard(
    current_model: str = "v3_pro",
    user_id: int | None = None,
):
    """Первый шаг: отдельный выбор модели видео.

    Seedance 2.5 remains an admin-only preview. The user id is deliberately
    supplied by the handler so ordinary users never receive its callback button.
    """
    builder = InlineKeyboardBuilder()

    model_rows = [
        ("v3_pro", "💎 Kling 3.0", preset_manager.get_video_cost("v3_pro", 5)),
        ("v3_std", "⚡ Kling v3", preset_manager.get_video_cost("v3_std", 5)),
        ("v26_pro", "🌀 Kling 2.5 Turbo", preset_manager.get_video_cost("v26_pro", 5)),
        ("grok_imagine", "🧠 Grok Imagine", preset_manager.get_video_cost("grok_imagine", 6)),
        ("grok_imagine_v15", "🧠 Grok Imagine 1.5 NEW🔥🔥🔥", preset_manager.get_video_cost("grok_imagine_v15", 8)),
        ("seedance_2", "🎞 Seedance 2.0", preset_manager.get_video_cost("seedance_2", 5)),
        ("gemini_omni", "🔷 Gemini Omni", preset_manager.get_video_cost("gemini_omni_video", 6)),
        ("veo3", "🎥 Veo 3.1 Quality", preset_manager.get_video_cost("veo3", 6)),
        ("veo3_fast", "🚀 Veo 3.1 Fast", preset_manager.get_video_cost("veo3_fast", 6)),
        ("veo3_lite", "🌿 Veo 3.1 Lite", preset_manager.get_video_cost("veo3_lite", 6)),
        ("glow", "✨ Kling Glow", preset_manager.get_video_cost("glow", 5)),
    ]
    if user_id is not None and config.is_admin(int(user_id)):
        seedance_25_row = (
            "seedance_2_5",
            "🧪 Seedance 2.5 (admin)",
            preset_manager.get_video_cost("seedance_2_5", 5),
        )
        insert_at = next(
            (index + 1 for index, row in enumerate(model_rows) if row[0] == "seedance_2"),
            len(model_rows),
        )
        model_rows.insert(insert_at, seedance_25_row)

    for model_key, label, cost in model_rows:
        check = "✅ " if current_model == model_key else ""
        if model_key == "gemini_omni" and current_model.startswith("gemini_omni"):
            check = "✅ "
        if model_key == "grok_imagine_v15":
            default_duration = 8
        elif model_key == "grok_imagine":
            default_duration = 6
        elif model_key.startswith("veo3") or model_key.startswith("gemini_omni"):
            default_duration = 6
        else:
            default_duration = 5
        pricing_quality = "720p" if model_key.startswith("veo3") or model_key == "gemini_omni" else None
        per_second = preset_manager.get_video_cost_per_second(model_key, default_duration, pricing_quality)
        if model_key == "gemini_omni":
            price_label = f"от {preset_manager.get_video_cost('gemini_omni_audio', 6)}🍌"
        elif model_key in {"gemini_omni_audio", "gemini_omni_character"}:
            price_label = f"{cost}🍌"
        else:
            price_label = f"{per_second}🍌/с"
        builder.row(
            InlineKeyboardButton(
                text=f"{check}{label} • {price_label}",
                callback_data=f"v_model_{model_key}",
            )
        )

    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


def get_video_media_step_keyboard(
    current_v_type: str = "text",
    current_model: str = "v3_pro",
    has_start_image: bool = False,
    reference_image_count: int = 0,
    reference_video_count: int = 0,
    has_avatar_audio: bool = False,
    max_reference_video_count: int = 5,
):
    builder = InlineKeyboardBuilder()
    if current_v_type == "motion":
        builder.button(text="▶️ К промпту", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(2, 1, 2)
        return builder.as_markup()
    if current_v_type == "avatar":
        image_status = "загружено" if has_start_image else "не загружено"
        audio_status = "загружено" if has_avatar_audio else "не загружено"
        builder.button(text=f"🖼 Аватар: {image_status}", callback_data="avatar_upload_image")
        builder.button(text=f"🎵 Аудио: {audio_status}", callback_data="avatar_upload_audio")
        builder.button(text="▶️ К промпту", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(2, 1, 2)
        return builder.as_markup()
    if current_v_type == "character":
        image_status = "загружено" if has_start_image else "не загружено"
        builder.button(text=f"🖼 Персонаж: {image_status}", callback_data="ignore")
        builder.button(text="▶️ К промпту", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(1, 1, 2)
        return builder.as_markup()
    if current_v_type == "audio":
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(1, 2)
        return builder.as_markup()
    if current_model in {"grok_imagine", "grok_imagine_v15"}:
        start_status = "загружено" if has_start_image else "не загружено"
        builder.button(text=f"📷 Стартовое фото: {start_status}", callback_data="ignore")
        if current_model == "grok_imagine" and reference_image_count:
            builder.button(text=f"🧩 Доп. референсы: {reference_image_count}", callback_data="ignore")
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(1, 1, 1, 2)
        return builder.as_markup()
    if current_model == "gemini_omni_video":
        image_count = (1 if has_start_image else 0) + reference_image_count
        text_check = "✅ " if current_v_type == "text" else ""
        imgtxt_check = "✅ " if current_v_type == "imgtxt" else ""
        video_check = "✅ " if current_v_type == "video" else ""
        builder.button(text=f"{text_check}📝 Текст", callback_data="v_type_text")
        builder.button(text=f"{imgtxt_check}🖼 Фото", callback_data="v_type_imgtxt")
        builder.button(text=f"{video_check}🎬 Видео", callback_data="v_type_video")
        builder.button(text=f"🖼 Фото: {image_count}", callback_data="ignore")
        builder.button(text=f"📹 Видео: {reference_video_count}/{max_reference_video_count}", callback_data="ignore")
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(3, 2, 1, 2)
        return builder.as_markup()

    text_check = "✅ " if current_v_type == "text" else ""
    imgtxt_check = "✅ " if current_v_type == "imgtxt" else ""
    video_check = "✅ " if current_v_type == "video" else ""
    builder.button(text=f"{text_check}📝 Текст → Видео", callback_data="v_type_text")
    builder.button(text=f"{imgtxt_check}🖼 Фото + Текст → Видео", callback_data="v_type_imgtxt")
    builder.button(text=f"{video_check}🎬 Видео + Текст → Видео", callback_data="v_type_video")
    if current_v_type == "imgtxt":
        start_status = "загружено" if has_start_image else "не загружено"
        builder.button(text=f"📷 Стартовое фото: {start_status}", callback_data="ignore")
        if reference_image_count > 0:
            builder.button(text=f"🧩 Доп. референсы: {reference_image_count}", callback_data="ignore")
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
    elif current_v_type == "video":
        builder.button(text=f"📹 Видео-референсы: {reference_video_count}/{max_reference_video_count}", callback_data="ignore")
        builder.button(text="⏭ Без видео-рефов", callback_data="video_media_skip")
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
    else:
        builder.button(text="▶️ К настройкам", callback_data="video_media_continue")
    builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    if current_v_type == "imgtxt" and reference_image_count > 0:
        builder.adjust(1, 2, 1, 2)
    elif current_v_type == "video":
        builder.adjust(3, 1, 2, 2)
    else:
        builder.adjust(3, 1, 2)
    return builder.as_markup()


def get_create_video_keyboard(
    current_v_type: str = "text",
    current_model: str = "v3_std",
    current_ratio: str = "16:9",
    current_duration: int = 5,
    current_mode: str = "720p",
    current_orientation: str = "video",
    current_video_model: str = None,
    current_grok_mode: str = "normal",
    current_grok_resolution: str = "480p",
    current_veo_generation_type: str = "TEXT_2_VIDEO",
    current_veo_translation: bool = True,
    current_veo_resolution: str = "720p",
    current_veo_seed: int = None,
    current_veo_watermark: str = "",
    current_kling_negative_prompt: str = "",
    current_kling_cfg_scale: float = 0.5,
    current_omni_resolution: str = "720p",
    current_omni_seed: int = None,
    current_omni_audio_ids: list | None = None,
    current_omni_character_ids: list | None = None,
    current_omni_base_voice: str = "achernar",
    current_omni_voice_name: str = "",
    current_omni_character_name: str = "",
    current_omni_character_audio_ids: list | None = None,
):
    if current_video_model is not None:
        current_model = current_video_model
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
    builder.button(text="🎞 Тип и медиа", callback_data="video_change_media")
    ratio_buttons = []
    available_durations = []
    no_ratio_duration_models = {"avatar_std", "avatar_pro", "gemini_omni_audio", "gemini_omni_character"}
    if current_model not in no_ratio_duration_models:
        supported_ratios = SUPPORTED_RATIOS.get(current_model, ["16:9", "9:16", "1:1"])
        for ratio in supported_ratios:
            if current_model == "grok_imagine_v15":
                check = "● " if current_ratio == ratio else "○ "
                ratio_label_map = {"auto": "Auto", "16:9": "16×9", "9:16": "9×16", "1:1": "1×1", "4:3": "4×3", "3:4": "3×4", "3:2": "3×2", "2:3": "2×3"}
                label = ratio_label_map.get(ratio, ratio.replace(":", "×"))
            else:
                check = "✅ " if current_ratio == ratio else ""
                label = ratio.replace(":", "∶")
            ratio_buttons.append(InlineKeyboardButton(text=f"{check}{label}", callback_data=f"ratio_{ratio.replace(':', '_')}"))
        builder.row(*ratio_buttons)
        model_data_for_durations = preset_manager._price_config.get("costs_reference", {}).get("video_models", {}).get(current_model, {})
        duration_costs = model_data_for_durations.get("duration_costs", {})
        if current_model == "grok_imagine_v15":
            if duration_costs:
                available_durations = sorted([int(k) for k in duration_costs.keys()])
            else:
                min_duration = int(model_data_for_durations.get("duration_min", 1) or 1)
                max_duration = int(model_data_for_durations.get("duration_max", 15) or 15)
                available_durations = list(range(min_duration, max_duration + 1))
            if current_duration not in available_durations:
                available_durations = sorted({*available_durations, int(current_duration)})
        elif current_model.startswith("veo3"):
            available_durations = [4, 6, 8]
        elif current_model in {"gemini_omni", "gemini_omni_video"}:
            available_durations = [4, 6, 8, 10]
        elif duration_costs:
            available_durations = sorted([int(k) for k in duration_costs.keys()])
        else:
            available_durations = [5, 10, 15]
        show_durations = True
        for dur in available_durations:
            check = ("● " if current_duration == dur else "○ ") if current_model == "grok_imagine_v15" else ("✅ " if current_duration == dur else "")
            label = f"{dur}с" if current_model == "grok_imagine_v15" else f"{dur} сек"
            builder.button(text=f"{check}{label}", callback_data=f"video_dur_{dur}")
    else:
        show_durations = False

    if current_model == "grok_imagine":
        builder.button(text=f"{'✅ ' if current_grok_mode == 'normal' else ''}Normal", callback_data="grok_mode_normal")
        builder.button(text=f"{'✅ ' if current_grok_mode == 'fun' else ''}Fun 🎉", callback_data="grok_mode_fun")
        builder.button(text=f"{'✅ ' if current_grok_mode == 'spicy' else ''}Spicy 🔥", callback_data="grok_mode_spicy")
    if current_model == "grok_imagine_v15":
        for resolution in ("480p", "720p"):
            check = "● " if current_grok_resolution == resolution else "○ "
            label = "SD 480p" if resolution == "480p" else "HD 720p"
            builder.button(text=f"{check}{label}", callback_data=f"grok_resolution_{resolution}")
    if current_model.startswith("veo3"):
        translate_check = "✅ " if current_veo_translation else ""
        builder.button(text=f"{translate_check}🌐 Перевод промпта", callback_data="veo_translation_toggle")
        if current_v_type == "imgtxt":
            frames_check = "✅ " if current_veo_generation_type == "FIRST_AND_LAST_FRAMES_2_VIDEO" else ""
            builder.button(text=f"{frames_check}🎞 Кадры", callback_data="veo_gen_FIRST_AND_LAST_FRAMES_2_VIDEO")
            if current_model == "veo3_fast":
                refs_check = "✅ " if current_veo_generation_type == "REFERENCE_2_VIDEO" else ""
                builder.button(text=f"{refs_check}🧩 Референсы", callback_data="veo_gen_REFERENCE_2_VIDEO")
        for resolution in ("720p", "1080p", "4k"):
            check = "✅ " if current_veo_resolution == resolution else ""
            label = resolution.upper() if resolution == "4k" else resolution
            resolution_cost = preset_manager.get_video_cost_with_quality(current_model, current_duration, resolution)
            builder.button(text=f"{check}🖥 {label} • {resolution_cost}🍌", callback_data=f"veo_resolution_{resolution}")
        seed_label = str(current_veo_seed) if current_veo_seed is not None else "auto"
        watermark_label = "off" if not current_veo_watermark else "on"
        builder.button(text=f"🎲 Seed: {seed_label}", callback_data="veo_seed_edit")
        builder.button(text=f"🏷 Метка: {watermark_label}", callback_data="veo_watermark_edit")
    if current_model == "v26_pro":
        negative_label = current_kling_negative_prompt[:24] + "..." if current_kling_negative_prompt and len(current_kling_negative_prompt) > 24 else (current_kling_negative_prompt or "off")
        builder.button(text=f"🚫 Negative: {negative_label}", callback_data="kling_negative_prompt_edit")
        builder.button(text=f"🎚 CFG: {current_kling_cfg_scale:.1f}", callback_data="kling_cfg_scale_edit")
    if current_model == "gemini_omni_video":
        for resolution in ("720p", "1080p", "4k"):
            check = "✅ " if current_omni_resolution == resolution else ""
            label = resolution.upper() if resolution == "4k" else resolution
            resolution_cost = preset_manager.get_video_cost_with_quality(current_model, current_duration, resolution)
            builder.button(text=f"{check}🖥 {label} • {resolution_cost}🍌", callback_data=f"omni_resolution_{resolution}")
        seed_label = str(current_omni_seed) if current_omni_seed is not None else "auto"
        audio_count = len(current_omni_audio_ids or [])
        character_count = len(current_omni_character_ids or [])
        builder.button(text=f"🎲 Seed: {seed_label}", callback_data="omni_seed_edit")
        builder.button(text=f"🎧 Audio IDs: {audio_count}", callback_data="omni_audio_ids_edit")
        builder.button(text=f"🧍 Character IDs: {character_count}", callback_data="omni_character_ids_edit")
    if current_model == "gemini_omni_audio":
        voice_label = (current_omni_base_voice or "achernar").title()
        name_label = current_omni_voice_name or "auto"
        if len(name_label) > 18:
            name_label = name_label[:18] + "..."
        builder.button(text=f"🎙 Голос: {voice_label}", callback_data="omni_voice_base_edit")
        builder.button(text=f"🏷 Имя: {name_label}", callback_data="omni_voice_name_edit")
        builder.button(text="🗣 Описание", callback_data="omni_voice_desc_edit")
        builder.button(text="💬 Пример фразы", callback_data="omni_voice_dialogue_edit")
    if current_model == "gemini_omni_character":
        name_label = current_omni_character_name or "auto"
        if len(name_label) > 18:
            name_label = name_label[:18] + "..."
        audio_count = len(current_omni_character_audio_ids or [])
        builder.button(text=f"🏷 Персонаж: {name_label}", callback_data="omni_character_name_edit")
        builder.button(text=f"🎧 Audio IDs: {audio_count}", callback_data="omni_character_audio_ids_edit")
    if current_v_type == "video":
        builder.button(text=f"{'✅ ' if current_mode == '720p' else ''}📱 720p (std)", callback_data="v_mode_720p")
        builder.button(text=f"{'✅ ' if current_mode == '1080p' else ''}🖥 1080p (pro)", callback_data="v_mode_1080p")
        builder.button(text=f"{'✅ ' if current_orientation == 'image' else ''}🖼 Image orient", callback_data="v_orientation_image")
        builder.button(text=f"{'✅ ' if current_orientation == 'video' else ''}🎬 Video orient", callback_data="v_orientation_video")

    pricing_quality = _video_pricing_quality(current_model, current_veo_resolution, current_omni_resolution, current_mode, current_grok_resolution)
    total_cost = preset_manager.get_video_cost_with_quality(current_model, current_duration, pricing_quality)
    per_second_cost = preset_manager.get_video_cost_per_second(current_model, current_duration, pricing_quality)
    builder.button(text=f"Цена: {per_second_cost}🍌/с", callback_data="ignore")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    widths = [2]
    if ratio_buttons:
        if current_model == "grok_imagine_v15":
            remaining_ratio_buttons = len(ratio_buttons)
            while remaining_ratio_buttons > 0:
                row_width = min(2, remaining_ratio_buttons)
                widths.append(row_width)
                remaining_ratio_buttons -= row_width
        else:
            widths.append(len(ratio_buttons))
    if show_durations and available_durations:
        remaining_durations = len(available_durations)
        while remaining_durations > 0:
            row_width = min(2 if current_model == "grok_imagine_v15" else 8, remaining_durations)
            widths.append(row_width)
            remaining_durations -= row_width
    if current_model == "grok_imagine":
        widths += [3]
    if current_model == "grok_imagine_v15":
        widths += [2]
    if current_v_type == "video":
        widths += [4, 2]
    if current_model.startswith("veo3"):
        widths += [1]
        if current_v_type == "imgtxt":
            widths += [2 if current_model == "veo3_fast" else 1]
        widths += [3, 2]
    if current_model == "v26_pro":
        widths += [2]
    if current_model == "gemini_omni_video":
        widths += [3, 3]
    if current_model == "gemini_omni_audio":
        widths += [2, 2]
    if current_model == "gemini_omni_character":
        widths += [2]
    widths += [2]
    builder.adjust(*widths)
    return builder.as_markup()


def get_reference_videos_upload_keyboard(current_count: int = 0, max_count: int = 9, preset_id: str = None):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Загружено: {current_count}/{max_count}", callback_data="back_main")
    if preset_id == "video_new":
        builder.button(text="⏭ Пропустить", callback_data="ref_skip_new")
        builder.button(text="✅ Продолжить", callback_data="vid_ref_continue_new")
    else:
        builder.button(text="⏭ Пропустить", callback_data="ref_skip")
        builder.button(text="✅ Продолжить", callback_data=f"ref_confirm_{preset_id}")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def get_reference_images_upload_keyboard(current_count: int = 0, max_count: int = 9, preset_id: str = None):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Загружено: {current_count}/{max_count}", callback_data="back_main")
    if preset_id == "new":
        builder.button(text="⏭ Пропустить", callback_data="ref_skip_new")
        builder.button(text="✅ Продолжить", callback_data="img_ref_continue_new")
    elif preset_id == "generate_image":
        builder.button(text="⏭ Пропустить", callback_data="ref_skip")
        builder.button(text="✅ Продолжить", callback_data="ref_confirm_generate_image")
    else:
        builder.button(text="⏭ Пропустить", callback_data="ref_skip")
        builder.button(text="✅ Продолжить", callback_data=f"ref_confirm_{preset_id}")
    builder.button(text="📚 Мои сохранённые рефы", callback_data="ref_saved_library")
    builder.button(text="🔄 Перезагрузить", callback_data=f"ref_reload_{preset_id}")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1, 2, 1, 2)
    return builder.as_markup()


def get_saved_reference_picker_keyboard(reference_id: int, current_index: int, total_count: int, *, already_selected: bool = False):
    builder = InlineKeyboardBuilder()
    if total_count > 1:
        if current_index > 0:
            builder.button(text="⬅️", callback_data=f"savedref_nav_{current_index - 1}")
        builder.button(text=f"{current_index + 1}/{total_count}", callback_data="savedref_noop")
        if current_index < total_count - 1:
            builder.button(text="➡️", callback_data=f"savedref_nav_{current_index + 1}")
    builder.button(text="✅ Уже добавлен" if already_selected else "✅ Использовать", callback_data=f"savedref_use_{reference_id}")
    builder.button(text="🗑 Удалить", callback_data=f"savedref_delete_{reference_id}_{current_index}")
    builder.button(text="❌ Закрыть", callback_data="savedref_close")
    builder.adjust(3, 2, 1) if total_count > 1 else builder.adjust(2, 1)
    return builder.as_markup()


def get_image_model_selection_keyboard(current_service: str = "banana_pro"):
    builder = InlineKeyboardBuilder()
    model_rows = [
        ("nano-banana-2-lite", "model_nano_banana_2_lite", "🍌 Nano Banana 2 Lite 🔥 НОВИНКА", preset_manager.get_generation_cost("nano-banana-2-lite")),
        ("seedream_5_pro", "model_seedream_5_pro", "🌟 Seedream 5 Pro 🔥 НОВИНКА", 2),
        ("banana_pro", "model_banana_pro", "💎 Nano Banana Pro", preset_manager.get_generation_cost("nano-banana-pro")),
        ("banana_2", "model_banana_2", "🍌 Nano Banana 2", preset_manager.get_generation_cost("banana_2")),
        ("seedream_edit", "model_seedream_edit", "🖌 Seedream 4.5", preset_manager.get_generation_cost("seedream_edit")),
        ("grok_imagine_i2i", "model_grok_i2i", "🧠 Grok Imagine", preset_manager.get_generation_cost("grok_imagine_i2i")),
        ("wan_27", "model_wan_27", "🧪 Wan 2.7 Pro", preset_manager.get_generation_cost("wan_27")),
        ("flux_pro", "model_flux_pro", "🧩 GPT Image 2", preset_manager.get_generation_cost("flux_pro")),
    ]
    for model_row in model_rows:
        model_key, callback_data, label, cost = model_row[:4]
        check = "✅ " if current_service == model_key else ""
        builder.row(InlineKeyboardButton(text=f"{check}{label} • {cost}🍌", callback_data=callback_data))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


def get_create_image_keyboard(
    current_service: str = "banana_pro",
    current_ratio: str = "1:1",
    current_count: int = 1,
    num_refs: int = 0,
    nsfw_enabled: bool = False,
    img_quality: str = "2K",
    img_nsfw_checker: bool = False,
):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🤖 Сменить модель", callback_data="image_change_model"))
    supported_ratios = ["auto", "1:1", "9:16", "16:9", "4:3", "3:4", "2:3"] if current_service == "flux_pro" else (["1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "21:9"] if current_service in {"seedream_edit", "seedream_5_pro"} else ["1:1", "16:9", "9:16", "4:3", "3:4", "4:5", "5:4", "3:2", "2:3", "21:9"])
    ratio_buttons = []
    for ratio in supported_ratios:
        marker = "◉" if current_ratio == ratio else "○"
        label = ratio.replace(":", "∶")
        ratio_buttons.append(InlineKeyboardButton(text=f"{marker} {label}", callback_data=f"img_ratio_{ratio.replace(':', '_')}"))
    if len(ratio_buttons) <= 3:
        builder.row(*ratio_buttons)
    elif len(ratio_buttons) <= 5:
        builder.row(*ratio_buttons[:3]); builder.row(*ratio_buttons[3:])
    else:
        builder.row(*ratio_buttons[:3]); builder.row(*ratio_buttons[3:6]); builder.row(*ratio_buttons[6:])
    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:
        q = str(img_quality or "2K").upper()
        builder.row(
            InlineKeyboardButton(text=("◉ 1K" if q == "1K" else "○ 1K"), callback_data="img_quality_1k"),
            InlineKeyboardButton(text=("◉ 2K" if q == "2K" else "○ 2K"), callback_data="img_quality_2k"),
            InlineKeyboardButton(text=("◉ 4K" if q == "4K" else "○ 4K"), callback_data="img_quality_4k"),
        )
    count_buttons = []
    for count in [1, 2, 4, 6]:
        marker = "◉" if current_count == count else "○"
        count_buttons.append(InlineKeyboardButton(text=f"{marker} {count}x", callback_data=f"img_count_{count}"))
    builder.row(*count_buttons[:2]); builder.row(*count_buttons[2:])
    if current_service in {"seedream_edit", "seedream_5_pro"}:
        basic_marker = "◉" if img_quality == "basic" else "○"
        high_marker = "◉" if img_quality == "high" else "○"
        builder.row(InlineKeyboardButton(text=f"{basic_marker} Basic", callback_data="img_quality_basic"), InlineKeyboardButton(text=f"{high_marker} High", callback_data="img_quality_high"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()


def get_topup_keyboard():
    return get_payment_packages_keyboard(preset_manager.get_packages())


def get_payment_packages_keyboard(packages: list, promo_active: bool = False):
    builder = InlineKeyboardBuilder()
    for pkg in packages:
        popular = " 🔥" if pkg.get("popular") else ""
        builder.button(text=f"{pkg['name']}: {pkg['credits']}🍌 за {pkg['price_rub']}₽{popular}", callback_data=f"choose_pay_{pkg['id']}")
    builder.button(text="🎟 Ввести промокод" if not promo_active else "🎟 Изменить промокод", callback_data="topup_enter_promo")
    if promo_active:
        builder.button(text="❌ Убрать промокод", callback_data="topup_remove_promo")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_payment_method_keyboard(
    package_id: str,
    has_crypto: bool = True,
    has_lava: bool = False,
    has_stars: bool = True,
    lava_price_usd: float | None = None,
    has_yookassa: bool = False,
    lava_currency: str = "RUB",
) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_yookassa:
        builder.button(
            text="💳 ЮKassa · ₽ / СБП",
            callback_data=f"buy_yookassa_{package_id}",
        )
    if has_lava:
        currency = str(lava_currency or "RUB").strip().upper()
        if currency == "EUR":
            lava_text = "💶 EUR"
        else:
            lava_suffix = f" · ${lava_price_usd:g}" if lava_price_usd else ""
            lava_text = f"💳 Lava Top{lava_suffix}"
        builder.button(text=lava_text, callback_data=f"buy_lava_{package_id}")
    if has_stars:
        builder.button(text="⭐ Telegram Stars", callback_data=f"buy_stars_{package_id}")
    if has_crypto:
        builder.button(text="₿ Криптовалюта (CryptoBot)", callback_data=f"buy_crypto_{package_id}")
    builder.button(text="◀️ Назад", callback_data="menu_topup")
    builder.adjust(1)
    return builder.as_markup()


def get_payment_provider_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 CryptoBot", callback_data="menu_topup")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_balance_keyboard(user_credits: int = 0):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"У тебя: {user_credits} 🍌", callback_data="back_main")
    builder.button(text="💰 Пополнить", callback_data="menu_topup")
    builder.button(text="📋 История", callback_data="menu_history")
    builder.adjust(1, 2)
    return builder.as_markup()


def get_support_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 ИИ-ассистент", callback_data="menu_ai_assistant")
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_help_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_create_menu_keyboard():
    return get_create_video_keyboard()


def get_payment_confirmation_keyboard(payment_url: str, order_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", url=payment_url)
    builder.button(text="✅ Проверить оплату", callback_data=f"check_payment_{order_id}")
    builder.button(text="🔙 Назад", callback_data="menu_topup")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 2)
    return builder.as_markup()


def get_main_menu_button_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    return builder.as_markup()


def get_photo_prompt_result_keyboard(prompt_en: str, prompt_ru: str = "", negative_prompt: str = ""):
    builder = InlineKeyboardBuilder()
    builder.button(text="🆕 Новый промпт", callback_data="photo_to_prompt")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2)
    return builder.as_markup()


def get_video_prompt_result_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🆕 Новый видео-промпт • {_video_prompt_price_label()}🍌", callback_data="video_to_prompt")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "back_main"):
    builder = InlineKeyboardBuilder()
    if callback_data == "back_main":
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(1)
        return builder.as_markup()
    builder.button(text="🔙 Назад", callback_data=callback_data)
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2)
    return builder.as_markup()


def get_confirm_keyboard(confirm_data: str, cancel_data: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=confirm_data)
    builder.button(text="❌ Отмена", callback_data=cancel_data)
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_video_result_keyboard(video_url: str, user_credits: int = 0, task_id: str = None, model: str = None, is_public_feed: bool = False):
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Скачать видео", url=video_url)
    if task_id:
        builder.button(text="🗑 Убрать из ленты" if is_public_feed else "🎞 В ленту", callback_data=f"feedrm_{task_id}" if is_public_feed else f"feedpub_{task_id}")
    if task_id and model and model.startswith("veo3"):
        builder.button(text="✨ Получить 1080p", callback_data=f"veo1080_{task_id}")
        builder.button(text="🖥 Получить 4K", callback_data=f"veo4k_{task_id}")
        builder.button(text="➕ Продлить", callback_data=f"veoextend_{task_id}")
    if task_id:
        builder.button(text="🔁 Повторить", callback_data=f"repeat_video_result_{task_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    if task_id and model and model.startswith("veo3"):
        builder.adjust(1, 1, 2, 1, 1, 1)
    elif task_id:
        builder.adjust(1, 1, 1, 1)
    else:
        builder.adjust(1)
    return builder.as_markup()


def get_image_result_keyboard(image_url: str, task_id: str = None, is_public_feed: bool = False, is_prompt_library: bool = False):
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Скачать оригинал", url=image_url)
    if task_id:
        builder.button(text="🎬 Оживить в Grok", callback_data=f"grokvid_{task_id}")
        builder.button(text="🎬 Grok 1.5", callback_data=f"grok15vid_{task_id}")
        builder.button(text="🗑 Убрать из ленты" if is_public_feed else "🖼 В ленту", callback_data=f"feedrm_{task_id}" if is_public_feed else f"feedpub_{task_id}")
        builder.button(text="🗑 Убрать из промптов" if is_prompt_library else "📚 В промпты", callback_data=f"promptrm_{task_id}" if is_prompt_library else f"promptsave_{task_id}")
        builder.button(text="🆕 Новый промпт", callback_data=f"retry_prompt_image_{task_id}")
        builder.button(text="🔁 Повторить", callback_data=f"repeat_result_{task_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 2, 2, 2, 2, 1)
    return builder.as_markup()


def get_failed_image_retry_keyboard(task_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Повторить", callback_data=f"repeat_result_{task_id}")
    builder.button(text="✏️ Изменить промпт / модель", callback_data=f"retry_prompt_image_{task_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_gemini_omni_result_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В меню Gemini", callback_data="v_model_gemini_omni")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_ai_assistant_keyboard(telegram_id: int | None = None, back_callback: str = "back_main", back_text: str = "🔙 В главное меню"):
    builder = InlineKeyboardBuilder()
    show_admin_tools = telegram_id is not None and config.is_admin(int(telegram_id))
    if show_admin_tools:
        builder.button(text="🛠 Админ-функции", callback_data="ai_admin_help")
        builder.button(text="🔧 Админ-панель", callback_data="admin_back")
    builder.button(text=back_text, callback_data=back_callback)
    if show_admin_tools:
        builder.adjust(2, 1)
    return builder.as_markup()


def get_referral_keyboard(referral_link: str):
    builder = InlineKeyboardBuilder()
    share_url = f"https://t.me/share/url?url={referral_link}"
    builder.button(text="📨 Поделиться", url=share_url)
    builder.button(text="🔄 Обновить", callback_data="menu_referrals")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_partner_program_keyboard(referral_link: str, is_partner: bool = False):
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Публичная оферта", callback_data="partner_offer")
    if not is_partner:
        builder.button(text="✔ Прочитал и согласен с условиями", callback_data="partner_accept")
    if referral_link:
        share_url = f"https://t.me/share/url?url={referral_link}"
        builder.button(text="📨 Поделиться ссылкой", url=share_url)
    builder.button(text="📈 Детальная статистика", callback_data="partner_stats")
    builder.button(text="🔄 Обновить", callback_data="menu_partner")
    builder.button(text="🎟️ Вывод заработка", callback_data="partner_withdraw")
    builder.button(text="🍌 Обменять на бананы", callback_data="partner_exchange")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1, 1, 1, 1)
    return builder.as_markup()


def get_partner_consent_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Публичная оферта", callback_data="partner_offer")
    builder.button(text="✔ Прочитал и согласен с условиями", callback_data="partner_accept")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def get_settings_keyboard(current_model: str = "flash", current_video_model: str = "v3_std", current_i2v_model: str = "v3_std", referral_purchase_notifications_enabled: bool = True):
    builder = InlineKeyboardBuilder()
    notify_label = "вкл" if referral_purchase_notifications_enabled else "выкл"
    notify_icon = "🔔" if referral_purchase_notifications_enabled else "🔕"
    builder.button(text=f"{notify_icon} Покупки рефералов: {notify_label}", callback_data="settings_ref_purchase_notify_toggle")
    builder.button(text="🔙 Назад в главное меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_settings_keyboard_with_ai(current_model: str = "flash", current_video_model: str = "v3_std", current_i2v_model: str = "v3_std", image_service: str = "nanobanana", referral_purchase_notifications_enabled: bool = True):
    builder = InlineKeyboardBuilder()
    image_services = [("nanobanana", "🍌 Nano Banana"), ("flux_pro", "💎 GPT Image 2"), ("seedream", "🖌 Seedream"), ("z_image_turbo", "⚡ Z-Image")]
    for service, label in image_services:
        check = "✅ " if image_service == service else ""
        builder.button(text=f"{check}{label}", callback_data=f"settings_service_{service}")
    image_models = [("flash", "⚡ Flash"), ("pro", "💎 Pro")]
    for model, label in image_models:
        check = "✅ " if current_model == model else ""
        builder.button(text=f"{check}{label}", callback_data=f"settings_model_{model}")
    video_models = [("v3_std", "⚡ Kling v3"), ("v3_pro", "💎 Kling 3.0"), ("v26_pro", "🌀 Kling 2.5")]
    for model, label in video_models:
        check = "✅ " if current_video_model == model else ""
        builder.button(text=f"{check}{label}", callback_data=f"settings_video_{model}")
    i2v_models = [("v3_std", "⚡ I2V Std"), ("v3_pro", "💎 I2V Pro"), ("v26_pro", "🌀 I2V 2.5")]
    for model, label in i2v_models:
        check = "✅ " if current_i2v_model == model else ""
        builder.button(text=f"{check}{label}", callback_data=f"settings_i2v_{model}")
    notify_label = "вкл" if referral_purchase_notifications_enabled else "выкл"
    notify_icon = "🔔" if referral_purchase_notifications_enabled else "🔕"
    builder.button(text=f"{notify_icon} Покупки рефералов: {notify_label}", callback_data="settings_ref_purchase_notify_toggle")
    builder.button(text="🤖 AI-помощник", callback_data="menu_ai_assistant")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 3, 3, 1, 2)
    return builder.as_markup()


def get_motion_control_keyboard(current_mode: str = "720p", current_orientation: str = "video"):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Standard", callback_data="motion_control_std")
    builder.button(text="💎 Pro", callback_data="motion_control_pro")
    for mode, label in (("720p", "📱 720p"), ("1080p", "🖥 1080p")):
        check = "✅ " if current_mode == mode else ""
        builder.button(text=f"{check}{label}", callback_data=f"motion_mode_{mode}")
    for orientation, label in (("video", "🎬 Видео"), ("image", "🖼 Фото")):
        check = "✅ " if current_orientation == orientation else ""
        builder.button(text=f"{check}{label}", callback_data=f"motion_orientation_{orientation}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_video_options_no_preset_keyboard(current_duration: int = 5, current_ratio: str = "16:9", generate_audio: bool = True):
    builder = InlineKeyboardBuilder()
    for duration in (5, 10, 15):
        check = "✅ " if int(current_duration) == duration else ""
        builder.button(text=f"{check}{duration} сек", callback_data=f"video_dur_{duration}")
    for ratio in ("16:9", "9:16", "1:1"):
        check = "✅ " if current_ratio == ratio else ""
        builder.button(text=f"{check}{ratio.replace(':', '∶')}", callback_data=f"ratio_{ratio.replace(':', '_')}")
    audio_label = "✅ Звук" if generate_audio else "Без звука"
    builder.button(text=audio_label, callback_data="ignore")
    builder.button(text="▶️ Продолжить", callback_data="video_media_continue")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(3, 3, 1, 2)
    return builder.as_markup()


def get_video_edit_input_type_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Видео", callback_data="video_edit_input_video")
    builder.button(text="🖼 Фото", callback_data="video_edit_input_image")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_video_edit_keyboard(input_type: str = "video", quality: str = "std", duration: int = 5, aspect_ratio: str = "16:9"):
    builder = InlineKeyboardBuilder()
    for value, label in (("std", "⚡ STD"), ("pro", "💎 PRO")):
        check = "✅ " if quality == value else ""
        builder.button(text=f"{check}{label}", callback_data=f"video_edit_quality_{value}")
    for value in (5, 10):
        check = "✅ " if int(duration) == value else ""
        builder.button(text=f"{check}{value} сек", callback_data=f"video_edit_duration_{value}")
    for ratio in ("16:9", "9:16", "1:1"):
        check = "✅ " if aspect_ratio == ratio else ""
        builder.button(text=f"{check}{ratio.replace(':', '∶')}", callback_data=f"video_edit_ratio_{ratio.replace(':', '_')}")
    change_label = "🎬 Сменить видео" if input_type == "video" else "🖼 Сменить фото"
    builder.button(text=change_label, callback_data="video_edit_change_type")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 3, 2)
    return builder.as_markup()


def get_reference_images_keyboard(preset_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Загрузить", callback_data=f"ref_upload_{preset_id}")
    builder.button(text="📚 Сохранённые", callback_data="ref_saved_library")
    builder.button(text="✅ Продолжить", callback_data=f"ref_confirm_{preset_id}")
    builder.button(text="⏭ Пропустить", callback_data=f"ref_skip_{preset_id}")
    builder.button(text="🧹 Очистить", callback_data=f"ref_clear_{preset_id}")
    builder.button(text="🔄 Обновить", callback_data=f"ref_reload_{preset_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_category_keyboard(category: str, presets: list, user_credits: int):
    builder = InlineKeyboardBuilder()
    for preset in presets:
        affordable = "✅" if user_credits >= preset.cost else "❌"
        builder.button(text=f"{preset.name} - {preset.cost}🍌 {affordable}", callback_data=f"preset_{preset.id}")
    builder.button(text="🔙 Назад в меню", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def get_preset_action_keyboard(preset_id: str, has_input: bool, category: str = None):
    builder = InlineKeyboardBuilder()
    if has_input:
        builder.button(text="✏️ Ввести свой вариант", callback_data=f"custom_{preset_id}")
        builder.button(text="🎲 Использовать пример", callback_data=f"default_{preset_id}")
    else:
        builder.button(text="▶️ Запустить генерацию", callback_data=f"run_{preset_id}")
    builder.button(text="🔙 Назад", callback_data=f"back_cat_{preset_id.split('_')[0]}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def get_duration_keyboard(preset_id: str, current_duration: int = 5):
    builder = InlineKeyboardBuilder()
    for dur in [5, 10, 15]:
        emoji = "✅" if dur == current_duration else ""
        builder.button(text=f"{dur} сек {emoji}", callback_data=f"duration_{preset_id}_{dur}")
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(2, 2)
    return builder.as_markup()


def get_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "16:9"):
    builder = InlineKeyboardBuilder()
    for ratio, label in [("16:9", "📺"), ("9:16", "📱"), ("1:1", "⬜")]:
        emoji = "✅ " if ratio == current_ratio else ""
        builder.button(text=f"{emoji}{label} {ratio.replace(':', '∶')}", callback_data=f"ratio_{preset_id}_{ratio}")
    builder.button(text="🔙 Назад", callback_data=f"preset_{preset_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(3, 2)
    return builder.as_markup()


def get_image_aspect_ratio_keyboard(preset_id: str, current_ratio: str = "1:1"):
    builder = InlineKeyboardBuilder()
    for ratio, label in [("1:1", "⬜"), ("16:9", "📺"), ("9:16", "📱"), ("3:4", "🖼"), ("2:3", "📐"), ("21:9", "🎬")]:
        emoji = "✅ " if ratio == current_ratio else ""
        builder.button(text=f"{emoji}{label} {ratio.replace(':', '∶')}", callback_data=f"img_ratio_{preset_id}_{ratio}")
    builder.button(text="🔙 Назад", callback_data=f"model_{preset_id}")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(3, 2, 2)
    return builder.as_markup()


def get_advanced_options_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
