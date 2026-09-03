'use client'

import { useMemo, useState, type ReactNode } from 'react'
import { uploadFile } from '@/lib/api'
import {
  generateSeedance25,
  uploadSeedance25Video,
  type Seedance25GenerateResponse,
  type Seedance25Resolution,
  type Seedance25Scenario,
} from '@/lib/seedance25-api'
import type { UploadedFile, VideoModel } from '@/lib/types'

const RATIOS = ['adaptive', '16:9', '9:16', '1:1', '4:3', '3:4', '21:9'] as const
const IMAGE_EXTS = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tiff', 'tif', 'gif'])
const VIDEO_EXTS = new Set(['mp4', 'mov'])
const AUDIO_EXTS = new Set(['wav', 'mp3'])

type Ratio = (typeof RATIOS)[number]

interface Props {
  model?: VideoModel
  credits: number
  isAdmin: boolean
  onQueued?: (result: Seedance25GenerateResponse) => void | Promise<void>
  onSavedReference?: (file: UploadedFile) => void
}

interface RefItem {
  file: UploadedFile
  duration?: number
}

const SCENARIOS: Array<{
  id: Seedance25Scenario
  icon: string
  title: string
  description: string
}> = [
  { id: 'text', icon: '✨', title: 'Видео по описанию', description: 'Создать ролик с нуля по текстовому промпту' },
  { id: 'first_frame', icon: '🖼', title: 'Оживить фото', description: 'Фото станет точным первым кадром ролика' },
  { id: 'first_last', icon: '🎞', title: 'Между двумя кадрами', description: 'Задать точное начало и финал видео' },
  { id: 'multimodal', icon: '🧩', title: 'По референсам', description: 'Смешать фото, видео и аудио как ориентиры' },
]

function extension(name: string) {
  return String(name || '').split('.').pop()?.toLowerCase() || ''
}

function splitSources(raw: string, limit: number) {
  const values = raw
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
  const unique = [...new Set(values)]
  if (unique.length > limit) throw new Error(`Максимум ${limit} ссылок / Asset ID`)
  for (const value of unique) {
    if (!value.startsWith('asset://') && !/^https?:\/\//i.test(value)) {
      throw new Error(`Некорректная ссылка / Asset ID: ${value}`)
    }
  }
  return unique
}

function fileDuration(file: File, kind: 'video' | 'audio'): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const media = document.createElement(kind)
    media.preload = 'metadata'
    media.onloadedmetadata = () => {
      const seconds = Number(media.duration || 0)
      URL.revokeObjectURL(url)
      resolve(seconds || null)
    }
    media.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    media.src = url
  })
}

function Choice({ active, children, onClick, disabled = false }: {
  active?: boolean
  children: ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      aria-pressed={Boolean(active)}
      disabled={disabled}
      onClick={onClick}
      className={`rounded-xl border px-3 py-2.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-45 ${
        active
          ? 'border-cyan/60 bg-cyan/15 text-cyan'
          : 'border-border/50 bg-secondary/35 text-muted-foreground hover:border-border hover:text-foreground'
      }`}
    >
      {children}
    </button>
  )
}

function ScenarioCard({ item, active, onClick }: {
  item: (typeof SCENARIOS)[number]
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`min-h-[88px] rounded-2xl border p-3 text-left transition ${
        active ? 'border-cyan/60 bg-cyan/10' : 'border-border/45 bg-secondary/25 hover:border-border/80'
      }`}
    >
      <div className="flex items-start gap-2.5">
        <span className="text-lg leading-none">{item.icon}</span>
        <div className="min-w-0">
          <div className={`text-sm font-semibold ${active ? 'text-cyan' : 'text-foreground'}`}>{item.title}</div>
          <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{item.description}</div>
        </div>
      </div>
    </button>
  )
}

function Toggle({ value, label, hint, onChange }: {
  value: boolean
  label: string
  hint: string
  onChange: (next: boolean) => void
}) {
  return (
    <button
      type="button"
      aria-pressed={value}
      onClick={() => onChange(!value)}
      className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-3 text-left transition ${
        value ? 'border-cyan/45 bg-cyan/8' : 'border-border/45 bg-secondary/20'
      }`}
    >
      <span className="min-w-0">
        <span className="block text-sm font-medium text-foreground">{label}</span>
        <span className="mt-0.5 block text-[11px] leading-relaxed text-muted-foreground">{hint}</span>
      </span>
      <span className={`relative h-6 w-11 shrink-0 rounded-full ${value ? 'bg-cyan/70' : 'bg-secondary'}`}>
        <span className={`absolute top-1 h-4 w-4 rounded-full bg-foreground transition ${value ? 'left-6' : 'left-1'}`} />
      </span>
    </button>
  )
}

function UploadButton({ label, accept, multiple = false, disabled, onFiles }: {
  label: string
  accept: string
  multiple?: boolean
  disabled?: boolean
  onFiles: (files: File[]) => void
}) {
  return (
    <label className={`flex cursor-pointer items-center justify-center rounded-xl border border-dashed border-cyan/35 bg-cyan/5 px-3 py-3 text-xs font-medium text-cyan ${disabled ? 'pointer-events-none opacity-50' : ''}`}>
      {label}
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files || [])
          if (files.length) onFiles(files)
          event.currentTarget.value = ''
        }}
      />
    </label>
  )
}

function FileRow({ item, onRemove }: { item: RefItem; onRemove: () => void }) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-xl border border-border/40 bg-background/45 px-3 py-2 text-xs">
      <span className="min-w-0 flex-1 truncate text-foreground">{item.file.name}</span>
      {item.duration ? <span className="shrink-0 text-muted-foreground">{item.duration.toFixed(1)}с</span> : null}
      <button type="button" onClick={onRemove} className="shrink-0 px-1 text-destructive" aria-label="Удалить файл">×</button>
    </div>
  )
}

export function Seedance25OfficialForm({ model, credits, isAdmin, onQueued, onSavedReference }: Props) {
  const [scenario, setScenario] = useState<Seedance25Scenario>('text')
  const [resolution, setResolution] = useState<Seedance25Resolution>('720p')
  const [ratio, setRatio] = useState<Ratio>('adaptive')
  const [duration, setDuration] = useState(5)
  const [generateAudio, setGenerateAudio] = useState(true)
  const [returnLastFrame, setReturnLastFrame] = useState(false)
  const [prompt, setPrompt] = useState('')

  const [firstFrame, setFirstFrame] = useState<RefItem | null>(null)
  const [lastFrame, setLastFrame] = useState<RefItem | null>(null)
  const [images, setImages] = useState<RefItem[]>([])
  const [videos, setVideos] = useState<RefItem[]>([])
  const [audios, setAudios] = useState<RefItem[]>([])

  const [firstSource, setFirstSource] = useState('')
  const [lastSource, setLastSource] = useState('')
  const [imageSources, setImageSources] = useState('')
  const [videoSources, setVideoSources] = useState('')
  const [audioSources, setAudioSources] = useState('')

  const [uploading, setUploading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queued, setQueued] = useState<Seedance25GenerateResponse | null>(null)

  const frameMode = scenario === 'first_frame' || scenario === 'first_last'
  const effectiveRatio: Ratio = frameMode ? 'adaptive' : ratio
  const knownVideoSeconds = useMemo(
    () => videos.reduce((sum, item) => sum + (item.duration || 0), 0),
    [videos],
  )
  const hasVideoReference = scenario === 'multimodal' && (videos.length > 0 || videoSources.trim().length > 0)
  const basePrice = useMemo(() => {
    const perSecond = Number(model?.quality_costs?.[resolution] || 0)
    return perSecond ? Math.round(perSecond * duration * 2) / 2 : 0
  }, [duration, model?.quality_costs, resolution])
  const price = hasVideoReference ? basePrice * 2 : basePrice
  const canAfford = isAdmin || !price || credits >= price

  const chooseScenario = (next: Seedance25Scenario) => {
    setScenario(next)
    setError(null)
    if (next === 'first_frame' || next === 'first_last') setRatio('adaptive')
    if (next === 'text') {
      setFirstFrame(null); setLastFrame(null); setImages([]); setVideos([]); setAudios([])
      setFirstSource(''); setLastSource(''); setImageSources(''); setVideoSources(''); setAudioSources('')
    } else if (next === 'first_frame') {
      setLastFrame(null); setImages([]); setVideos([]); setAudios([])
      setLastSource(''); setImageSources(''); setVideoSources(''); setAudioSources('')
    } else if (next === 'first_last') {
      setImages([]); setVideos([]); setAudios([])
      setImageSources(''); setVideoSources(''); setAudioSources('')
    } else {
      setFirstFrame(null); setLastFrame(null); setFirstSource(''); setLastSource('')
    }
  }

  const runUpload = async (fn: () => Promise<void>) => {
    setUploading(true)
    setError(null)
    try {
      await fn()
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Не удалось загрузить файл')
    } finally {
      setUploading(false)
    }
  }

  const uploadImage = async (file: File, target: 'first' | 'last' | 'refs') => {
    if (!IMAGE_EXTS.has(extension(file.name))) throw new Error('Фото: JPEG, PNG, WEBP, BMP, TIFF или GIF')
    if (file.size > 30 * 1024 * 1024) throw new Error('Фото должно быть не больше 30 MB')
    const uploaded = await uploadFile('seedance25_image_reference' as any, file)
    onSavedReference?.(uploaded)
    const item = { file: uploaded }
    if (target === 'first') setFirstFrame(item)
    else if (target === 'last') setLastFrame(item)
    else setImages((current) => [...current, item].slice(0, 30))
  }

  const uploadVideo = async (file: File) => {
    if (!VIDEO_EXTS.has(extension(file.name))) throw new Error('Видео должно быть MP4 или MOV')
    if (file.size > 200 * 1024 * 1024) throw new Error('Видео должно быть не больше 200 MB')
    if (videos.length >= 10) throw new Error('Можно добавить максимум 10 видео')
    const seconds = await fileDuration(file, 'video')
    if (seconds && (seconds < 2 || seconds > 30)) throw new Error('Одно видео должно длиться 2–30 секунд')
    if (seconds && knownVideoSeconds + seconds > 30.01) throw new Error('Видео-референсы суммарно — максимум 30 секунд')
    const uploaded = await uploadSeedance25Video(file)
    onSavedReference?.(uploaded)
    setVideos((current) => [...current, { file: uploaded, duration: seconds || undefined }].slice(0, 10))
  }

  const uploadAudio = async (file: File) => {
    if (!AUDIO_EXTS.has(extension(file.name))) throw new Error('Аудио должно быть WAV или MP3')
    if (file.size > 15 * 1024 * 1024) throw new Error('Аудио должно быть не больше 15 MB')
    if (audios.length >= 10) throw new Error('Можно добавить максимум 10 аудио')
    const seconds = await fileDuration(file, 'audio')
    if (seconds && (seconds < 2 || seconds > 30)) throw new Error('Аудио должно длиться 2–30 секунд')
    const uploaded = await uploadFile('seedance25_audio_reference' as any, file)
    onSavedReference?.(uploaded)
    setAudios((current) => [...current, { file: uploaded, duration: seconds || undefined }].slice(0, 10))
  }

  const submit = async () => {
    setError(null)
    setQueued(null)
    try {
      if (prompt.length > 5000) throw new Error('Промпт — максимум 5000 символов')
      if (duration < 4 || duration > 30) throw new Error('Длительность — от 4 до 30 секунд')

      const first = firstSource.trim() || firstFrame?.file.url || null
      const last = lastSource.trim() || lastFrame?.file.url || null
      const refImages = [...images.map((item) => item.file.url), ...splitSources(imageSources, 30)]
      const refVideos = [...videos.map((item) => item.file.url), ...splitSources(videoSources, 10)]
      const refAudios = [...audios.map((item) => item.file.url), ...splitSources(audioSources, 10)]

      if (scenario === 'text' && !prompt.trim()) throw new Error('Опишите, какое видео нужно создать')
      if (scenario === 'first_frame' && !first) throw new Error('Добавьте первый кадр')
      if (scenario === 'first_last' && (!first || !last)) throw new Error('Добавьте первый и последний кадры')
      if (scenario === 'multimodal' && !refImages.length && !refVideos.length && !refAudios.length) {
        throw new Error('Добавьте хотя бы один фото, видео или аудио-референс')
      }
      if (!canAfford) throw new Error(`Недостаточно бананов. Нужно ${price}🍌`)

      setSubmitting(true)
      const result = await generateSeedance25({
        scenario,
        prompt: prompt.trim(),
        ratio: effectiveRatio,
        duration,
        resolution,
        generateAudio,
        returnLastFrame,
        firstFrameUrl: frameMode ? first : null,
        lastFrameUrl: scenario === 'first_last' ? last : null,
        referenceImages: scenario === 'multimodal' ? [...new Set(refImages)].slice(0, 30) : [],
        referenceVideos: scenario === 'multimodal' ? [...new Set(refVideos)].slice(0, 10) : [],
        referenceAudios: scenario === 'multimodal' ? [...new Set(refAudios)].slice(0, 10) : [],
      })
      setQueued(result)
      await onQueued?.(result)
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Не удалось запустить Seedance 2.5')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="glass min-w-0 space-y-5 overflow-hidden rounded-2xl border border-cyan/25 p-3 sm:p-4">
      <div className="rounded-2xl border border-cyan/25 bg-gradient-to-br from-cyan/10 via-cyan/5 to-transparent p-4">
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-gold/40 bg-gold/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.14em] text-gold">NEW</span>
          <h3 className="font-serif text-xl font-semibold text-foreground">Seedance 2.5</h3>
        </div>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Полный KIE-флоу: текст, первый кадр, первый + последний кадр или мультимодальные фото, видео и аудио-референсы.
        </p>
      </div>

      <section className="space-y-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan/80">Шаг 1</div>
          <h4 className="mt-1 text-sm font-semibold text-foreground">Выберите сценарий</h4>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {SCENARIOS.map((item) => (
            <ScenarioCard key={item.id} item={item} active={scenario === item.id} onClick={() => chooseScenario(item.id)} />
          ))}
        </div>
      </section>

      {frameMode ? (
        <section className="space-y-3 rounded-2xl border border-border/45 bg-secondary/15 p-3 sm:p-4">
          <h4 className="text-sm font-semibold text-foreground">Шаг 2 · {scenario === 'first_last' ? 'Начало и финал' : 'Исходный кадр'}</h4>
          <div className={`grid gap-3 ${scenario === 'first_last' ? 'sm:grid-cols-2' : ''}`}>
            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">Первый кадр</div>
              <UploadButton label={firstFrame ? 'Заменить фото' : '＋ Загрузить фото'} accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif" disabled={uploading} onFiles={(files) => void runUpload(() => uploadImage(files[0], 'first'))} />
              {firstFrame ? <FileRow item={firstFrame} onRemove={() => setFirstFrame(null)} /> : null}
              <input value={firstSource} onChange={(event) => setFirstSource(event.target.value)} placeholder="или https:// / asset://" className="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs text-foreground outline-none focus:border-cyan/50" />
            </div>
            {scenario === 'first_last' ? (
              <div className="space-y-2">
                <div className="text-xs text-muted-foreground">Последний кадр</div>
                <UploadButton label={lastFrame ? 'Заменить фото' : '＋ Загрузить фото'} accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif" disabled={uploading} onFiles={(files) => void runUpload(() => uploadImage(files[0], 'last'))} />
                {lastFrame ? <FileRow item={lastFrame} onRemove={() => setLastFrame(null)} /> : null}
                <input value={lastSource} onChange={(event) => setLastSource(event.target.value)} placeholder="или https:// / asset://" className="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs text-foreground outline-none focus:border-cyan/50" />
              </div>
            ) : null}
          </div>
          <div className="rounded-xl border border-cyan/20 bg-cyan/5 px-3 py-2 text-[11px] text-muted-foreground">
            Для кадрового режима формат берётся из исходного фото автоматически.
          </div>
        </section>
      ) : null}

      {scenario === 'multimodal' ? (
        <section className="space-y-4 rounded-2xl border border-border/45 bg-secondary/15 p-3 sm:p-4">
          <div>
            <h4 className="text-sm font-semibold text-foreground">Шаг 2 · Добавьте референсы</h4>
            <p className="mt-1 text-xs text-muted-foreground">Фото задают внешность и стиль, видео — движение, аудио — звук и ритм.</p>
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="space-y-2 rounded-xl border border-border/35 bg-background/30 p-3">
              <div className="flex justify-between text-sm"><span>📷 Фото</span><span className="text-xs text-muted-foreground">{images.length}/30</span></div>
              <UploadButton label="＋ Добавить фото" multiple accept="image/*,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif" disabled={uploading || images.length >= 30} onFiles={(files) => void runUpload(async () => { for (const file of files.slice(0, 30 - images.length)) await uploadImage(file, 'refs') })} />
              {images.map((item, index) => <FileRow key={`${item.file.id}-${index}`} item={item} onRemove={() => setImages((current) => current.filter((_, i) => i !== index))} />)}
            </div>
            <div className="space-y-2 rounded-xl border border-gold/25 bg-gold/5 p-3">
              <div className="flex justify-between text-sm"><span>🎬 Видео</span><span className="text-xs text-muted-foreground">{videos.length}/10</span></div>
              <UploadButton label="＋ Добавить видео" multiple accept=".mp4,.mov,video/mp4,video/quicktime" disabled={uploading || videos.length >= 10} onFiles={(files) => void runUpload(async () => { for (const file of files.slice(0, 10 - videos.length)) await uploadVideo(file) })} />
              <div className="text-[10px] leading-relaxed text-muted-foreground">MP4/MOV · 2–30с каждое · суммарно до 30с{knownVideoSeconds ? ` · выбрано ${knownVideoSeconds.toFixed(1)}с` : ''}</div>
              {videos.map((item, index) => <FileRow key={`${item.file.id}-${index}`} item={item} onRemove={() => setVideos((current) => current.filter((_, i) => i !== index))} />)}
            </div>
            <div className="space-y-2 rounded-xl border border-border/35 bg-background/30 p-3">
              <div className="flex justify-between text-sm"><span>🎵 Аудио</span><span className="text-xs text-muted-foreground">{audios.length}/10</span></div>
              <UploadButton label="＋ Добавить аудио" multiple accept=".wav,.mp3,audio/wav,audio/mpeg" disabled={uploading || audios.length >= 10} onFiles={(files) => void runUpload(async () => { for (const file of files.slice(0, 10 - audios.length)) await uploadAudio(file) })} />
              <div className="text-[10px] text-muted-foreground">WAV/MP3 · 2–30с</div>
              {audios.map((item, index) => <FileRow key={`${item.file.id}-${index}`} item={item} onRemove={() => setAudios((current) => current.filter((_, i) => i !== index))} />)}
            </div>
          </div>
          <details className="rounded-xl border border-border/35 bg-background/30 px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Добавить URL / Asset ID</summary>
            <div className="mt-3 grid gap-2">
              <textarea rows={2} value={imageSources} onChange={(event) => setImageSources(event.target.value)} placeholder="Фото: по одной ссылке / asset:// на строку" className="rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs" />
              <textarea rows={2} value={videoSources} onChange={(event) => setVideoSources(event.target.value)} placeholder="Видео: по одной ссылке / asset:// на строку" className="rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs" />
              <textarea rows={2} value={audioSources} onChange={(event) => setAudioSources(event.target.value)} placeholder="Аудио: по одной ссылке / asset:// на строку" className="rounded-xl border border-border/50 bg-background/50 px-3 py-2 text-xs" />
            </div>
          </details>
        </section>
      ) : null}

      <section className="space-y-2">
        <h4 className="text-sm font-semibold text-foreground">{scenario === 'text' ? 'Шаг 2' : 'Шаг 3'} · Опишите результат</h4>
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={6} placeholder="Что происходит, как движется камера, какой свет, настроение и звук..." className="w-full resize-y rounded-2xl border border-border/50 bg-background/45 px-3 py-3 text-sm leading-relaxed text-foreground outline-none focus:border-cyan/50" />
        <div className="flex justify-between gap-3 text-[11px] text-muted-foreground">
          <span>{scenario === 'multimodal' ? 'Указывайте роль референсов прямо в тексте.' : 'Камеру и фиксацию объектива задавайте словами в промпте.'}</span>
          <span className={prompt.length > 5000 ? 'text-destructive' : ''}>{prompt.length}/5000</span>
        </div>
      </section>

      <section className="space-y-4 rounded-2xl border border-border/45 bg-secondary/15 p-3 sm:p-4">
        <h4 className="text-sm font-semibold text-foreground">Основные настройки</h4>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <div className="text-xs font-medium">Качество</div>
            <div className="grid grid-cols-2 gap-2">
              {(['480p', '720p'] as Seedance25Resolution[]).map((value) => {
                const rate = Number(model?.quality_costs?.[value] || 0)
                return <Choice key={value} active={resolution === value} onClick={() => setResolution(value)}>{value}{rate ? ` · ${rate}🍌/с` : ''}</Choice>
              })}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between text-xs"><span>Длительность</span><strong className="text-cyan">{duration}с</strong></div>
            <div className="flex items-center gap-2">
              <button type="button" className="h-10 w-10 rounded-xl border border-border/50" onClick={() => setDuration((value) => Math.max(4, value - 1))}>−</button>
              <input type="range" min={4} max={30} value={duration} onChange={(event) => setDuration(Number(event.target.value))} className="min-w-0 flex-1" aria-label="Длительность видео" />
              <button type="button" className="h-10 w-10 rounded-xl border border-border/50" onClick={() => setDuration((value) => Math.min(30, value + 1))}>+</button>
            </div>
          </div>
        </div>
        <div className="space-y-2">
          <div className="text-xs font-medium">Формат кадра</div>
          {frameMode ? (
            <div className="rounded-xl border border-cyan/25 bg-cyan/5 px-3 py-2.5 text-xs text-muted-foreground">Авто — по размеру исходного кадра</div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {RATIOS.map((value) => <Choice key={value} active={effectiveRatio === value} onClick={() => setRatio(value)}>{value === 'adaptive' ? 'Авто' : value}</Choice>)}
            </div>
          )}
        </div>
        <Toggle value={generateAudio} onChange={setGenerateAudio} label="🔊 Сгенерировать звук" hint="Seedance создаст синхронное аудио вместе с видео" />
        <Toggle value={returnLastFrame} onChange={setReturnLastFrame} label="🖼 Вернуть последний кадр" hint="После готового видео бот отдельно пришлёт финальный кадр" />
      </section>

      <div className={`rounded-2xl border p-4 ${hasVideoReference ? 'border-gold/35 bg-gold/7' : 'border-cyan/25 bg-cyan/5'}`}>
        <div className="flex items-end justify-between gap-4">
          <div><div className="text-xs text-muted-foreground">Стоимость</div><div className="mt-1 text-2xl font-bold">{price || 0}🍌</div></div>
          <div className="text-right text-xs text-muted-foreground">{isAdmin ? <>Для админа<br /><span className="font-semibold text-cyan">без списания</span></> : <>Баланс<br /><span className="font-semibold text-foreground">{credits}🍌</span></>}</div>
        </div>
        {hasVideoReference ? <div className="mt-3 text-xs text-gold">🎬 Видео-референс: цена ×2</div> : null}
      </div>

      {error ? <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null}
      {queued ? <div className="rounded-xl border border-cyan/30 bg-cyan/5 p-3 text-sm"><strong>✅ Видео поставлено в очередь</strong><div className="mt-1 break-all font-mono text-xs text-muted-foreground">{queued.task_id}</div></div> : null}

      <button type="button" onClick={() => void submit()} disabled={submitting || uploading || !canAfford} className="w-full rounded-2xl bg-cyan px-4 py-3.5 text-sm font-semibold text-background transition disabled:cursor-not-allowed disabled:opacity-50">
        {submitting ? 'Запускаю Seedance 2.5…' : uploading ? 'Загружаю референсы…' : !canAfford ? `Нужно ${price}🍌` : `Создать видео · ${price || 0}🍌`}
      </button>
    </div>
  )
}
