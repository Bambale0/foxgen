import fs from 'node:fs'
import path from 'node:path'

const read = (file: string) => fs.readFileSync(path.join(process.cwd(), file), 'utf8')

describe('Mini App media UX contracts', () => {
  it('preserves configured vertical ratio and iOS first-frame previews for trends', () => {
    const source = read('components/tabs/trends-tab.tsx')
    expect(source).toContain('mediaAspectRatio(trend.generation_settings?.ratio)')
    expect(source).toContain('videoPreviewFrameUrl(trend.preview_url)')
    expect(source).toContain('normalizeMiniAppMediaUrl(previewTrend.preview_url)')
  })

  it('uses lightweight thumbnails for public feed image references', () => {
    const source = read('components/tabs/feed-tab.tsx')
    expect(source).toContain('feedReferenceImageThumbnailUrl(previewItem.id, index)')
    expect(source).toContain('feedReferenceImageFullUrl(previewItem.id, index)')
    expect(source).toContain('loading="lazy"')
    expect(source).toContain('decoding="async"')
    expect(source).not.toContain('<img src={normalizeMiniAppMediaUrl(reference.url)}')
    expect(source).toContain('item.references_hidden || item.feed_references_visible === false')

    const media = read('lib/media-url.ts')
    expect(media).toContain('/thumbnail`')
    expect(media).toContain('/full`')
  })

  it('keeps upload normalization scoped to the current HappyFox origin', () => {
    const source = read('lib/media-url.ts')
    expect(source).toContain("url.pathname.startsWith('/uploads/')")
    expect(source).toContain('url.origin === window.location.origin')
    expect(source).not.toContain("'tanyapi.chillcreative.ru'")
    expect(source).not.toContain("'tanyapp.chillcreative.ru'")
    expect(source).not.toContain("'cdn.chillcreative.ru'")
    expect(source).toContain("url.hash = 't=0.001'")
  })

  it('does not rewrite trend reference URLs to the source product', () => {
    const source = read('lib/trend-api.ts')
    expect(source).toContain('reference_urls: referenceUrls')
    expect(source).toContain('reference_images: referenceUrls')
    expect(source).not.toContain('tanyapi.chillcreative.ru')
    expect(source).not.toContain('providerReferenceUrl')
  })
})
