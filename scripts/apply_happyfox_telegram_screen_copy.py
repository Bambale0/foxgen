from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _replace_once_or_verify(path: str, old: str, new: str, *, context: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{context}: expected exactly one old copy anchor, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def _patch_common() -> None:
    path = "bot/handlers/common.py"
    replacements = (
        (
            '        "Создавайте фото, видео и анимацию по описанию или референсам.\\n"\n'
            '        "Выберите задачу — дальше покажу только нужные шаги. 👇\\n\\n"\n'
            '        "<b>Что можно сделать</b>\\n"\n'
            '        "🖼 Создать фото — по описанию или референсу\\n"\n'
            '        "🎬 Создать видео — по тексту, фото или готовому ролику\\n"\n'
            '        "🎭 Оживить фото — добавить или перенести движение\\n"\n'
            '        "📱 Лента — посмотреть работы других пользователей\\n"\n'
            '        "📚 Библиотека промптов — выбрать готовую идею для генерации\\n"\n'
            '        "🤖 Помощник — подобрать модель, настройки и улучшить промпт\\n\\n"\n',
            '        "Скажите, что хотите получить: изображение, ролик, озвучку или музыку. "\n'
            '        "Можно начать с идеи или готового файла.\\n"\n'
            '        "Выберите действие ниже — дальше останутся только нужные шаги. 👇\\n\\n"\n'
            '        "<b>Быстрый старт</b>\\n"\n'
            '        "🖼 Фото — создать с нуля или изменить по референсу\\n"\n'
            '        "🎬 Видео — сделать по тексту, фото или ролику\\n"\n'
            '        "🎯 Motion Control — перенести движение на персонажа\\n"\n'
            '        "✨ Промпты — разобрать референс или подготовить запрос\\n"\n'
            '        "🤖 AI-помощник — подобрать модель и собрать промпт\\n\\n"\n',
            "Telegram main screen",
        ),
        (
            '        "Выберите, что хотите получить — дальше покажу только подходящие настройки."\n',
            '        "Что создаём? Выберите результат — дальше бот покажет только нужные шаги и настройки."\n',
            "Telegram create hub",
        ),
        (
            '        "💎 <b>Баланс и статистика</b>\\n\\n"\n',
            '        "🐾 <b>Баланс HappyFox</b>\\n\\n"\n',
            "Telegram balance title",
        ),
        (
            '        "Можно написать прямо сюда — AI-ассистент поможет с:\\n"\n'
            '        "• генерацией изображений и видео\\n"\n'
            '        "• выбором модели и настроек\\n"\n'
            '        "• оплатой и балансом\\n"\n'
            '        "• любыми непонятными шагами в боте\\n\\n"\n'
            '        "<b>Если нужен человек:</b>\\n"\n',
            '        "Опишите проблему одним сообщением. AI-поддержка попробует решить её сразу.\\n\\n"\n'
            '        "<b>С чем поможем</b>\\n"\n'
            '        "• генерация не запускается или результат не пришёл\\n"\n'
            '        "• непонятно, какую модель или настройку выбрать\\n"\n'
            '        "• вопрос по оплате, списанию или балансу\\n"\n'
            '        "• нужен разбор конкретной ошибки\\n\\n"\n'
            '        "Если нужна ручная проверка, обращение можно передать оператору.\\n"\n',
            "Telegram support screen",
        ),
        (
            '                f"🤖 <b>BotAI:</b>{response}",\n',
            '                f"🤖 <b>HappyFox:</b>{response}",\n',
            "Telegram assistant response brand",
        ),
        (
            '    new_body = "Выберите, что хотите сделать: создать видео, создать фото или улучшить готовое изображение."\n',
            '    new_body = "Быстрый доступ к дополнительным сценариям: создайте фото или видео либо улучшите готовое изображение."\n',
            "HappyFox other tools copy",
        ),
    )
    for old, new, context in replacements[:-1]:
        _replace_once_or_verify(path, old, new, context=context)
    old, new, context = replacements[-1]
    _replace_once_or_verify("scripts/apply_happyfox_main_menu.py", old, new, context=context)


def _patch_partner() -> None:
    path = "bot/partner_copy.py"
    _replace_once_or_verify(
        path,
        '    "💼 <b>Партнёрам</b>\\n\\n"\n'
        '    "Это практическое руководство по участию в партнёрской программе.\\n\\n"\n'
        '    "<b>Ваши ссылки:</b>\\n"\n',
        '    "🤝 <b>Партнёрская программа</b>\\n\\n"\n'
        '    "Приглашайте пользователей по своей ссылке и получайте вознаграждение с их покупок.\\n\\n"\n'
        '    "<b>Ваши ссылки</b>\\n"\n',
        context="Telegram partner screen",
    )
    _replace_once_or_verify(
        path,
        '    "Для канала рекомендуем ссылку на бота (надёжнее).\\n\\n"\n'
        '    "<b>1 уровень</b> — {level1_percent}% от всех покупок ваших рефералов.\\n"\n'
        '    "<b>2 уровень</b> — {level2_percent}% от покупок рефералов ваших рефералов.\\n\\n"\n'
        '    "<b>Как это работает:</b>\\n"\n'
        '    "• Пользователь переходит по вашей ссылке\\n"\n'
        '    "• Регистрируется и закрепляется за вами навсегда\\n"\n'
        '    "• После каждой оплаты реферала вам начисляется денежное вознаграждение\\n\\n"\n'
        '    "<b>2 уровень:</b>\\n"\n'
        '    "Если ваш реферал привёл ещё людей, за их покупки вам также начисляется "\n'
        '    "вознаграждение — {level2_percent}%.\\n\\n"\n',
        '    "Для публикации в канале удобнее использовать ссылку на бота.\\n\\n"\n'
        '    "<b>Ваше вознаграждение</b>\\n"\n'
        '    "• 1 уровень — {level1_percent}% от покупок приглашённых вами пользователей\\n"\n'
        '    "• 2 уровень — {level2_percent}% от покупок пользователей, которых пригласили ваши рефералы\\n\\n"\n'
        '    "Пользователь закрепляется за вами после регистрации по ссылке, а начисления появляются после подтверждённой оплаты.\\n\\n"\n',
        context="Telegram partner explanation",
    )


def _patch_payments() -> None:
    _replace_once_or_verify(
        "bot/handlers/payments.py",
        '        "Выберите пакет бананов ниже.\\n\\n"\n'
        '        "<b>Бонусы по промокоду:</b>\\n"\n'
        '        f"{_build_promo_rules_text()}\\n\\n"\n'
        '        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>"\n',
        '        "Выберите пакет лапок. Итоговую сумму увидите до перехода к оплате.\\n\\n"\n'
        '        "<b>Бонусы по промокоду</b>\\n"\n'
        '        f"{_build_promo_rules_text()}\\n\\n"\n'
        '        "<i>Большие пакеты дают более выгодную стоимость одной лапки.</i>"\n',
        context="Telegram top-up screen",
    )


def _patch_miniapp_backend_messages() -> None:
    path = "bot/miniapp.py"
    replacements = (
        (
            '        "Выберите, что хотите получить. Можно использовать готовый сценарий "\n'
            '        "или открыть пошаговый режим."\n',
            '        "Выберите результат — дальше останутся только подходящие настройки и шаги."\n',
            "Telegram Mini App create callback screen",
        ),
        (
            '        "Здесь находятся баланс, история, помощь, поддержка и партнёрская программа."\n',
            '        "Здесь собраны баланс, история, поддержка и партнёрская программа."\n',
            "Telegram Mini App more callback screen",
        ),
        (
            '        "Оплата выполняется через CryptoBot.\\n"\n'
            '        "Выберите пакет бананов ниже.\\n\\n"\n'
            '        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>"\n',
            '        "Выберите пакет лапок и способ оплаты. Итоговую сумму увидите до подтверждения.\\n\\n"\n'
            '        "<i>Большие пакеты дают более выгодную стоимость одной лапки.</i>"\n',
            "Telegram Mini App top-up callback screen",
        ),
    )
    for old, new, context in replacements:
        _replace_once_or_verify(path, old, new, context=context)


def _patch_trends() -> None:
    _replace_once_or_verify(
        "bot/handlers/trends_compat.py",
        '            "Здесь скоро появятся готовые шаблоны от команды NEUROMIX. "\n',
        '            "Здесь скоро появятся готовые шаблоны HappyFox. "\n',
        context="Telegram trends empty screen",
    )


def _patch_help() -> None:
    path = "bot/utils/help_texts.py"
    _replace_once_or_verify(
        path,
        '🍌 <b>Добро пожаловать!</b>\n\nДоступные сценарии: фото, видео, Motion Control, анализ фото и работа с референсами.\n',
        '🦊 <b>HappyFox</b>\n\nВыберите результат — фото, видео, движение или промпт. Бот проведёт по нужным шагам и не покажет лишние настройки.\n',
        context="Telegram help welcome",
    )
    _replace_once_or_verify(
        path,
        '⚠️ <b>注意:</b> Большее разрешение = больше кредитов',
        '💡 Чем выше разрешение, тем больше лапок потребуется на генерацию.',
        context="Telegram resolution help",
    )


def apply_happyfox_telegram_screen_copy() -> None:
    _patch_common()
    _patch_partner()
    _patch_payments()
    _patch_miniapp_backend_messages()
    _patch_trends()
    _patch_help()


if __name__ == "__main__":
    apply_happyfox_telegram_screen_copy()
