"""Validate and normalize user-facing copy for the production bot image.

The Telegram bot and Mini App are deployed separately. This guard validates
and normalizes only the text-bot image and fails the build if the expected
source layout changes.
"""


BUTTON_TEXT = (
    'InlineKeyboardButton(text="✍️ Промпт по описанию", '
    'callback_data="photo_to_prompt"),'
)
PRICE_IN_BUTTON_FRAGMENT = "Промпт по описанию •"

OLD_SCREEN = (
    '        "📸 <b>Промпт по фото</b>\\n\\n"\n'
    '        f"Стоимость анализа фото: <b>{photo_prompt_price_label()}</b>\\n\\n"\n'
)
NEW_SCREEN = (
    '        "✍️ <b>Промпт по описанию</b>\\n\\n"\n'
    '        f"Стоимость анализа: <b>{photo_prompt_price_label()}</b>\\n\\n"\n'
)
ACTIVE_PROMPT_SCREEN = (
    '        "✨ <b>Анализ и создание промпта</b>\\n\\n"\n'
    '        f"Стоимость анализа: <b>{photo_prompt_price_label()}</b>\\n\\n"\n'
)
ACTIVE_PROMPT_SCREEN_WITHOUT_PRICE = (
    '        "✨ <b>Анализ и создание промпта</b>\\n\\n"\n'
    '        "Отправьте одним сообщением:\\n"\n'
)
ACTIVE_PROMPT_REPLACED_TITLE = "✍️ <b>Промпт по описанию</b>"

DATABASE_IMPORT_ANCHOR = "    PARTNER_INVITER_BONUS,\n"
DATABASE_IMPORT_WITH_WELCOME_BONUS = (
    "    PARTNER_INVITER_BONUS,\n"
    "    PARTNER_NEW_USER_BONUS,\n"
)
OLD_WELCOME_COPY = (
    '        "🎁 <b>Новым пользователям — 15 бананов в подарок!</b>\\n"\n'
)
NEW_WELCOME_COPY = (
    '        f"🎁 <b>Новым пользователям — {PARTNER_NEW_USER_BONUS} '
    'бананов в подарок!</b>\\n"\n'
)
OLD_PARTNER_BONUS_COPY = (
    '        "• Каждый, кто перейдёт по вашей реферальной ссылке, получает '
    '🍌 <code>15</code> бананов для тестирования бота\\n"\n'
)
NEW_PARTNER_BONUS_COPY = (
    '        f"• Каждый, кто перейдёт по вашей реферальной ссылке, получает '
    '🍌 <code>{PARTNER_NEW_USER_BONUS}</code> бананов для тестирования бота\\n"\n'
)

MINIAPP_PREVIEW_IMPORT_ANCHOR = "from bot.services.preset_manager import preset_manager\n"
MINIAPP_PREVIEW_IMPORT = (
    "from bot.services.trend_preview_service import "
    "ensure_lightweight_trend_preview_url\n"
)
MINIAPP_PREVIEW_HELPERS_ANCHOR = "\n\nasync def miniapp_prompts(request: web.Request) -> web.Response:\n"
MINIAPP_PREVIEW_HELPERS = '''


def _is_video_trend_prompt(prompt: dict) -> bool:
    tags = {
        str(tag or "").strip().lower()
        for tag in list(prompt.get("tags") or [])
        if str(tag or "").strip()
    }
    settings = prompt.get("generation_settings")
    return (
        "trend" in tags
        and isinstance(settings, dict)
        and str(settings.get("kind") or "").strip().lower() == "video"
    )


async def _apply_lightweight_trend_preview(prompt: dict) -> dict:
    if not isinstance(prompt, dict) or not _is_video_trend_prompt(prompt):
        return prompt
    preview_url = str(prompt.get("preview_url") or "").strip()
    if not preview_url:
        return prompt
    lightweight_url = await ensure_lightweight_trend_preview_url(preview_url)
    if not lightweight_url or lightweight_url == preview_url:
        return prompt
    updated = dict(prompt)
    updated["preview_url"] = lightweight_url
    updated["original_preview_url"] = preview_url
    return updated


async def _apply_lightweight_trend_previews(prompts) -> list[dict]:
    return [
        await _apply_lightweight_trend_preview(prompt)
        for prompt in list(prompts or [])
    ]
'''
MINIAPP_PROMPTS_RETURN = '        return web.json_response({"ok": True, "prompts": prompts})\n'
MINIAPP_PROMPTS_RETURN_WITH_PREVIEWS = (
    "        prompts = await _apply_lightweight_trend_previews(prompts)\n"
    '        return web.json_response({"ok": True, "prompts": prompts})\n'
)
MINIAPP_DETAIL_RETURN_BLOCK = (
    '        return web.json_response({"ok": True, "prompt": prompt})\n'
    "    except Exception as e:\n"
    "        return _miniapp_error_response(e, log_message=\"Mini App prompt detail failed\")\n"
)
MINIAPP_DETAIL_RETURN_BLOCK_WITH_PREVIEW = (
    "        prompt = await _apply_lightweight_trend_preview(prompt)\n"
    '        return web.json_response({"ok": True, "prompt": prompt})\n'
    "    except Exception as e:\n"
    "        return _miniapp_error_response(e, log_message=\"Mini App prompt detail failed\")\n"
)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as source:
        return source.read()


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as target:
        target.write(content)


def normalize_photo_prompt_screen() -> None:
    handler_path = "bot/handlers/image_analyzer.py"
    handler_text = read_text(handler_path)
    if OLD_SCREEN in handler_text:
        handler_text = handler_text.replace(OLD_SCREEN, NEW_SCREEN, 1)
        write_text(handler_path, handler_text)
    elif NEW_SCREEN not in handler_text:
        raise RuntimeError("Photo prompt screen copy was not found")


def validate_active_prompt_analyzer_screen() -> None:
    handler_text = read_text("bot/handlers/prompt_analyzer_v2.py")
    if ACTIVE_PROMPT_SCREEN_WITHOUT_PRICE in handler_text:
        raise RuntimeError("Active prompt analyzer still misses the price line")
    if ACTIVE_PROMPT_SCREEN not in handler_text:
        raise RuntimeError("Active prompt analyzer price screen copy was not found")
    callback_block = handler_text.split('async def prompt_analyzer_handler', 1)[1].split(
        '@router.message', 1
    )[0]
    if ACTIVE_PROMPT_REPLACED_TITLE in callback_block:
        raise RuntimeError("Active prompt analyzer title must stay unchanged")
    for required_fragment in (
        "photo_prompt_price_label",
        "reserve_photo_prompt_charge",
        "refund_photo_prompt_charge",
        "PhotoPromptInsufficientBalance",
    ):
        if required_fragment not in handler_text:
            raise RuntimeError(
                f"Active prompt analyzer is missing billing fragment: {required_fragment}"
            )


def normalize_runtime_bonus_copy() -> None:
    handler_path = "bot/handlers/common.py"
    handler_text = read_text(handler_path)

    if "    PARTNER_NEW_USER_BONUS,\n" not in handler_text:
        if DATABASE_IMPORT_ANCHOR not in handler_text:
            raise RuntimeError("Welcome bonus database import anchor was not found")
        handler_text = handler_text.replace(
            DATABASE_IMPORT_ANCHOR,
            DATABASE_IMPORT_WITH_WELCOME_BONUS,
            1,
        )

    if OLD_WELCOME_COPY in handler_text:
        handler_text = handler_text.replace(
            OLD_WELCOME_COPY,
            NEW_WELCOME_COPY,
            1,
        )
    elif NEW_WELCOME_COPY not in handler_text:
        raise RuntimeError("Telegram welcome bonus copy was not found")

    if OLD_PARTNER_BONUS_COPY in handler_text:
        handler_text = handler_text.replace(
            OLD_PARTNER_BONUS_COPY,
            NEW_PARTNER_BONUS_COPY,
            1,
        )
    elif NEW_PARTNER_BONUS_COPY not in handler_text:
        raise RuntimeError("Telegram partner cabinet bonus copy was not found")

    stale_fragments = (
        "Новым пользователям — 15 бананов",
        "<code>15</code> бананов для тестирования бота",
    )
    for fragment in stale_fragments:
        if fragment in handler_text:
            raise RuntimeError(f"Stale Telegram bonus copy remains: {fragment}")

    write_text(handler_path, handler_text)


def normalize_miniapp_trend_video_previews() -> None:
    miniapp_path = "bot/miniapp.py"
    miniapp_text = read_text(miniapp_path)

    if MINIAPP_PREVIEW_IMPORT not in miniapp_text:
        if MINIAPP_PREVIEW_IMPORT_ANCHOR not in miniapp_text:
            raise RuntimeError("Mini App trend preview import anchor was not found")
        miniapp_text = miniapp_text.replace(
            MINIAPP_PREVIEW_IMPORT_ANCHOR,
            MINIAPP_PREVIEW_IMPORT_ANCHOR + MINIAPP_PREVIEW_IMPORT,
            1,
        )

    if "async def _apply_lightweight_trend_preview" not in miniapp_text:
        if MINIAPP_PREVIEW_HELPERS_ANCHOR not in miniapp_text:
            raise RuntimeError("Mini App prompts handler anchor was not found")
        miniapp_text = miniapp_text.replace(
            MINIAPP_PREVIEW_HELPERS_ANCHOR,
            MINIAPP_PREVIEW_HELPERS + MINIAPP_PREVIEW_HELPERS_ANCHOR,
            1,
        )

    if MINIAPP_PROMPTS_RETURN_WITH_PREVIEWS not in miniapp_text:
        if MINIAPP_PROMPTS_RETURN not in miniapp_text:
            raise RuntimeError("Mini App prompts response anchor was not found")
        miniapp_text = miniapp_text.replace(
            MINIAPP_PROMPTS_RETURN,
            MINIAPP_PROMPTS_RETURN_WITH_PREVIEWS,
            1,
        )

    if MINIAPP_DETAIL_RETURN_BLOCK_WITH_PREVIEW not in miniapp_text:
        if MINIAPP_DETAIL_RETURN_BLOCK not in miniapp_text:
            raise RuntimeError("Mini App prompt detail response anchor was not found")
        miniapp_text = miniapp_text.replace(
            MINIAPP_DETAIL_RETURN_BLOCK,
            MINIAPP_DETAIL_RETURN_BLOCK_WITH_PREVIEW,
            1,
        )

    for required_fragment in (
        "ensure_lightweight_trend_preview_url",
        "_apply_lightweight_trend_previews(prompts)",
        "_apply_lightweight_trend_preview(prompt)",
    ):
        if required_fragment not in miniapp_text:
            raise RuntimeError(
                f"Mini App trend preview patch is missing: {required_fragment}"
            )

    write_text(miniapp_path, miniapp_text)


def main() -> None:
    keyboard_path = "bot/keyboards.py"
    keyboard_text = read_text(keyboard_path)
    if BUTTON_TEXT not in keyboard_text:
        raise RuntimeError("Main-menu photo prompt button was not found")
    if PRICE_IN_BUTTON_FRAGMENT in keyboard_text:
        raise RuntimeError("Photo prompt price must not be shown in the menu button")

    normalize_photo_prompt_screen()
    validate_active_prompt_analyzer_screen()
    normalize_runtime_bonus_copy()
    normalize_miniapp_trend_video_previews()

    database_text = read_text("bot/database.py")
    if "PARTNER_NEW_USER_BONUS: int = 5" not in database_text:
        raise RuntimeError("New-user welcome bonus must be 5 bananas")


if __name__ == "__main__":
    main()
