'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { copyTextToClipboard } from '@/lib/clipboard'
import type { PromptItem } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { deactivatePrompt, fetchPromptLink, fetchPrompts, submitPrompt, uploadFile } from '@/lib/api'
import { mediaAspectRatio, normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'
import { TrendRunnerDialog } from '@/components/trend-runner-dialog'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import {
  Film,
  Flame,
  Check,
  Copy,
  ImagePlus,
  Loader2,
  Plus,
  Repeat2,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react'

type TrendKind = 'image' | 'video'

const TREND_TAG = 'trend'
const VIDEO_TREND_TAG = 'trend-video'
const VIDEO_TREND_PREVIEW_MAX_BYTES = 200 * 1024 * 1024

function normalizedTags(trend: PromptItem) {
  return new Set((trend.tags || []).map((tag) => String(tag).trim().toLowerCase()))
}

function hasTrendTag(trend: PromptItem) {
  return normalizedTags(trend).has(TREND_TAG)
}

function hasVideoTag(trend: PromptItem) {
  return normalizedTags(trend).has(VIDEO_TREND_TAG)
}

export function TrendsTab() {
  const { state, trendToRun, setTrendToRun } = useApp()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const previewUploadAttemptRef = useRef(0)
  const previewUploadPromiseRef = useRef<Promise<string | null> | null>(null)
  const [items, setItems] = useState<PromptItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [trendKind, setTrendKind] = useState<TrendKind>('image')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [promptText, setPromptText] = useState('')
  const [model, setModel] = useState('banana_pro')
  const [videoDuration, setVideoDuration] = useState(5)
  const [trendRatio, setTrendRatio] = useState('1:1')
  const [imageQuality, setImageQuality] = useState('2K')
  const [previewUrl, setPreviewUrl] = useState('')
  const [uploadingPreview, setUploadingPreview] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [removingId, setRemovingId] = useState<number | null>(null)
  const [copiedId, setCopiedId] = useState<number | null>(null)
  const [previewTrend, setPreviewTrend] = useState<PromptItem | null>(null)
  const [videoAspectRatios, setVideoAspectRatios] = useState<Record<number, string>>({})

  const isLive = state.mode === 'live'
  const isAdmin = state.user.isAdmin
  const availableModels = trendKind === 'video'
    ? state.videoModels.filter((item) => item.supports.includes('imgtxt'))
    : state.imageModels
  const selectedTrendImageModel = state.imageModels.find((item) => item.id === model)
  const selectedTrendVideoModel = state.videoModels.find((item) => item.id === model)
  const trendImageQualities =
    selectedTrendImageModel?.id === 'banana_pro' || selectedTrendImageModel?.id === 'banana_2'
      ? ['1K', '2K', '4K']
      : selectedTrendImageModel?.qualities?.length
        ? selectedTrendImageModel.qualities
        : ['basic']

  const videoModelIds = useMemo(
    () => new Set(state.videoModels.map((item) => item.id)),
    [state.videoModels],
  )

  const isVideoTrend = (trend: PromptItem) =>
    trend.category === 'video' ||
    hasVideoTag(trend) ||
    videoModelIds.has(String(trend.model || ''))

  const photoTrends = useMemo(() => items.filter((item) => !isVideoTrend(item)), [items, videoModelIds])
  const videoTrends = useMemo(() => items.filter((item) => isVideoTrend(item)), [items, videoModelIds])

  async function loadTrends() {
    if (!isLive) {
      setItems([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const trends = await fetchPrompts({ source: 'tag', tag: TREND_TAG, limit: 80 })
      // Keep a client-side guard as well, so a backend/cache regression cannot
      // leak ordinary public prompts into the curated trends section.
      setItems(trends.filter(hasTrendTag))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить тренды')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadTrends()
  }, [isLive])

  useEffect(() => {
    const models = trendKind === 'video' ? state.videoModels : state.imageModels
    if (!models.some((item) => item.id === model)) {
      setModel(models[0]?.id || (trendKind === 'video' ? 'v3_pro' : 'banana_pro'))
    }
  }, [model, state.imageModels, state.videoModels, trendKind])

  useEffect(() => {
  if (trendKind !== 'video' || !selectedTrendVideoModel) return
  setVideoDuration((current) => (
    selectedTrendVideoModel.durations.includes(current)
      ? current
      : selectedTrendVideoModel.durations[0] || 5
  ))
}, [selectedTrendVideoModel, trendKind])

  useEffect(() => {
    const selectedModel = trendKind === 'video'
      ? state.videoModels.find((item) => item.id === model)
      : state.imageModels.find((item) => item.id === model)
    const ratios = selectedModel?.ratios || []
    if (ratios.length && !ratios.includes(trendRatio)) {
      setTrendRatio(ratios[0])
    }
    if (trendKind === 'image' && !trendImageQualities.includes(imageQuality)) {
      setImageQuality(trendImageQualities[0] || 'basic')
    }
  }, [
    imageQuality,
    model,
    state.imageModels,
    state.videoModels,
    trendImageQualities,
    trendKind,
    trendRatio,
  ])

  const changeTrendKind = (nextKind: TrendKind) => {
    if (nextKind === trendKind) return
    setTrendKind(nextKind)
    setPreviewUrl('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const resetForm = () => {
    setTrendKind('image')
    setTitle('')
    setDescription('')
    setPromptText('')
    setModel(state.imageModels[0]?.id || 'banana_pro')
    setVideoDuration(5)
    setTrendRatio('1:1')
    setImageQuality('2K')
    setPreviewUrl('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const applyTrend = (trend: PromptItem) => {
    setTrendToRun(trend)
  }

  const handlePreviewUpload = async (file?: File) => {
    if (!file) return
    const expectedPrefix = trendKind === 'video' ? 'video/' : 'image/'
    const extension = file.name.split('.').pop()?.toLowerCase() || ''
    const fallbackExtensions = trendKind === 'video'
      ? new Set(['mp4', 'mov', 'm4v', 'webm'])
      : new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])
    if (!file.type.startsWith(expectedPrefix) && !fallbackExtensions.has(extension)) {
      setError(
        trendKind === 'video'
          ? 'Для видео-тренда нужен видеофайл'
          : 'Для фото-тренда нужно изображение',
      )
      return
    }
    if (trendKind === 'video' && file.size > VIDEO_TREND_PREVIEW_MAX_BYTES) {
      setError('Видео-пример слишком большой, максимум 200MB')
      return
    }

    const attemptId = ++previewUploadAttemptRef.current
    const localPreviewUrl = URL.createObjectURL(file)
    setUploadingPreview(true)
    setError(null)
    setPreviewUrl((current) => {
      if (current.startsWith('blob:')) URL.revokeObjectURL(current)
      return localPreviewUrl
    })
    const uploadPromise = uploadFile(
        trendKind === 'video' ? 'trend_video_preview' : 'image_reference',
        file,
      )
      .then((uploaded) => uploaded.url)
      .catch((e) => {
        if (previewUploadAttemptRef.current === attemptId) {
          setPreviewUrl((current) => current === localPreviewUrl ? '' : current)
          setError(e instanceof Error ? e.message : 'Не удалось загрузить preview')
        }
        return null
      })
    previewUploadPromiseRef.current = uploadPromise
    try {
      const uploadedUrl = await uploadPromise
      if (previewUploadAttemptRef.current !== attemptId) return
      if (uploadedUrl) setPreviewUrl(uploadedUrl)
    } finally {
      if (previewUploadAttemptRef.current === attemptId) {
        setUploadingPreview(false)
        previewUploadPromiseRef.current = null
      }
      URL.revokeObjectURL(localPreviewUrl)
    }
  }

  const handleCreate = async () => {
    if (!isAdmin || submitting) return
    if (!title.trim() || !promptText.trim() || !previewUrl || !model) {
      setError('Заполните название, preview, нейросеть и скрытый prompt')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      let finalPreviewUrl = previewUrl
      if (finalPreviewUrl.startsWith('blob:') && previewUploadPromiseRef.current) {
        setError('Дожидаюсь сохранения preview на сервере…')
        const uploadedUrl = await previewUploadPromiseRef.current
        if (!uploadedUrl) {
          setError('Не удалось сохранить preview. Повторите загрузку файла.')
          return
        }
        finalPreviewUrl = uploadedUrl
        setPreviewUrl(uploadedUrl)
      }
      if (finalPreviewUrl.startsWith('blob:')) {
        setError('Preview еще не сохранен на сервере. Подождите несколько секунд и повторите.')
        return
      }
      const generationSettings = trendKind === 'video'
        ? {
            kind: 'video' as const,
            user_input: 'photo' as const,
            model,
            scenario: 'imgtxt' as const,
            ratio: trendRatio,
            duration: videoDuration,
            grok_mode: selectedTrendVideoModel?.grok_modes?.[0] || 'normal',
            grok_resolution: selectedTrendVideoModel?.grok_resolutions?.[0] || '480p',
            veo_generation_type:
              selectedTrendVideoModel?.veo_generation_types?.find((value) =>
                value.toUpperCase().includes('IMAGE'),
              ) ||
              selectedTrendVideoModel?.veo_generation_types?.[0] ||
              'IMAGE_2_VIDEO',
            veo_translation: true,
            veo_resolution: selectedTrendVideoModel?.veo_resolutions?.[0] || '720p',
            veo_seed: null,
            veo_watermark: '',
            kling_negative_prompt: '',
            kling_cfg_scale: 0.5,
            omni_resolution: selectedTrendVideoModel?.omni_resolutions?.[0] || '720p',
            omni_seed: null,
            omni_audio_ids: [],
            omni_character_ids: [],
            omni_base_voice: selectedTrendVideoModel?.omni_base_voices?.[0] || 'achernar',
            omni_voice_name: '',
            omni_voice_description: '',
            omni_example_dialogue: '',
            omni_character_name: '',
            omni_character_audio_ids: [],
          }
        : {
            kind: 'image' as const,
            user_input: 'photo' as const,
            model,
            ratio: trendRatio,
            quality: imageQuality,
            count: 1,
            nsfw_checker: false,
            nsfw_enabled: false,
          }

      const created = await submitPrompt({
        title: title.trim(),
        description: description.trim(),
        promptText: promptText.trim(),
        previewUrl: finalPreviewUrl,
        model,
        tags: trendKind === 'video'
          ? [TREND_TAG, VIDEO_TREND_TAG]
          : [TREND_TAG],
        generationSettings,
      })
      setItems((prev) => [created, ...prev.filter((item) => item.id !== created.id)])
      resetForm()
      setIsCreateOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось опубликовать тренд')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRemove = async (trend: PromptItem) => {
    if (!isAdmin || removingId !== null) return
    setRemovingId(trend.id)
    setError(null)
    try {
      await deactivatePrompt(trend.id)
      setItems((prev) => prev.filter((item) => item.id !== trend.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось убрать тренд')
    } finally {
      setRemovingId(null)
    }
  }

  const handleCopyLink = async (trend: PromptItem) => {
    try {
      const link = await fetchPromptLink(trend.id)
      await copyTextToClipboard(link)
      setCopiedId(trend.id)
      window.setTimeout(() => setCopiedId((current) => current === trend.id ? null : current), 1800)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось скопировать ссылку')
    }
  }

  const rememberVideoAspectRatio = (trendId: number, video: HTMLVideoElement) => {
    const width = Number(video.videoWidth || 0)
    const height = Number(video.videoHeight || 0)
    if (!width || !height) return
    setVideoAspectRatios((current) => {
      const ratio = `${width} / ${height}`
      return current[trendId] === ratio ? current : { ...current, [trendId]: ratio }
    })
  }

  const renderTrendGrid = (trendItems: PromptItem[], sectionTitle: string, videoSection: boolean) => {
    if (!trendItems.length) return null
    return (
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-serif text-lg font-semibold text-foreground">{sectionTitle}</h3>
          <span className="rounded-full bg-secondary/60 px-2.5 py-1 text-xs text-muted-foreground">{trendItems.length}</span>
        </div>
        <div className="grid grid-cols-2 items-start gap-3 md:grid-cols-3">
          {trendItems.map((trend) => {
            const modelLabel = videoSection
              ? state.videoModels.find((item) => item.id === trend.model)?.label
              : state.imageModels.find((item) => item.id === trend.model)?.label
            return (
              <article key={trend.id} className="glass min-w-0 overflow-hidden rounded-2xl border border-border/50">
                <div className="relative bg-secondary/40">
                  {trend.preview_url ? videoSection ? (
                    <button type="button" className="block w-full" onClick={() => setPreviewTrend(trend)} aria-label={`Открыть видео ${trend.title}`}>
                      <video
                        src={videoPreviewFrameUrl(trend.preview_url)}
                        muted
                        playsInline
                        preload="metadata"
                        onLoadedMetadata={(event) => rememberVideoAspectRatio(trend.id, event.currentTarget)}
                        style={{ aspectRatio: videoAspectRatios[trend.id] || mediaAspectRatio(trend.generation_settings?.ratio) }}
                        className="w-full bg-black object-contain"
                      />
                      <span className="absolute inset-0 grid place-items-center bg-black/10"><Film className="h-8 w-8 rounded-full bg-black/55 p-1.5 text-white" /></span>
                    </button>
                  ) : (
                    <img src={normalizeMiniAppMediaUrl(trend.preview_url)} alt={trend.title} loading="lazy" className="h-auto max-h-[420px] w-full object-contain" />
                  ) : (
                    <div className={videoSection ? 'flex aspect-video items-center justify-center' : 'flex aspect-square items-center justify-center'}><Sparkles className="h-8 w-8 text-gold" /></div>
                  )}
                </div>
                <div className="space-y-2.5 p-3">
                  <div><h4 className="line-clamp-2 text-sm font-semibold text-foreground">{trend.title}</h4>{trend.description ? <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{trend.description}</p> : null}</div>
                  <div className="truncate rounded-lg bg-secondary/55 px-2 py-1.5 text-[10px] text-muted-foreground">{modelLabel || trend.model}</div>
                  <Button type="button" size="sm" className="w-full bg-gold text-primary-foreground hover:bg-gold/90" onClick={() => applyTrend(trend)}><Repeat2 className="h-3.5 w-3.5" />Повторить</Button>
                  <div className={isAdmin ? 'grid grid-cols-[1fr_auto] gap-2' : 'grid'}>
                    <Button type="button" size="sm" variant="secondary" onClick={() => void handleCopyLink(trend)}>{copiedId === trend.id ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copiedId === trend.id ? 'Скопировано' : 'Ссылка'}</Button>
                    {isAdmin ? <Button type="button" variant="secondary" size="icon" onClick={() => void handleRemove(trend)} disabled={removingId === trend.id} aria-label="Убрать тренд">{removingId === trend.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}</Button> : null}
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      </section>
    )
  }

  return (
    <div className="space-y-5 px-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Flame className="h-5 w-5 text-gold" />
            <h2 className="font-serif text-xl font-semibold text-foreground">Тренды</h2>
          </div>
          <p className="mt-1 max-w-xl text-sm text-muted-foreground">
            Готовые фото- и видео-шаблоны от команды NEUROMIX.
          </p>
        </div>
        {isAdmin ? (
          <Button
            type="button"
            size="sm"
            className="shrink-0 bg-gold text-primary-foreground hover:bg-gold/90"
            onClick={() => setIsCreateOpen((value) => !value)}
          >
            {isCreateOpen ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            {isCreateOpen ? 'Закрыть' : 'Добавить'}
          </Button>
        ) : null}
      </div>

      {isAdmin && isCreateOpen ? (
        <section className="glass space-y-4 rounded-2xl border border-gold/25 p-4">
          <div>
            <p className="text-sm font-semibold text-foreground">Новый тренд</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Пользователи увидят пример и описание, но не увидят скрытый prompt.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => changeTrendKind('image')}
              className={`rounded-xl border px-3 py-3 text-sm font-medium transition ${
                trendKind === 'image'
                  ? 'border-gold/50 bg-gold/15 text-gold'
                  : 'border-border/50 bg-secondary/40 text-muted-foreground'
              }`}
            >
              Фото-тренд
            </button>
            <button
              type="button"
              onClick={() => changeTrendKind('video')}
              className={`rounded-xl border px-3 py-3 text-sm font-medium transition ${
                trendKind === 'video'
                  ? 'border-gold/50 bg-gold/15 text-gold'
                  : 'border-border/50 bg-secondary/40 text-muted-foreground'
              }`}
            >
              Видео-тренд
            </button>
          </div>

          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Название тренда"
            maxLength={80}
            className="h-11 w-full rounded-xl border border-border/50 bg-secondary/50 px-3 text-sm outline-none focus:border-gold/50"
          />

          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={
              trendKind === 'video'
                ? 'Что получится и какие исходники нужны'
                : 'Что получится и какое фото лучше загрузить'
            }
            className="min-h-[76px] resize-none bg-secondary/50"
            maxLength={240}
          />

          <label className="block space-y-2">
            <span className="text-xs font-medium text-muted-foreground">
              {trendKind === 'video' ? 'Видео-нейросеть' : 'Нейросеть для фото'}
            </span>
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground outline-none focus:border-gold/50"
            >
              {availableModels.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label.replace('🔥 НОВИНКА', '').trim()}
                </option>
              ))}
            </select>
          </label>

          {trendKind === 'video' ? (
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Формат</span>
                <select value={trendRatio} onChange={(event) => setTrendRatio(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendVideoModel?.ratios || ['16:9']).map((ratio) => (
                    <option key={ratio} value={ratio}>{ratio}</option>
                  ))}
                </select>
              </label>
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Длительность</span>
                <select value={videoDuration} onChange={(event) => setVideoDuration(Number(event.target.value))} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendVideoModel?.durations || [5]).map((duration) => (
                    <option key={duration} value={duration}>{duration} сек</option>
                  ))}
                </select>
              </label>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Формат</span>
                <select value={trendRatio} onChange={(event) => setTrendRatio(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {(selectedTrendImageModel?.ratios || ['1:1']).map((ratio) => (
                    <option key={ratio} value={ratio}>{ratio}</option>
                  ))}
                </select>
              </label>
              <label className="block space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Качество</span>
                <select value={imageQuality} onChange={(event) => setImageQuality(event.target.value)} className="h-11 w-full rounded-xl border border-border/50 bg-secondary/70 px-3 text-sm text-foreground">
                  {trendImageQualities.map((quality) => (
                    <option key={quality} value={quality}>{quality}</option>
                  ))}
                </select>
              </label>
            </div>
          )}

          <div className="space-y-2">
            <span className="text-xs font-medium text-muted-foreground">
              {trendKind === 'video' ? 'Видео-пример шаблона' : 'Preview шаблона'}
            </span>
            {previewUrl ? (
              <div className="relative overflow-hidden rounded-2xl border border-border/50 bg-secondary/40">
                {trendKind === 'video' ? (
                  <video
                    src={previewUrl}
                    controls
                    muted
                    playsInline
                    preload="metadata"
                    className="h-auto max-h-[70vh] w-full bg-black object-contain"
                  />
                ) : (
                  <img
                    src={previewUrl}
                    alt="Preview тренда"
                    className="aspect-square w-full object-cover"
                  />
                )}
                <button
                  type="button"
                  onClick={() => {
                    setPreviewUrl('')
                    if (fileInputRef.current) fileInputRef.current.value = ''
                  }}
                  className="absolute right-2 top-2 rounded-full bg-background/80 p-2 text-foreground backdrop-blur"
                  aria-label="Удалить preview"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div
                className="relative flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 overflow-hidden rounded-2xl border border-dashed border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground transition-colors hover:border-gold/40 hover:text-foreground"
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={
                    trendKind === 'video'
                      ? 'video/mp4,video/webm,video/quicktime'
                      : 'image/jpeg,image/png,image/webp'
                  }
                  className="relative z-10 block w-full cursor-pointer rounded-lg border border-border/60 bg-background/80 px-3 py-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-60 file:mr-3 file:rounded-md file:border-0 file:bg-gold file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
                  disabled={uploadingPreview}
                  onChange={(event) => void handlePreviewUpload(event.target.files?.[0])}
                />
                {uploadingPreview ? (
                  <Loader2 className="h-6 w-6 animate-spin" />
                ) : trendKind === 'video' ? (
                  <Film className="h-7 w-7" />
                ) : (
                  <ImagePlus className="h-7 w-7" />
                )}
                {uploadingPreview
                  ? 'Загружаю…'
                  : trendKind === 'video'
                    ? 'Загрузить видео'
                    : 'Загрузить изображение'}
              </div>
            )}
            {uploadingPreview ? (
              <p className="text-xs text-muted-foreground">
                Сохраняю preview на сервере. Не закрывайте mini app до завершения.
              </p>
            ) : error ? (
              <p className="text-xs text-destructive">{error}</p>
            ) : null}
          </div>

          <Textarea
            value={promptText}
            onChange={(event) => setPromptText(event.target.value)}
            placeholder="Скрытый prompt, который подставится при повторе"
            className="min-h-[150px] resize-none bg-secondary/50"
          />

          <Button
            type="button"
            className="w-full bg-gold text-primary-foreground hover:bg-gold/90"
            disabled={submitting}
            onClick={() => void handleCreate()}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Опубликовать тренд
          </Button>
        </section>
      ) : null}

      {error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex justify-center py-12 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : items.length ? (
        <div className="space-y-7">
          {renderTrendGrid(photoTrends, '🖼 Фото-тренды', false)}
          {renderTrendGrid(videoTrends, '🎬 Видео-тренды', true)}
        </div>
      ) : (
        <div className="glass rounded-2xl border border-border/50 p-8 text-center">
          <Flame className="mx-auto h-9 w-9 text-gold/70" />
          <p className="mt-3 text-sm font-medium text-foreground">Трендов пока нет</p>
          <p className="mt-1 text-xs text-muted-foreground">{isAdmin ? 'Нажмите «Добавить», чтобы опубликовать первый шаблон.' : 'Команда NEUROMIX скоро добавит новые шаблоны.'}</p>
        </div>
      )}

      <TrendRunnerDialog
        trend={trendToRun}
        open={Boolean(trendToRun)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setTrendToRun(null)
        }}
      />

      <Dialog open={Boolean(previewTrend)} onOpenChange={(open) => { if (!open) setPreviewTrend(null) }}>
        <DialogContent className="max-w-3xl border-border/60 bg-background p-3">
          <DialogTitle className="pr-8 text-sm">{previewTrend?.title || 'Видео-тренд'}</DialogTitle>
          {previewTrend?.preview_url ? (
            <video
              src={normalizeMiniAppMediaUrl(previewTrend.preview_url)}
              controls
              autoPlay
              playsInline
              onLoadedMetadata={(event) => rememberVideoAspectRatio(previewTrend.id, event.currentTarget)}
              style={{ aspectRatio: videoAspectRatios[previewTrend.id] || mediaAspectRatio(previewTrend.generation_settings?.ratio) }}
              className="mx-auto max-h-[78vh] max-w-full rounded-xl bg-black object-contain"
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
