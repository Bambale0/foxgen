from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_telegram_home_uses_action_first_happyfox_voice() -> None:
    common = _read("bot/handlers/common.py")
    expected = (
        "Создавай то, что нужно прямо сейчас",
        "<b>Сделать фото</b>",
        "<b>Собрать видео</b>",
        "<b>Оживить персонажа</b>",
        "<b>Создать музыку</b>",
        "<b>Повторить движение</b>",
        "<b>Разобрать идею</b>",
        "<b>Не знаешь, с чего начать?</b>",
        "<b>Вернуться к результатам</b>",
        "лапок на балансе",
        "Выбирай, что создаём",
    )
    for fragment in expected:
        assert fragment in common

    stale = (
        "<b>Быстрый старт</b>",
        "Скажите, что хотите получить",
        "Выберите действие ниже",
        "Создавайте фото, видео, озвучку и музыку с AI.",
    )
    for fragment in stale:
        assert fragment not in common


def test_telegram_main_buttons_use_result_oriented_labels() -> None:
    keyboards = _read("bot/keyboards.py")
    for label in (
        "🖼 Сделать фото",
        "🎬 Собрать видео",
        "🎙 Оживить персонажа",
        "🎵 Создать музыку",
        "🎯 Повторить движение",
        "✨ Разобрать идею",
        "🤖 Помочь с идеей",
        "🔗 Мои результаты",
        "💬 Нужна помощь",
        "💳 Добавить лапки",
    ):
        assert label in keyboards

    assert 'text=f"🐾 {user_credits} лапок"' in keyboards


def test_max_main_navigation_uses_same_product_vocabulary() -> None:
    max_ui = _read("bot/max_ui.py")
    for label in (
        "🖼 Сделать фото",
        "🎬 Собрать видео",
        "🎯 Повторить движение",
        "🤖 Помочь с идеей",
        "📚 Готовые идеи",
        "💬 Нужна помощь",
        "🤝 Партнёрка",
    ):
        assert label in max_ui

    assert "🐾 Баланс:" in max_ui
    assert "Промпт по видео •" not in max_ui


def test_core_support_balance_and_partner_copy_is_plain_and_actionable() -> None:
    common = _read("bot/handlers/common.py")
    payments = _read("bot/handlers/payments.py")
    partner = _read("bot/partner_copy.py")
    max_product = _read("bot/max_product_channel.py")

    assert "🐾 <b>Твои лапки</b>" in common
    assert "💬 <b>Что случилось?</b>" in common
    assert "🐾 <b>Добавить лапки</b>" in payments
    assert "🤝 <b>Зарабатывай с HappyFox</b>" in partner
    assert "🤖 <b>Расскажи идею</b>" in max_product
    assert "💬 <b>Что случилось?</b>" in max_product


def test_miniapp_uses_the_same_action_language_and_channel_neutral_launch_copy() -> None:
    quick = _read("frontend/miniapp-v0/components/quick-action-grid.tsx")
    services = _read("frontend/miniapp-v0/components/service-grid.tsx")
    workspace = _read("frontend/miniapp-v0/components/workspace-sheet.tsx")
    photo = _read("frontend/miniapp-v0/components/tabs/photo-tab.tsx")
    video = _read("frontend/miniapp-v0/components/tabs/video-tab.tsx")
    motion = _read("frontend/miniapp-v0/components/tabs/motion-tab.tsx")

    for label in ("Сделать фото", "Собрать видео", "Оживить кадр", "Помочь с идеей"):
        assert label in quick

    assert "Что хочешь сделать?" in services
    assert "Нужна помощь" in services
    assert "Расскажи идею" in workspace
    assert ">Сделать фото</h2>" in photo
    assert ">Собрать видео</h2>" in video
    assert "Повторить движение" in motion

    combined = "\n".join((photo, video, motion))
    assert "Откройте Mini App через Telegram" not in combined
    assert "Открой HappyFox из Telegram или MAX" in combined



def test_max_creator_flows_share_the_same_direct_voice() -> None:
    paths = (
        "bot/max_channel.py",
        "bot/max_creator_channel.py",
        "bot/max_creation_parity.py",
        "bot/max_suno_channel.py",
        "bot/max_omni_channel.py",
        "bot/max_parity_channel.py",
    )
    combined = "\n".join(_read(path) for path in paths)

    for stale in (
        "Выберите",
        "Загрузите",
        "Отправьте",
        "Попробуйте",
        "Пополните",
        "Создавайте",
        "выберите",
        "загрузите",
        "отправьте",
        "пополните",
        "пришлите",
        "используйте",
        "приложите",
        "добавьте",
        "нажмите",
        "🍌 Баланс",
        "3🍌",
    ):
        assert stale not in combined

    assert "🎯 <b>Повторить движение</b>" in _read("bot/max_creator_channel.py")
    assert "🎵 <b>Создать музыку</b>" in _read("bot/max_suno_channel.py")
    assert "🎙 <b>Создать голос</b>" in _read("bot/max_omni_channel.py")
    assert "🐾 <b>Твои лапки</b>" in _read("bot/max_parity_channel.py")
