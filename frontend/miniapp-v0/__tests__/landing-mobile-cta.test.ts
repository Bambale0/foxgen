import fs from 'node:fs'
import path from 'node:path'

describe('HappyFox mobile landing CTA', () => {
  it('loads a landing-only mobile CTA stylesheet', () => {
    const layout = fs.readFileSync(
      path.join(process.cwd(), 'app/landing/layout.tsx'),
      'utf8',
    )

    expect(layout).toContain("import './mobile-cta.css'")
  })

  it('makes the web CTA large, full-width and visually labels it Попробовать on phones', () => {
    const css = fs.readFileSync(
      path.join(process.cwd(), 'app/landing/mobile-cta.css'),
      'utf8',
    )

    expect(css).toContain('@media (max-width: 639px)')
    expect(css).toContain("header > div [data-referral-link='bot']")
    expect(css).toContain('display: none')
    expect(css).toContain("header > div [data-referral-link='web']")
    expect(css).toContain('min-height: 76px')
    expect(css).toContain('width: 100%')
    expect(css).toContain("content: 'Попробовать'")
    expect(css).toContain('font-size: 22px')
  })
})
