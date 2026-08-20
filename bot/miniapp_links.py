from urllib.parse import quote

from bot.config import config


def _clean_bot_username(bot_username: str | None) -> str:
    return str(bot_username or "").strip().lstrip("@")


def _clean_referral_code(referral_code: str | None) -> str:
    return str(referral_code or "").strip().upper()


def miniapp_startapp_link(
    bot_username: str | None,
    start_param: str | None = None,
    *,
    fallback_url: str | None = None,
) -> str:
    username = _clean_bot_username(bot_username)
    if not username:
        return fallback_url or config.mini_app_url

    param = str(start_param or "").strip()
    if not param:
        return f"https://t.me/{username}?startapp"
    return f"https://t.me/{username}?startapp={quote(param, safe='_-')}"


def bot_start_link(
    bot_username: str | None,
    start_param: str | None = None,
    *,
    fallback_url: str | None = None,
) -> str:
    username = _clean_bot_username(bot_username)
    if not username:
        return fallback_url or config.mini_app_url

    param = str(start_param or "").strip()
    if not param:
        return f"https://t.me/{username}"
    return f"https://t.me/{username}?start={quote(param, safe='_-')}"


def referral_start_param(referral_code: str | None) -> str:
    code = _clean_referral_code(referral_code)
    return f"ref_{code}" if code else ""


def referral_link(bot_username: str | None, referral_code: str | None) -> str:
    """Партнёрская ссылка на мини-приложение (?startapp=ref_CODE)."""
    return miniapp_startapp_link(bot_username, referral_start_param(referral_code))


def referral_bot_link(bot_username: str | None, referral_code: str | None) -> str:
    """Партнёрская ссылка на бота (?start=ref_CODE)."""
    return bot_start_link(bot_username, referral_start_param(referral_code))


def profile_start_param(referral_code: str | None) -> str:
    code = _clean_referral_code(referral_code)
    return f"profile_{code}_ref_{code}" if code else ""


def profile_link(bot_username: str | None, referral_code: str | None) -> str:
    return miniapp_startapp_link(bot_username, profile_start_param(referral_code))


def feed_start_param(gen_id: int | str, referral_code: str | None = None) -> str:
    value = str(gen_id or "").strip()
    if not value:
        return ""
    code = _clean_referral_code(referral_code)
    base = f"feed_{value}"
    return f"{base}_ref_{code}" if code else base


def feed_link(
    bot_username: str | None,
    gen_id: int | str,
    referral_code: str | None = None,
) -> str:
    return miniapp_startapp_link(bot_username, feed_start_param(gen_id, referral_code))


def feed_bot_link(
    bot_username: str | None,
    gen_id: int | str,
    referral_code: str | None = None,
) -> str:
    return bot_start_link(bot_username, feed_start_param(gen_id, referral_code))


def remix_start_param(gen_id: int | str, referral_code: str | None = None) -> str:
    value = str(gen_id or "").strip()
    if not value:
        return ""
    code = _clean_referral_code(referral_code)
    base = f"remix_{value}"
    return f"{base}_ref_{code}" if code else base


def remix_link(
    bot_username: str | None,
    gen_id: int | str,
    referral_code: str | None = None,
) -> str:
    return miniapp_startapp_link(bot_username, remix_start_param(gen_id, referral_code))


def remix_bot_link(
    bot_username: str | None,
    gen_id: int | str,
    referral_code: str | None = None,
) -> str:
    return bot_start_link(bot_username, remix_start_param(gen_id, referral_code))


def prompt_start_param(prompt_id: int | str, referral_code: str | None = None) -> str:
    value = str(prompt_id or "").strip()
    if not value:
        return ""
    code = _clean_referral_code(referral_code)
    base = f"prompt_{value}"
    return f"{base}_ref_{code}" if code else base


def prompt_link(
    bot_username: str | None,
    prompt_id: int | str,
    referral_code: str | None = None,
) -> str:
    return miniapp_startapp_link(
        bot_username,
        prompt_start_param(prompt_id, referral_code),
    )


def task_start_param(task_id: int | str) -> str:
    value = str(task_id or "").strip()
    return f"task_{value}" if value else ""


def task_link(bot_username: str | None, task_id: int | str) -> str:
    return miniapp_startapp_link(bot_username, task_start_param(task_id))
