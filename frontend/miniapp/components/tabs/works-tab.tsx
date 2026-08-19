'use client'

import { useEffect, useMemo, useState } from 'react'
import { useApp } from '@/lib/app-context'
import type { Generation } from '@/lib/types'

const ACTIVE = new Set(['queued','submitting','submitted','processing','submission_unknown','result_ready','storing_media','delivery_pending'])
const POLL_MS = 3_000

function Media({ url, contentType }: { url?: string; contentType?: string }) {
  if (!url) return <div className="work-thumb" />
  if (contentType?.startsWith('image/')) return <img className="work-thumb" src={url} alt="Результат" />
  if (contentType?.startsWith('video/')) return <video className="work-thumb" src={url} muted playsInline controls preload="metadata" />
  if (contentType?.startsWith('audio/')) return <audio src={url} controls preload="metadata" style={{ width: '100%' }} />
  return <div className="work-thumb" style={{ display:'grid', placeItems:'center' }}>♫</div>
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ru-RU')
}

function GenerationDetail({ item, onClose }: { item: Generation; onClose: () => void }) {
  return (
    <section className="section form-card" data-testid="generation-detail">
      <div className="form-head">
        <button className="back" type="button" onClick={onClose}>‹</button>
        <div>
          <span className="eyebrow">GENERATION DETAIL</span>
          <h2 style={{ margin: '5px 0 0' }}>{item.model_slug}</h2>
        </div>
      </div>
      <div className="kv"><span>Статус</span><b className={`status ${item.status}`}>{item.status}</b></div>
      <div className="kv"><span>Создано</span><b>{formatDate(item.created_at)}</b></div>
      <div className="kv"><span>Завершено</span><b>{formatDate(item.completed_at)}</b></div>
      {item.prompt && <div className="notice" style={{ whiteSpace: 'pre-wrap' }}>{item.prompt}</div>}
      {item.error_code && <div className="notice error">Ошибка: {item.error_code}</div>}
      {(item.media ?? []).map((media, index) => (
        <div key={media.id ?? `${media.url}-${index}`} className="section">
          <Media url={media.url} contentType={media.content_type} />
          <button className="primary" type="button" onClick={() => window.open(media.url, '_blank')}>Открыть результат {item.media && item.media.length > 1 ? index + 1 : ''}</button>
        </div>
      ))}
      {ACTIVE.has(item.status) && <div className="notice" data-testid="generation-live">Статус обновляется автоматически.</div>}
    </section>
  )
}

export function WorksTab() {
  const {
    generations,
    focusedGeneration,
    refreshGenerations,
    openGeneration,
    clearGenerationFocus,
    cancelGeneration,
    publishGeneration,
  } = useApp()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void refreshGenerations().catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
  }, [refreshGenerations])

  const hasActive = generations.some((item) => ACTIVE.has(item.status)) || Boolean(focusedGeneration && ACTIVE.has(focusedGeneration.status))

  useEffect(() => {
    if (!hasActive) return
    let disposed = false
    let running = false

    const poll = async () => {
      if (disposed || running || document.hidden) return
      running = true
      try {
        await refreshGenerations()
        if (!disposed) setError(null)
      } catch (reason) {
        if (!disposed) setError(reason instanceof Error ? reason.message : String(reason))
      } finally {
        running = false
      }
    }

    const onVisibilityChange = () => {
      if (!document.hidden) void poll()
    }

    const timer = window.setInterval(() => void poll(), POLL_MS)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      disposed = true
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [hasActive, refreshGenerations])

  const rows = useMemo(() => {
    if (!focusedGeneration) return generations
    return [focusedGeneration, ...generations.filter((item) => item.id !== focusedGeneration.id)]
  }, [focusedGeneration, generations])

  return (
    <main className="page" data-testid="screen-works">
      <section className="hero">
        <span className="eyebrow">WORKS / LIVE</span>
        <h1>Мои <span>работы</span></h1>
        <p>Активные генерации обновляются автоматически, а фоновые WebView не тратят запросы.</p>
      </section>
      {focusedGeneration && <GenerationDetail item={focusedGeneration} onClose={clearGenerationFocus} />}
      <section className="section">
        <div className="section-head">
          <h2>История</h2>
          <button onClick={() => void refreshGenerations()}>Обновить ↻</button>
        </div>
        {hasActive && <div className="notice" data-testid="works-auto-poll">Есть активные задачи · автообновление каждые 3 секунды</div>}
        {error && <div className="notice error">{error}</div>}
        <div className="list">
          {rows.map((item) => (
            <article className="work-card" key={item.id} data-testid={`generation-${item.id}`}>
              <div className="work-row">
                <Media url={item.media?.[0]?.url} contentType={item.media?.[0]?.content_type} />
                <div className="work-copy">
                  <strong>{item.model_slug}</strong>
                  <small>{item.prompt || 'Без текстового промпта'}</small>
                  <span className={`status ${item.status}`}>{item.status}</span>
                </div>
              </div>
              <div className="card-actions">
                <button onClick={() => void openGeneration(item.id)}>Подробнее</button>
                {ACTIVE.has(item.status) && <button onClick={() => void cancelGeneration(item.id)}>Отменить</button>}
                {item.status === 'succeeded' && <button onClick={() => void publishGeneration(item.id, 'feed')}>В ленту</button>}
                {item.status === 'succeeded' && <button onClick={() => void publishGeneration(item.id, 'profile')}>В профиль</button>}
                {item.media?.[0]?.url && <button onClick={() => window.open(item.media?.[0]?.url, '_blank')}>Открыть результат</button>}
              </div>
            </article>
          ))}
          {!rows.length && <div className="empty">Работ пока нет. Откройте «Создать» и выберите модель.</div>}
        </div>
      </section>
    </main>
  )
}
