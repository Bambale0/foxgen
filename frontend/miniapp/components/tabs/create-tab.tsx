'use client'

import { useApp } from '@/lib/app-context'
import { ModelForm } from '../model-form'
import { isSpecialModel, SpecialModelForm } from '../special-model-form'

export function CreateTab() {
  const { bootstrap, selectedModel, selectModel, setActiveTab } = useApp()
  const models = bootstrap?.models ?? []

  if (selectedModel) {
    return (
      <main className="page" data-testid="screen-create">
        {isSpecialModel(selectedModel.slug) ? <SpecialModelForm model={selectedModel} /> : <ModelForm model={selectedModel} />}
      </main>
    )
  }

  const groups = [
    ['Изображения', models.filter((item) => item.media_kind === 'image' && !item.slug.startsWith('suno-'))],
    ['Видео', models.filter((item) => item.media_kind === 'video' && !item.slug.includes('motion'))],
    ['Motion', models.filter((item) => item.slug.includes('motion'))],
    ['Музыка и аудио', models.filter((item) => item.media_kind === 'audio' || item.slug.startsWith('suno-'))],
  ] as const

  return (
    <main className="page" data-testid="screen-create">
      <section className="hero">
        <span className="eyebrow">CREATE</span>
        <h1>Выберите <span>сценарий</span></h1>
        <p>Каждая карточка открывает реальную схему backend. Для Motion и Suno используются их специализированные endpoint&apos;ы.</p>
      </section>
      {groups.map(([title, rows]) => rows.length ? (
        <section className="section" key={title}>
          <div className="section-head"><h2>{title}</h2></div>
          <div className="model-strip">
            {rows.map((model) => <button className="model-tile" key={model.slug} onClick={() => selectModel(model)}><span className="model-icon">✦</span><strong>{model.title}</strong><small>{model.family || model.slug}</small></button>)}
          </div>
        </section>
      ) : null)}
      <section className="section">
        <button className="primary" onClick={() => setActiveTab('models')}>Открыть полный каталог · {models.length}</button>
      </section>
    </main>
  )
}
