from __future__ import annotations

import re

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from bot.channel_link import ChannelLinkError, consume_channel_link_token
from bot.channel_promotions import ensure_instagram_first_image_promotion
from bot.database import get_or_create_user

router = Router()
_START_LINK_RE = re.compile(
    r"^/start(?:@[A-Za-z0-9_]+)?\s+iglink_([A-Za-z0-9_-]{8,64})$"
)


def extract_link_token(text: str | None) -> str:
    match = _START_LINK_RE.fullmatch(str(text or "").strip())
    return match.group(1) if match else ""


def _link_error_text(error: ChannelLinkError) -> str:
    if error.code == "expired":
        return (
            "Ссылка на привязку Instagram уже истекла.\n\n"
            "Вернитесь в Direct HappyFox и запросите новую ссылку."
        )
    if error.code == "used":
        return (
            "Эта ссылка уже использована.\n\n"
            "Если Instagram ещё не привязан, запросите новую ссылку в Direct."
        )
    if error.code == "conflict":
        return (
            "Этот Instagram уже привязан к другому аккаунту HappyFox.\n\n"
            "Для смены аккаунта обратитесь в поддержку."
        )
    return (
        "Не получилось подтвердить привязку Instagram.\n\n"
        "Запросите новую ссылку в Direct HappyFox и попробуйте ещё раз."
    )


@router.message(F.text.regexp(_START_LINK_RE.pattern))
async def confirm_instagram_account_link(
    message: types.Message,
    state: FSMContext,
) -> None:
    token = extract_link_token(message.text)
    if not token:
        return

    await state.clear()
    user = await get_or_create_user(message.from_user.id)
    try:
        identity = await consume_channel_link_token(token, user.id)
    except ChannelLinkError as error:
        await message.answer(_link_error_text(error))
        return

    promotion = await ensure_instagram_first_image_promotion(identity.id)
    free_image_text = (
        "Первая генерация фото в Instagram — бесплатно 🎁\n"
        if promotion.status != "consumed"
        else ""
    )
    await message.answer(
        "✅ Instagram привязан к вашему HappyFox.\n\n"
        f"{free_image_text}"
        "Баланс и история теперь общие. После бесплатной генерации действуют обычные цены HappyFox.\n\n"
        "Вернитесь в Direct — можно продолжать там."
    )
