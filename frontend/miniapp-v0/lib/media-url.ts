function miniAppApiBasePath(): string {
  if (typeof window === 'undefined') return '/mini-app/api'
  const pathname = window.location.pathname || '/mini-app/'
  const marker = '/mini-app'
  const markerIndex = pathname.indexOf(marker)
  const prefix = markerIndex >= 0 ? pathname.slice(0, markerIndex) : ''
  return `${prefix}/mini-app/api`
}

export function normalizeMiniAppMediaUrl(value?: string | null): string {
  const raw = String(value || '').trim()
  if (!raw || typeof window === 'undefined') return raw
  if (raw.startsWith('blob:') || raw.startsWith('data:')) return raw

  try {
    const url = new URL(raw, window.location.origin)
    if (
      url.pathname.startsWith('/uploads/')
      && url.origin === window.location.origin
    ) {
      return `${window.location.origin}${url.pathname}${url.search}${url.hash}`
    }
    return url.toString()
  } catch {
    return raw
  }
}

export function feedReferenceImageThumbnailUrl(feedId: number, index: number): string {
  const safeFeedId = Math.max(0, Math.trunc(Number(feedId) || 0))
  const safeIndex = Math.max(0, Math.trunc(Number(index) || 0))
  return `${miniAppApiBasePath()}/feed/reference-image/${safeFeedId}/${safeIndex}/thumbnail`
}

export function feedReferenceImageFullUrl(feedId: number, index: number): string {
  const safeFeedId = Math.max(0, Math.trunc(Number(feedId) || 0))
  const safeIndex = Math.max(0, Math.trunc(Number(index) || 0))
  return `${miniAppApiBasePath()}/feed/reference-image/${safeFeedId}/${safeIndex}/full`
}

export function mediaAspectRatio(value?: string | null, fallback = '16 / 9'): string {
  const match = String(value || '').match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/)
  if (!match) return fallback
  const width = Number(match[1])
  const height = Number(match[2])
  if (!width || !height) return fallback
  return `${width} / ${height}`
}

export function videoPreviewFrameUrl(value?: string | null): string {
  const normalized = normalizeMiniAppMediaUrl(value)
  if (!normalized || typeof window === 'undefined' || normalized.startsWith('blob:')) return normalized
  try {
    const url = new URL(normalized, window.location.origin)
    if (!url.hash && /\.(mp4|m4v|mov|webm)$/i.test(url.pathname)) {
      url.hash = 't=0.001'
    }
    return url.toString()
  } catch {
    return normalized
  }
}
