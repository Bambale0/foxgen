import { describe, expect, it } from 'vitest'
import { parseDeepLinkIntent, remixInputSeed, tabForDeepLink } from '@/lib/deep-links'
import type { ModelDefinition, RemixSource } from '@/lib/types'

describe('Telegram deep-link contract', () => {
  it.each([
    ['model_seedream-5-pro', 'model', 'seedream-5-pro', 'create'],
    ['generation_4e67c04f-cf93-44f6-8510-633432cc58a1', 'generation', '4e67c04f-cf93-44f6-8510-633432cc58a1', 'works'],
    ['profile_alena', 'profile', 'alena', 'profile'],
    ['post_25ed4b23-72e3-4826-a692-b6177851f06a', 'post', '25ed4b23-72e3-4826-a692-b6177851f06a', 'services'],
    ['remix_25ed4b23-72e3-4826-a692-b6177851f06a', 'remix', '25ed4b23-72e3-4826-a692-b6177851f06a', 'create'],
  ] as const)('parses %s', (raw, kind, value, tab) => {
    const intent = parseDeepLinkIntent(raw)
    expect(intent).toEqual({ kind, value })
    expect(intent && tabForDeepLink(intent)).toBe(tab)
  })

  it('rejects empty and malformed payloads', () => {
    expect(parseDeepLinkIntent('')).toBeNull()
    expect(parseDeepLinkIntent('model_')).toBeNull()
    expect(parseDeepLinkIntent('unknown_value')).toBeNull()
  })

  it('prefills remix prompt and the first compatible media field', () => {
    const model: ModelDefinition = {
      slug: 'nano-banana-2',
      title: 'Nano Banana 2',
      media_kind: 'image',
      input_schema: {
        type: 'object',
        properties: {
          prompt: { type: 'string' },
          image_urls: { type: 'array', items: { type: 'string' } },
        },
      },
    }
    const source: RemixSource = {
      publication_id: 'pub-1',
      generation_id: 'gen-1',
      author_slug: 'alena',
      model_slug: 'nano-banana-2',
      media_kind: 'image',
      prompt: 'fox in neon city',
      media: [{ url: 'https://storage.test/reference.webp', content_type: 'image/webp' }],
    }

    expect(remixInputSeed(model, source)).toEqual({
      prompt: 'fox in neon city',
      image_urls: ['https://storage.test/reference.webp'],
    })
  })
})
