'use client'

import { useEffect, useMemo, useState } from 'react'
import { miniAppApi } from '@/lib/api'
import { useApp } from '@/lib/app-context'
import type { JsonSchemaProperty, ModelDefinition } from '@/lib/types'

const MEDIA_FIELDS = new Set([
  'image_url', 'image_urls', 'image_input', 'input_urls', 'video_url', 'video_urls', 'audio_url',
  'first_frame_url', 'last_frame_url', 'reference_image_urls', 'reference_video_urls', 'reference_audio_urls',
])

const LABELS: Record<string, string> = {
  prompt: 'Промпт', negative_prompt: 'Негативный промпт', aspect_ratio: 'Соотношение сторон', quality: 'Качество',
  output_format: 'Формат', resolution: 'Разрешение', duration: 'Длительность', generate_audio: 'Сгенерировать аудио',
  image_url: 'Изображение', image_urls: 'Изображения', video_url: 'Видео', audio_url: 'Аудио',
  first_frame_url: 'Первый кадр', last_frame_url: 'Последний кадр', reference_image_urls: 'Референсы изображений',
  reference_video_urls: 'Референсы видео', reference_audio_urls: 'Референсы аудио',
}

function titleOf(name: string, schema: JsonSchemaProperty) {
  return schema.title || LABELS[name] || name.replaceAll('_', ' ')
}

function normalizedType(schema: JsonSchemaProperty) {
  if (Array.isArray(schema.type)) return schema.type.find((value) => value !== 'null') ?? 'string'
  if (schema.type) return schema.type
  const union = schema.anyOf ?? schema.oneOf
  return union?.map((item) => item.type).find((value) => value && value !== 'null') ?? 'string'
}

function enumValues(schema: JsonSchemaProperty) {
  if (schema.enum) return schema.enum
  for (const candidate of schema.anyOf ?? schema.oneOf ?? []) if (candidate.enum) return candidate.enum
  return null
}

function initialInput(model: ModelDefinition, seed: Record<string, unknown> = {}) {
  const result: Record<string, unknown> = { ...(model.defaults ?? {}) }
  for (const [name, schema] of Object.entries(model.input_schema?.properties ?? {})) {
    if (result[name] !== undefined) continue
    if (schema.default !== undefined) result[name] = schema.default
    else if (normalizedType(schema) === 'boolean') result[name] = false
    else if (normalizedType(schema) === 'array') result[name] = []
  }
  return { ...result, ...seed }
}

function coerce(raw: string, schema: JsonSchemaProperty) {
  const type = normalizedType(schema)
  if (type === 'integer') return raw === '' ? undefined : Number.parseInt(raw, 10)
  if (type === 'number') return raw === '' ? undefined : Number(raw)
  if (type === 'array') return raw.split('\n').map((item) => item.trim()).filter(Boolean)
  return raw
}

function acceptFor(name: string) {
  if (name.includes('video')) return 'video/mp4,video/webm,video/quicktime'
  if (name.includes('audio')) return 'audio/mpeg,audio/mp4,audio/wav'
  return 'image/jpeg,image/png,image/webp'
}

export function ModelForm({ model }: { model: ModelDefinition }) {
  const { submitModel, selectModel, busy, bootstrap, draftInput } = useApp()
  const [input, setInput] = useState<Record<string, unknown>>(() => initialInput(model, draftInput))
  const [uploading, setUploading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const properties = useMemo(() => Object.entries(model.input_schema?.properties ?? {}), [model])
  const required = new Set(model.input_schema?.required ?? [])
  const price = bootstrap?.prices.find((item) => item.model_slug === model.slug)?.amount_units ?? 0

  useEffect(() => {
    setInput(initialInput(model, draftInput))
    setError(null)
  }, [draftInput, model])

  function update(name: string, value: unknown) {
    setInput((current) => ({ ...current, [name]: value }))
  }

  async function upload(name: string, file: File) {
    setUploading(name)
    setError(null)
    try {
      const result = await miniAppApi.uploadInput(file)
      const type = normalizedType(model.input_schema.properties?.[name] ?? {})
      update(name, type === 'array' || name.endsWith('_urls') ? [result.url] : result.url)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось загрузить файл')
    } finally {
      setUploading(null)
    }
  }

  async function submit() {
    setError(null)
    try {
      await submitModel(model, Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined && value !== '')))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось запустить генерацию')
    }
  }

  return (
    <section className="form-card" data-testid="model-form">
      <div className="form-head">
        <button className="back" type="button" onClick={() => selectModel(null)}>‹</button>
        <div><span className="eyebrow">{model.family || model.media_kind}</span><h2 style={{ margin: '5px 0 0' }}>{model.title}</h2></div>
      </div>
      {Object.keys(draftInput).length > 0 && <div className="notice" data-testid="remix-prefill">Remix: исходный промпт и совместимый медиа-референс перенесены в форму.</div>}
      {model.recommended_for?.length ? <div className="notice">Лучше всего: {model.recommended_for.join(' · ')}</div> : null}
      {properties.map(([name, schema]) => {
        const type = normalizedType(schema)
        const values = enumValues(schema)
        const value = input[name]
        const label = `${titleOf(name, schema)}${required.has(name) ? ' *' : ''}`
        const testId = `field-${name}`
        if (MEDIA_FIELDS.has(name)) {
          const display = Array.isArray(value) ? value.join('\n') : String(value ?? '')
          return (
            <label className="form-field" key={name}>
              <span>{label}</span>
              <input data-testid={testId} type="file" accept={acceptFor(name)} disabled={uploading === name} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(name, file) }} />
              {display && <small style={{ color: '#8c8882', display: 'block', marginTop: 6 }}>Референс выбран ✓</small>}
            </label>
          )
        }
        if (type === 'boolean') {
          return <label className="form-field checkbox" key={name}><input data-testid={testId} type="checkbox" checked={Boolean(value)} onChange={(event) => update(name, event.target.checked)} /><span>{label}</span></label>
        }
        if (values) {
          return (
            <label className="form-field" key={name}><span>{label}</span><select data-testid={testId} value={String(value ?? '')} onChange={(event) => update(name, coerce(event.target.value, schema))}><option value="">Выберите…</option>{values.map((item) => <option key={String(item)} value={String(item)}>{String(item)}</option>)}</select></label>
          )
        }
        if (type === 'array') {
          return <label className="form-field" key={name}><span>{label}</span><textarea data-testid={testId} value={Array.isArray(value) ? value.join('\n') : ''} onChange={(event) => update(name, coerce(event.target.value, schema))} placeholder="По одному значению на строку" /></label>
        }
        const longText = name.includes('prompt') || name.includes('description') || Number(schema.maxLength ?? 0) > 250
        if (longText) {
          return <label className="form-field" key={name}><span>{label}</span><textarea data-testid={testId} value={String(value ?? '')} maxLength={schema.maxLength} onChange={(event) => update(name, event.target.value)} placeholder={schema.description} /></label>
        }
        return <label className="form-field" key={name}><span>{label}</span><input data-testid={testId} type={type === 'integer' || type === 'number' ? 'number' : 'text'} min={schema.minimum} max={schema.maximum} value={String(value ?? '')} onChange={(event) => update(name, coerce(event.target.value, schema))} placeholder={schema.description} /></label>
      })}
      {error && <div className="notice error">{error}</div>}
      <button className="primary" type="button" disabled={busy || Boolean(uploading)} onClick={() => void submit()}>
        {busy ? 'Запускаем…' : price > 0 ? `Создать · ${price.toLocaleString('ru-RU')} ●` : 'Создать'}
      </button>
    </section>
  )
}
