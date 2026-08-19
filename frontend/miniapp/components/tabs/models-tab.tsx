'use client'

import { useMemo, useState } from 'react'
import { useApp } from '@/lib/app-context'
import type { ModelDefinition } from '@/lib/types'

type Filter = 'all' | 'image' | 'video' | 'audio' | 'music' | 'motion'

function category(model: ModelDefinition): Filter {
  const slug = model.slug.toLowerCase()
  const family = String(model.family ?? '').toLowerCase()
  if (slug.includes('motion')) return 'motion'
  if (slug.startsWith('suno-') || family.includes('suno')) return 'music'
  if (model.media_kind === 'audio') return 'audio'
  if (model.media_kind === 'video') return 'video'
  return 'image'
}

const labels: Record<Filter, string> = {
  all: 'Все', image: 'Фото', video: 'Видео', audio: 'Голос', music: 'Музыка', motion: 'Motion',
}

export function ModelsTab() {
  const { bootstrap, selectModel } = useApp()
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const models = bootstrap?.models ?? []
  const prices = bootstrap?.prices ?? []
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return models.filter((model) => {
      if (filter !== 'all' && category(model) !== filter) return false
      if (!needle) return true
      return `${model.title} ${model.slug} ${model.family ?? ''} ${(model.recommended_for ?? []).join(' ')}`.toLowerCase().includes(needle)
    })
  }, [filter, models, query])
  const priceFor = (slug: string) => prices.find((item) => item.model_slug === slug)?.amount_units ?? 0

  return (
    <main className="page" data-testid="screen-models">
      <section className="hero">
        <span className="eyebrow">MODELS / BACKEND LIVE</span>
        <h1>Все <span>модели</span></h1>
        <p>{models.length} активных сценариев. Каталог, параметры и доступность берутся из ModelRegistry backend.</p>
      </section>
      <section className="section">
        <input className="search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Модель, семейство или задача" />
        <div className="filters">
          {(Object.keys(labels) as Filter[]).map((value) => {
            const count = value === 'all' ? models.length : models.filter((model) => category(model) === value).length
            return <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{labels[value]} · {count}</button>
          })}
        </div>
        <div className="catalog">
          {visible.map((model) => {
            const price = priceFor(model.slug)
            return (
              <button className="model-card" type="button" key={model.slug} onClick={() => selectModel(model)} data-testid={`model-${model.slug}`}>
                <header><span className="model-icon">✦</span><span><strong>{model.title}</strong><small>{model.family || model.media_kind}</small></span></header>
                <p>{(model.recommended_for ?? []).join(' · ') || model.contract || model.slug}</p>
                <footer><span>{labels[category(model)]}</span><b>{price > 0 ? `${price.toLocaleString('ru-RU')} ●` : 'backend price'}</b></footer>
              </button>
            )
          })}
        </div>
        {!visible.length && <div className="empty">По этому фильтру моделей нет.</div>}
      </section>
    </main>
  )
}
