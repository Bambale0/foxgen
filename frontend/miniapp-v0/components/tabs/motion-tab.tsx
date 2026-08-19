'use client'

import { useState } from 'react'
import { Sparkles, Upload, Video, Image as ImageIcon, Wand2, CheckCircle2 } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { generateMotion, uploadFile } from '@/lib/api'
import type { Task, UploadedFile } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ResultCard } from '../result-card'
import { cn } from '@/lib/utils'

type MotionMode = '720p' | '1080p'
type MotionModel = 'motion_control_v26' | 'motion_control_v30'
type MotionDirection = 'video' | 'image'

function MotionUploadCard({
  title,
  description,
  icon: Icon,
  accept,
  file,
  onUpload,
  disabled,
}: {
  title: string
  description: string
  icon: typeof ImageIcon
  accept: string
  file: UploadedFile | null
  onUpload: (file: File) => Promise<void>
  disabled?: boolean
}) {
  const [isUploading, setIsUploading] = useState(false)

  async function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0]
    if (!selected) return

    setIsUploading(true)
    try {
      await onUpload(selected)
    } finally {
      setIsUploading(false)
      event.target.value = ''
    }
  }

  return (
    <label
      className={cn(
        'group relative block overflow-hidden rounded-[1.75rem] border p-4',
        'transition-all duration-300 active:scale-[0.99]',
        file
          ? 'border-gold/45 bg-gold/[0.06]'
          : 'border-border/60 bg-card/45 hover:border-gold/35 hover:bg-card/70'
      )}
    >
      <input
        type="file"
        accept={accept}
        className={cn(
          'relative z-10 mt-3 block w-full cursor-pointer rounded-lg border border-border/60',
          'bg-background/80 px-3 py-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-60',
          'file:mr-3 file:rounded-md file:border-0 file:bg-gold file:px-3 file:py-1.5',
          'file:text-sm file:font-medium file:text-primary-foreground'
        )}
        disabled={disabled || isUploading}
        onChange={handleChange}
      />

      <div className="relative flex items-center gap-3">
        <div
          className={cn(
            'flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border',
            file
              ? 'border-gold/35 bg-gold/10'
              : 'border-border/60 bg-background/70'
          )}
        >
          {file ? (
            <CheckCircle2 className="h-5 w-5 text-gold" />
          ) : (
            <Icon className="h-5 w-5 text-muted-foreground" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <p className="font-serif text-lg leading-6 text-foreground">{title}</p>
          <p className="mt-1 text-sm leading-5 text-muted-foreground">{description}</p>

          <div className="mt-3 inline-flex max-w-full items-center gap-2 rounded-full border border-border/70 bg-background/55 px-3 py-2 text-sm">
            <Upload className="h-4 w-4 shrink-0 text-gold" />
            <span className="truncate">
              {isUploading ? 'Загрузка…' : file ? file.name : 'Загрузить'}
            </span>
          </div>
        </div>
      </div>
    </label>
  )
}

export function MotionTab() {
  const { state, addTask, setCredits, setTaskDetail, selectTask } = useApp()
  const formatPerSecondCost = (raw: number) => Number(raw.toFixed(2)).toString()

  const [characterImage, setCharacterImage] = useState<UploadedFile | null>(null)
  const [motionVideo, setMotionVideo] = useState<UploadedFile | null>(null)
  const [videoDuration, setVideoDuration] = useState<number>(5)
  const [motionModel, setMotionModel] = useState<MotionModel>('motion_control_v26')
  const [mode, setMode] = useState<MotionMode>('720p')
  const [direction, setDirection] = useState<MotionDirection>('video')
  const [prompt, setPrompt] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [lastРезультат, setLastРезультат] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)
  const motionModelData = state.videoModels.find((item) => item.id === motionModel)
  const perSecondCost =
    (motionModelData?.quality_costs?.[mode] ??
    (motionModelData?.costs?.['5'] ?? 15) / 5)
  const motionCost = Math.round(perSecondCost * videoDuration * 2) / 2

  async function uploadImage(file: File) {
    if (state.mode !== 'live') {
      setError('Откройте Mini App через Telegram, чтобы загрузить фото.')
      return
    }

    setCharacterImage(await uploadFile('image_reference', file))
  }

  async function uploadVideo(file: File) {
    // read duration before uploading
    const duration = await new Promise<number>((resolve) => {
      const url = URL.createObjectURL(file)
      const el = document.createElement('video')
      el.preload = 'metadata'
      el.onloadedmetadata = () => {
        resolve(Math.max(1, Math.round(el.duration)))
        URL.revokeObjectURL(url)
      }
      el.onerror = () => { resolve(5); URL.revokeObjectURL(url) }
      el.src = url
    })
    setVideoDuration(duration)

    if (state.mode !== 'live') {
      setError('Откройте Mini App через Telegram, чтобы загрузить видео.')
      return
    }

    setMotionVideo(await uploadFile('video_reference', file))
  }

  async function handleSubmit() {
    setError(null)

    if (state.mode !== 'live') {
      setError('Откройте Mini App через Telegram, чтобы запустить Motion Control.')
      return
    }

    if (!characterImage) {
      setError('Загрузите фото персонажа')
      return
    }

    if (!motionVideo) {
      setError('Загрузите видео движения')
      return
    }

    setIsSubmitting(true)

    try {
      const result = await generateMotion({
        imageUrl: characterImage.url,
        videoUrl: motionVideo.url,
        prompt,
        mode,
        direction,
        model: motionModel,
        videoDuration,
      })

      addTask(result.task)
      setCredits(result.credits)
      setLastРезультат(result.task)
      selectTask(result.task)

      if (result.detail) {
        setTaskDetail(result.detail)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось запустить Motion Control')
    } finally {
      setIsSubmitting(false)
    }
  }

  const estimatedCost = `${motionCost}🍌 • ${formatPerSecondCost(perSecondCost)}🍌/с`

  return (
    <div className="px-4 space-y-5 pb-28">
      <div className="relative overflow-hidden rounded-[1.75rem] border border-gold/20 bg-gradient-to-br from-gold/[0.12] via-card/70 to-cyan/[0.10] p-5">
        <div className="absolute -right-12 -top-12 h-32 w-32 rounded-full bg-gold/20 blur-3xl" />
        <div className="absolute -left-10 bottom-0 h-24 w-24 rounded-full bg-cyan/15 blur-3xl" />

        <div className="relative">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-gold/25 bg-background/50 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-gold">
            <Sparkles className="h-3.5 w-3.5" />
            Motion Control
          </div>

          <h2 className="font-serif text-2xl font-semibold leading-tight text-foreground">
            Перенос движения
          </h2>

          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Загрузите фото персонажа и видео с движением. Модель перенесёт динамику на ваш образ.
          </p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.12fr)_minmax(320px,0.88fr)]">
        <div className="space-y-4">
          <MotionUploadCard
            title="Фото персонажа"
            description="Кого нужно оживить."
            icon={ImageIcon}
            accept="image/*"
            file={characterImage}
            onUpload={uploadImage}
            disabled={isSubmitting}
          />

          <MotionUploadCard
            title="Видео движения"
            description="Откуда берём движение."
            icon={Video}
            accept="video/*"
            file={motionVideo}
            onUpload={uploadVideo}
            disabled={isSubmitting}
          />

          <div className="glass rounded-[1.75rem] border border-border/60 p-4">
            <p className="font-serif text-lg text-foreground mb-4">Настройки</p>

            <div className="space-y-3">
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Версия Kling
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: 'motion_control_v26' as const, label: 'Kling 2.6' },
                    { id: 'motion_control_v30' as const, label: 'Kling 3.0' },
                  ].map((item) => {
                    const itemModel = state.videoModels.find((model) => model.id === item.id)
                    const itemPerSecondCost =
                      (itemModel?.quality_costs?.[mode] ??
                      (itemModel?.costs?.['5'] ?? 15) / 5)
                    const itemCost = Math.round(itemPerSecondCost * videoDuration * 2) / 2
                    return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setMotionModel(item.id)}
                      className={cn(
                        'rounded-2xl border px-4 py-3 text-sm font-medium transition-all',
                        motionModel === item.id
                          ? 'border-gold/60 bg-gold/10 text-gold'
                          : 'border-border/70 bg-background/40 text-muted-foreground'
                      )}
                    >
                      <span className="block">{item.label}</span>
                      <span className="mt-1 block text-xs opacity-80">
                        {itemCost}🍌 · {formatPerSecondCost(itemPerSecondCost)}🍌/с
                      </span>
                    </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Качество
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {(['720p', '1080p'] as MotionMode[]).map((item) => {
                    const qPerSec = (motionModelData?.quality_costs?.[item] ??
                      (motionModelData?.costs?.['5'] ?? 15) / 5)
                    const qCost = Math.round(qPerSec * videoDuration * 2) / 2
                    return (
                    <button
                      key={item}
                      type="button"
                      onClick={() => setMode(item)}
                      className={cn(
                        'rounded-2xl border px-4 py-3 text-sm font-medium transition-all',
                        mode === item
                          ? 'border-gold/60 bg-gold/10 text-gold'
                          : 'border-border/70 bg-background/40 text-muted-foreground'
                      )}
                    >
                      <span className="block">{item}</span>
                      <span className="mt-1 block text-xs opacity-80">
                        {qCost}🍌 · {formatPerSecondCost(qPerSec)}🍌/с
                      </span>
                    </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Ориентация
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: 'video' as const, label: 'Из видео' },
                    { id: 'image' as const, label: 'Из фото' },
                  ].map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setDirection(item.id)}
                      className={cn(
                        'rounded-2xl border px-3 py-3 text-sm font-medium transition-all',
                        direction === item.id
                          ? 'border-cyan/60 bg-cyan/10 text-cyan'
                          : 'border-border/70 bg-background/40 text-muted-foreground'
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Промпт
                </p>
                <Textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Например: сохранить лицо, плавная камера, киношный свет…"
                  className="min-h-24 rounded-2xl bg-background/50 text-sm"
                />
              </div>
            </div>
          </div>

          {error && (
            <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-4">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          <Button
            type="button"
            size="lg"
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="h-14 w-full rounded-2xl bg-gold text-background hover:bg-gold/90"
          >
            <Wand2 className="mr-2 h-5 w-5" />
            {isSubmitting ? 'Запускаю…' : 'Запустить Motion'}
          </Button>
        </div>

        <div className="space-y-4">
          <div className="glass rounded-[1.75rem] border border-border/60 p-5">
            <p className="text-xs uppercase tracking-[0.18em] text-gold/80 mb-3">
              Проверка
            </p>

            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Модель</span>
                <strong>{motionModel === 'motion_control_v30' ? 'Kling 3.0 Motion' : 'Kling 2.6 Motion'}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Качество</span>
                <strong>{mode}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Ориентация</span>
                <strong>{direction === 'video' ? 'из видео' : 'из фото'}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Фото</span>
                <strong>{characterImage ? 'готово' : 'нет'}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Видео</span>
                <strong>{motionVideo ? 'готово' : 'нет'}</strong>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Тариф</span>
                <strong>{estimatedCost}</strong>
              </div>
            </div>
          </div>

          {lastРезультат ? (
            <ResultCard task={lastРезультат} onClose={() => setLastРезультат(null)} />
          ) : (
            <div className="rounded-[1.75rem] border border-cyan/20 bg-cyan/[0.06] p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-cyan/80 mb-2">
                Результат
              </p>
              <h3 className="font-serif text-lg text-foreground mb-2">
                Готово к запуску
              </h3>
              <p className="text-sm leading-6 text-muted-foreground">
                После запуска здесь появится задача. Готовый ролик придёт в чат и историю.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
