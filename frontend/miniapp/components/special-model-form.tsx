'use client'

import { useEffect, useState } from 'react'
import { miniAppApi } from '@/lib/api'
import { useApp } from '@/lib/app-context'
import type { ModelDefinition } from '@/lib/types'

function randomId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function Wrapper({ model, children }: { model: ModelDefinition; children: React.ReactNode }) {
  const { selectModel } = useApp()
  return (
    <section className="form-card" data-testid="special-model-form">
      <div className="form-head">
        <button className="back" onClick={() => selectModel(null)}>‹</button>
        <div><span className="eyebrow">DEDICATED WORKFLOW</span><h2 style={{ margin: '5px 0 0' }}>{model.title}</h2></div>
      </div>
      {children}
    </section>
  )
}

function MotionForm({ model }: { model: ModelDefinition }) {
  const { refreshGenerations, setActiveTab, selectModel } = useApp()
  const [prompt, setPrompt] = useState('')
  const [image, setImage] = useState<File | null>(null)
  const [video, setVideo] = useState<File | null>(null)
  const [mode, setMode] = useState<'720p' | '1080p'>('720p')
  const [orientation, setOrientation] = useState<'image' | 'video'>('image')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!image || !video || !prompt.trim()) { setError('Нужны изображение, видео и промпт.'); return }
    setBusy(true); setError(null)
    try {
      const [imageInput, videoInput] = await Promise.all([
        miniAppApi.uploadMotion('image', image),
        miniAppApi.uploadMotion('video', video),
      ])
      await miniAppApi.submitMotion({
        prompt: prompt.trim(), image_storage_key: imageInput.storage_key, video_storage_key: videoInput.storage_key,
        mode, character_orientation: orientation, background_source: 'input_video',
      })
      await refreshGenerations(); selectModel(null); setActiveTab('works')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Motion Control не запустился') }
    finally { setBusy(false) }
  }

  return <Wrapper model={model}>
    <label className="form-field"><span>Промпт</span><textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} /></label>
    <label className="form-field"><span>Изображение персонажа</span><input type="file" accept="image/jpeg,image/png" onChange={(e) => setImage(e.target.files?.[0] ?? null)} /></label>
    <label className="form-field"><span>Видео движения</span><input type="file" accept="video/mp4,video/quicktime" onChange={(e) => setVideo(e.target.files?.[0] ?? null)} /></label>
    <label className="form-field"><span>Режим</span><select value={mode} onChange={(e) => setMode(e.target.value as '720p'|'1080p')}><option value="720p">720p</option><option value="1080p">1080p</option></select></label>
    <label className="form-field"><span>Ориентация персонажа</span><select value={orientation} onChange={(e) => setOrientation(e.target.value as 'image'|'video')}><option value="image">По изображению</option><option value="video">По видео</option></select></label>
    {error && <div className="notice error">{error}</div>}
    <button className="primary" disabled={busy} onClick={() => void submit()}>{busy ? 'Загружаем и запускаем…' : 'Запустить Motion Control'}</button>
  </Wrapper>
}

type SunoSource = { generation_id: string; audio_id: string; title?: string | null; duration_seconds?: number | null; preview_url?: string | null }

function SunoExtendForm({ model }: { model: ModelDefinition }) {
  const { refreshGenerations, setActiveTab, selectModel } = useApp()
  const [sources, setSources] = useState<SunoSource[]>([])
  const [sourceKey, setSourceKey] = useState('')
  const [prompt, setPrompt] = useState('')
  const [style, setStyle] = useState('')
  const [title, setTitle] = useState('')
  const [continueAt, setContinueAt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { void miniAppApi.request<{items:SunoSource[]}>('/music/suno/sources?limit=100').then((data) => setSources(data.items)).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason))) }, [])
  const selected = sources.find((item) => `${item.generation_id}:${item.audio_id}` === sourceKey)
  async function submit() {
    if (!selected) { setError('Выберите исходный трек.'); return }
    setBusy(true); setError(null)
    try {
      await miniAppApi.request('/music/suno/extend', {
        method: 'POST', headers: {'Content-Type':'application/json','Idempotency-Key':randomId()},
        body: JSON.stringify({ source_generation_id:selected.generation_id, audio_id:selected.audio_id, prompt, style, title, continue_at:continueAt ? Number(continueAt) : null }),
      })
      await refreshGenerations(); selectModel(null); setActiveTab('works')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Suno Extend не запустился') }
    finally { setBusy(false) }
  }
  return <Wrapper model={model}>
    <label className="form-field"><span>Исходный трек</span><select value={sourceKey} onChange={(e)=>setSourceKey(e.target.value)}><option value="">Выберите…</option>{sources.map((item)=><option key={`${item.generation_id}:${item.audio_id}`} value={`${item.generation_id}:${item.audio_id}`}>{item.title || item.audio_id}{item.duration_seconds ? ` · ${item.duration_seconds.toFixed(0)}с` : ''}</option>)}</select></label>
    <label className="form-field"><span>Промпт</span><textarea value={prompt} onChange={(e)=>setPrompt(e.target.value)} /></label>
    <label className="form-field"><span>Стиль</span><input value={style} onChange={(e)=>setStyle(e.target.value)} /></label>
    <label className="form-field"><span>Название</span><input value={title} onChange={(e)=>setTitle(e.target.value)} /></label>
    <label className="form-field"><span>Продолжить с секунды</span><input type="number" min="0.1" step="0.1" value={continueAt} onChange={(e)=>setContinueAt(e.target.value)} /></label>
    {error && <div className="notice error">{error}</div>}
    <button className="primary" disabled={busy || !selected} onClick={() => void submit()}>{busy ? 'Запускаем…' : 'Продолжить трек'}</button>
  </Wrapper>
}

function SunoUploadForm({ model, kind }: { model: ModelDefinition; kind: 'cover' | 'extend' }) {
  const { refreshGenerations, setActiveTab, selectModel } = useApp()
  const [file, setFile] = useState<File | null>(null)
  const [prompt, setPrompt] = useState('')
  const [style, setStyle] = useState('')
  const [title, setTitle] = useState('')
  const [continueAt, setContinueAt] = useState('')
  const [instrumental, setInstrumental] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!file) { setError('Выберите аудиофайл.'); return }
    setBusy(true); setError(null)
    try {
      const upload = await miniAppApi.uploadInput(file)
      const path = kind === 'cover' ? '/music/suno/upload-cover' : '/music/suno/upload-extend'
      const body: Record<string, unknown> = { input_storage_key: upload.storage_key, prompt, style, title, instrumental }
      if (kind === 'cover') body.custom_mode = Boolean(prompt || style || title)
      else { body.default_param_flag = false; body.continue_at = continueAt ? Number(continueAt) : null }
      await miniAppApi.request(path, { method:'POST', headers:{'Content-Type':'application/json','Idempotency-Key':randomId()}, body:JSON.stringify(body) })
      await refreshGenerations(); selectModel(null); setActiveTab('works')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Suno не запустился') }
    finally { setBusy(false) }
  }
  return <Wrapper model={model}>
    <label className="form-field"><span>Аудиофайл</span><input type="file" accept="audio/mpeg,audio/mp4,audio/wav" onChange={(e)=>setFile(e.target.files?.[0] ?? null)} /></label>
    <label className="form-field"><span>Промпт</span><textarea value={prompt} onChange={(e)=>setPrompt(e.target.value)} /></label>
    <label className="form-field"><span>Стиль</span><input value={style} onChange={(e)=>setStyle(e.target.value)} /></label>
    <label className="form-field"><span>Название</span><input value={title} onChange={(e)=>setTitle(e.target.value)} /></label>
    {kind === 'extend' && <label className="form-field"><span>Продолжить с секунды</span><input type="number" min="0.1" step="0.1" value={continueAt} onChange={(e)=>setContinueAt(e.target.value)} /></label>}
    <label className="form-field checkbox"><input type="checkbox" checked={instrumental} onChange={(e)=>setInstrumental(e.target.checked)} /><span>Инструментал</span></label>
    {error && <div className="notice error">{error}</div>}
    <button className="primary" disabled={busy} onClick={() => void submit()}>{busy ? 'Загружаем и запускаем…' : kind === 'cover' ? 'Создать cover' : 'Продолжить загруженный трек'}</button>
  </Wrapper>
}

export function SpecialModelForm({ model }: { model: ModelDefinition }) {
  if (model.slug === 'kling-3-motion-control') return <MotionForm model={model} />
  if (model.slug === 'suno-v5-extend') return <SunoExtendForm model={model} />
  if (model.slug === 'suno-v5-upload-cover') return <SunoUploadForm model={model} kind="cover" />
  if (model.slug === 'suno-v5-upload-extend') return <SunoUploadForm model={model} kind="extend" />
  return null
}

export function isSpecialModel(slug: string) {
  return ['kling-3-motion-control','suno-v5-extend','suno-v5-upload-cover','suno-v5-upload-extend'].includes(slug)
}
