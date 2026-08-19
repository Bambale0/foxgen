'use client'

import { useState } from 'react'
import { miniAppApi } from '@/lib/api'
import { useApp } from '@/lib/app-context'

function fmt(value: unknown) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}

function BalanceWorkspace() {
  const { bootstrap, starPackages, openStarInvoice, busy } = useApp()
  const balance = bootstrap?.balance
  return (
    <>
      <div className="hero">
        <span className="eyebrow">BALANCE / LIVE</span>
        <h1>{fmt(balance?.available_units)} <span>●</span></h1>
        <p>Доступный баланс CREDIT. Резерв: {fmt(balance?.reserved_units)}.</p>
      </div>
      <section className="section">
        <div className="section-head"><h2>Пополнить Stars</h2></div>
        <div className="list">
          {starPackages.map((item) => (
            <button
              className="quick-card"
              key={item.code}
              type="button"
              disabled={busy}
              onClick={() => void openStarInvoice(item.code)}
            >
              <span>★</span><strong>{item.title}</strong>
              <small>{fmt(item.total_credits_units)} CREDIT · {fmt(item.stars_amount)} Stars</small>
            </button>
          ))}
          {!starPackages.length && <div className="empty">Пакеты Stars сейчас недоступны.</div>}
        </div>
      </section>
      <section className="section">
        <div className="section-head"><h2>Последние операции</h2></div>
        <div className="list">
          {(bootstrap?.ledger ?? []).slice(0, 30).map((entry, index) => (
            <div className="kv" key={String(entry.id ?? index)}>
              <span>{String(entry.reason ?? 'Операция')}</span>
              <b>{fmt(entry.delta_units ?? entry.amount_units)} ●</b>
            </div>
          ))}
        </div>
      </section>
    </>
  )
}

function FeedWorkspace() {
  const { feed, refreshFeed } = useApp()
  const [sort, setSort] = useState('recent')
  async function changeSort(value: string) {
    setSort(value)
    await refreshFeed(value)
  }
  return (
    <>
      <div className="filters">
        {['recent', 'top_day', 'top'].map((value) => (
          <button className={sort === value ? 'active' : ''} key={value} onClick={() => void changeSort(value)}>
            {value === 'recent' ? 'Новое' : value === 'top_day' ? 'Топ дня' : 'Топ'}
          </button>
        ))}
      </div>
      <div className="list">
        {feed.map((item) => (
          <article className="feed-card" key={item.id}>
            <div className="work-row">
              {item.media?.[0]?.content_type?.startsWith('image/') && item.media[0].url ? (
                <img className="work-thumb" src={item.media[0].url} alt="Публикация" />
              ) : <div className="work-thumb" />}
              <div className="work-copy">
                <strong>{item.author?.display_name || item.author?.slug || 'Happy Fox'}</strong>
                <small>{item.model_slug}</small>
                {item.prompt && <small>{item.prompt}</small>}
              </div>
            </div>
            <div className="card-actions">
              <LikeButton id={item.id} liked={item.liked_by_viewer} count={item.likes_count} />
              <span className="status">💬 {item.comments_count} · Remix {item.remix_count}</span>
            </div>
          </article>
        ))}
        {!feed.length && <div className="empty">В ленте пока нет публикаций.</div>}
      </div>
    </>
  )
}

function LikeButton({ id, liked, count }: { id: string; liked: boolean; count: number }) {
  const [state, setState] = useState({ liked, count })
  return (
    <button
      type="button"
      onClick={() => void miniAppApi.setLike(id, !state.liked).then((value) => setState({ liked: value.liked, count: value.likes_count }))}
    >
      {state.liked ? '♥' : '♡'} {state.count}
    </button>
  )
}

function ReferencesWorkspace() {
  const { references } = useApp()
  return (
    <div className="list">
      {references.map((item) => (
        <div className="reference-card" key={item.id}>
          <div className="work-row">
            {item.content_type.startsWith('image/') ? (
              <img className="work-thumb" src={item.preview_url} alt="Референс" />
            ) : <div className="work-thumb" />}
            <div className="work-copy">
              <strong>{item.content_type}</strong>
              <small>{(item.size_bytes / 1024 / 1024).toFixed(1)} МБ</small>
              <small>{new Date(item.created_at).toLocaleString('ru-RU')}</small>
            </div>
          </div>
        </div>
      ))}
      {!references.length && <div className="empty">Сохранённых референсов пока нет.</div>}
    </div>
  )
}

function TariffWorkspace() {
  const { tariff } = useApp()
  if (!tariff) return <div className="empty">Опубликованный тариф пока не найден.</div>
  return (
    <>
      <div className="notice">Версия {tariff.version} · опубликовано {new Date(tariff.published_at).toLocaleString('ru-RU')}</div>
      <pre style={{ whiteSpace: 'pre-wrap', color: '#c6c0ba', fontSize: 12 }}>{JSON.stringify(tariff.payload, null, 2)}</pre>
    </>
  )
}

function PartnerWorkspace() {
  const { partner, refreshWorkspace } = useApp()
  const [amount, setAmount] = useState('')
  const [destination, setDestination] = useState('')
  if (!partner) return <div className="empty">Загружаем партнёрский кабинет…</div>
  return (
    <>
      <div className="hero">
        <span className="eyebrow">PARTNER</span>
        <h1>{fmt(partner.profile.available_units)} <span>●</span></h1>
        <p>Рефералов: {partner.profile.referrals_count} · заработано: {fmt(partner.profile.earned_units)}</p>
      </div>
      {!partner.profile.joined && (
        <button className="primary" style={{ marginTop: 14 }} onClick={() => void miniAppApi.joinPartner().then(() => refreshWorkspace('partner'))}>
          Вступить в партнёрскую программу
        </button>
      )}
      {partner.profile.joined && (
        <section className="form-card section">
          <h3>Заявка на выплату</h3>
          <label className="form-field"><span>Сумма CREDIT</span><input value={amount} inputMode="numeric" onChange={(event) => setAmount(event.target.value)} /></label>
          <label className="form-field"><span>Реквизиты</span><input value={destination} onChange={(event) => setDestination(event.target.value)} /></label>
          <button className="primary" onClick={() => void miniAppApi.requestWithdrawal(Number(amount), destination).then(() => refreshWorkspace('partner'))}>Отправить заявку</button>
        </section>
      )}
      <section className="section list">
        {partner.withdrawals.map((row) => <div className="kv" key={row.id}><span>{row.destination} · {row.status}</span><b>{fmt(row.amount_units)} ●</b></div>)}
      </section>
    </>
  )
}

function SupportWorkspace() {
  const { supportTickets, refreshWorkspace } = useApp()
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  async function create() {
    if (!subject.trim() || !body.trim()) return
    await miniAppApi.createSupport(subject.trim(), body.trim())
    setSubject('')
    setBody('')
    await refreshWorkspace('support')
  }
  return (
    <>
      <section className="form-card">
        <h3>Новый запрос</h3>
        <label className="form-field"><span>Тема</span><input value={subject} onChange={(event) => setSubject(event.target.value)} /></label>
        <label className="form-field"><span>Сообщение</span><textarea value={body} onChange={(event) => setBody(event.target.value)} /></label>
        <button className="primary" onClick={() => void create()}>Отправить</button>
      </section>
      <section className="section list">
        {supportTickets.map((ticket) => (
          <div className="ticket-card" key={ticket.id}>
            <strong>{ticket.subject}</strong>
            <small className="status">{ticket.status}</small>
            {ticket.messages.slice(-2).map((message) => <p key={message.id} style={{ color: '#aaa49e', fontSize: 12 }}>{message.body}</p>)}
          </div>
        ))}
      </section>
    </>
  )
}

const titles = {
  balance: 'Баланс',
  feed: 'Сообщество',
  references: 'Референсы',
  tariff: 'Тарифы',
  partner: 'Партнёры',
  support: 'Поддержка',
} as const

export function WorkspaceSheet() {
  const { activeWorkspace, closeWorkspace, busy } = useApp()
  if (!activeWorkspace) return null
  return (
    <div className="workspace-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeWorkspace() }}>
      <section className="workspace" role="dialog" aria-modal="true" aria-label={titles[activeWorkspace]} data-testid={`workspace-${activeWorkspace}`}>
        <header className="workspace-head"><h2>{titles[activeWorkspace]}</h2><button onClick={closeWorkspace}>×</button></header>
        {busy && <div className="notice">Обновляем данные…</div>}
        {activeWorkspace === 'balance' && <BalanceWorkspace />}
        {activeWorkspace === 'feed' && <FeedWorkspace />}
        {activeWorkspace === 'references' && <ReferencesWorkspace />}
        {activeWorkspace === 'tariff' && <TariffWorkspace />}
        {activeWorkspace === 'partner' && <PartnerWorkspace />}
        {activeWorkspace === 'support' && <SupportWorkspace />}
      </section>
    </div>
  )
}
