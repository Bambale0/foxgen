from pathlib import Path

COMMON = Path('bot/handlers/common.py')
MENU = Path('scripts/apply_happyfox_main_menu.py')
CSS = Path('frontend/miniapp-v0/app/globals.css')

common = COMMON.read_text(encoding='utf-8')
old_screen = '''    text = (
        "⋯ <b>Ещё</b>\\n"
        f"🍌 Баланс: <code>{user.credits}</code> бананов\\n\\n"
        "Баланс, история генераций, поддержка и другие полезные разделы."
    )
'''
new_screen = '''    text = (
        "✨ <b>Другие AI-инструменты</b>\\n"
        f"🐾 Баланс: <code>{user.credits}</code> лапок\\n\\n"
        "Выберите, что хотите сделать: создать видео, создать фото или улучшить готовое изображение."
    )
'''
if old_screen in common:
    common = common.replace(old_screen, new_screen, 1)
elif new_screen not in common:
    raise SystemExit('other-AI screen anchor changed')
COMMON.write_text(common, encoding='utf-8')

menu = MENU.read_text(encoding='utf-8')
old_block = '''    old_title = "⋯ <b>Ещё</b>"
    new_title = "✨ <b>Прочий AI</b>"
    if old_title in text:
        text = text.replace(old_title, new_title, 1)
    elif new_title not in text:
        raise RuntimeError("HappyFox other-AI title anchor was not found")

    old_body = "Здесь находятся баланс, история, помощь и поддержка."
    new_body = "Выберите дополнительный сценарий: видео, фото или улучшение."
    if old_body in text:
        text = text.replace(old_body, new_body, 1)
    elif new_body not in text:
        raise RuntimeError("HappyFox other-AI body anchor was not found")
'''
new_block = '''    new_title = "✨ <b>Другие AI-инструменты</b>"
    legacy_titles = ("⋯ <b>Ещё</b>", "✨ <b>Прочий AI</b>")
    if new_title not in text:
        for legacy_title in legacy_titles:
            if legacy_title in text:
                text = text.replace(legacy_title, new_title, 1)
                break
        else:
            raise RuntimeError("HappyFox other-AI title anchor was not found")

    new_body = "Выберите, что хотите сделать: создать видео, создать фото или улучшить готовое изображение."
    legacy_bodies = (
        "Здесь находятся баланс, история, помощь и поддержка.",
        "Выберите дополнительный сценарий: видео, фото или улучшение.",
        "Баланс, история генераций, поддержка и другие полезные разделы.",
    )
    if new_body not in text:
        for legacy_body in legacy_bodies:
            if legacy_body in text:
                text = text.replace(legacy_body, new_body, 1)
                break
        else:
            raise RuntimeError("HappyFox other-AI body anchor was not found")
'''
if old_block in menu:
    menu = menu.replace(old_block, new_block, 1)
elif new_block not in menu:
    raise SystemExit('other-AI normalizer block changed')
MENU.write_text(menu, encoding='utf-8')

css = CSS.read_text(encoding='utf-8')
touch_block = '''

/* Coarse pointers need a reliable hit area even when a visual control is compact. */
@media (pointer: coarse) {
  button:not([aria-hidden="true"]) {
    min-width: 44px;
    min-height: 44px;
  }
}
'''
if '@media (pointer: coarse)' not in css:
    css += touch_block
CSS.write_text(css, encoding='utf-8')
