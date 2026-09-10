from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace(path: str, old: str, new: str, *, required: bool = True, count: int = -1) -> None:
    text = read(path)
    if old not in text:
        if required:
            raise RuntimeError(f"Expected UX anchor not found in {path}: {old!r}")
        return
    text = text.replace(old, new, count)
    write(path, text)


def normalize_frontend_tokens() -> None:
    components = ROOT / "frontend/miniapp-v0/components"
    currency_words = (
        ("бананов", "лапок"),
        ("Бананов", "Лапок"),
        ("бананы", "лапки"),
        ("Бананы", "Лапки"),
        ("банана", "лапки"),
        ("Банана", "Лапки"),
    )
    for path in components.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        patched = text.replace("text-[9px]", "text-[11px]").replace("text-[10px]", "text-[11px]")
        patched = patched.replace("🍌", "🐾")
        for old, new in currency_words:
            patched = patched.replace(old, new)
        if patched != text:
            path.write_text(patched, encoding="utf-8")


def fix_product_brand_normalizer_contract() -> None:
    path = "bot/handlers/common.py"
    text = read(path)
    if "from bot.product import product\n" not in text:
        anchor = "from bot.config import config\n"
        if anchor not in text:
            raise RuntimeError("common.py product import anchor missing")
        text = text.replace(anchor, anchor + "from bot.product import product\n", 1)
    literal = '        "🏠 <b>HappyFox</b>\\n"\n'
    dynamic = '        f"🏠 <b>{html.escape(product.brand_name)}</b>\\n"\n'
    if literal in text:
        text = text.replace(literal, dynamic, 1)
    elif dynamic not in text:
        raise RuntimeError("HappyFox dynamic main-menu brand anchor missing")
    write(path, text)

    test_path = "tests/test_happyfox_public_screen_copy.py"
    test = read(test_path)
    test = test.replace(
        "    assert '🏠 <b>HappyFox</b>' in telegram\n",
        "    assert 'html.escape(product.brand_name)' in telegram\n",
    )
    write(test_path, test)


def fix_global_accessibility() -> None:
    path = "frontend/miniapp-v0/app/globals.css"
    text = read(path)
    block = """

/* Keyboard and motion accessibility: keep navigation visible and respect OS preferences. */
:is(button, a, input, textarea, select):focus-visible {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
"""
    if "@media (prefers-reduced-motion: reduce)" not in text:
        text += block
    write(path, text)


def fix_primary_navigation() -> None:
    path = "frontend/miniapp-v0/components/tab-nav.tsx"
    text = read(path)
    old_import = """import {
  Flame,
  Grid3X3,
  Image,
  Images,
  LayoutDashboard,
  Sparkles,
  UserRound,
  Video,
} from 'lucide-react'
"""
    new_import = """import {
  Flame,
  Grid3X3,
  Images,
  LayoutDashboard,
  UserRound,
} from 'lucide-react'
"""
    if old_import in text:
        text = text.replace(old_import, new_import, 1)

    old_tabs = """const tabs = [
  { id: 0, label: 'Студия', icon: LayoutDashboard },
  { id: 1, label: 'Фото', icon: Image },
  { id: 2, label: 'Видео', icon: Video },
  { id: 3, label: 'Motion', icon: Sparkles },
  { id: 5, label: 'Тренды', icon: Flame },
  { id: 4, label: 'Лента', icon: Images },
  { id: 6, label: 'Сервисы', icon: Grid3X3 },
  { id: 7, label: 'Профиль', icon: UserRound },
]
"""
    new_tabs = """const tabs = [
  { id: 0, label: 'Главная', icon: LayoutDashboard, activeIds: [0, 1, 2, 3] },
  { id: 5, label: 'Тренды', icon: Flame, activeIds: [5] },
  { id: 4, label: 'Лента', icon: Images, activeIds: [4] },
  { id: 6, label: 'Сервисы', icon: Grid3X3, activeIds: [6] },
  { id: 7, label: 'Профиль', icon: UserRound, activeIds: [7] },
]
"""
    if old_tabs not in text:
        raise RuntimeError("tab navigation inventory changed")
    text = text.replace(old_tabs, new_tabs, 1)
    text = text.replace("  return (\n    <nav className=", "  return (\n    <nav aria-label=\"Основная навигация\" className=", 1)
    text = text.replace("const isActive = activeTab === tab.id", "const isActive = tab.activeIds.includes(activeTab)", 1)
    text = text.replace(
        '<div className="overflow-x-auto px-1.5 py-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">',
        '<div className="overflow-x-auto px-1.5 py-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">',
        1,
    )
    text = text.replace(
        "                    onClick={() => setActiveTab(tab.id)}\n                    className={cn(",
        "                    onClick={() => setActiveTab(tab.id)}\n                    aria-current={isActive ? 'page' : undefined}\n                    className={cn(",
        1,
    )
    text = text.replace("'relative flex min-w-[66px]", "'relative flex min-w-[66px] flex-1", 1)
    text = text.replace("<div className=\"flex min-w-max items-stretch gap-1\">", "<div className=\"flex min-w-full items-stretch gap-1\">", 1)
    write(path, text)


def fix_header() -> None:
    path = "frontend/miniapp-v0/components/hero-header.tsx"
    text = read(path)
    text = text.replace("'inline-flex h-9 w-9 items-center", "'inline-flex h-11 w-11 items-center", 1)
    old = """              onClick={openBalance}
              className="inline-flex items-center gap-2 rounded-full border border-gold/35 bg-gold/[0.09] px-3 py-2 transition-all hover:bg-gold/[0.14] active:scale-[0.98]"
"""
    new = """              onClick={openBalance}
              aria-label={`Баланс: ${user.credits} лапок. Пополнить баланс`}
              className="inline-flex min-h-11 items-center gap-2 rounded-full border border-gold/35 bg-gold/[0.09] px-3 py-2 transition-all hover:bg-gold/[0.14] active:scale-[0.98]"
"""
    if old not in text:
        raise RuntimeError("balance header button anchor changed")
    text = text.replace(old, new, 1)
    write(path, text)


def fix_studio_hierarchy() -> None:
    path = "frontend/miniapp-v0/components/tabs/studio-tab.tsx"
    text = read(path)
    text = text.replace(
        "import { ArrowRight, Gauge, Sparkles, WandSparkles } from 'lucide-react'",
        "import { ArrowRight, Sparkles } from 'lucide-react'",
        1,
    )
    marketing = """
          <div className="mt-5 grid max-w-[430px] grid-cols-3 gap-2">
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-2 py-2.5">
              <WandSparkles className="h-4 w-4 text-gold" />
              <div className="mt-2 text-[11px] font-semibold leading-tight text-foreground">Топовые модели</div>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-2 py-2.5">
              <Gauge className="h-4 w-4 text-gold" />
              <div className="mt-2 text-[11px] font-semibold leading-tight text-foreground">Быстрый старт</div>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-2 py-2.5">
              <Sparkles className="h-4 w-4 text-gold" />
              <div className="mt-2 text-[11px] font-semibold leading-tight text-foreground">Понятный путь</div>
            </div>
          </div>
"""
    if marketing not in text:
        raise RuntimeError("studio marketing cards anchor changed")
    text = text.replace(marketing, "", 1)
    text = text.replace("            Начать творить\n", "            Создать фото\n", 1)
    write(path, text)


def remove_fake_step_progress(path: str) -> None:
    text = read(path)
    block = """        <div className="shrink-0 pt-1 text-right">
          <div className="text-[11px] font-bold uppercase tracking-[0.13em] text-muted-foreground">Шаг 1 из 3</div>
          <div className="mt-2 flex justify-end gap-1">
            <span className="h-1 w-5 rounded-full bg-gold" />
            <span className="h-1 w-3 rounded-full bg-white/10" />
            <span className="h-1 w-3 rounded-full bg-white/10" />
          </div>
        </div>
"""
    if block not in text:
        raise RuntimeError(f"fake progress block changed in {path}")
    write(path, text.replace(block, "", 1))


def fix_selectors() -> None:
    for path in (
        "frontend/miniapp-v0/components/forms/ratio-select.tsx",
        "frontend/miniapp-v0/components/forms/quality-select.tsx",
        "frontend/miniapp-v0/components/forms/duration-select.tsx",
    ):
        text = read(path)
        text = text.replace("          <button\n            key=", "          <button\n            type=\"button\"\n            key=", 1)
        text = text.replace("            onClick={() => onChange(", "            aria-pressed={isSelected}\n            onClick={() => onChange(", 1)
        text = text.replace("px-2 py-2 rounded-lg", "min-h-11 px-2 py-2 rounded-lg", 1)
        text = text.replace("px-3 py-2 rounded-lg", "min-h-11 px-3 py-2 rounded-lg", 1)
        write(path, text)

    path = "frontend/miniapp-v0/components/forms/ratio-select.tsx"
    replace(path, '<div className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-4">', '<div role="group" aria-label="Формат" className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-4">')

    path = "frontend/miniapp-v0/components/forms/quality-select.tsx"
    text = read(path)
    text = text.replace("  high: 'High',", "  high: 'Высокое',")
    text = text.replace("  ultra: 'Ultra',", "  ultra: 'Максимум',")
    text = text.replace('<div className="flex gap-2">', '<div role="group" aria-label="Качество" className="flex gap-2">', 1)
    write(path, text)

    path = "frontend/miniapp-v0/components/forms/duration-select.tsx"
    text = read(path)
    text = text.replace("import { Banana } from 'lucide-react'", "import { PawPrint } from 'lucide-react'", 1)
    text = text.replace("<Banana className=", "<PawPrint className=", 1)
    text = text.replace('<div className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-4">', '<div role="group" aria-label="Длительность" className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-4">', 1)
    write(path, text)

    path = "frontend/miniapp-v0/components/forms/scenario-select.tsx"
    text = read(path)
    text = text.replace('<div className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-6">', '<div role="group" aria-label="Сценарий" className="grid min-w-0 grid-cols-3 gap-2 sm:grid-cols-6">', 1)
    text = text.replace("          <button\n            key={scenario}", "          <button\n            type=\"button\"\n            key={scenario}", 1)
    text = text.replace("            onClick={() => isAvailable && onChange(scenario)}", "            aria-pressed={isSelected}\n            onClick={() => isAvailable && onChange(scenario)}", 1)
    text = text.replace("label: 'Avatar',", "label: 'Аватар',")
    write(path, text)

    path = "frontend/miniapp-v0/components/forms/model-select.tsx"
    text = read(path)
    text = text.replace(
        "        type=\"button\"\n        onClick={() => setIsOpen(!isOpen)}",
        "        type=\"button\"\n        aria-label=\"Выбрать модель\"\n        aria-haspopup=\"listbox\"\n        aria-expanded={isOpen}\n        onClick={() => setIsOpen(!isOpen)}",
        1,
    )
    text = text.replace(
        "              className={cn(\n                'glass-strong absolute",
        "              role=\"listbox\"\n              aria-label=\"Доступные модели\"\n              className={cn(\n                'glass-strong absolute",
        1,
    )
    text = text.replace(
        "                    type=\"button\"\n                    onClick={() => {",
        "                    type=\"button\"\n                    role=\"option\"\n                    aria-selected={model.id === value}\n                    onClick={() => {",
        1,
    )
    write(path, text)


def fix_image_form() -> None:
    path = "frontend/miniapp-v0/components/forms/image-generator-form.tsx"
    text = read(path)
    text = text.replace(" Banana,", " PawPrint,", 1)
    text = text.replace("<Banana className=", "<PawPrint className=", 1)
    text = text.replace(
        "                  onClick={() => setSelectedCount(count)}\n                  className={cn(",
        "                  onClick={() => setSelectedCount(count)}\n                  aria-pressed={selectedCount === count}\n                  className={cn(",
        1,
    )
    text = text.replace(
        '"rounded-lg border px-3 py-2 text-xs font-medium transition-all duration-200",',
        '"min-h-11 rounded-lg border px-3 py-2 text-xs font-medium transition-all duration-200",',
        1,
    )
    text = text.replace(
        "                      onClick={() => toggleChange(chip.id, chip.insert)}\n                      className={cn(",
        "                      onClick={() => toggleChange(chip.id, chip.insert)}\n                      aria-pressed={isActive}\n                      className={cn(",
        1,
    )
    text = text.replace(
        "'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-200',",
        "'inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3 py-2 text-xs font-medium transition-all duration-200',",
        1,
    )
    text = text.replace("'Edit / reference'", "'Редактирование по фото'")
    text = text.replace("'Text / image mix'", "'По описанию или фото'")
    text = text.replace("'Пустой prompt не отправится'", "'Добавьте описание для запуска'")
    text = text.replace("Недостаточно лапок. Пополните баланс.", "Недостаточно лапок — пополните баланс и повторите запуск.")
    write(path, text)


def fix_video_form_currency() -> None:
    path = "frontend/miniapp-v0/components/forms/video-generator-form.tsx"
    text = read(path)
    text = text.replace("  Banana,\n", "  PawPrint,\n", 1)
    text = text.replace("<Banana className=", "<PawPrint className=")
    text = text.replace("prompt", "prompt")
    write(path, text)


def fix_service_copy() -> None:
    path = "frontend/miniapp-v0/components/service-grid.tsx"
    text = read(path)
    text = text.replace("title: 'Avatar',", "title: 'Говорящий аватар',", 1)
    write(path, text)


def fix_upload_area() -> None:
    path = "frontend/miniapp-v0/components/forms/upload-area.tsx"
    text = read(path)
    old = """                className={cn(
                  'w-6 h-6 rounded flex items-center justify-center',
                  'text-muted-foreground hover:text-foreground hover:bg-secondary',
                  'transition-colors'
                )}
"""
    new = """                aria-label={`Удалить ${file.name}`}
                className={cn(
                  'h-11 w-11 rounded flex items-center justify-center',
                  'text-muted-foreground hover:text-foreground hover:bg-secondary',
                  'transition-colors'
                )}
"""
    if old not in text:
        raise RuntimeError("upload remove button anchor changed")
    text = text.replace(old, new, 1)
    write(path, text)


def fix_result_card() -> None:
    path = "frontend/miniapp-v0/components/result-card.tsx"
    text = read(path)
    text = text.replace(
        "        <button\n          onClick={onClose}\n          className=\"absolute right-3 top-3 flex h-8 w-8",
        "        <button\n          type=\"button\"\n          onClick={onClose}\n          aria-label=\"Закрыть результат\"\n          className=\"absolute right-3 top-3 flex h-11 w-11",
        1,
    )
    text = text.replace(
        "          <button\n            onClick={handleCopy}\n            className=\"text-muted-foreground transition-colors hover:text-foreground\"",
        "          <button\n            type=\"button\"\n            onClick={handleCopy}\n            aria-label=\"Скопировать номер задачи\"\n            className=\"flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground\"",
        1,
    )
    text = text.replace("'Проверьте prompt, файлы и попробуйте снова'", "'Проверьте описание и файлы, затем попробуйте снова'")
    text = text.replace('alt="Generated result"', 'alt="Готовый результат"')
    text = text.replace('alt="Generated result full"', 'alt="Готовый результат в полном размере"')
    text = text.replace(
        'className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/10 text-white"',
        'aria-label="Закрыть полный просмотр"\n                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/10 text-white"',
        1,
    )
    write(path, text)


def fix_task_detail() -> None:
    path = "frontend/miniapp-v0/components/task-detail-panel.tsx"
    text = read(path)
    text = text.replace("  Banana, ExternalLink", "  PawPrint, ExternalLink", 1)
    text = text.replace("icon={Banana}", "icon={PawPrint}", 1)
    text = text.replace(
        "              <button\n                onClick={closeTaskDetail}\n                className=\"w-8 h-8",
        "              <button\n                type=\"button\"\n                onClick={closeTaskDetail}\n                aria-label=\"Закрыть детали задачи\"\n                className=\"w-11 h-11",
        1,
    )
    text = text.replace(
        "                <button\n                  onClick={handleCopyTaskId}\n                  className=\"text-muted-foreground hover:text-foreground transition-colors\"",
        "                <button\n                  type=\"button\"\n                  onClick={handleCopyTaskId}\n                  aria-label=\"Скопировать номер задачи\"\n                  className=\"flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors\"",
        1,
    )
    text = text.replace('className="h-8 px-3"', 'className="min-h-11 px-3"', 1)
    text = text.replace("'rounded-lg border px-3 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45',", "'min-h-11 rounded-lg border px-3 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45',", 1)
    text = text.replace("'rounded-lg border px-3 py-2 text-xs font-medium transition-colors',", "'min-h-11 rounded-lg border px-3 py-2 text-xs font-medium transition-colors',", 1)
    text = text.replace("'flex h-10 items-center", "'flex h-11 items-center")
    text = text.replace("                          Prompt\n", "                          Промпт\n", 1)
    text = text.replace("                          Рефы {referenceCount", "                          Исходники {referenceCount", 1)
    text = text.replace("                          Blur\n", "                          Размытие\n", 1)
    text = text.replace("'Не удалось сохранить prompt'", "'Не удалось сохранить промпт'")
    write(path, text)


def fix_profile_and_feed_targets() -> None:
    for path in (
        "frontend/miniapp-v0/components/tabs/profile-tab.tsx",
        "frontend/miniapp-v0/components/tabs/feed-tab.tsx",
    ):
        text = read(path)
        text = text.replace("className=\"flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-muted-foreground\"", "className=\"flex h-11 w-11 items-center justify-center rounded-full bg-secondary text-muted-foreground\"")
        write(path, text)

    path = "frontend/miniapp-v0/components/tabs/profile-tab.tsx"
    text = read(path)
    text = text.replace('className="h-10 min-w-0 rounded-lg border', 'aria-label="Ссылка на канал"\n                className="h-11 min-w-0 rounded-lg border', 1)
    text = text.replace('className="h-10 w-10 rounded-lg"', 'className="h-11 w-11 rounded-lg"')
    text = text.replace('className="h-10 rounded-lg"', 'className="min-h-11 rounded-lg"')
    text = text.replace('className="h-10 min-w-0 rounded-lg px-3"', 'className="min-h-11 min-w-0 rounded-lg px-3"')
    write(path, text)


def add_ux_contract() -> None:
    path = ROOT / "frontend/miniapp-v0/__tests__/ux-ui-contract.test.ts"
    content = r'''import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(__dirname, '..')
const read = (relative: string) => fs.readFileSync(path.join(root, relative), 'utf8')

function componentSources() {
  const dir = path.join(root, 'components')
  const files: string[] = []
  const walk = (current: string) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.name.endsWith('.tsx')) files.push(fs.readFileSync(full, 'utf8'))
    }
  }
  walk(dir)
  return files.join('\n')
}

describe('HappyFox UX/UI guardrails', () => {
  test('keeps primary navigation to five destinations with active semantics', () => {
    const nav = read('components/tab-nav.tsx')
    expect(nav).toContain("label: 'Главная'")
    expect(nav).toContain("aria-current={isActive ? 'page' : undefined}")
    expect((nav.match(/label:/g) || []).length).toBe(5)
  })

  test('does not ship tiny 9–10px component copy or legacy banana currency', () => {
    const source = componentSources()
    expect(source).not.toContain('text-[9px]')
    expect(source).not.toContain('text-[10px]')
    expect(source).not.toContain('🍌')
    expect(source).not.toContain('Недостаточно бананов')
  })

  test('honors reduced motion and visible keyboard focus', () => {
    const css = read('app/globals.css')
    expect(css).toContain('@media (prefers-reduced-motion: reduce)')
    expect(css).toContain(':focus-visible')
  })

  test('critical icon-only actions have accessible names and 44px targets', () => {
    const header = read('components/hero-header.tsx')
    const upload = read('components/forms/upload-area.tsx')
    const detail = read('components/task-detail-panel.tsx')
    const result = read('components/result-card.tsx')

    expect(header).toContain('h-11 w-11')
    expect(upload).toContain('aria-label={`Удалить ${file.name}`}')
    expect(upload).toContain("'h-11 w-11 rounded flex items-center justify-center'")
    expect(detail).toContain('aria-label="Закрыть детали задачи"')
    expect(detail).toContain('aria-label="Скопировать номер задачи"')
    expect(result).toContain('aria-label="Закрыть результат"')
    expect(result).toContain('aria-label="Закрыть полный просмотр"')
  })
})
'''
    path.write_text(content, encoding="utf-8")


def main() -> None:
    normalize_frontend_tokens()
    fix_product_brand_normalizer_contract()
    fix_global_accessibility()
    fix_primary_navigation()
    fix_header()
    fix_studio_hierarchy()
    remove_fake_step_progress("frontend/miniapp-v0/components/tabs/photo-tab.tsx")
    remove_fake_step_progress("frontend/miniapp-v0/components/tabs/video-tab.tsx")
    fix_selectors()
    fix_image_form()
    fix_video_form_currency()
    fix_service_copy()
    fix_upload_area()
    fix_result_card()
    fix_task_detail()
    fix_profile_and_feed_targets()
    add_ux_contract()


if __name__ == "__main__":
    main()
