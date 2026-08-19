'use client'

import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApp } from '@/lib/app-context'
import type { FeedComment, FeedItem, ScenarioType, UploadedFile } from '@/lib/types'
import { cn, isHttpUrl } from '@/lib/utils'
import {
  feedReferenceImageFullUrl,
  feedReferenceImageThumbnailUrl,
  normalizeMiniAppMediaUrl,
  videoPreviewFrameUrl,
} from '@/lib/media-url'
import { copyTextToClipboard } from '@/lib/clipboard'
import { mergePendingPublication } from '@/lib/feed-events'
import { Button } from '@/components/ui/button'
import {
  addFeedComment,
  fetchFeed,
  fetchFeedComments,
  likeFeedItem,
  removeFeedItem,
  setFeedItemBlurred,
  shareFeedItem,
} from '@/lib/api'
import {
  Eye,
  EyeOff,
  Heart,
  ImageOff,
  Loader2,
  MessageCircle,
  Play,
  Repeat2,
  Send,
  Share2,
  Trash2,
  UserRound,
  Video,
  X,
} from 'lucide-react'

const sources = [
  { id: 'recent', label: 'Новые' },
  { id: 'top_day', label: 'Топ дня' },
  { id: 'top', label: 'Лучшие' },
] as const
const FEED_PAGE_SIZE = 12
const PRIORITY_IMAGE_COUNT = 2

const videoScenarios = new Set<ScenarioType>(['text', 'imgtxt', 'video', 'avatar', 'audio', 'character'])

function feedReferenceToUploadedFile(url: string, index: number, type: 'image' | 'video' = 'image'): UploadedFile {
  return { id: `feed-ref-${index}-${url}`, name: `reference-${index + 1}`, url, type, size: 0 }
}

function normalizeVideoScenario(value?: string | null): ScenarioType {
  return videoScenarios.has(value as ScenarioType) ? (value as ScenarioType) : 'text'
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function feedMediaUrl(value?: string | null): string {
  return normalizeMiniAppMediaUrl(value)
}

function getPinAspectRatio(
  value?: string | null,
  genType: FeedItem['gen_type'] = 'image'
): CSSProperties['aspectRatio'] {
  const match = String(value || '').match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/)
  if (!match) return genType === 'video' ? '16 / 9' : '4 / 5'
  const width = Number(match[1])
  const height = Number(match[2])
  if (!width || !height) return genType === 'video' ? '16 / 9' : '4 / 5'
  return `${width} / ${height}`
}

function getPinHeightWeight(value?: string | null, genType: FeedItem['gen_type'] = 'image') {
  const match = String(value || '').match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/)
  if (!match) return genType === 'video' ? 0.56 : 1.25
  const width = Number(match[1])
  const height = Number(match[2])
  if (!width || !height) return genType === 'video' ? 0.56 : 1.25
  return height / width
}

function getPublicReferences(item: FeedItem | null) {
  if (!item || item.references_hidden || item.feed_references_visible === false) return []
  return [
    ...(item.reference_images || []).map((url) => ({ type: 'image' as const, url })),
    ...(item.reference_videos || []).map((url) => ({ type: 'video' as const, url })),
  ].filter((item) => Boolean(String(item.url || '').trim()))
}

function FeedImage({ src, fallbackSrc, alt, priority, onError, style, className }: {
  src: string
  fallbackSrc?: string
  alt: string
  priority?: boolean
  onError?: () => void
  style?: CSSProperties
  className?: string
}) {
  const [currentSrc, setCurrentSrc] = useState(src)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    setCurrentSrc(src)
    setLoaded(false)
  }, [src])

  const handleError = () => {
    if (fallbackSrc && fallbackSrc !== currentSrc) {
      setCurrentSrc(fallbackSrc)
      return
    }
    onError?.()
  }

  return (
    <div
      className={cn('relative overflow-hidden bg-secondary/50', className)}
      style={style}
    >
      {!loaded ? (
        <div className="absolute inset-0 animate-pulse bg-gradient-to-br from-secondary via-muted to-secondary/70" />
      ) : null}
      <img
        src={currentSrc}
        alt={alt}
        fetchPriority={priority ? 'high' : undefined}
        loading={priority ? 'eager' : 'lazy'}
        decoding="async"
        onLoad={() => setLoaded(true)}
        onError={handleError}
        className={cn(
          'relative z-10 h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]',
          loaded ? 'opacity-100' : 'opacity-0'
        )}
      />
    </div>
  )
}

function FeedVideoPreview({ src, aspectRatio, blurred, onError }: {
  src?: string | null
  aspectRatio?: string | null
  blurred?: boolean
  onError?: () => void
}) {
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    setLoaded(false)
  }, [src])

  return (
    <div
      style={{ aspectRatio: getPinAspectRatio(aspectRatio, 'video') }}
      className={cn(
        'relative w-full overflow-hidden bg-secondary/70 transition-transform duration-500 group-hover:scale-[1.03]',
        blurred && 'scale-[1.04] blur-xl'
      )}
    >
      {src ? (
        <>
          {!loaded ? (
            <div className="absolute inset-0 animate-pulse bg-gradient-to-br from-secondary via-muted to-secondary/70" />
          ) : null}
          <video
            src={videoPreviewFrameUrl(src)}
            muted
            playsInline
            preload="metadata"
            onLoadedData={() => setLoaded(true)}
            onLoadedMetadata={() => setLoaded(true)}
            onError={onError}
            className={cn(
              'relative z-10 h-full w-full object-cover transition-opacity duration-500',
              loaded ? 'opacity-100' : 'opacity-0'
            )}
          />
        </>
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-secondary/70 text-muted-foreground">
          <Video className="h-8 w-8" />
        </div>
      )}
    </div>
  )
}

export function FeedTab() {
  const {
    state,
    feedDeepLink,
    consumeFeedDeepLink,
    setActiveTab,
    setPromptPreset,
    setVideoPromptPreset,
    openProfile,
  } = useApp()
  const [source, setSource] = useState<(typeof sources)[number]['id']>('recent')
  const [model, setModel] = useState('banana_pro')
  const [availableModels, setAvailableModels] = useState<Array<{ id: string; label: string }>>([])
  const [items, setItems] = useState<FeedItem[]>([])
  const [brokenMediaIds, setBrokenMediaIds] = useState<Set<number>>(() => new Set())
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewItem, setPreviewItem] = useState<FeedItem | null>(null)
  const [referencePreview, setReferencePreview] = useState<{ type: 'image' | 'video'; url: string } | null>(null)
  const [revealedPreviewIds, setRevealedPreviewIds] = useState<Set<number>>(() => new Set())
  const [commentsItem, setCommentsItem] = useState<FeedItem | null>(null)
  const [comments, setComments] = useState<FeedComment[]>([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentText, setCommentText] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)

  const isLive = state.mode === 'live'
  const modelTabs = useMemo(() => {
    const byId = new Map<string, { id: string; label: string }>()
    for (const item of availableModels) {
      const id = String(item.id || '').trim()
      if (!id || byId.has(id)) continue
      byId.set(id, {
        id,
        label: String(item.label || id).replace('🔥 НОВИНКА', '').trim(),
      })
    }
    const banana = byId.get('banana_pro') || { id: 'banana_pro', label: 'Nano Banana Pro' }
    return [banana, ...Array.from(byId.values()).filter((item) => item.id !== 'banana_pro')]
  }, [availableModels])
  const selectedModelLabel = modelTabs.find((item) => item.id === model)?.label || model
  const visibleItems = useMemo(
    () => items,
    [items]
  )
  const priorityImageIds = useMemo(
    () => new Set(
      visibleItems
        .filter((item) => item.gen_type === 'image')
        .slice(0, PRIORITY_IMAGE_COUNT)
        .map((item) => item.id)
    ),
    [visibleItems]
  )
  const feedColumns = useMemo(() => {
    const columns: [FeedItem[], FeedItem[]] = [[], []]
    const heights = [0, 0.45]

    visibleItems.forEach((item) => {
      const columnIndex = heights[0] <= heights[1] ? 0 : 1
      columns[columnIndex].push(item)
      heights[columnIndex] += getPinHeightWeight(item.aspect_ratio, item.gen_type) + 0.4
    })

    return columns
  }, [visibleItems])
  const previewReferences = useMemo(() => getPublicReferences(previewItem), [previewItem])
  const previewBlurRevealed = Boolean(previewItem && revealedPreviewIds.has(previewItem.id))
  const previewBlurActive = Boolean(previewItem?.feed_blurred && !previewBlurRevealed)

  useEffect(() => {
    let ignore = false
    let requestInFlight = false

    function mergeRefreshedFirstPage(currentItems: FeedItem[], firstPage: FeedItem[]) {
      if (currentItems.length <= FEED_PAGE_SIZE) return firstPage

      const refreshedById = new Map(firstPage.map((item) => [item.id, item]))
      const updatedCurrent = currentItems.map((item) => refreshedById.get(item.id) || item)
      const existingIds = new Set(updatedCurrent.map((item) => item.id))
      const newItems = firstPage.filter((item) => !existingIds.has(item.id))
      return [...newItems, ...updatedCurrent]
    }

    async function load(showSpinner = true) {
      if (!isLive) {
        setItems([])
        return
      }
      if (requestInFlight) return
      requestInFlight = true
      if (showSpinner) setLoading(true)
      setError(null)
      try {
        const response = await fetchFeed({ source, model, limit: FEED_PAGE_SIZE, offset: 0 })
        if (!ignore) {
          const firstPage = mergePendingPublication(response.feed, 'feed')
          setItems((prev) => showSpinner ? firstPage : mergeRefreshedFirstPage(prev, firstPage))
          setAvailableModels(response.models)
          setHasMore((current) => current || response.feed.length === FEED_PAGE_SIZE)
          if (showSpinner) setBrokenMediaIds(new Set())
        }
      } catch (e) {
        if (!ignore) setError(getErrorMessage(e, 'Не удалось загрузить ленту'))
      } finally {
        requestInFlight = false
        if (!ignore && showSpinner) setLoading(false)
      }
    }

    void load()
    const refreshIfVisible = () => {
      if (document.visibilityState === 'visible') void load(false)
    }
    document.addEventListener('visibilitychange', refreshIfVisible)
    window.addEventListener('focus', refreshIfVisible)
    const refreshTimer = window.setInterval(refreshIfVisible, 15_000)

    return () => {
      ignore = true
      document.removeEventListener('visibilitychange', refreshIfVisible)
      window.removeEventListener('focus', refreshIfVisible)
      window.clearInterval(refreshTimer)
    }
  }, [isLive, source, model])

  const handleLoadMore = async () => {
    if (!isLive || loadingMore || !hasMore) return
    setLoadingMore(true)
    setError(null)
    try {
      const { feed } = await fetchFeed({ source, model, limit: FEED_PAGE_SIZE, offset: items.length })
      setItems((prev) => {
        const seen = new Set(prev.map((item) => item.id))
        const nextItems = feed.filter((item) => !seen.has(item.id))
        return [...prev, ...nextItems]
      })
      setHasMore(feed.length === FEED_PAGE_SIZE)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось загрузить ещё работы'))
    } finally {
      setLoadingMore(false)
    }
  }

  useEffect(() => {
    if (!isLive || !feedDeepLink) return
    setItems((prev) => {
      const exists = prev.some((item) => item.id === feedDeepLink.item.id)
      return exists
        ? prev.map((item) => (item.id === feedDeepLink.item.id ? feedDeepLink.item : item))
        : [feedDeepLink.item, ...prev]
    })
    if (feedDeepLink.action === 'preview') {
      setPreviewItem(feedDeepLink.item)
    }
    consumeFeedDeepLink()
  }, [consumeFeedDeepLink, feedDeepLink, isLive])

  useEffect(() => {
    let ignore = false
    async function loadComments() {
      if (!commentsItem || !isLive) {
        setComments([])
        return
      }
      setCommentsLoading(true)
      try {
        const nextComments = await fetchFeedComments(commentsItem.id)
        if (!ignore) setComments(nextComments)
      } catch (e) {
        if (!ignore) setError(getErrorMessage(e, 'Не удалось загрузить комментарии'))
      } finally {
        if (!ignore) setCommentsLoading(false)
      }
    }
    loadComments()
    return () => {
      ignore = true
    }
  }, [commentsItem, isLive])

  const handleLike = async (item: FeedItem) => {
    if (!isLive) return
    setBusyId(item.id)
    try {
      const updated = await likeFeedItem(item.id)
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось поставить лайк'))
    } finally {
      setBusyId(null)
    }
  }

  const handleShare = async (item: FeedItem) => {
    if (!isLive || typeof navigator === 'undefined') return
    setBusyId(item.id)
    try {
      const { item: updated, link } = await shareFeedItem(item.id)
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
      await copyTextToClipboard(link)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось создать ссылку'))
    } finally {
      setBusyId(null)
    }
  }

  const handleRemix = async (item: FeedItem) => {
    if (!isLive) return
    if (item.gen_type === 'video') {
      const modelExists = state.videoModels.some((model) => model.id === item.model)
      const imageReferences = item.references_hidden ? [] : (item.reference_images || []).map((url, index) => feedReferenceToUploadedFile(url, index))
      const videoReferences = item.references_hidden ? [] : (item.reference_videos || []).map((url, index) => feedReferenceToUploadedFile(url, index, 'video'))
      const scenario = imageReferences.length ? 'imgtxt' : videoReferences.length ? 'video' : normalizeVideoScenario(item.scenario)
      setVideoPromptPreset({
        title: 'Повторить видео из ленты',
        prompt: item.prompt || '',
        model: modelExists ? item.model : state.videoModels[0]?.id || 'v3_pro',
        scenario,
        ratio: item.aspect_ratio || '16:9',
        duration: item.duration || 5,
        sourceFeedGenId: item.id,
        promptHidden: item.prompt_hidden,
        initialStartImage: scenario === 'imgtxt' ? imageReferences.slice(0, 1) : [],
        initialPhotoReferences: scenario === 'imgtxt' ? imageReferences.slice(1) : imageReferences,
        initialVideoReferences: videoReferences,
      })
      setActiveTab(2)
      return
    }
    const modelExists = state.imageModels.some((model) => model.id === item.model)
    setPromptPreset({
      promptId: null,
      title: 'Повторить образ из ленты',
      prompt: item.prompt || '',
      model: modelExists ? item.model : state.imageModels[0]?.id || 'banana_pro',
      ratio: item.aspect_ratio || '1:1',
      sourceFeedGenId: item.id,
      promptHidden: false,
    })
    setActiveTab(1)
  }

  const handleToggleBlur = async (item: FeedItem) => {
    if (!isLive || !(item.can_blur || state.user.isAdmin)) return
    setBusyId(item.id)
    try {
      const updated = await setFeedItemBlurred(item.id, !item.feed_blurred)
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
      setPreviewItem((prev) => (prev?.id === updated.id ? updated : prev))
      setCommentsItem((prev) => (prev?.id === updated.id ? updated : prev))
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось обновить blur'))
    } finally {
      setBusyId(null)
    }
  }

  const handleRemove = async (item: FeedItem) => {
    if (!isLive || !(item.is_mine || item.can_remove || state.user.isAdmin)) return
    setBusyId(item.id)
    try {
      await removeFeedItem(item.id)
      setItems((prev) => prev.filter((feedItem) => feedItem.id !== item.id))
      setPreviewItem((prev) => (prev?.id === item.id ? null : prev))
      setCommentsItem((prev) => (prev?.id === item.id ? null : prev))
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось убрать пост'))
    } finally {
      setBusyId(null)
    }
  }

  const handleOpenAuthor = (item: FeedItem) => {
    const code = String(item.author_referral_code || '').trim()
    if (!code) return
    openProfile(code)
  }

  const handleMediaError = (item: FeedItem) => {
    setBrokenMediaIds((prev) => {
      if (prev.has(item.id)) return prev
      const next = new Set(prev)
      next.add(item.id)
      return next
    })
  }

  const handleSubmitComment = async () => {
    const text = commentText.trim()
    if (!isLive || !commentsItem || !text) return
    setBusyId(commentsItem.id)
    try {
      const { comment, commentsCount } = await addFeedComment(commentsItem.id, text)
      setComments((prev) => [...prev, comment])
      setCommentText('')
      setItems((prev) =>
        prev.map((item) =>
          item.id === commentsItem.id ? { ...item, comments_count: commentsCount } : item
        )
      )
      setCommentsItem((prev) =>
        prev ? { ...prev, comments_count: commentsCount } : prev
      )
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось отправить комментарий'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="px-4 space-y-5">
      <div>
        <h2 className="font-serif text-xl font-semibold text-foreground">Лента работ</h2>
        <p className="mt-1 text-sm text-muted-foreground">Публичные фото и видео, которые можно лайкнуть, открыть или повторить.</p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Нейросеть</p>
          <span className="truncate text-xs text-gold">{selectedModelLabel}</span>
        </div>
        <div className="flex gap-2 overflow-x-auto pb-1">
          {modelTabs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                setModel(item.id)
                setItems([])
                setHasMore(false)
              }}
              className={cn(
                'shrink-0 rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
                model === item.id
                  ? 'border-cyan/50 bg-cyan/15 text-cyan'
                  : 'border-border/50 bg-secondary/50 text-muted-foreground'
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1">
        {sources.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setSource(item.id)}
            className={cn(
              'rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
              source === item.id
                ? 'border-gold/50 bg-gold/15 text-gold'
                : 'border-border/50 bg-secondary/50 text-muted-foreground'
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-10 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : visibleItems.length ? (
        <div className="space-y-4 pb-28">
          <div className="grid grid-cols-2 items-start gap-3">
            {feedColumns.map((column, columnIndex) => (
              <div
                key={columnIndex}
                className={cn('flex min-w-0 flex-col gap-3', columnIndex === 1 && 'pt-8')}
              >
                {column.map((item) => {
                  const mediaUrl = feedMediaUrl(item.result_url)
                  const previewUrl = feedMediaUrl(item.preview_url || item.result_url)
                  return (
                <article
                  key={item.id}
                  className="min-w-0 overflow-hidden rounded-2xl border border-border/45 bg-card/45 shadow-sm shadow-background/30"
                  style={{ contentVisibility: 'auto', containIntrinsicSize: '400px' }}
                >
                  <div className="relative overflow-hidden bg-secondary/50">
                    <button
                      type="button"
                      onClick={() => setPreviewItem(item)}
                      className="group block w-full text-left"
                      aria-label={item.gen_type === 'video' ? 'Открыть видео' : 'Открыть фото'}
                    >
                      {brokenMediaIds.has(item.id) ? (
                        <div
                          style={{ aspectRatio: getPinAspectRatio(item.aspect_ratio, item.gen_type) }}
                          className="flex w-full items-center justify-center text-muted-foreground"
                        >
                          <ImageOff className="h-8 w-8" />
                        </div>
                      ) : isHttpUrl(mediaUrl) ? (
                        item.gen_type === 'video' ? (
                          <FeedVideoPreview
                            src={previewUrl}
                            aspectRatio={item.aspect_ratio}
                            blurred={item.feed_blurred}
                            onError={() => handleMediaError(item)}
                          />
                        ) : (
                          <FeedImage
                            src={previewUrl}
                            fallbackSrc={mediaUrl}
                            alt=""
                            priority={priorityImageIds.has(item.id)}
                            onError={() => handleMediaError(item)}
                            style={{ aspectRatio: getPinAspectRatio(item.aspect_ratio, item.gen_type) }}
                            className={cn('w-full', item.feed_blurred && '[&_img]:scale-[1.04] [&_img]:blur-xl')}
                          />
                        )
                      ) : (
                        <div
                          style={{ aspectRatio: getPinAspectRatio(item.aspect_ratio, item.gen_type) }}
                          className="flex w-full items-center justify-center text-muted-foreground"
                        >
                          <ImageOff className="h-8 w-8" />
                        </div>
                      )}
                      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-background/70 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                      {item.gen_type === 'video' ? (
                        <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
                          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-background/75 text-foreground backdrop-blur">
                            <Play className="h-5 w-5 fill-current" />
                          </span>
                        </span>
                      ) : null}
                      {item.feed_blurred ? (
                        <span className="pointer-events-none absolute inset-0 bg-background/10 backdrop-blur-[1px]" />
                      ) : null}
                    </button>
                    <div className="absolute left-2 top-2 rounded-full bg-background/80 px-2 py-1 text-[10px] font-medium text-foreground backdrop-blur">
                      {item.gen_type === 'video' ? (
                        <span className="inline-flex items-center gap-1">
                          <Video className="h-3 w-3" />
                          {item.duration ? `${item.duration}с` : item.aspect_ratio || 'video'}
                        </span>
                      ) : (
                        item.aspect_ratio || 'image'
                      )}
                    </div>
                  </div>
                  <div className="space-y-2.5 px-2.5 pb-3 pt-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-foreground">{item.model}</p>
                        <button
                          type="button"
                          className={cn(
                            'mt-0.5 flex max-w-full items-center gap-1 truncate text-[11px] text-muted-foreground transition-colors',
                            item.author_referral_code && 'hover:text-cyan'
                          )}
                          disabled={!item.author_referral_code}
                          onClick={() => handleOpenAuthor(item)}
                        >
                          <UserRound className="h-3 w-3 shrink-0" />
                          <span className="truncate">{item.author}</span>
                        </button>
                      </div>
                      <div className="shrink-0 rounded-full bg-secondary/70 px-2 py-1 text-[10px] text-muted-foreground">
                        {item.remixes}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        className="h-8 min-w-0 flex-1 rounded-full px-2 text-[11px]"
                        disabled={busyId === item.id}
                        onClick={() => handleLike(item)}
                        aria-label="Лайк"
                      >
                        <Heart className="h-4 w-4" />
                        {item.likes_count}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        className="h-8 min-w-0 flex-1 rounded-full px-2 text-[11px]"
                        disabled={busyId === item.id}
                        onClick={() => handleShare(item)}
                        aria-label="Ссылка"
                      >
                        <Share2 className="h-4 w-4" />
                        {item.shares_count}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        className="h-8 min-w-0 flex-1 rounded-full px-2 text-[11px]"
                        onClick={() => setCommentsItem(item)}
                        aria-label="Комментарии"
                      >
                        <MessageCircle className="h-4 w-4" />
                        {item.comments_count || 0}
                      </Button>
                      {item.can_blur || state.user.isAdmin ? (
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="secondary"
                          className="h-8 w-8 rounded-full"
                          disabled={busyId === item.id}
                          onClick={() => handleToggleBlur(item)}
                          aria-label={item.feed_blurred ? 'Снять blur' : 'Blur'}
                        >
                          {item.feed_blurred ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </Button>
                      ) : null}
                      {item.is_mine || item.can_remove || state.user.isAdmin ? (
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="secondary"
                          className="h-8 w-8 rounded-full"
                          disabled={busyId === item.id}
                          onClick={() => handleRemove(item)}
                          aria-label="Убрать"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </article>
                  )
                })}
              </div>
            ))}
          </div>
          {hasMore ? (
            <Button
              type="button"
              variant="secondary"
              className="h-11 w-full rounded-full"
              disabled={loadingMore}
              onClick={handleLoadMore}
            >
              {loadingMore ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                'Загрузить ещё'
              )}
            </Button>
          ) : null}
        </div>
      ) : (
        <div className="glass rounded-2xl border border-border/50 p-6 text-center text-sm text-muted-foreground">
          {isLive ? 'В ленте пока нет опубликованных работ.' : 'Откройте mini app из Telegram, чтобы увидеть ленту.'}
        </div>
      )}

      {previewItem ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-background/95 px-3 py-6">
          <button
            type="button"
            onClick={() => setPreviewItem(null)}
            className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-secondary/80 text-foreground"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
          {isHttpUrl(feedMediaUrl(previewItem.result_url)) ? (
            previewItem.gen_type === 'video' ? (
              <video
                src={feedMediaUrl(previewItem.result_url)}
                className={cn(
                  'max-h-full w-auto max-w-full object-contain',
                  previewBlurActive && 'blur-xl'
                )}
                controls
                autoPlay
                playsInline
                preload="auto"
                onError={() => {
                  handleMediaError(previewItem)
                  setPreviewItem(null)
                }}
              />
            ) : (
              <img
                src={feedMediaUrl(previewItem.result_url)}
                alt=""
                onError={() => {
                  handleMediaError(previewItem)
                  setPreviewItem(null)
                }}
                className={cn(
                  'max-h-full w-auto max-w-full object-contain',
                  previewBlurActive && 'blur-xl'
                )}
              />
            )
          ) : (
            <div className="flex h-48 w-full items-center justify-center text-muted-foreground">
              <ImageOff className="h-8 w-8" />
            </div>
          )}
          {previewBlurActive && previewItem ? (
            <button
              type="button"
              onClick={() => {
                setRevealedPreviewIds((current) => {
                  const next = new Set(current)
                  next.add(previewItem.id)
                  return next
                })
              }}
              className="absolute inset-0 flex items-center justify-center bg-background/10 text-foreground backdrop-blur-[2px]"
              aria-label="Показать"
            >
              <span className="inline-flex h-11 items-center gap-2 rounded-full bg-background/85 px-4 text-sm font-medium shadow-lg backdrop-blur">
                <Eye className="h-4 w-4" />
                <span>Показать</span>
              </span>
            </button>
          ) : null}
          {previewReferences.length ? (
            <div className="absolute bottom-[4.5rem] left-3 right-3 flex justify-center">
              <div className="flex max-w-full gap-2 overflow-x-auto rounded-xl border border-border/60 bg-background/80 p-2 backdrop-blur">
                {previewReferences.map((reference, index) => (
                  <button
                    type="button"
                    key={`${reference.url}_${index}`}
                    onClick={() => setReferencePreview(
            reference.type === 'image'
              ? { type: 'image', url: feedReferenceImageFullUrl(previewItem.id, index) }
              : reference
          )}
                    className="h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-secondary"
                    aria-label={`Открыть референс ${index + 1}`}
                  >
                    {reference.type === 'video' ? (
                      <video src={videoPreviewFrameUrl(reference.url)} muted playsInline preload="metadata" className="h-full w-full object-cover" />
                    ) : (
                      <img src={feedReferenceImageThumbnailUrl(previewItem.id, index)} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" />
                    )}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="absolute bottom-4 left-3 right-3 flex justify-center gap-2">
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full bg-secondary/90 px-4"
              disabled={!isLive}
              onClick={() => setCommentsItem(previewItem)}
            >
              <MessageCircle className="h-4 w-4" />
              {previewItem.comments_count || 0}
            </Button>
            <Button
              type="button"
              className="h-10 rounded-full px-4"
              disabled={!isLive}
              onClick={() => handleRemix(previewItem)}
            >
              <Repeat2 className="h-4 w-4" />
              <span>Повторить</span>
            </Button>

          </div>
        </div>
      ) : null}

      {referencePreview ? (
        <div className="fixed inset-0 z-[95] flex items-center justify-center bg-background/95 px-3 py-6">
          <button
            type="button"
            onClick={() => setReferencePreview(null)}
            className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-secondary/85 text-foreground"
            aria-label="Закрыть референс"
          >
            <X className="h-5 w-5" />
          </button>
          {referencePreview.type === 'video' ? (
            <video
              src={normalizeMiniAppMediaUrl(referencePreview.url)}
              controls
              autoPlay
              playsInline
              preload="auto"
              className="max-h-full max-w-full rounded-xl bg-black object-contain"
            />
          ) : (
            <img
              src={normalizeMiniAppMediaUrl(referencePreview.url)}
              alt="Референс"
              className="max-h-full max-w-full rounded-xl object-contain"
            />
          )}
        </div>
      ) : null}

      {commentsItem ? (
        <div className="fixed inset-0 z-[85] flex items-end bg-background/70 backdrop-blur-sm">
          <div className="flex max-h-[82vh] w-full flex-col rounded-t-2xl border border-border/60 bg-card shadow-2xl">
            <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
              <div className="text-sm font-semibold text-foreground">Комментарии</div>
              <button
                type="button"
                onClick={() => setCommentsItem(null)}
                className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-muted-foreground"
                aria-label="Закрыть"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
              {commentsLoading ? (
                <div className="flex justify-center py-6 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : comments.length ? (
                comments.map((comment) => (
                  <div key={comment.id} className="flex gap-2 text-sm">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold text-foreground">
                      {comment.author.replace(/^@/, '').slice(0, 1).toUpperCase() || 'U'}
                    </div>
                    <div className="min-w-0 flex-1">
                      <span className="mr-2 font-semibold text-foreground">{comment.author}</span>
                      <span className="break-words text-foreground/90">{comment.text}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="py-8 text-center text-sm text-muted-foreground">Пока пусто</div>
              )}
            </div>
            <div className="flex items-center gap-2 border-t border-border/60 p-3">
              <input
                value={commentText}
                onChange={(event) => setCommentText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    handleSubmitComment()
                  }
                }}
                maxLength={500}
                className="h-10 min-w-0 flex-1 rounded-full border border-border/60 bg-background px-4 text-sm text-foreground outline-none focus:border-cyan"
                placeholder="Комментарий"
              />
              <Button
                type="button"
                size="icon"
                className="h-10 w-10 rounded-full"
                disabled={!commentText.trim() || busyId === commentsItem.id}
                onClick={handleSubmitComment}
                aria-label="Отправить"
              >
                {busyId === commentsItem.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
