import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(__dirname, '..')
const repoRoot = path.resolve(root, '../..')
const read = (relative: string) => fs.readFileSync(path.join(root, relative), 'utf8')
const readRepo = (relative: string) => fs.readFileSync(path.join(repoRoot, relative), 'utf8')

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
    expect(nav).toContain('activeIds: [0, 1, 2, 3]')
    expect(nav).toContain("aria-current={isActive ? 'page' : undefined}")
    expect((nav.match(/label:/g) || []).length).toBe(5)
  })

  test('does not ship tiny 9–10px component copy or legacy banana currency', () => {
    const source = componentSources()
    expect(source).not.toContain('text-[9px]')
    expect(source).not.toContain('text-[10px]')
    expect(source).not.toContain('🍌')
    expect(source).not.toContain('<Banana className=')
    expect(source).not.toContain('Недостаточно бананов')
  })

  test('does not show fake progress or provider-facing language in core generation screens', () => {
    const photo = read('components/tabs/photo-tab.tsx')
    const video = read('components/tabs/video-tab.tsx')
    const detail = read('components/task-detail-panel.tsx')

    expect(photo).not.toContain('Шаг 1 из 3')
    expect(video).not.toContain('Шаг 1 из 3')
    expect(detail).not.toContain('>Prompt<')
    expect(detail).not.toContain('>Blur<')
  })

  test('honors reduced motion, keyboard focus and coarse-pointer targets', () => {
    const css = read('app/globals.css')
    expect(css).toContain('@media (prefers-reduced-motion: reduce)')
    expect(css).toContain(':focus-visible')
    expect(css).toContain('@media (pointer: coarse)')
    expect(css).toContain('min-width: 44px')
    expect(css).toContain('min-height: 44px')
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

  test('other-AI screen describes the actions its keyboard actually offers', () => {
    const common = readRepo('bot/handlers/common.py')
    const normalizer = readRepo('scripts/apply_happyfox_main_menu.py')

    expect(common).toContain('✨ <b>Другие AI-инструменты</b>')
    expect(common).toContain('создать видео, создать фото или улучшить готовое изображение')
    expect(normalizer).toContain('🎬 Видео')
    expect(normalizer).toContain('🖼 Фото')
    expect(normalizer).toContain('✨ Улучшение')
    expect(normalizer).toContain('Другие AI-инструменты')
  })
})
