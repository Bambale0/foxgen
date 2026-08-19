'use client'

import { useEffect, useState } from 'react'
import { miniAppApi } from '@/lib/api'
import { useApp } from '@/lib/app-context'
import type { Publication, PublicProfile } from '@/lib/types'

function PublicationList({ publications, removable = false, onRemove }: {
  publications: Publication[]
  removable?: boolean
  onRemove?: (generationId: string, scope: string) => void
}) {
  return (
    <div className="list">
      {publications.map((item) => (
        <div className="work-card" key={item.id} data-testid={`profile-publication-${item.id}`}>
          <div className="work-row">
            {item.media?.[0]?.url && item.media[0].content_type.startsWith('image/') ? <img className="work-thumb" src={item.media[0].url} alt="Публикация" /> : <div className="work-thumb" />}
            <div className="work-copy"><strong>{item.model_slug}</strong><small>{item.scope} · ♥ {item.likes_count}</small>{item.prompt && <small>{item.prompt}</small>}</div>
          </div>
          {removable && onRemove && <div className="card-actions"><button onClick={() => onRemove(item.generation_id, item.scope)}>Снять публикацию</button></div>}
        </div>
      ))}
      {!publications.length && <div className="empty">Публикаций пока нет.</div>}
    </div>
  )
}

export function ProfileTab() {
  const { bootstrap, publicProfileView } = useApp()
  const [profile, setProfile] = useState<PublicProfile | null>(null)
  const [publications, setPublications] = useState<Publication[]>([])
  const [slug, setSlug] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [bio, setBio] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  async function load() {
    const [current, pubs] = await Promise.all([
      miniAppApi.ownProfile(),
      miniAppApi.request<{ items: Publication[] }>('/me/publications?limit=50'),
    ])
    setProfile(current)
    setPublications(pubs.items)
    setSlug(current.slug)
    setDisplayName(current.display_name || '')
    setBio(current.bio || '')
  }

  useEffect(() => {
    if (publicProfileView) return
    void load().catch((reason) => setMessage(reason instanceof Error ? reason.message : String(reason)))
  }, [publicProfileView])

  async function save() {
    setMessage(null)
    try {
      await miniAppApi.updateProfile({ slug, display_name: displayName || null, bio: bio || null })
      setMessage('Профиль сохранён.')
      await load()
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : 'Не удалось сохранить профиль') }
  }

  async function remove(generationId: string, scope: string) {
    if (scope !== 'feed' && scope !== 'profile') return
    await miniAppApi.unpublish(generationId, scope)
    await load()
  }

  if (publicProfileView) {
    const current = publicProfileView.profile
    return (
      <main className="page" data-testid="screen-profile">
        <section className="hero" data-testid="deep-link-profile">
          <span className="eyebrow">PUBLIC PROFILE</span>
          <h1>{current.display_name || `@${current.slug}`}</h1>
          <p>{current.bio || `@${current.slug}`}</p>
        </section>
        <section className="section">
          <div className="section-head"><h2>Публикации</h2><small>{publicProfileView.publications.length}</small></div>
          <PublicationList publications={publicProfileView.publications} />
        </section>
      </main>
    )
  }

  const user = bootstrap?.user
  return (
    <main className="page" data-testid="screen-profile">
      <section className="profile-hero">
        {user?.photo_url ? <img className="avatar" src={user.photo_url} alt="Аватар" /> : <div className="avatar" />}
        <div><h2>{user?.display_name || user?.username || 'Happy Fox'}</h2><p>{user?.username ? `@${user.username}` : 'Telegram profile'}</p></div>
      </section>
      <section className="section form-card">
        <div className="section-head"><h2>Публичный профиль</h2></div>
        <label className="form-field"><span>Slug</span><input value={slug} onChange={(event) => setSlug(event.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))} /></label>
        <label className="form-field"><span>Имя</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
        <label className="form-field"><span>О себе</span><textarea value={bio} maxLength={500} onChange={(event) => setBio(event.target.value)} /></label>
        {message && <div className={`notice${message.includes('сохранён') ? '' : ' error'}`}>{message}</div>}
        <button className="primary" type="button" disabled={!profile || slug.length < 3} onClick={() => void save()}>Сохранить профиль</button>
      </section>
      <section className="section">
        <div className="section-head"><h2>Мои публикации</h2><small>{publications.length}</small></div>
        <PublicationList publications={publications} removable onRemove={(generationId, scope) => void remove(generationId, scope)} />
      </section>
    </main>
  )
}
