from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_screen_copy_uses_happyfox_brand() -> None:
    telegram = _read("bot/handlers/common.py")
    trends = _read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")

    assert 'html.escape(product.brand_name)' in telegram
    assert '🏠 <b>NEUROMIX</b>' not in telegram
    assert 'Готовые фото- и видео-шаблоны от команды NEUROMIX.' not in trends
    assert 'Готовые идеи для фото и видео' in trends


def test_miniapp_descriptions_hide_provider_plumbing() -> None:
    video = _read("frontend/miniapp-v0/components/tabs/video-tab.tsx")
    services = _read("frontend/miniapp-v0/components/service-grid.tsx")

    assert 'Для image-to-video добавьте стартовый кадр.' not in video
    assert 'Задача отправлена в Kie.ai.' not in video
    assert 'polling fallback' not in video
    assert 'После запуска здесь появятся очередь, task id' not in video
    assert 'точный prompt для похожей генерации' not in services
    assert 'Если делаете видео из фото' in video


def test_max_descriptions_use_user_language() -> None:
    max_copy = _read("bot/max_product_channel.py")

    assert 'платёжный шлюз MAX' not in max_copy
    assert 'MAX-прайс' not in max_copy
    assert 'Task ID, если он появился' not in max_copy
    assert 'улучшить prompt' not in max_copy
    assert 'Если есть номер задачи — приложите его.' in max_copy


def test_support_and_partner_descriptions_are_actionable() -> None:
    workspace = _read("frontend/miniapp-v0/components/workspace-sheet.tsx")
    partner = _read("frontend/miniapp-v0/components/partner-approval-sheet.tsx")

    assert 'Расскажите, с чем нужна помощь.' in _read("frontend/miniapp-v0/components/tabs/services-tab.tsx")
    assert 'Если есть номер задачи — приложите его.' in workspace
    assert 'Отправьте заявку — после одобрения откроются партнёрская ссылка' in partner
