'use client'

import type {
  AuthResponse,
  BootstrapResponse,
  Generation,
  PartnerData,
  Publication,
  PublicProfile,
  ReferenceItem,
  RemixSource,
  StarPackage,
  SupportTicket,
  TariffData,
} from './types'

const API_BASE = '/v1/miniapp'
const TIMEOUT_MS = 15_000

export class ApiError extends Error {
  status: number
  payload: unknown

  constructor(message: string, status: number, payload: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function messageFromPayload(payload: unknown, fallback: string): string {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload
  if (Array.isArray(payload)) {
    return payload
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item) return String(item.msg)
        return JSON.stringify(item)
      })
      .join(' · ')
  }
  if (typeof payload === 'object') {
    const value = payload as Record<string, unknown>
    return messageFromPayload(value.detail ?? value.message ?? value.error, fallback)
  }
  return fallback
}

async function fetchJson(path: string, init: RequestInit = {}, timeoutMs = TIMEOUT_MS) {
  const controller = new AbortController()
  const timer = globalThis.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(path, { ...init, signal: controller.signal })
    const contentType = response.headers.get('content-type') ?? ''
    const payload = response.status === 204
      ? null
      : contentType.includes('application/json')
        ? await response.json().catch(() => null)
        : await response.text().catch(() => '')
    if (!response.ok) {
      throw new ApiError(messageFromPayload(payload, `HTTP ${response.status}`), response.status, payload)
    }
    return payload
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('Сервер Happy Fox отвечает слишком долго. Повторите попытку.', 408)
    }
    throw error
  } finally {
    globalThis.clearTimeout(timer)
  }
}

function randomId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function telegramInitData(): string {
  if (typeof window === 'undefined') return ''
  return window.Telegram?.WebApp?.initData ?? ''
}

export function telegramStartParam(): string {
  if (typeof window === 'undefined') return ''
  return (
    window.Telegram?.WebApp?.initDataUnsafe?.start_param ??
    new URLSearchParams(window.location.search).get('tgWebAppStartParam') ??
    ''
  )
}

export class MiniAppApi {
  private token: string | null = null
  private initData: string | null

  constructor(initData?: string) {
    this.initData = initData ?? null
  }

  get authenticated() {
    return Boolean(this.token)
  }

  private currentInitData() {
    if (this.initData === null) this.initData = telegramInitData()
    return this.initData
  }

  async authenticate(force = false): Promise<AuthResponse> {
    if (this.token && !force) {
      return { access_token: this.token, token_type: 'bearer', expires_in: 0, user: { id: 0 } }
    }
    const initData = this.currentInitData()
    if (!initData) throw new ApiError('Откройте Happy Fox внутри Telegram.', 401)
    const payload = (await fetchJson(`${API_BASE}/auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: initData }),
    })) as AuthResponse
    this.token = payload.access_token
    return payload
  }

  async request<T>(path: string, init: RequestInit = {}, retryAuth = true): Promise<T> {
    if (!this.token) await this.authenticate()
    const headers = new Headers(init.headers ?? {})
    headers.set('Authorization', `Bearer ${this.token}`)
    try {
      return (await fetchJson(`${API_BASE}${path}`, { ...init, headers })) as T
    } catch (error) {
      if (error instanceof ApiError && error.status === 401 && retryAuth) {
        await this.authenticate(true)
        return this.request<T>(path, init, false)
      }
      throw error
    }
  }

  bootstrap() {
    return this.request<BootstrapResponse>('/bootstrap')
  }

  models() {
    return this.request<BootstrapResponse['models']>('/models')
  }

  validateModel(modelSlug: string, input: Record<string, unknown>) {
    return this.request<{ model_slug: string; input: Record<string, unknown> }>(
      `/models/${encodeURIComponent(modelSlug)}/validate`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input }),
      },
    )
  }

  createTask(modelSlug: string, input: Record<string, unknown>, sourcePublicationId?: string | null) {
    return this.request<{ generation_id: string; model: string; status: string; replayed: boolean }>('/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': randomId() },
      body: JSON.stringify({
        model_slug: modelSlug,
        input,
        source_publication_id: sourcePublicationId ?? null,
      }),
    })
  }

  generations(limit = 100) {
    return this.request<Generation[]>(`/generations?limit=${limit}`)
  }

  generation(id: string) {
    return this.request<Generation>(`/generations/${encodeURIComponent(id)}`)
  }

  cancelGeneration(id: string) {
    return this.request<Generation>(`/generations/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
  }

  balance() {
    return this.request<BootstrapResponse['balance']>('/balance')
  }

  prices() {
    return this.request<BootstrapResponse['prices']>('/prices')
  }

  ledger(limit = 200) {
    return this.request<BootstrapResponse['ledger']>(`/ledger?limit=${limit}`)
  }

  async uploadInput(file: File) {
    return this.request<{ kind: string; storage_key: string; url: string; content_type: string; size_bytes: number }>(
      '/input-media',
      { method: 'POST', headers: { 'Content-Type': file.type }, body: file },
    )
  }

  feed(sort = 'recent', limit = 20, offset = 0) {
    return this.request<{ items: Publication[]; next_offset: number | null }>(
      `/feed?sort=${encodeURIComponent(sort)}&limit=${limit}&offset=${offset}`,
    )
  }

  publication(publicationId: string) {
    return this.request<Publication>(`/publications/${encodeURIComponent(publicationId)}`)
  }

  remixSource(publicationId: string) {
    return this.request<RemixSource>(`/publications/${encodeURIComponent(publicationId)}/remix`)
  }

  publicProfile(slug: string) {
    return this.request<PublicProfile>(`/profiles/${encodeURIComponent(slug)}`)
  }

  profilePublications(slug: string, limit = 30, offset = 0) {
    return this.request<{ items: Publication[]; next_offset: number | null }>(
      `/profiles/${encodeURIComponent(slug)}/publications?limit=${limit}&offset=${offset}`,
    )
  }

  setLike(publicationId: string, liked: boolean) {
    return this.request<{ liked: boolean; likes_count: number }>(
      `/publications/${encodeURIComponent(publicationId)}/like`,
      { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ liked }) },
    )
  }

  publish(generationId: string, scope: 'feed' | 'profile') {
    return this.request<Publication>(`/generations/${encodeURIComponent(generationId)}/publications`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope }),
    })
  }

  unpublish(generationId: string, scope: 'feed' | 'profile') {
    return this.request<{ unpublished: boolean; scope: string }>(
      `/generations/${encodeURIComponent(generationId)}/publications/${scope}`,
      { method: 'DELETE' },
    )
  }

  ownProfile() {
    return this.request<PublicProfile>('/me/profile')
  }

  updateProfile(payload: { slug: string; display_name?: string | null; bio?: string | null }) {
    return this.request('/me/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }

  references(limit = 100) {
    return this.request<{ items: ReferenceItem[]; total: number; used_bytes: number; max_items: number; max_bytes: number }>(
      `/reference-memory?limit=${limit}`,
    )
  }

  tariff() {
    return this.request<TariffData | null>('/tariff')
  }

  support() {
    return this.request<{ items: SupportTicket[] }>('/support')
  }

  createSupport(subject: string, body: string) {
    return this.request<SupportTicket>('/support', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject, body }),
    })
  }

  replySupport(ticketId: string, body: string) {
    return this.request<SupportTicket>(`/support/${encodeURIComponent(ticketId)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    })
  }

  closeSupport(ticketId: string) {
    return this.request<SupportTicket>(`/support/${encodeURIComponent(ticketId)}/close`, { method: 'POST' })
  }

  partner() {
    return this.request<PartnerData>('/partner')
  }

  joinPartner() {
    return this.request<PartnerData['profile']>('/partner/join', { method: 'POST' })
  }

  requestWithdrawal(amountUnits: number, destination: string) {
    return this.request('/partner/withdrawals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': randomId() },
      body: JSON.stringify({ amount_units: amountUnits, destination }),
    })
  }

  starPackages() {
    return this.request<{ items: StarPackage[] }>('/payments/stars/packages')
  }

  createStarInvoice(packageCode: string) {
    return this.request<{ invoice_url: string; invoice_payload: string; order_id: string }>('/payments/stars/invoices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': randomId() },
      body: JSON.stringify({ package_code: packageCode }),
    })
  }

  uploadMotion(kind: 'image' | 'video', file: File) {
    return this.request<{ storage_key: string; kind: string; content_type: string; size_bytes: number }>(
      `/motion/kling/inputs/${kind}`,
      { method: 'POST', headers: { 'Content-Type': file.type }, body: file },
    )
  }

  submitMotion(payload: {
    prompt: string
    image_storage_key: string
    video_storage_key: string
    mode: '720p' | '1080p'
    character_orientation: 'image' | 'video'
    background_source: 'input_video'
  }) {
    return this.request('/motion/kling', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': randomId() },
      body: JSON.stringify(payload),
    })
  }
}

export const miniAppApi = new MiniAppApi()
