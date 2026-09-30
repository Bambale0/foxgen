from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_telegram_primary_screens_use_current_happyfox_copy() -> None:
    common = _read("bot/handlers/common.py")
    assert "Создавай то, что нужно прямо сейчас" in common
    assert "<b>Сделать фото</b>" in common
    assert "<b>Собрать видео</b>" in common
    assert "<b>Оживить персонажа</b>" in common
    assert "<b>Создать музыку</b>" in common
    assert "<b>Повторить движение</b>" in common
    assert "<b>Разобрать идею</b>" in common
    assert "Выбирай, что создаём" in common
    assert "🐾 <b>Твои лапки</b>" in common
    assert "💬 <b>Что случилось?</b>" in common
    assert "🤖 <b>HappyFox:</b>" in common


def test_telegram_primary_screens_drop_stale_copy() -> None:
    common = _read("bot/handlers/common.py")
    stale = (
        "Создавайте фото, видео и анимацию по описанию или референсам.",
        "Создавайте фото, видео, озвучку и музыку с AI.",
        "Скажите, что хотите получить: изображение, ролик, озвучку или музыку.",
        "Выберите действие ниже",
        "<b>Быстрый старт</b>",
        "🖼 Фото — создать с нуля или изменить по референсу",
        "Реферальный бонус не начислен",
        "Если вы ещё не нажимали «Запустить»",
        "💎 <b>Баланс и статистика</b>",
        "Можно написать прямо сюда — AI-ассистент поможет с:",
        "🤖 <b>BotAI:</b>",
    )
    for fragment in stale:
        assert fragment not in common


def test_referral_status_copy_is_short_and_does_not_claim_extra_welcome_credit() -> None:
    common = _read("bot/handlers/common.py")
    assert "🤝 <b>Приглашение привязано</b>" in common
    assert "Ссылка-приглашение применяется только при первой регистрации." in common
    assert "лапок за регистрацию по приглашению" not in common


def test_telegram_partner_and_payment_screens_are_current() -> None:
    partner = _read("bot/partner_copy.py")
    payments = _read("bot/handlers/payments.py")
    assert "🤝 <b>Зарабатывай с HappyFox</b>" in partner
    assert "<b>Как начисляется</b>" in partner
    assert "Это практическое руководство по участию" not in partner
    assert (
        "Выбери пакет — сумму увидишь до перехода к оплате." in payments
    )
    assert "Выберите пакет бананов ниже." not in payments


def test_telegram_auxiliary_copy_has_no_old_public_brand() -> None:
    trends = _read("bot/handlers/trends_compat.py")
    help_text = _read("bot/utils/help_texts.py")
    assert "готовые шаблоны HappyFox" in trends
    assert "готовые шаблоны от команды NEUROMIX" not in trends
    assert "🦊 <b>HappyFox</b>" in help_text
    assert "⚠️ <b>注意:</b>" not in help_text


def test_product_normalizer_runs_telegram_screen_copy_before_currency_guard() -> None:
    normalizer = _read("scripts/apply_happyfox_product_copy.py")
    assert (
        "from apply_happyfox_telegram_screen_copy import apply_happyfox_telegram_screen_copy"
        in normalizer
    )
    assert "apply_happyfox_telegram_screen_copy()" in normalizer
    assert normalizer.index("apply_happyfox_telegram_screen_copy()") < normalizer.index(
        "_patch_currency_copy()", normalizer.index("def main()")
    )
