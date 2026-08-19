'use client'

import { BookImage, CircleDollarSign, Headphones, Images, Newspaper, UsersRound } from 'lucide-react'
import { useApp } from '@/lib/app-context'

function modelPrice(slug: string, prices: ReturnType<typeof useApp>['bootstrap'] extends infer _ ? never : never) {
  void prices
  return 0
}

export function HomeTab() {
  const { bootstrap, generations, selectModel, setActiveTab, openWorkspace } = useApp()
  const models = bootstrap?.models ?? []
  const prices = bootstrap?.prices ?? []
  const imageModel = models.find((item) => item.media_kind === 'image') ?? models[0]
  const videoModel = models.find((item) => item.media_kind === 'video') ?? models[0]
  const priceFor = (slug: string) => prices.find((item) => item.model_slug === slug)?.amount_units ?? 0

  return (
    <main className="page" data-testid="screen-home">
      <section className="hero">
        <span className="eyebrow">HAPPY FOX / LIVE</span>
        <h1>Что создаём <span>сегодня?</span></h1>
        <p>Все доступные модели и цены приходят напрямую из backend. Выбирайте сценарий — дальше только нужные параметры.</p>
      </section>

      <section className="section">
        <div className="create-grid">
          <button className="create-card image" type="button" onClick={() => imageModel && selectModel(imageModel)}>
            <span>◉</span><strong>Создать изображение</strong>
          </button>
          <button className="create-card video" type="button" onClick={() => videoModel && selectModel(videoModel)}>
            <span>▣</span><strong>Создать видео</strong>
          </button>
        </div>
      </section>

      <section className="section">
        <div className="section-head"><h2>Быстрый доступ</h2></div>
        <div className="quick-grid">
          <button className="quick-card" onClick={() => setActiveTab('works')}><Images /><strong>Мои работы</strong><small>{generations.length} последних</small></button>
          <button className="quick-card" onClick={() => openWorkspace('feed')}><Newspaper /><strong>Сообщество</strong><small>Лента и remix</small></button>
          <button className="quick-card" onClick={() => openWorkspace('balance')}><CircleDollarSign /><strong>Баланс</strong><small>{(bootstrap?.balance.available_units ?? 0).toLocaleString('ru-RU')} CREDIT</small></button>
          <button className="quick-card" onClick={() => openWorkspace('references')}><BookImage /><strong>Референсы</strong><small>Память образов</small></button>
          <button className="quick-card" onClick={() => openWorkspace('partner')}><UsersRound /><strong>Партнёры</strong><small>Доход и выплаты</small></button>
          <button className="quick-card" onClick={() => openWorkspace('support')}><Headphones /><strong>Поддержка</strong><small>Тикеты и ответы</small></button>
        </div>
      </section>

      <section className="section">
        <div className="section-head"><h2>Популярные модели</h2><button onClick={() => setActiveTab('models')}>Все модели ›</button></div>
        <div className="model-strip">
          {models.slice(0, 8).map((model) => (
            <button className="model-tile" type="button" key={model.slug} onClick={() => selectModel(model)}>
              <span className="model-icon">✦</span>
              <strong>{model.title}</strong>
              <small>{model.family || model.media_kind}</small>
              <small className="model-price">{priceFor(model.slug) ? `${priceFor(model.slug).toLocaleString('ru-RU')} ●` : 'Цена по backend'}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head"><h2>Недавние работы</h2><button onClick={() => setActiveTab('works')}>Смотреть все ›</button></div>
        <div className="list">
          {generations.slice(0, 3).map((item) => (
            <div className="work-card" key={item.id}>
              <div className="work-row">
                {item.media?.[0]?.url && item.media[0].content_type.startsWith('image/') ? <img className="work-thumb" src={item.media[0].url} alt="Результат" /> : <div className="work-thumb" />}
                <div className="work-copy"><strong>{item.model_slug}</strong><small>{item.prompt || 'Без текстового промпта'}</small><span className={`status ${item.status}`}>{item.status}</span></div>
              </div>
            </div>
          ))}
          {!generations.length && <div className="empty">Пока нет генераций. Запустите первую модель.</div>}
        </div>
      </section>
    </main>
  )
}
