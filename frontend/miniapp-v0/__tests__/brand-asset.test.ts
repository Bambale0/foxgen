import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { PRODUCT } from '@/lib/product'

describe('HappyFox brand asset', () => {
  it('uses the alpha-capable WebP in the Mini App', () => {
    const webp = readFileSync(resolve(process.cwd(), 'public/happyfox-brand.webp'))

    expect(webp.subarray(0, 4).toString('ascii')).toBe('RIFF')
    expect(webp.subarray(8, 12).toString('ascii')).toBe('WEBP')
    expect(webp.subarray(12, 16).toString('ascii')).toBe('VP8X')
    expect(webp[20] & 0x10).toBe(0x10)
    expect(PRODUCT.brandLogo).toBe('/mini-app/happyfox-brand.webp')
  })
})
