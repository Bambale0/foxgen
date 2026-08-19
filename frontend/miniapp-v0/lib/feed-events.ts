import type { FeedItem } from './types'

const STORAGE_KEY = 'banano:pending-publication'
const MAX_AGE_MS = 2 * 60 * 1000

type PendingPublication = {
  item: FeedItem
  savedAt: number
}

declare global {
  interface Window {
    __BANANO_PENDING_PUBLICATION__?: PendingPublication | null
  }
}

// TaskDetailPanel and ProfileTab are loaded as separate dynamic chunks. A
// module-scoped variable is therefore not a reliable cross-chunk transport in
// every Telegram WebView. Keep the authoritative same-session value on window,
// which is shared by all chunks, and retain module/sessionStorage fallbacks.
let latestPublication: PendingPublication | null = null

function isFresh(value: PendingPublication | null | undefined): value is PendingPublication {
  return Boolean(
    value?.item?.id &&
      Number.isFinite(value.savedAt) &&
      Date.now() - value.savedAt <= MAX_AGE_MS
  )
}

function isVisibleOnSurface(item: FeedItem, scope: 'feed' | 'profile'): boolean {
  if (scope === 'feed') return item.publication_scope === 'feed'
  return item.publication_scope !== 'private' && item.is_profile_visible !== false
}

function rememberPublication(value: PendingPublication): void {
  latestPublication = value
  if (typeof window === 'undefined') return
  window.__BANANO_PENDING_PUBLICATION__ = value
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // window remains the cross-chunk source of truth in constrained WebViews.
  }
}

export function notifyFeedChanged(item?: FeedItem): void {
  if (typeof window === 'undefined') return
  if (item) rememberPublication({ item, savedAt: Date.now() })
  window.dispatchEvent(new CustomEvent<FeedItem | undefined>('banano:feed-changed', { detail: item }))
}

function pendingPublication(): FeedItem | null {
  if (typeof window !== 'undefined' && isFresh(window.__BANANO_PENDING_PUBLICATION__)) {
    latestPublication = window.__BANANO_PENDING_PUBLICATION__
    return window.__BANANO_PENDING_PUBLICATION__.item
  }
  if (isFresh(latestPublication)) return latestPublication.item

  latestPublication = null
  if (typeof window === 'undefined') return null
  window.__BANANO_PENDING_PUBLICATION__ = null

  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as PendingPublication
    if (!isFresh(value)) {
      window.sessionStorage.removeItem(STORAGE_KEY)
      return null
    }
    rememberPublication(value)
    return value.item
  } catch {
    return null
  }
}

export function mergePublication(
  items: FeedItem[],
  item: FeedItem | null | undefined,
  scope: 'feed' | 'profile'
): FeedItem[] {
  if (!item?.id || !isVisibleOnSurface(item, scope)) return items
  return [item, ...items.filter((current) => current.id !== item.id)]
}

export function mergePendingPublication(items: FeedItem[], scope: 'feed' | 'profile'): FeedItem[] {
  return mergePublication(items, pendingPublication(), scope)
}
