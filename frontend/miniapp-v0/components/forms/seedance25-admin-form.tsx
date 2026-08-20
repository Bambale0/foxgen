'use client'

import { useMemo, useState } from 'react'
import { uploadFile } from '@/lib/api'
import {
  generateSeedance25,
  type Seedance25GenerateResponse,
  type Seedance25OutputFormat,
  type Seedance25Resolution,
  type Seedance25Scenario,
} from '@/lib/seedance25-api'
import type { UploadedFile, VideoModel } from '@/lib/types'

const RATIOS = ['adaptive', '16:9', '9:16', '1:1', '4:3', '3:4', '21:9'] as const
const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tiff', 'tif', 'gif'])
const VIDEO_EXTENSIONS = new Set(['mp4', 'mov'])
const AUDIO_EXTENSIONS = new Set(['wav', 'mp3'])
const MAX_IMAGE_BYTES = 30 * 1024 * 1024
const MAX_VIDEO_BYTES = 200 * 1024 * 1024
const MAX_AUDIO_BYTES = 15 * 1024 * 1024
const MIN_PIXELS = 640 * 640
const MAX_PIXELS = 834 * 1112

interface Seedance25Model extends VideoModel {
  seedance25_resolutions?: Seedance25Resolution[]
  seedance25_output_formats?: Seedance25OutputFormat[]
  seedance25_scenarios?: Seedance25Scenario[]
  max_audio_references?: number
  supports_generate_audio?: boolean
  supports_return_last_frame?: boolean
  supports_web_search?: boolean
  supports_nsfw_checker?: boolean
  supports_auto_duration?: boolean
  camera_control_via_prompt?: boolean
}

interface RefWithDuration {
  file: UploadedFile
  duration?: number
}

interface Props {
  model?: VideoModel
  onQueued?: (result: Seedance25GenerateResponse) => void | Promise<void>
  onSavedReference?: (file: UploadedFile) => void
}

function extension(name: string) {
  return String(name || '').split('.').pop()?.toLowerCase() || ''
}

function parseLines(value: string, limit: number) {
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of value.split(/\r?\n/)) {
    const item = raw.trim()
    if (!item || seen.has(item)) continue
    if (!item.startsWith('asset://') && !/^https?:\/\//i.test(item)) {
      throw new Error(`Некорректный URL/asset: ${item}`)
    }
    seen.add(item)
    result.push(item)
  }
  if (result.length > limit) throw new Error(`Максимум ${limit} ссылок/asset ID`)
  return result
}

function imageDimensions(file: File): Promise<{ width: number; height: number } | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve({ width: img.naturalWidth, height: img.naturalHeight })
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    img.src = url
  })
}

function videoMetadata(file: File): Promise<{ width: number; height: number; duration: number } | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.onloadedmetadata = () => {
      const value = {
        width: video.videoWidth,
        height: video.videoHeight,
        duration: Number(video.duration || 0),
      }
      URL.revokeObjectURL(url)
      resolve(value)
    }
    video.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    video.src = url
  })
}

function audioDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const audio = document.createElement('audio')
    audio.preload = 'metadata'
    audio.onloadedmetadata = () => {
      const value = Number(audio.duration || 0)
      URL.revokeObjectURL(url)
      resolve(value || null)
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    audio.src = url
  })
}

function validateGeometry(width: number, height: number, video = false) {
  if (!width || !height) return
  if (width < 300 || height < 300 || width > 6000 || height > 6000) {
    throw new Error('Размеры медиа должны быть 300–6000 px по каждой стороне')
  }
  const ratio = width / height
  if (ratio < 0.4 || ratio > 2.5) {
    throw new Error('Соотношение сторон референса должно быть 0.4–2.5')
  }
  if (video) {
    const pixels = width * height
    if (pixels < MIN_PIXELS || pixels > MAX_PIXELS) {
      throw new Error(`Видео должно иметь ${MIN_PIXELS}–${MAX_PIXELS} пикселей на кадр`)
    }
  }
}

function PillButton({ active, children, onClick }: { active?: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-xl border px-3 py-2 text-xs font-medium transition ${
        active
          ? 'border-cyan/60 bg-cyan/15 text-cyan'
          : 'border-border/50 bg-secondary/40 text-muted-foreground hover:text-foreground'
      }`}
    >
      {children}
    </button>
  )
}

function Toggle({ value, label, onChange }: { value: boolean; label: string; onChange: (value: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={`flex items-center justify-between rounded-xl border px-3 py-2 text-left text-xs transition ${
        value ? 'border-cyan/50 bg-cyan/10 text-foreground' : 'border-border/50 bg-secondary/30 text-muted-foreground'
      }`}
    >
      <span>{label}</span>
      <span className="ml-3 font-mono">{value ? 'ON' : 'OFF'}</span>
    </button>
  )
}

function FileChip({ item, onRemove }: { item: RefWithDuration; onRemove: () => void }) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-lg border border-border/40 bg-background/40 px-2 py-1.5 text-xs">
      <span className="min-w-0 flex-1 truncate">{item.file.name}</span>
      {item.duration ? <span className="shrink-0 text-muted-foreground">{item.duration.toFixed(1)}с</span> : null}
      <button type="button" onClick={onRemove} className="shrink-0 text-destructive">×</button>
    </div>
  )
}

export function Seedance25AdminForm({ model: rawModel, onQueued, onSavedReference }: Props) {
  const model = rawModel as Seedance25Model | undefined
  const [scenario, setScenario] = useState<Seedance25Scenario>('text')
  const [resolution, setResolution] = useState<Seedance25Resolution>('720p')
  const [ratio, setRatio] = useState<(typeof RATIOS)[number]>('adaptive')
  const [duration, setDuration] = useState(5)
  const [outputFormat, setOutputFormat] = useState<Seedance25OutputFormat>('mp4')
  const [generateAudio, setGenerateAudio] = useState(true)
  const [returnLastFrame, setReturnLastFrame] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const [nsfwChecker, setNsfwChecker] = useState(false)
  const [prompt, setPrompt] = useState('')

  const [firstFrame, setFirstFrame] = useState<RefWithDuration | null>(null)
  const [lastFrame, setLastFrame] = useState<RefWithDuration | null>(null)
  const [images, setImages] = useState<RefWithDuration[]>([])
  const [videos, setVideos] = useState<RefWithDuration[]>([])
  const [audios, setAudios] = useState<RefWithDuration[]>([])

  const [firstAsset, setFirstAsset] = useState('')
  const [lastAsset, setLastAsset] = useState('')
  const [imageAssets, setImageAssets] = useState('')
  const [videoAssets, setVideoAssets] = useState('')
  const [audioAssets, setAudioAssets] = useState('')

  const [uploading, setUploading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queued, setQueued] = useState<Seedance25GenerateResponse | null>(null)

  const totalKnownVideoDuration = useMemo(
    () => videos.reduce((sum, item) => sum + (item.duration || 0), 0),
    [videos],
  )
  const priceQuote = useMemo(() => {
    const seconds = duration === -1 ? 5 : duration
    const perSecond = Number(model?.quality_costs?.[resolution] ?? 0)
    return perSecond ? Math.round(perSecond * seconds * 2) / 2 : 0
  }, [duration, model?.quality_costs, resolution])

  const uploadImage = async (file: File, target: 'first' | 'last' | 'refs') => {
    const ext = extension(file.name)
    if (!IMAGE_EXTENSIONS.has(ext)) throw new Error('Изображение: JPEG/PNG/WEBP/BMP/TIFF/GIF')
    if (file.size > MAX_IMAGE_BYTES) throw new Error('Изображение — максимум 30 MB')
    const meta = await imageDimensions(file)
    if (meta) validateGeometry(meta.width, meta.height)
    const uploaded = await uploadFile('seedance25_image_reference' as any, file)
    onSavedReference?.(uploaded)
    const item = { file: uploaded }
    if (target === 'first') setFirstFrame(item)
    else if (target === 'last') setLastFrame(item)
    else setImages((current) => [...current, item].slice(0, 30))
  }

  const uploadVideo = async (file: File) => {
    if (videos.length >= 10) throw new Error('Максимум 10 видео-референсов')
    const ext = extension(file.name)
    if (!VIDEO_EXTENSIONS.has(ext)) throw new Error('Видео: MP4 или MOV')
    if (file.size > MAX_VIDEO_BYTES) throw new Error('Видео — максимум 200 MB')
    const meta = await videoMetadata(file)
    if (meta) {
      validateGeometry(meta.width, meta.height, true)
      if (meta.duration < 2 || meta.duration > 30) throw new Error('Длительность одного видео: 2–30 секунд')
      if (totalKnownVideoDuration + meta.duration > 30.01) throw new Error('Суммарная длительность видео-референсов — максимум 30 секунд')
    }
    const uploaded = await uploadFile('seedance25_video_reference' as any, file)
    onSavedReference?.(uploaded)
    setVideos((current) => [...current, { file: uploaded, duration: meta?.duration }].slice(0, 10))
  }

  const uploadAudio = async (file: File) => {
    if (audios.length >= 10) throw new Error('Максимум 10 аудио-референсов')
    const ext = extension(file.name)
    if (!AUDIO_EXTENSIONS.has(ext)) throw new Error('Аудио: WAV или MP3')
    if (file.size > MAX_AUDIO_BYTES) throw new Error('Аудио — максимум 15 MB')
    const seconds = await audioDuration(file)
    if (seconds && (seconds < 2 || seconds > 30)) throw new Error('Длительность аудио: 2–30 секунд')
    const uploaded = await uploadFile('seedance25_audio_reference' as any, file)
    onSavedReference?.(uploaded)
    setAudios((current) => [...current, { file: uploaded, duration: seconds || undefined }].slice(0, 10))
  }

  const withUpload = async (fn: () => Promise<void>) => {
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

  const resetMediaForScenario = (next: Seedance25Scenario) => {
    setScenario(next)
    setError(null)
    if (next === 'text') {
      setFirstFrame(null); setLastFrame(null); setImages([]); setVideos([]); setAudios([])
      setFirstAsset(''); setLastAsset(''); setImageAssets(''); setVideoAssets(''); setAudioAssets('')
    } else if (next === 'first_frame') {
      setLastFrame(null); setImages([]); setVideos([]); setAudios([])
      setLastAsset(''); setImageAssets(''); setVideoAssets(''); setAudioAssets('')
    } else if (next === 'first_last') {
      setImages([]); setVideos([]); setAudios([])
      setImageAssets(''); setVideoAssets(''); setAudioAssets('')
    } else {
      setFirstFrame(null); setLastFrame(null); setFirstAsset(''); setLastAsset('')
    }
  }

  const submit = async () => {
    setError(null)
    setQueued(null)
    if (prompt.length > 5000) {
      setError('Промпт — максимум 5000 символов')
      return
    }

    try {
      const advancedImages = parseLines(imageAssets, 30)
      const advancedVideos = parseLines(videoAssets, 10)
      const advancedAudios = parseLines(audioAssets, 10)
      const first = firstAsset.trim() || firstFrame?.file.url || null
      const last = lastAsset.trim() || lastFrame?.file.url || null
      if (first && !first.startsWith('asset://') && !/^https?:\/\//i.test(first)) throw new Error('Первый кадр должен быть URL или asset:// ID')
      if (last && !last.startsWith('asset://') && !/^https?:\/\//i.test(last)) throw new Error('Последний кадр должен быть URL или asset:// ID')

      if (scenario === 'text' && !prompt.trim()) throw new Error('Для Text-to-Video нужен промпт')
      if (scenario === 'first_frame' && !first) throw new Error('Добавьте первый кадр')
      if (scenario === 'first_last' && (!first || !last)) throw new Error('Добавьте первый и последний кадры')

      const refsImages = [...images.map((item) => item.file.url), ...advancedImages]
      const refsVideos = [...videos.map((item) => item.file.url), ...advancedVideos]
      const refsAudios = [...audios.map((item) => item.file.url), ...advancedAudios]
      if (new Set(refsImages).size > 30) throw new Error('Максимум 30 image refs')
      if (new Set(refsVideos).size > 10) throw new Error('Максимум 10 video refs')
      if (new Set(refsAudios).size > 10) throw new Error('Максимум 10 audio refs')
      if (scenario === 'multimodal' && !refsImages.length && !refsVideos.length && !refsAudios.length) {
        throw new Error('Добавьте хотя бы один мультимодальный референс')
      }

      setSubmitting(true)
      const result = await generateSeedance25({
        scenario,
        prompt: prompt.trim(),
        ratio,
        duration,
        resolution,
        outputFormat,
        generateAudio,
        returnLastFrame,
        webSearch,
        nsfwChecker,
        firstFrameUrl: scenario === 'first_frame' || scenario === 'first_last' ? first : null,
        lastFrameUrl: scenario === 'first_last' ? last : null,
        referenceImages: scenario === 'multimodal' ? refsImages : [],
        referenceVideos: scenario === 'multimodal' ? refsVideos : [],
        referenceAudios: scenario === 'multimodal' ? refsAudios : [],
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
    <div className="glass min-w-0 space-y-5 overflow-hidden rounded-2xl border border-cyan/30 p-3 sm:p-4">
      <div className="rounded-xl border border-cyan/30 bg-cyan/5 p-3">
        <p className="text-xs uppercase tracking-[0.18em] text-cyan">Admin preview</p>
        <h3 className="mt-1 font-serif text-lg font-semibold text-foreground">Bytedance Seedance 2.5</h3>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          Полный Kie-контур: Text-to-Video, первый кадр, первый+последний кадр и мультимодальные image/video/audio refs. Камеру, lens lock и движение задавайте прямо в промпте — отдельного API-поля у модели нет.
        </p>
      </div>

      <section className="space-y-2">
        <label className="text-sm font-medium">Сценарий</label>
        <div className="grid grid-cols-2 gap-2">
          <PillButton active={scenario === 'text'} onClick={() => resetMediaForScenario('text')}>✍️ Текст</PillButton>
          <PillButton active={scenario === 'first_frame'} onClick={() => resetMediaForScenario('first_frame')}>🖼 Первый кадр</PillButton>
          <PillButton active={scenario === 'first_last'} onClick={() => resetMediaForScenario('first_last')}>🎞 Первый + последний</PillButton>
          <PillButton active={scenario === 'multimodal'} onClick={() => resetMediaForScenario('multimodal')}>🧩 Мультимодально</PillButton>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <label className="text-sm font-medium">Качество</label>
          <div className="grid grid-cols-2 gap-2">
            {(['480p', '720p'] as Seedance25Resolution[]).map((value) => (
              <PillButton key={value} active={resolution === value} onClick={() => setResolution(value)}>{value}</PillButton>
            ))}
          </div>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium">Выходной файл</label>
          <div className="grid grid-cols-2 gap-2">
            {(['mp4', 'mov'] as Seedance25OutputFormat[]).map((value) => (
              <PillButton key={value} active={outputFormat === value} onClick={() => setOutputFormat(value)}>{value.toUpperCase()}</PillButton>
            ))}
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <label className="text-sm font-medium">Формат кадра</label>
        <div className="flex flex-wrap gap-2">
          {RATIOS.map((value) => (
            <PillButton key={value} active={ratio === value} onClick={() => setRatio(value)}>{value}</PillButton>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <label className="text-sm font-medium">Длительность</label>
          <span className="text-xs text-muted-foreground">{duration === -1 ? 'Auto' : `${duration} сек`}</span>
        </div>
        <div className="flex items-center gap-2">
          <PillButton active={duration === -1} onClick={() => setDuration(-1)}>Auto</PillButton>
          <button type="button" onClick={() => setDuration((value) => Math.max(4, value === -1 ? 5 : value - 1))} className="rounded-xl border border-border/50 px-3 py-2 text-sm">−</button>
          <input
            type="range"
            min={4}
            max={30}
            value={duration === -1 ? 5 : duration}
            onChange={(event) => setDuration(Number(event.target.value))}
            className="min-w-0 flex-1"
          />
          <button type="button" onClick={() => setDuration((value) => Math.min(30, value === -1 ? 5 : value + 1))} className="rounded-xl border border-border/50 px-3 py-2 text-sm">+</button>
        </div>
      </section>

      <section className="grid gap-2 sm:grid-cols-2">
        <Toggle value={generateAudio} onChange={setGenerateAudio} label="🔊 Генерировать аудио" />
        <Toggle value={returnLastFrame} onChange={setReturnLastFrame} label="🖼 Вернуть последний кадр" />
        <Toggle value={webSearch} onChange={setWebSearch} label="🌐 Web search" />
        <Toggle value={nsfwChecker} onChange={setNsfwChecker} label="🛡 Kie NSFW checker" />
      </section>

      {(scenario === 'first_frame' || scenario === 'first_last') ? (
        <section className="space-y-3 rounded-xl border border-border/50 p-3">
          <div className="space-y-2">
            <label className="text-sm font-medium">Первый кадр</label>
            <input type="file" accept=".jpg,.jpeg,.png,.webp,.bmp,.tiff,.tif,.gif,image/*" disabled={uploading} onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void withUpload(() => uploadImage(file, 'first'))
              event.currentTarget.value = ''
            }} className="block w-full text-xs" />
            {firstFrame ? <FileChip item={firstFrame} onRemove={() => setFirstFrame(null)} /> : null}
            <input value={firstAsset} onChange={(event) => setFirstAsset(event.target.value)} placeholder="или asset://asset-id / https://..." className="w-full rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs outline-none focus:border-cyan/50" />
          </div>
          {scenario === 'first_last' ? (
            <div className="space-y-2">
              <label className="text-sm font-medium">Последний кадр</label>
              <input type="file" accept=".jpg,.jpeg,.png,.webp,.bmp,.tiff,.tif,.gif,image/*" disabled={uploading} onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void withUpload(() => uploadImage(file, 'last'))
                event.currentTarget.value = ''
              }} className="block w-full text-xs" />
              {lastFrame ? <FileChip item={lastFrame} onRemove={() => setLastFrame(null)} /> : null}
              <input value={lastAsset} onChange={(event) => setLastAsset(event.target.value)} placeholder="или asset://asset-id / https://..." className="w-full rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs outline-none focus:border-cyan/50" />
            </div>
          ) : null}
        </section>
      ) : null}

      {scenario === 'multimodal' ? (
        <section className="space-y-4 rounded-xl border border-border/50 p-3">
          <div className="space-y-2">
            <div className="flex items-center justify-between"><label className="text-sm font-medium">Фото-референсы</label><span className="text-xs text-muted-foreground">{images.length}/30</span></div>
            <input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.bmp,.tiff,.tif,.gif,image/*" disabled={uploading || images.length >= 30} onChange={(event) => {
              const files = Array.from(event.target.files || []).slice(0, Math.max(0, 30 - images.length))
              if (files.length) void withUpload(async () => { for (const file of files) await uploadImage(file, 'refs') })
              event.currentTarget.value = ''
            }} className="block w-full text-xs" />
            <div className="space-y-1">{images.map((item, index) => <FileChip key={`${item.file.id}-${index}`} item={item} onRemove={() => setImages((current) => current.filter((_, idx) => idx !== index))} />)}</div>
            <textarea value={imageAssets} onChange={(event) => setImageAssets(event.target.value)} rows={2} placeholder="asset:// или https:// image refs, по одному на строку" className="w-full resize-y rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs outline-none focus:border-cyan/50" />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between"><label className="text-sm font-medium">Видео-референсы</label><span className="text-xs text-muted-foreground">{videos.length}/10 · известных {totalKnownVideoDuration.toFixed(1)}/30с</span></div>
            <input type="file" multiple accept=".mp4,.mov,video/mp4,video/quicktime" disabled={uploading || videos.length >= 10} onChange={(event) => {
              const files = Array.from(event.target.files || []).slice(0, Math.max(0, 10 - videos.length))
              if (files.length) void withUpload(async () => { for (const file of files) await uploadVideo(file) })
              event.currentTarget.value = ''
            }} className="block w-full text-xs" />
            <p className="text-[11px] leading-relaxed text-muted-foreground">MP4/MOV, 2–30с каждый, суммарно ≤30с, 24–60 FPS. FPS повторно проверяется сервером через ffprobe.</p>
            <div className="space-y-1">{videos.map((item, index) => <FileChip key={`${item.file.id}-${index}`} item={item} onRemove={() => setVideos((current) => current.filter((_, idx) => idx !== index))} />)}</div>
            <textarea value={videoAssets} onChange={(event) => setVideoAssets(event.target.value)} rows={2} placeholder="asset:// или https:// video refs, по одному на строку" className="w-full resize-y rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs outline-none focus:border-cyan/50" />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between"><label className="text-sm font-medium">Аудио-референсы</label><span className="text-xs text-muted-foreground">{audios.length}/10</span></div>
            <input type="file" multiple accept=".wav,.mp3,audio/wav,audio/mpeg" disabled={uploading || audios.length >= 10} onChange={(event) => {
              const files = Array.from(event.target.files || []).slice(0, Math.max(0, 10 - audios.length))
              if (files.length) void withUpload(async () => { for (const file of files) await uploadAudio(file) })
              event.currentTarget.value = ''
            }} className="block w-full text-xs" />
            <div className="space-y-1">{audios.map((item, index) => <FileChip key={`${item.file.id}-${index}`} item={item} onRemove={() => setAudios((current) => current.filter((_, idx) => idx !== index))} />)}</div>
            <textarea value={audioAssets} onChange={(event) => setAudioAssets(event.target.value)} rows={2} placeholder="asset:// или https:// audio refs, по одному на строку" className="w-full resize-y rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-xs outline-none focus:border-cyan/50" />
          </div>
        </section>
      ) : null}

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <label className="text-sm font-medium">Промпт</label>
          <span className={`text-xs ${prompt.length > 5000 ? 'text-destructive' : 'text-muted-foreground'}`}>{prompt.length}/5000</span>
        </div>
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          rows={7}
          placeholder="Опишите сцену, движение объектов и камеры. Например: slow dolly-in, lock focal length, no zoom, stable lens..."
          className="w-full resize-y rounded-xl border border-border/50 bg-background/40 px-3 py-3 text-sm outline-none focus:border-cyan/50"
        />
      </section>

      <div className="rounded-xl border border-gold/20 bg-gold/5 p-3 text-xs">
        <div className="flex items-center justify-between gap-3"><span className="text-muted-foreground">Цена по текущему админ-прайсу</span><strong>{priceQuote ? `${priceQuote}🍌` : 'из конфигурации'}</strong></div>
        <p className="mt-1 text-muted-foreground">Admin preview запускается бесплатно. Для Auto показан ориентир за 5 секунд.</p>
      </div>

      {error ? <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null}
      {queued ? (
        <div className="rounded-xl border border-cyan/30 bg-cyan/5 p-3 text-sm">
          <strong>✅ Seedance 2.5 поставлена в очередь</strong>
          <div className="mt-1 font-mono text-xs text-muted-foreground">{queued.task_id}</div>
          <p className="mt-1 text-xs text-muted-foreground">Результат придёт через dedicated Kie webhook; polling fallback также включён.</p>
        </div>
      ) : null}

      <button
        type="button"
        disabled={submitting || uploading || prompt.length > 5000}
        onClick={() => void submit()}
        className="w-full rounded-xl border border-cyan/50 bg-cyan/15 px-4 py-3 text-sm font-semibold text-cyan transition hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? 'Запускаю Seedance 2.5…' : uploading ? 'Загружаю медиа…' : '🚀 Запустить Seedance 2.5'}
      </button>
    </div>
  )
}
