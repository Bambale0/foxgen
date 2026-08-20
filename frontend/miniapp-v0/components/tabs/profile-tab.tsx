'use client'

import { useEffect, useMemo, useState } from 'react'
import { useApp } from '@/lib/app-context'
import type { FeedComment, FeedItem, ProfileSummary, ScenarioType, UploadedFile } from '@/lib/types'
import { cn, isHttpUrl } from '@/lib/utils'
import { copyTextToClipboard } from '@/lib/clipboard'
import { mergePendingPublication, mergePublication } from '@/lib/feed-events'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  addFeedComment,
  fetchFeedComments,
  fetchMyFeed,
  fetchPartnerOverview,
  fetchProfileFeed,
  likeFeedItem,
  saveProfileChannel,
  setFeedItemBlurred,
  shareFeedItem,
} from '@/lib/api'
import {
  Check,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  Grid3X3,
  Heart,
  ImageOff,
  Link2,
  Loader2,
  MessageCircle,
  Play,
  Radio,
  Repeat2,
  Save,
  Send,
  Share2,
  Sparkles,
  UserRound,
  Wallet,
  X,
} from 'lucide-react'

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function formatCompactNumber(value: number) {
  return new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function formatRub(value?: number) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(value || 0))
}

const videoScenarios = new Set<ScenarioType>(['text', 'imgtxt', 'video', 'avatar', 'audio', 'character'])
const PROFILE_FEED_PAGE_SIZE = 24

function feedReferenceToUploadedFile(url: string, index: number, type: 'image' | 'video' = 'image'): UploadedFile {
  return { id: `profile-ref-${index}-${url}`, name: `reference-${index + 1}`, url, type, size: 0 }
}

function normalizeVideoScenario(value?: string | null): ScenarioType {
  return videoScenarios.has(value as ScenarioType) ? (value as ScenarioType) : 'text'
}

function profileInitials(firstName?: string, lastName?: string, username?: string) {
  const value = `${firstName?.[0] || ''}${lastName?.[0] || ''}` || username?.[0] || 'U'
  return value.toUpperCase()
}

function getPublicReferences(item: FeedItem | null) {
  if (!item) return []
  return [
    ...(item.reference_images || []).map((url) => ({ type: 'image' as const, url })),
    ...(item.reference_videos || []).map((url) => ({ type: 'video' as const, url })),
  ].filter((item) => isHttpUrl(item.url))
}

function ProfileFeedImage({ src, fallbackSrc, blurred, onError }: {
  src: string
  fallbackSrc: string
  blurred?: boolean
  onError: () => void
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
    onError()
  }

  return (
    <>
      {!loaded ? (
        <span className="absolute inset-0 animate-pulse bg-gradient-to-br from-secondary via-muted to-secondary/70" />
      ) : null}
      <img
        src={currentSrc}
        alt=""
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={handleError}
        className={cn(
          'relative z-10 h-full w-full object-cover transition-all duration-500 group-hover:scale-[1.04]',
          loaded ? 'opacity-100' : 'opacity-0',
          blurred && 'scale-110 blur-xl'
        )}
      />
    </>
  )
}

function profileInteractionsEnabled(item: FeedItem | null | undefined) {
  return Boolean(
    item &&
      item.publication_scope !== 'private' &&
      item.is_profile_visible !== false
  )
}

export function ProfileTab() {
  const {
    state,
    viewedProfileCode,
    feedDeepLink,
    consumeFeedDeepLink,
    setActiveTab,
    setPromptPreset,
    setVideoPromptPreset,
  } = useApp()
  const { user } = state
  const [items, setItems] = useState<FeedItem[]>([])
  const [brokenMediaIds, setBrokenMediaIds] = useState<Set<number>>(() => new Set())
  const [profile, setProfile] = useState<ProfileSummary | null>(null)
  const [previewItem, setPreviewItem] = useState<FeedItem | null>(null)
  const [commentsItem, setCommentsItem] = useState<FeedItem | null>(null)
  const [comments, setComments] = useState<FeedComment[]>([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentText, setCommentText] = useState('')
  const [ownChannelUrl, setOwnChannelUrl] = useState(user.channelUrl || '')
  const [channelInput, setChannelInput] = useState(user.channelUrl || '')
  const [channelSaving, setChannelSaving] = useState(false)
  const [partnerStats, setPartnerStats] = useState<{
    prompt_repeat_balance_rub: number
    prompt_repeat_total_rub: number
  } | null>(null)
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [copied, setCopied] = useState<string | number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [feedRefreshToken, setFeedRefreshToken] = useState(0)
  const [revealedIds, setRevealedIds] = useState<Set<number>>(() => new Set())
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)

  const isLive = state.mode === 'live'
  const ownReferralCode = String(user.referralCode || '').trim().toUpperCase()
  const targetReferralCode = String(viewedProfileCode || '').trim().toUpperCase()
  const isOwnProfile = !targetReferralCode || targetReferralCode === ownReferralCode
  const displayName = isOwnProfile
    ? [user.firstName, user.lastName].filter(Boolean).join(' ') || user.username || 'Профиль'
    : profile?.display_name || profile?.username || 'Профиль'
  const handle = isOwnProfile
    ? user.username
      ? `@${user.username}`
      : user.telegramId
        ? `id${user.telegramId}`
        : '@profile'
    : profile?.username
      ? `@${profile.username}`
      : profile?.referral_code
        ? profile.referral_code
        : '@profile'
  const avatarUrl = isOwnProfile ? user.photoUrl : profile?.photo_url
  const avatarFallback = profileInitials(
    isOwnProfile ? user.firstName : profile?.first_name,
    isOwnProfile ? user.lastName : profile?.last_name,
    isOwnProfile ? user.username : profile?.username
  )
  const profileShareLink =
    isOwnProfile
      ? user.profileLink ||
        (user.botUsername && ownReferralCode
          ? `https://t.me/${user.botUsername}?startapp=${encodeURIComponent(`profile_${ownReferralCode}_ref_${ownReferralCode}`)}`
          : '')
      : ''
  const displayChannelUrl = isOwnProfile ? ownChannelUrl : profile?.channel_url || ''
  const repeatBalance =
    partnerStats?.prompt_repeat_balance_rub ?? user.promptRepeatBalanceRub ?? 0
  const repeatTotal =
    partnerStats?.prompt_repeat_total_rub ?? user.promptRepeatTotalRub ?? 0

  const demoItems = useMemo(() => {
    return state.recentTasks.reduce<FeedItem[]>((acc, task, index) => {
      const url = task.result_url || ''
      if (!['image', 'video'].includes(task.type) || task.status !== 'completed' || !isHttpUrl(url)) {
        return acc
      }
      const urls = (task.result_urls || []).filter(isHttpUrl)
      if (!urls.includes(url)) {
        urls.unshift(url)
      }
      acc.push({
        id: task.feed_id || index + 1,
        task_id: task.task_id,
        model: task.model_label || task.model,
        gen_type: task.type === 'video' ? 'video' : 'image',
        result_url: url,
        result_urls: urls,
        prompt: task.prompt_preview,
        likes_count: Math.max(2, 18 - index * 3),
        shares_count: Math.max(0, 5 - index),
        aspect_ratio: task.aspect_ratio || '1:1',
        duration: task.duration || null,
        scenario: task.type === 'video' ? 'text' : null,
        author: displayName,
        author_referral_code: ownReferralCode || null,
        author_photo_url: user.photoUrl || null,
        is_mine: true,
        remixes: Math.max(0, 4 - index),
        score: 0,
        created_at: task.created_at,
        prompt_hidden: task.prompt_hidden,
        prompt_actions_allowed: task.prompt_actions_allowed,
      })
      return acc
    }, [])
  }, [displayName, ownReferralCode, state.recentTasks, user.photoUrl])

  const profileItems = useMemo(
    () => (isLive ? items : demoItems),
    [demoItems, isLive, items]
  )
  const previewReferences = useMemo(() => getPublicReferences(previewItem), [previewItem])
  const totals = useMemo(() => {
    if (isLive && profile) {
      return {
        posts: Math.max(Number(profile.posts_count || 0), profileItems.length),
        likes: Number(profile.likes_count || 0),
        shares: Number(profile.shares_count || 0),
        remixes: Number(profile.remixes_count || 0),
      }
    }
    return profileItems.reduce(
      (acc, item) => ({
        posts: acc.posts + 1,
        likes: acc.likes + item.likes_count,
        shares: acc.shares + item.shares_count,
        remixes: acc.remixes + item.remixes,
      }),
      { posts: 0, likes: 0, shares: 0, remixes: 0 }
    )
  }, [isLive, profile, profileItems])

  useEffect(() => {
    if (!isOwnProfile) return
    setItems((current) => mergePendingPublication(current, 'profile'))
  }, [isOwnProfile])

  useEffect(() => {
    const refreshProfileFeed = (event: Event) => {
      const published = (event as CustomEvent<FeedItem | undefined>).detail
      if (published) {
        if (isOwnProfile) {
          setItems((current) => mergePublication(current, published, 'profile'))
        }
        return
      }
      setFeedRefreshToken((value) => value + 1)
    }
    window.addEventListener('banano:feed-changed', refreshProfileFeed)
    return () => window.removeEventListener('banano:feed-changed', refreshProfileFeed)
  }, [isOwnProfile])

  useEffect(() => {
    if (!isLive || !feedDeepLink || feedDeepLink.action !== 'preview') return
    if (feedDeepLink.item.publication_scope !== 'profile') return
    setItems((prev) => {
      const exists = prev.some((item) => item.id === feedDeepLink.item.id)
      return exists
        ? prev.map((item) => (item.id === feedDeepLink.item.id ? feedDeepLink.item : item))
        : [feedDeepLink.item, ...prev]
    })
    setPreviewItem(feedDeepLink.item)
    consumeFeedDeepLink()
  }, [consumeFeedDeepLink, feedDeepLink, isLive])

  useEffect(() => {
    let ignore = false

    async function loadProfileFeed() {
      if (!isLive) {
        setItems([])
        setProfile(null)
        setError(null)
        return
      }

      setLoading(true)
      setError(null)
      try {
        if (isOwnProfile) {
          if (ownReferralCode) {
            const result = await fetchProfileFeed(ownReferralCode, PROFILE_FEED_PAGE_SIZE)
            if (!ignore) {
              setItems(mergePendingPublication(result.feed, 'profile'))
              setBrokenMediaIds(new Set())
              setProfile(result.profile)
              setHasMore(result.feed.length === PROFILE_FEED_PAGE_SIZE)
            }
            return
          }
          const feed = await fetchMyFeed(PROFILE_FEED_PAGE_SIZE)
          if (!ignore) {
            setItems(mergePendingPublication(feed, 'profile'))
            setBrokenMediaIds(new Set())
            setProfile(null)
            setHasMore(feed.length === PROFILE_FEED_PAGE_SIZE)
          }
          return
        }

        const result = await fetchProfileFeed(targetReferralCode, PROFILE_FEED_PAGE_SIZE)
        if (!ignore) {
          setItems(result.feed)
          setBrokenMediaIds(new Set())
          setProfile(result.profile)
          setHasMore(result.feed.length === PROFILE_FEED_PAGE_SIZE)
        }
      } catch (e) {
        if (!ignore) setError(getErrorMessage(e, 'Не удалось загрузить профиль'))
      } finally {
        if (!ignore) setLoading(false)
      }
    }

    loadProfileFeed()
    return () => {
      ignore = true
    }
  }, [feedRefreshToken, isLive, isOwnProfile, ownReferralCode, targetReferralCode])

  useEffect(() => {
    if (!isOwnProfile) return
    setOwnChannelUrl(user.channelUrl || '')
    setChannelInput(user.channelUrl || '')
  }, [isOwnProfile, user.channelUrl])

  useEffect(() => {
    let ignore = false

    async function loadPartnerStats() {
      if (!isLive || !isOwnProfile) {
        setPartnerStats(null)
        return
      }
      try {
        const data = await fetchPartnerOverview()
        if (!ignore) {
          setPartnerStats({
            prompt_repeat_balance_rub: data.prompt_repeat_balance_rub || 0,
            prompt_repeat_total_rub: data.prompt_repeat_total_rub || 0,
          })
          setOwnChannelUrl(data.channel_url || user.channelUrl || '')
          setChannelInput(data.channel_url || user.channelUrl || '')
        }
      } catch {
        if (!ignore) setPartnerStats(null)
      }
    }

    loadPartnerStats()
    return () => {
      ignore = true
    }
  }, [isLive, isOwnProfile, user.channelUrl])

  useEffect(() => {
    let ignore = false

    async function loadComments() {
      if (!commentsItem || !isLive || !profileInteractionsEnabled(commentsItem)) {
        setComments([])
        return
      }
      setCommentsLoading(true)
      try {
        const nextComments = await fetchFeedComments(commentsItem.id, 40, 'profile')
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

  async function copyText(text: string, marker: string | number) {
    if (!text) return
    await copyTextToClipboard(text)
    setCopied(marker)
    window.setTimeout(() => setCopied(null), 1500)
  }

  async function handleCopyProfileLink() {
    if (!isOwnProfile || !profileShareLink) return
    try {
      await copyText(profileShareLink, 'profile')
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось скопировать ссылку'))
    }
  }

  async function handleLike(item: FeedItem) {
    if (!isLive || !profileInteractionsEnabled(item)) return
    setBusyId(item.id)
    try {
      const updated = await likeFeedItem(item.id, 'profile')
      setItems((prev) => prev.map((entry) => (entry.id === updated.id ? updated : entry)))
      setPreviewItem((prev) => (prev?.id === updated.id ? updated : prev))
      setCommentsItem((prev) => (prev?.id === updated.id ? updated : prev))
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось поставить лайк'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleCopyPostLink(item: FeedItem, kind: 'post' | 'remix' = 'post') {
    if (!isLive || !profileInteractionsEnabled(item)) return
    setBusyId(item.id)
    try {
      const { item: updated, postLink, remixLink } = await shareFeedItem(item.id, 'profile')
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
      setPreviewItem((prev) => (prev?.id === updated.id ? updated : prev))
      const marker = kind === 'remix' ? `remix_${item.id}` : item.id
      await copyText(kind === 'remix' ? remixLink : postLink, marker)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось создать ссылку на публикацию'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleToggleBlur(item: FeedItem) {
    if (!isLive || !(item.can_blur || item.is_mine)) return
    setBusyId(item.id)
    try {
      const updated = await setFeedItemBlurred(item.id, !item.feed_blurred)
      setItems((prev) => prev.map((entry) => (entry.id === updated.id ? updated : entry)))
      setPreviewItem((prev) => (prev?.id === updated.id ? updated : prev))
      setRevealedIds((prev) => {
        const next = new Set(prev)
        next.delete(item.id)
        return next
      })
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось обновить blur'))
    } finally {
      setBusyId(null)
    }
  }

  function revealItem(item: FeedItem) {
    setRevealedIds((prev) => new Set(prev).add(item.id))
  }

  async function handleSaveChannel() {
    if (!isLive || !isOwnProfile) return
    setChannelSaving(true)
    setError(null)
    try {
      const nextUrl = await saveProfileChannel(channelInput)
      setOwnChannelUrl(nextUrl)
      setChannelInput(nextUrl)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось сохранить канал'))
    } finally {
      setChannelSaving(false)
    }
  }

  async function handleSubmitComment() {
    const text = commentText.trim()
    if (!isLive || !commentsItem || !text || !profileInteractionsEnabled(commentsItem)) return
    setBusyId(commentsItem.id)
    try {
      const { comment, commentsCount } = await addFeedComment(commentsItem.id, text, 'profile')
      setComments((prev) => [...prev, comment])
      setCommentText('')
      setItems((prev) =>
        prev.map((item) =>
          item.id === commentsItem.id ? { ...item, comments_count: commentsCount } : item
        )
      )
      setCommentsItem((prev) => (prev ? { ...prev, comments_count: commentsCount } : prev))
      setPreviewItem((prev) =>
        prev?.id === commentsItem.id ? { ...prev, comments_count: commentsCount } : prev
      )
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось отправить комментарий'))
    } finally {
      setBusyId(null)
    }
  }

  function handleMediaError(item: FeedItem) {
    setBrokenMediaIds((prev) => {
      if (prev.has(item.id)) return prev
      const next = new Set(prev)
      next.add(item.id)
      return next
    })
  }

  async function loadMoreProfileItems() {
    if (!isLive || loadingMore || !hasMore) return
    setLoadingMore(true)
    setError(null)
    try {
      const offset = items.length
      const nextItems = isOwnProfile
        ? ownReferralCode
          ? (await fetchProfileFeed(ownReferralCode, PROFILE_FEED_PAGE_SIZE, offset)).feed
          : await fetchMyFeed(PROFILE_FEED_PAGE_SIZE, offset)
        : (await fetchProfileFeed(targetReferralCode, PROFILE_FEED_PAGE_SIZE, offset)).feed
      setItems((current) => {
        const existingIds = new Set(current.map((item) => item.id))
        const unique = nextItems.filter((item) => !existingIds.has(item.id))
        return [...current, ...unique]
      })
      setHasMore(nextItems.length === PROFILE_FEED_PAGE_SIZE)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось загрузить ещё публикации'))
    } finally {
      setLoadingMore(false)
    }
  }

  function handleRemix(item: FeedItem) {
    if (!profileInteractionsEnabled(item)) return
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
        sourceFeedGenId: isLive ? item.id : null,
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
      title: 'Повторить публикацию',
      prompt: item.prompt || '',
      model: modelExists ? item.model : state.imageModels[0]?.id || 'banana_pro',
      ratio: item.aspect_ratio || '1:1',
      sourceFeedGenId: isLive ? item.id : null,
      promptHidden: item.prompt_hidden,
    })
    setActiveTab(1)
  }

  return (
    <div className="px-4 pb-28">
      <section className="space-y-5">
        <div className="flex items-center gap-4">
          <div className="rounded-full bg-gradient-to-tr from-gold via-cyan to-chart-4 p-0.5">
            <Avatar className="size-24 border-4 border-background bg-secondary">
              {isHttpUrl(avatarUrl) ? (
                <AvatarImage src={avatarUrl} alt={displayName} className="object-cover" />
              ) : null}
              <AvatarFallback className="bg-secondary text-2xl font-semibold text-foreground">
                {avatarFallback}
              </AvatarFallback>
            </Avatar>
          </div>

          <div className="grid min-w-0 flex-1 grid-cols-3 gap-2 text-center">
            <div>
              <div className="text-lg font-bold text-foreground">{formatCompactNumber(totals.posts)}</div>
              <div className="text-[11px] text-muted-foreground">постов</div>
            </div>
            <div>
              <div className="text-lg font-bold text-foreground">{formatCompactNumber(totals.likes)}</div>
              <div className="text-[11px] text-muted-foreground">лайков</div>
            </div>
            <div>
              <div className="text-lg font-bold text-foreground">{formatCompactNumber(totals.remixes)}</div>
              <div className="text-[11px] text-muted-foreground">повторов</div>
            </div>
          </div>
        </div>

        <div className="min-w-0 space-y-1.5">
          <h2 className="truncate text-xl font-semibold text-foreground">{displayName}</h2>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <UserRound className="h-4 w-4 shrink-0" />
            <span className="truncate">{handle}</span>
          </div>
          {profileShareLink ? (
            <div className="flex items-center gap-2 text-sm text-cyan">
              <Link2 className="h-4 w-4 shrink-0" />
              <span className="truncate">{profileShareLink}</span>
            </div>
          ) : null}
        </div>

        {isOwnProfile ? (
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Wallet className="h-3.5 w-3.5" />
                <span>Повторы</span>
              </div>
              <div className="mt-1 text-base font-semibold text-foreground">
                {formatRub(repeatBalance)} ₽
              </div>
            </div>
            <div className="rounded-lg border border-border/50 bg-card/45 p-3">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Sparkles className="h-3.5 w-3.5" />
                <span>Всего</span>
              </div>
              <div className="mt-1 text-base font-semibold text-foreground">
                {formatRub(repeatTotal)} ₽
              </div>
            </div>
          </div>
        ) : null}

        {isOwnProfile ? (
          <div className="rounded-lg border border-border/50 bg-card/45 p-3">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
              <Radio className="h-4 w-4 text-cyan" />
              <span>Канал</span>
            </div>
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <input
                value={channelInput}
                onChange={(event) => setChannelInput(event.target.value)}
                maxLength={160}
                className="h-10 min-w-0 rounded-lg border border-border/60 bg-background px-3 text-sm text-foreground outline-none focus:border-cyan"
                placeholder="@channel"
              />
              <Button
                type="button"
                size="icon"
                className="h-10 w-10 rounded-lg"
                disabled={channelSaving || !isLive}
                onClick={handleSaveChannel}
                aria-label="Сохранить канал"
              >
                {channelSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
              </Button>
            </div>
            {displayChannelUrl ? (
              <a
                href={displayChannelUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 flex min-w-0 items-center gap-1.5 text-sm text-cyan"
              >
                <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{displayChannelUrl}</span>
              </a>
            ) : null}
          </div>
        ) : displayChannelUrl ? (
          <Button asChild type="button" variant="secondary" className="h-10 rounded-lg">
            <a href={displayChannelUrl} target="_blank" rel="noreferrer">
              <Radio className="h-4 w-4" />
              <span className="truncate">Канал автора</span>
            </a>
          </Button>
        ) : null}

        {isOwnProfile ? (
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <Button
              type="button"
              variant="secondary"
              className="h-10 min-w-0 rounded-lg px-3"
              disabled={!profileShareLink}
              onClick={handleCopyProfileLink}
            >
              {copied === 'profile' ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              <span className="truncate">{copied === 'profile' ? 'Скопировано' : 'Ссылка на профиль'}</span>
            </Button>
            {profileShareLink ? (
              <Button asChild type="button" variant="secondary" size="icon" className="h-10 w-10 rounded-lg">
                <a href={profileShareLink} target="_blank" rel="noreferrer" aria-label="Открыть профиль">
                  <ExternalLink className="h-4 w-4" />
                </a>
              </Button>
            ) : (
              <Button type="button" variant="secondary" size="icon" className="h-10 w-10 rounded-lg" disabled>
                <ExternalLink className="h-4 w-4" />
              </Button>
            )}
          </div>
        ) : null}
      </section>

      <div className="mt-6 flex items-center justify-center border-t border-border/60 py-3 text-gold">
        <Grid3X3 className="h-5 w-5" />
      </div>

      {error ? (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {loading && !profileItems.length ? (
        <div className="flex justify-center py-10 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : profileItems.length ? (
        <div className="grid grid-cols-4 gap-px sm:grid-cols-5">
          {profileItems.map((item) => (
            <article key={item.id} className="relative aspect-square min-w-0 overflow-hidden bg-secondary/80">
              <button
                type="button"
                className="group h-full w-full text-left"
                onClick={() => setPreviewItem(item)}
                aria-label="Открыть публикацию"
              >
                {brokenMediaIds.has(item.id) ? (
                  <span className="flex h-full w-full items-center justify-center text-muted-foreground">
                    <ImageOff className="h-5 w-5" />
                  </span>
                ) : isHttpUrl(item.result_url) ? (
                  item.gen_type === 'video' ? (
                    isHttpUrl(item.preview_url) ? (
                      <img
                        src={item.preview_url}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        onError={() => handleMediaError(item)}
                        className={cn(
                          'h-full w-full object-cover opacity-80 transition-all duration-500 group-hover:scale-[1.04]',
                          item.feed_blurred && !revealedIds.has(item.id) && 'scale-110 blur-xl'
                        )}
                      />
                    ) : (
                      <span className="flex h-full w-full items-center justify-center text-muted-foreground">
                        <Play className="h-6 w-6 fill-current" />
                      </span>
                    )
                  ) : (
                    <ProfileFeedImage
                      src={item.preview_url || item.result_url}
                      fallbackSrc={item.result_url}
                      blurred={item.feed_blurred && !revealedIds.has(item.id)}
                      onError={() => handleMediaError(item)}
                    />
                  )
                ) : (
                  <span className="flex h-full w-full items-center justify-center text-muted-foreground">
                    <ImageOff className="h-5 w-5" />
                  </span>
                )}
                {item.gen_type === 'video' ? (
                  <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-background/75 text-foreground backdrop-blur">
                      <Play className="h-4 w-4 fill-current" />
                    </span>
                  </span>
                ) : null}
                <span className="pointer-events-none absolute inset-0 bg-background/0 transition-colors group-hover:bg-background/35" />
                {item.feed_blurred && !revealedIds.has(item.id) ? (
                  <span
                    className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-1 bg-background/25 text-center text-foreground backdrop-blur-[2px]"
                  >
                    <Eye className="h-5 w-5" />
                    <span className="rounded-full bg-background/80 px-2 py-1 text-[10px] font-semibold">
                      Открыть
                    </span>
                  </span>
                ) : null}
                <span className="pointer-events-none absolute left-1 top-1 flex items-center gap-0.5 rounded bg-background/80 px-1 py-0.5 text-[9px] font-semibold text-foreground backdrop-blur">
                  <Heart className="h-3 w-3" />
                  {formatCompactNumber(item.likes_count)}
                </span>
                <span className="pointer-events-none absolute right-1 top-1 flex items-center gap-0.5 rounded bg-background/80 px-1 py-0.5 text-[9px] font-semibold text-foreground backdrop-blur">
                  <Share2 className="h-3 w-3" />
                  {formatCompactNumber(item.shares_count)}
                </span>
                <span
                  className="pointer-events-none absolute right-1 bottom-8 flex items-center gap-0.5 rounded bg-background/80 px-1 py-0.5 text-[9px] font-semibold text-foreground backdrop-blur"
                  aria-label={`Повторов: ${item.remixes || 0}`}
                >
                  <Repeat2 className="h-3 w-3" />
                  {formatCompactNumber(item.remixes)}
                </span>
                {item.publication_scope === 'profile' ? (
                  <span className="pointer-events-none absolute bottom-1 left-1/2 -translate-x-1/2 rounded bg-background/85 px-1.5 py-0.5 text-[9px] font-semibold text-cyan backdrop-blur">
                    Только профиль
                  </span>
                ) : null}
              </button>
              <button
                type="button"
                className={cn(
                  'absolute bottom-1 left-1 flex h-6 w-6 items-center justify-center rounded-full',
                  'bg-background/80 text-foreground backdrop-blur transition-colors hover:bg-background',
                  (!isLive || busyId === item.id) && 'opacity-60'
                )}
                disabled={!isLive || busyId === item.id || !profileInteractionsEnabled(item)}
                onClick={() => handleCopyPostLink(item)}
                aria-label="Скопировать ссылку на пост"
              >
                {busyId === item.id ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : copied === item.id ? (
                  <Check className="h-3 w-3" />
                ) : (
                  <Share2 className="h-3 w-3" />
                )}
              </button>
              <button
                type="button"
                className="absolute bottom-1 right-1 flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-full bg-background/80 px-1.5 text-[10px] font-medium text-foreground backdrop-blur transition-colors hover:bg-background disabled:opacity-60"
                disabled={!isLive || !profileInteractionsEnabled(item)}
                onClick={() => setCommentsItem(item)}
                aria-label="Комментарии"
              >
                <MessageCircle className="h-3 w-3" />
                {item.comments_count || 0}
              </button>
            </article>
          ))}
          {hasMore ? (
            <div className="col-span-4 py-4 sm:col-span-5">
              <Button
                type="button"
                variant="secondary"
                className="h-10 w-full rounded-lg"
                disabled={loadingMore}
                onClick={loadMoreProfileItems}
              >
                {loadingMore ? <Loader2 className="h-4 w-4 animate-spin" /> : <Grid3X3 className="h-4 w-4" />}
                <span>{loadingMore ? 'Загружаю...' : 'Загрузить ещё'}</span>
              </Button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="rounded-lg border border-border/50 bg-card/45 p-6 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-muted-foreground">
            <Grid3X3 className="h-6 w-6" />
          </div>
          <p className="mt-3 text-sm font-medium text-foreground">Публикаций пока нет</p>
          <p className="mt-1 text-sm text-muted-foreground">Здесь появятся работы, опубликованные в ленте или только в профиле.</p>
          <Button
            type="button"
            variant="secondary"
            className="mt-4 rounded-lg"
            onClick={() => setActiveTab(4)}
          >
            Открыть ленту
          </Button>
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
          {isHttpUrl(previewItem.result_url) ? (
            previewItem.gen_type === 'video' ? (
              <video
                src={previewItem.result_url}
                className="max-h-full w-auto max-w-full object-contain"
                controls
                autoPlay
                playsInline
                onError={() => {
                  handleMediaError(previewItem)
                  setPreviewItem(null)
                }}
              />
            ) : (
              <img
                src={previewItem.result_url}
                alt=""
                onError={() => {
                  handleMediaError(previewItem)
                  setPreviewItem(null)
                }}
                className={cn(
                  'max-h-full w-auto max-w-full object-contain transition-all',
                  previewItem.feed_blurred && !revealedIds.has(previewItem.id) && 'scale-105 blur-2xl'
                )}
              />
            )
          ) : (
            <div className="flex h-48 w-full items-center justify-center text-muted-foreground">
              <ImageOff className="h-8 w-8" />
            </div>
          )}
          {previewItem.feed_blurred && !revealedIds.has(previewItem.id) ? (
            <button
              type="button"
              onClick={() => revealItem(previewItem)}
              className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-background/25 text-foreground"
            >
              <Eye className="h-7 w-7" />
              <span className="rounded-full bg-background/85 px-4 py-2 text-sm font-semibold backdrop-blur">
                {previewItem.is_adult_content ? 'Показать контент 18+' : 'Показать изображение'}
              </span>
            </button>
          ) : null}
          {previewReferences.length ? (
            <div className="absolute bottom-[4.5rem] left-3 right-3 flex justify-center">
              <div className="flex max-w-full gap-2 overflow-x-auto rounded-xl border border-border/60 bg-background/80 p-2 backdrop-blur">
                {previewReferences.map((reference, index) => (
                  <a
                    key={`${reference.url}_${index}`}
                    href={reference.url}
                    target="_blank"
                    rel="noreferrer"
                    className="h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-secondary"
                  >
                    {reference.type === 'video' ? (
                      <video src={reference.url} muted playsInline preload="none" className="h-full w-full object-cover" />
                    ) : (
                      <img src={reference.url} alt="" className="h-full w-full object-cover" />
                    )}
                  </a>
                ))}
              </div>
            </div>
          ) : null}
          <div className="absolute bottom-4 left-3 right-3 flex flex-wrap justify-center gap-2">
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full bg-secondary/90 px-4"
              disabled={!isLive || busyId === previewItem.id || !profileInteractionsEnabled(previewItem)}
              onClick={() => handleLike(previewItem)}
            >
              <Heart className="h-4 w-4" />
              {previewItem.likes_count || 0}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full bg-secondary/90 px-4"
              disabled={!isLive || !profileInteractionsEnabled(previewItem)}
              onClick={() => setCommentsItem(previewItem)}
            >
              <MessageCircle className="h-4 w-4" />
              {previewItem.comments_count || 0}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full px-4"
              disabled={!isLive || busyId === previewItem.id || !profileInteractionsEnabled(previewItem)}
              onClick={() => handleCopyPostLink(previewItem, 'post')}
            >
              {copied === previewItem.id ? <Check className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
              <span>{copied === previewItem.id ? 'Скопировано' : 'Поделиться'}</span>
            </Button>
            {previewItem.gen_type === 'image' ? (
              <Button
                type="button"
                variant="secondary"
                className="h-10 rounded-full px-4"
                disabled={!isLive || busyId === previewItem.id || !profileInteractionsEnabled(previewItem)}
                onClick={() => handleCopyPostLink(previewItem, 'remix')}
              >
                {copied === `remix_${previewItem.id}` ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
                <span>{copied === `remix_${previewItem.id}` ? 'Скопировано' : 'Ссылка ремикса'}</span>
              </Button>
            ) : null}
            {previewItem.can_blur || previewItem.is_mine ? (
              <Button
                type="button"
                variant="secondary"
                className="h-10 rounded-full px-4"
                disabled={!isLive || busyId === previewItem.id}
                onClick={() => handleToggleBlur(previewItem)}
              >
                {previewItem.feed_blurred ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                <span>
                  {previewItem.feed_blurred ? 'Убрать blur' : 'Blur'}
                </span>
              </Button>
            ) : null}
            <Button
              type="button"
              className="h-10 rounded-full px-4"
              disabled={!profileInteractionsEnabled(previewItem)}
              onClick={() => handleRemix(previewItem)}
            >
              <Repeat2 className="h-4 w-4" />
              <span>Повторить · {formatCompactNumber(previewItem.remixes || 0)}</span>
            </Button>
          </div>
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
                disabled={
                  !commentText.trim() ||
                  busyId === commentsItem.id ||
                  !isLive ||
                  !profileInteractionsEnabled(commentsItem)
                }
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
