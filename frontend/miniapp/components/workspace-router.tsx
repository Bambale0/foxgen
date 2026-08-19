'use client'

import { useState } from 'react'
import { remixInputSeed } from '@/lib/deep-links'
import { miniAppApi } from '@/lib/api'
import { socialApi } from '@/lib/social-api'
import type { Publication, PublicationComment } from '@/lib/types'
import { useApp } from '@/lib/app-context'
import { WorkspaceSheet as LegacyWorkspaceSheet } from './workspace-sheet'

function LikeButton({ item }: { item: Publication }) {
  const [state, setState] = useState({ liked: item.liked_by_viewer, count: item.likes_count })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      const result = await miniAppApi.setLike(item.id, !state.liked)
      setState({ liked: result.liked, count: result.likes_count })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось обновить лайк.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button type="button" disabled={busy} onClick={() => void toggle()}>
        {state.liked ? '♥' : '♡'} {state.count}
      </button>
      {error && <small className="notice error">{error}</small>}
    </>
  )
}

function CommentPanel({ item }: { item: Publication }) {
  const [comments, setComments] = useState<PublicationComment[] | null>(null)
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const result = await socialApi.comments(item.id)
      setComments(result.items)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось загрузить комментарии.')
    } finally {
      setBusy(false)
    }
  }

  async function submit() {
    const value = body.trim()
    if (!value) return
    setBusy(true)
    setError(null)
    try {
      const comment = await socialApi.addComment(item.id, value)
      setComments((current) => [...(current ?? []), comment])
      setBody('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось отправить комментарий.')
    } finally {
      setBusy(false)
    }
  }

  if (comments === null) {
    return (
      <button
        type="button"
        data-testid={`comments-${item.id}`}
        disabled={busy}
        onClick={() => void load()}
      >
        💬 {item.comments_count} · Комментарии
      </button>
    )
  }

  return (
    <section className="form-card" data-testid={`comments-panel-${item.id}`}>
      <div className="section-head">
        <h3>Комментарии</h3>
        <button type="button" onClick={() => setComments(null)}>Свернуть</button>
      </div>
      <div className="list">
        {comments.map((comment) => (
          <article className="ticket-card" key={comment.id}>
            <strong>{comment.author.display_name || comment.author.slug}</strong>
            <p>{comment.body}</p>
            <small>{new Date(comment.created_at).toLocaleString('ru-RU')}</small>
          </article>
        ))}
        {!comments.length && <div className="empty">Комментариев пока нет.</div>}
      </div>
      <label className="form-field">
        <span>Ваш комментарий</span>
        <textarea
          value={body}
          maxLength={1000}
          placeholder="Напишите комментарий"
          onChange={(event) => setBody(event.target.value)}
        />
      </label>
      {error && <div className="notice error">{error}</div>}
      <button className="primary" type="button" disabled={busy || !body.trim()} onClick={() => void submit()}>
        {busy ? 'Отправляем…' : 'Отправить комментарий'}
      </button>
    </section>
  )
}

function FeedWorkspace() {
  const {
    bootstrap,
    feed,
    refreshFeed,
    selectModel,
    closeWorkspace,
  } = useApp()
  const [sort, setSort] = useState('recent')
  const [remixBusy, setRemixBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function changeSort(value: string) {
    setSort(value)
    setError(null)
    try {
      await refreshFeed(value)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось обновить ленту.')
    }
  }

  async function remix(item: Publication) {
    setRemixBusy(item.id)
    setError(null)
    try {
      const source = await miniAppApi.remixSource(item.id)
      const model = bootstrap?.models.find(
        (candidate) => candidate.slug === source.model_slug || candidate.ui_key === source.model_slug,
      )
      if (!model) throw new Error('Модель исходной публикации сейчас недоступна для Remix.')
      const input = remixInputSeed(model, source)
      closeWorkspace()
      selectModel(model, { input, sourcePublicationId: source.publication_id })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось открыть Remix.')
    } finally {
      setRemixBusy(null)
    }
  }

  return (
    <>
      <div className="filters">
        {['recent', 'top_day', 'top'].map((value) => (
          <button
            className={sort === value ? 'active' : ''}
            key={value}
            type="button"
            onClick={() => void changeSort(value)}
          >
            {value === 'recent' ? 'Новое' : value === 'top_day' ? 'Топ дня' : 'Топ'}
          </button>
        ))}
      </div>
      {error && <div className="notice error" data-testid="feed-action-error">{error}</div>}
      <div className="list">
        {feed.map((item) => (
          <article className="feed-card" key={item.id} data-testid={`publication-${item.id}`}>
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
              <LikeButton item={item} />
              <CommentPanel item={item} />
              {item.prompt_actions_allowed !== false && (
                <button
                  type="button"
                  data-testid={`remix-${item.id}`}
                  disabled={remixBusy === item.id}
                  onClick={() => void remix(item)}
                >
                  {remixBusy === item.id ? 'Готовим Remix…' : `Remix · ${item.remix_count}`}
                </button>
              )}
            </div>
          </article>
        ))}
        {!feed.length && <div className="empty">В ленте пока нет публикаций.</div>}
      </div>
    </>
  )
}

export function WorkspaceRouter() {
  const { activeWorkspace, closeWorkspace, busy } = useApp()
  if (activeWorkspace !== 'feed') return <LegacyWorkspaceSheet />

  return (
    <div
      className="workspace-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) closeWorkspace()
      }}
    >
      <section
        className="workspace"
        role="dialog"
        aria-modal="true"
        aria-label="Сообщество"
        data-testid="workspace-feed"
      >
        <header className="workspace-head">
          <h2>Сообщество</h2>
          <button type="button" aria-label="Закрыть" onClick={closeWorkspace}>×</button>
        </header>
        {busy && <div className="notice">Обновляем данные…</div>}
        <FeedWorkspace />
      </section>
    </div>
  )
}
