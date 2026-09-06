'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ImagePlus, Loader2, RefreshCcw, Sparkles } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { uploadFile } from '@/lib/api'
import { runTrend } from '@/lib/trend-api'
import { mediaAspectRatio, normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'
import type { PromptItem, TrendUserField, UploadedFile } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

type RunnerPhase = 'idle' | 'uploading' | 'generating' | 'error'
interface TrendRunnerDialogProps { trend: PromptItem | null; open: boolean; onOpenChange: (open: boolean) => void }
const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'avif'])
const MAX_REFERENCES = 12

function validField(field: TrendUserField, value: string): boolean {
  const clean = value.trim()
  if (!clean) return field.required === false
  if (field.type === 'number') {
    const n = Number(clean.replace(',', '.'))
    return Number.isFinite(n) && (typeof field.min !== 'number' || n >= field.min) && (typeof field.max !== 'number' || n <= field.max)
  }
  return clean.length <= Math.max(1, Math.min(160, field.max_length || 80))
}

export function TrendRunnerDialog({ trend, open, onOpenChange }: TrendRunnerDialogProps) {
  const { addTask, setCredits, setTaskDetail, selectTask, addSavedReference } = useApp()
  const inputRef = useRef<HTMLInputElement>(null)
  const previewRefs = useRef<string[]>([])
  const [phase, setPhase] = useState<RunnerPhase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [previewUrls, setPreviewUrls] = useState<string[]>([])
  const [uploadedReferences, setUploadedReferences] = useState<UploadedFile[]>([])
  const [userValues, setUserValues] = useState<Record<string, string>>({})
  const busy = phase === 'uploading' || phase === 'generating'
  const isVideoTrend = trend?.generation_settings?.kind === 'video'
  const userFields = useMemo(() => (trend?.generation_settings?.user_fields || []).slice(0, 6), [trend?.generation_settings?.user_fields])
  const personalizedReady = uploadedReferences.length > 0 && userFields.every((field) => validField(field, userValues[field.key] || ''))

  const clearPreviews = useCallback(() => {
    for (const url of previewRefs.current) if (url.startsWith('blob:')) URL.revokeObjectURL(url)
    previewRefs.current = []
    setPreviewUrls([])
  }, [])

  useEffect(() => {
    if (open) {
      setUploadedReferences([])
      setUserValues(Object.fromEntries(userFields.map((field) => [field.key, field.default_value || ''])))
      setPhase('idle')
      setError(null)
      return
    }
    clearPreviews()
    if (inputRef.current) inputRef.current.value = ''
  }, [clearPreviews, open, trend?.id, userFields])
  useEffect(() => clearPreviews, [clearPreviews])

  const finish = (result: Awaited<ReturnType<typeof runTrend>>) => {
    addTask(result.task); setCredits(result.credits); if (result.detail) setTaskDetail(result.detail); selectTask(result.task); onOpenChange(false)
  }

  const handlePhotos = async (files: File[]) => {
    if (!trend || busy || !files.length) return
    if (files.length > MAX_REFERENCES) { setPhase('error'); setError(`Можно загрузить максимум ${MAX_REFERENCES} фото`); return }
    const invalid = files.find((file) => !file.type.startsWith('image/') && !IMAGE_EXTENSIONS.has(file.name.split('.').pop()?.toLowerCase() || ''))
    if (invalid) { setPhase('error'); setError(`Файл «${invalid.name}» не является изображением`); return }
    clearPreviews()
    const local = files.map((file) => URL.createObjectURL(file)); previewRefs.current = local; setPreviewUrls(local); setError(null); setPhase('uploading')
    try {
      const uploaded = await Promise.all(files.map((file) => uploadFile('image_reference', file)))
      for (const item of uploaded) addSavedReference(item)
      if (userFields.length) { setUploadedReferences(uploaded); setPhase('idle'); return }
      setPhase('generating'); finish(await runTrend(trend.id, uploaded.map((item) => item.url)))
    } catch (cause) { setPhase('error'); setError(cause instanceof Error ? cause.message : 'Не удалось запустить тренд') }
  }

  const generate = async () => {
    if (!trend || busy || !personalizedReady) return
    setPhase('generating'); setError(null)
    try { finish(await runTrend(trend.id, uploadedReferences.map((item) => item.url), userValues)) }
    catch (cause) { setPhase('error'); setError(cause instanceof Error ? cause.message : 'Не удалось запустить тренд') }
  }

  return <Dialog open={open} onOpenChange={(next) => { if (!busy) onOpenChange(next) }}>
    <DialogContent className="max-w-lg border-border/60 bg-background p-4">
      <DialogTitle className="pr-8 font-serif text-lg">{trend?.title || 'Повторить тренд'}</DialogTitle>
      {trend?.preview_url ? isVideoTrend
        ? <video src={videoPreviewFrameUrl(trend.preview_url)} muted loop autoPlay controls playsInline preload="metadata" style={{ aspectRatio: mediaAspectRatio(trend.generation_settings?.ratio) }} className="mx-auto max-h-[42vh] max-w-full rounded-2xl bg-black object-contain" />
        : <img src={normalizeMiniAppMediaUrl(trend.preview_url)} alt={trend.title} className="max-h-[42vh] w-full rounded-2xl object-contain" /> : null}
      <div className="rounded-2xl border border-gold/25 bg-gold/10 p-4 text-center">
        <Sparkles className="mx-auto h-6 w-6 text-gold" />
        <p className="mt-2 text-sm font-semibold text-foreground">{userFields.length ? 'Загрузите фото и заполните свои данные' : 'Загрузите свои фото'}</p>
        <p className="mt-1 text-xs text-muted-foreground">{userFields.length ? 'Генерация начнётся после заполнения полей и нажатия кнопки.' : 'После загрузки генерация начнётся сразу. Все параметры уже настроены.'}</p>
      </div>
      {previewUrls.length ? <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto rounded-2xl bg-secondary/20 p-2">{previewUrls.map((url, i) => <img key={url} src={url} alt={`Референс ${i + 1}`} className="h-28 w-full rounded-xl object-cover" />)}</div> : null}
      <label className="relative flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground transition hover:border-gold/50 hover:text-foreground">
        <input ref={inputRef} type="file" multiple accept="image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif" className="absolute inset-0 cursor-pointer opacity-0" disabled={busy} onChange={(event) => { const files = Array.from(event.currentTarget.files || []); event.currentTarget.value = ''; void handlePhotos(files) }} />
        {busy ? <Loader2 className="h-7 w-7 animate-spin text-gold" /> : phase === 'error' ? <RefreshCcw className="h-7 w-7 text-gold" /> : <ImagePlus className="h-7 w-7 text-gold" />}
        <span className="font-medium">{phase === 'uploading' ? 'Загружаю референсы…' : phase === 'generating' ? 'Запускаю тренд…' : uploadedReferences.length ? 'Фото загружены ✓' : 'Выбрать фото'}</span>
      </label>
      {userFields.length ? <div className="space-y-3 rounded-2xl border border-border/60 bg-secondary/20 p-3">
        <div><p className="text-sm font-semibold text-foreground">Персонализируйте шаблон</p><p className="mt-1 text-[11px] text-muted-foreground">Заполните только свои данные. Скрытый prompt останется скрытым.</p></div>
        {userFields.map((field) => { const value = userValues[field.key] || ''; const valid = validField(field, value); return <label key={field.key} className="block space-y-1.5"><span className="text-xs font-medium text-foreground">{field.label}{field.required === false ? '' : ' *'}</span><input type="text" inputMode={field.type === 'number' ? 'decimal' : 'text'} value={value} placeholder={field.placeholder || ''} disabled={busy} aria-invalid={Boolean(value) && !valid} onChange={(e) => setUserValues((cur) => ({ ...cur, [field.key]: e.target.value }))} className="h-11 w-full rounded-xl border border-border/70 bg-background/55 px-3 text-sm" />{value && !valid ? <p className="text-[10px] text-destructive">Проверьте значение поля «{field.label}»</p> : null}</label> })}
        <Button type="button" disabled={busy || !personalizedReady} onClick={() => void generate()}>{phase === 'generating' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{phase === 'generating' ? 'Генерирую…' : 'Сгенерировать'}</Button>
      </div> : null}
      {error ? <p className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</p> : null}
      <Button type="button" variant="secondary" disabled={busy} onClick={() => onOpenChange(false)}>Закрыть</Button>
    </DialogContent>
  </Dialog>
}
