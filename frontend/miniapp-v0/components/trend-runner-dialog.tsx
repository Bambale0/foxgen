'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ImagePlus, Loader2, RefreshCcw, Sparkles } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { uploadFile } from '@/lib/api'
import { runTrend } from '@/lib/trend-api'
import { mediaAspectRatio, normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'
import type { PromptItem } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

type RunnerPhase = 'idle' | 'uploading' | 'generating' | 'error'
type TrendTemplateFieldType = 'text' | 'number' | 'date'

interface TrendTemplateField {
  key: string
  label: string
  type: TrendTemplateFieldType
  required?: boolean
  placeholder?: string
  max_length?: number
}

interface TrendRunnerDialogProps {
  trend: PromptItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])
const MAX_REFERENCES = 12

function trendTemplateFields(trend: PromptItem | null): TrendTemplateField[] {
  const settings = trend?.generation_settings as
    | (NonNullable<PromptItem['generation_settings']> & {
        template_fields?: TrendTemplateField[]
      })
    | null
    | undefined
  return Array.isArray(settings?.template_fields) ? settings.template_fields : []
}

export function TrendRunnerDialog({
  trend,
  open,
  onOpenChange,
}: TrendRunnerDialogProps) {
  const {
    addTask,
    setCredits,
    setTaskDetail,
    selectTask,
    addSavedReference,
  } = useApp()
  const inputRef = useRef<HTMLInputElement>(null)
  const previewRefs = useRef<string[]>([])
  const [phase, setPhase] = useState<RunnerPhase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [previewUrls, setPreviewUrls] = useState<string[]>([])
  const [parameterValues, setParameterValues] = useState<Record<string, string>>({})

  const busy = phase === 'uploading' || phase === 'generating'
  const isVideoTrend = trend?.generation_settings?.kind === 'video'
  const templateFields = trendTemplateFields(trend)

  const clearPreviews = useCallback(() => {
    for (const previewUrl of previewRefs.current) {
      if (previewUrl.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    }
    previewRefs.current = []
    setPreviewUrls([])
  }, [])

  useEffect(() => {
    if (open) return
    setPhase('idle')
    setError(null)
    setParameterValues({})
    clearPreviews()
    if (inputRef.current) inputRef.current.value = ''
  }, [clearPreviews, open])

  useEffect(() => clearPreviews, [clearPreviews])

  const handlePhotos = async (selectedFiles: File[]) => {
    if (!trend || busy || !selectedFiles.length) return

    const missingField = templateFields.find(
      (field) => field.required !== false && !String(parameterValues[field.key] || '').trim(),
    )
    if (missingField) {
      setPhase('error')
      setError(`Заполните поле «${missingField.label}»`)
      return
    }

    if (selectedFiles.length > MAX_REFERENCES) {
      setPhase('error')
      setError(`Можно загрузить максимум ${MAX_REFERENCES} фото`)
      return
    }

    const invalidFile = selectedFiles.find((file) => {
      const extension = file.name.split('.').pop()?.toLowerCase() || ''
      return !file.type.startsWith('image/') && !IMAGE_EXTENSIONS.has(extension)
    })
    if (invalidFile) {
      setPhase('error')
      setError(`Файл «${invalidFile.name}» не является изображением`)
      return
    }

    clearPreviews()
    const localPreviews = selectedFiles.map((file) => URL.createObjectURL(file))
    previewRefs.current = localPreviews
    setPreviewUrls(localPreviews)
    setError(null)
    setPhase('uploading')

    try {
      const uploadedReferences = await Promise.all(
        selectedFiles.map((file) => uploadFile('image_reference', file)),
      )
      for (const uploaded of uploadedReferences) addSavedReference(uploaded)

      setPhase('generating')
      const result = await runTrend(
        trend.id,
        uploadedReferences.map((uploaded) => uploaded.url),
        parameterValues,
      )
      addTask(result.task)
      setCredits(result.credits)
      if (result.detail) setTaskDetail(result.detail)
      selectTask(result.task)
      onOpenChange(false)
    } catch (cause) {
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось запустить тренд')
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!busy) onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="max-w-lg border-border/60 bg-background p-4">
        <DialogTitle className="pr-8 font-serif text-lg">
          {trend?.title || 'Повторить тренд'}
        </DialogTitle>

        {trend?.preview_url ? (
          isVideoTrend ? (
            <video
              src={videoPreviewFrameUrl(trend.preview_url)}
              muted
              loop
              autoPlay
              controls
              playsInline
              preload="metadata"
              style={{ aspectRatio: mediaAspectRatio(trend.generation_settings?.ratio) }}
              className="mx-auto max-h-[42vh] max-w-full rounded-2xl bg-black object-contain"
            />
          ) : (
            <img
              src={normalizeMiniAppMediaUrl(trend.preview_url)}
              alt={trend.title}
              className="max-h-[42vh] w-full rounded-2xl object-contain"
            />
          )
        ) : null}

        <div className="rounded-2xl border border-gold/25 bg-gold/10 p-4 text-center">
          <Sparkles className="mx-auto h-6 w-6 text-gold" />
          <p className="mt-2 text-sm font-semibold text-foreground">
            Сделайте этот шаблон своим
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {templateFields.length
              ? 'Заполните данные ниже и загрузите свои фото. Скрытый сценарий, модель и настройки уже готовы.'
              : 'Загрузите свои фото. Скрытый сценарий, модель, формат и качество уже настроены.'}
          </p>
        </div>

        {templateFields.length ? (
          <div className="space-y-3 rounded-2xl border border-border/60 bg-secondary/20 p-4">
            <div>
              <p className="text-sm font-semibold text-foreground">Ваши данные</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Эти значения меняются только в вашей генерации.
              </p>
            </div>
            {templateFields.map((field) => (
              <label key={field.key} className="block space-y-1.5">
                <span className="text-xs font-medium text-foreground">{field.label}</span>
                <input
                  type={field.type === 'date' ? 'date' : 'text'}
                  inputMode={field.type === 'number' ? 'decimal' : undefined}
                  value={parameterValues[field.key] || ''}
                  maxLength={field.max_length || 120}
                  placeholder={field.type === 'date' ? undefined : field.placeholder}
                  disabled={busy}
                  onChange={(event) => {
                    const value = event.currentTarget.value
                    setParameterValues((current) => ({
                      ...current,
                      [field.key]: value,
                    }))
                    if (phase === 'error') {
                      setPhase('idle')
                      setError(null)
                    }
                  }}
                  className="h-11 w-full rounded-xl border border-border/70 bg-background px-3 text-sm text-foreground outline-none transition placeholder:text-muted-foreground focus:border-gold/60 focus:ring-2 focus:ring-gold/15 disabled:opacity-60"
                />
              </label>
            ))}
          </div>
        ) : null}

        {previewUrls.length ? (
          <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto rounded-2xl bg-secondary/20 p-2">
            {previewUrls.map((previewUrl, index) => (
              <img
                key={previewUrl}
                src={previewUrl}
                alt={`Референс ${index + 1}`}
                className="h-28 w-full rounded-xl object-cover"
              />
            ))}
          </div>
        ) : null}

        <label className="relative flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground transition hover:border-gold/50 hover:text-foreground">
          <input
            ref={inputRef}
            type="file"
            multiple
            accept="image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif"
            className="absolute inset-0 cursor-pointer opacity-0"
            disabled={busy}
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files || [])
              event.currentTarget.value = ''
              void handlePhotos(files)
            }}
          />
          {busy ? (
            <Loader2 className="h-7 w-7 animate-spin text-gold" />
          ) : phase === 'error' ? (
            <RefreshCcw className="h-7 w-7 text-gold" />
          ) : (
            <ImagePlus className="h-7 w-7 text-gold" />
          )}
          <span className="font-medium">
            {phase === 'uploading'
              ? 'Загружаю референсы…'
              : phase === 'generating'
                ? 'Запускаю тренд…'
                : phase === 'error'
                  ? 'Выбрать фото заново'
                  : 'Выбрать фото и запустить'}
          </span>
          {!busy ? (
            <span className="text-xs text-muted-foreground">
              До {MAX_REFERENCES} изображений
            </span>
          ) : null}
        </label>

        {error ? (
          <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => onOpenChange(false)}
        >
          Закрыть
        </Button>
      </DialogContent>
    </Dialog>
  )
}
