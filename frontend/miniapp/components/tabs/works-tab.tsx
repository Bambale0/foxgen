'use client'

import { useEffect, useState } from 'react'
import { useApp } from '@/lib/app-context'

const ACTIVE = new Set(['queued','submitting','submitted','processing','submission_unknown','result_ready','storing_media','delivery_pending'])

function Media({ url, contentType }: { url?: string; contentType?: string }) {
  if (!url) return <div className="work-thumb" />
  if (contentType?.startsWith('image/')) return <img className="work-thumb" src={url} alt="Результат" />
  if (contentType?.startsWith('video/')) return <video className="work-thumb" src={url} muted playsInline preload="metadata" />
  return <div className="work-thumb" style={{ display:'grid', placeItems:'center' }}>♫</div>
}

export function WorksTab() {
  const { generations, refreshGenerations, cancelGeneration, publishGeneration } = useApp()
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { void refreshGenerations().catch((reason) => setError(reason instanceof Error ? reason.message : String(reason))) }, [refreshGenerations])

  return (
    <main className="page" data-testid="screen-works">
      <section className="hero">
        <span className="eyebrow">WORKS / LIVE</span>
        <h1>Мои <span>работы</span></h1>
        <p>Статусы, результаты, отмена и публикация работают напрямую через backend.</p>
      </section>
      <section className="section">
        <div className="section-head"><h2>История</h2><button onClick={() => void refreshGenerations()}>Обновить ↻</button></div>
        {error && <div className="notice error">{error}</div>}
        <div className="list">
          {generations.map((item) => (
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
                {ACTIVE.has(item.status) && <button onClick={() => void cancelGeneration(item.id)}>Отменить</button>}
                {item.status === 'succeeded' && <button onClick={() => void publishGeneration(item.id, 'feed')}>В ленту</button>}
                {item.status === 'succeeded' && <button onClick={() => void publishGeneration(item.id, 'profile')}>В профиль</button>}
                {item.media?.[0]?.url && <button onClick={() => window.open(item.media?.[0]?.url, '_blank')}>Открыть результат</button>}
              </div>
            </article>
          ))}
          {!generations.length && <div className="empty">Работ пока нет. Откройте «Создать» и выберите модель.</div>}
        </div>
      </section>
    </main>
  )
}
