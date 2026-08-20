'use client'

import type {
  BootstrapResponse,
  CreatePaymentResponse,
  FeedComment,
  FeedItem,
  PaymentProvider,
  ProfileSummary,
  PromptItem,
  SavedReference,
  ScenarioType,
  Task,
  TaskDetail,
  TrendGenerationSettings,
  UploadedFile,
} from './types'

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData?: string
        initDataUnsafe?: { start_param?: string }
        ready?: () => void
        expand?: () => void
        openInvoice?: (url: string, callback?: (status: string) => void) => void
      }
    }
    __BANANO_MINIAPP_CONFIG__?: {
      botUsername?: string
      miniAppUrl?: string
    }
    __BANANO_INITIAL_LAUNCH__?: {
      hash?: string
      search?: string
    }
    __BANANO_TG_INIT_DATA__?: string
  }
}

const INIT_DATA_STORAGE_KEY = '__banano_tg_init_data'

function getWebApp() {
  if (typeof window === 'undefined') {
    return null
  }
  return window.Telegram?.WebApp || null
}

function getLaunchParams(): URLSearchParams {
  if (typeof window === 'undefined') {
    return new URLSearchParams()
  }

  const rawHash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash
  const hashParams = new URLSearchParams(rawHash)
  const searchParams = new URLSearchParams(window.location.search)

  for (const [key, value] of searchParams.entries()) {
    if (!hashParams.has(key)) {
      hashParams.set(key, value)
    }
  }

  return hashParams
}

function getTelegramLaunchValue(name: string): string {
  const params = getLaunchParams()
  return String(params.get(name) || '').trim()
}

function getInitDataFromLocation(): string {
  // tgWebAppData may appear in hash OR search params depending on Telegram version
  const raw = getTelegramLaunchValue('tgWebAppData')
  if (raw) return raw

  if (typeof window === 'undefined') return ''

  const parseLaunch = (rawValue: string) => {
    const value = String(rawValue || '').trim()
    if (!value) return ''
    const params = new URLSearchParams(value.startsWith('#') || value.startsWith('?') ? value.slice(1) : value)
    return String(params.get('tgWebAppData') || '').trim()
  }

  try {
    const snap = window.__BANANO_INITIAL_LAUNCH__
    const fromSnapshot = parseLaunch(snap?.hash || '') || parseLaunch(snap?.search || '')
    if (fromSnapshot) return fromSnapshot
  } catch {}

  for (const key of ['__banano_initial_hash', '__banano_initial_search']) {
    try {
      const fromStorageSnapshot = parseLaunch(window.sessionStorage.getItem(key) || '')
      if (fromStorageSnapshot) return fromStorageSnapshot
    } catch {}
  }

  return ''
}

export function getInitData(): string {
  // Prefer initData from location hash (tgWebAppData) — it's available
  // before window.Telegram.WebApp is fully initialized. This is critical
  // on slow networks/VPN where the Telegram SDK CDN may be delayed.
  const fromLocation = getInitDataFromLocation()
  const fromTelegram = getWebApp()?.initData || ''
  const fromWindow =
    typeof window !== 'undefined'
      ? String(window.__BANANO_TG_INIT_DATA__ || '').trim()
      : ''
  const initData = fromLocation || fromTelegram || fromWindow
  if (initData && typeof window !== 'undefined') {
    try {
      window.__BANANO_TG_INIT_DATA__ = initData
      window.sessionStorage.setItem(INIT_DATA_STORAGE_KEY, initData)
    } catch {}
    return initData
  }

  if (typeof window !== 'undefined') {
    try {
      const fromStorage = window.sessionStorage.getItem(INIT_DATA_STORAGE_KEY) || ''
      if (fromStorage) {
        window.__BANANO_TG_INIT_DATA__ = fromStorage
        return fromStorage
      }
    } catch {}
  }
  return ''
}

export function hasTelegramInitData(): boolean {
  return Boolean(getInitData())
}

export function waitForTelegramInitData(timeoutMs = 10000): Promise<boolean> {
  if (hasTelegramInitData()) {
    return Promise.resolve(true)
  }
  if (typeof window === 'undefined') {
    return Promise.resolve(false)
  }

  const startedAt = Date.now()
  return new Promise((resolve) => {
    const check = () => {
      if (hasTelegramInitData()) {
        resolve(true)
        return
      }
      if (Date.now() - startedAt >= timeoutMs) {
        resolve(false)
        return
      }
      window.setTimeout(check, 50)
    }
    check()
  })
}

export function getStartParamFallback(): string {
  if (typeof window === "undefined") return ""

  // 1. Check Telegram initDataUnsafe.start_param (standard Telegram API)
  const direct = String(getWebApp()?.initDataUnsafe?.start_param || "").trim()
  if (direct) return direct

  // 2. Check our early snapshot (captured BEFORE Telegram SDK modifies the URL)
  try {
    const snap = (window as any).__BANANO_INITIAL_LAUNCH__
    if (snap) {
      // Check hash for tgWebAppStartParam (Telegram passes startapp in hash launch params)
      const hashSnap = String(snap.hash || "").trim()
      if (hashSnap.startsWith("#")) {
        const hashParams = new URLSearchParams(hashSnap.slice(1))
        const fromHash = String(hashParams.get("tgWebAppStartParam") || "").trim()
        if (fromHash) return fromHash
      }
    }
  } catch (_) {}

  // 3. Check Telegram SDK initParams (raw launch params from URL hash at SDK init)
  try {
    const sdk = (window as any).Telegram?.WebApp
    const rawStartParam = sdk?.initParams?.tgWebAppStartParam
    if (rawStartParam && typeof rawStartParam === 'string' && rawStartParam.trim()) {
      return rawStartParam.trim()
    }
  } catch (_) {}

  // 4. Check sessionStorage snapshots (captured at page load, before any script modifications)
  for (const key of ['__banano_initial_hash', '__telegram__initParams']) {
    try {
      const raw = window.sessionStorage.getItem(key)
      if (!raw) continue
      let parsed: any = raw
      if (key === '__telegram__initParams') {
        parsed = JSON.parse(raw)
        const sp = parsed?.tgWebAppStartParam
        if (sp && typeof sp === 'string' && sp.trim()) return sp.trim()
      } else {
        // __banano_initial_hash
        if (typeof parsed === 'string' && parsed.startsWith('#')) {
          const hp = new URLSearchParams(parsed.slice(1))
          const sp = String(hp.get('tgWebAppStartParam') || '').trim()
          if (sp) return sp
        }
      }
    } catch (_) {}
  }

  // 5. Fallback: parse current URL hash/search params
  const launchParams = getLaunchParams()
  const tg = String(launchParams.get("tgWebAppStartParam") || launchParams.get("startapp") || "").trim()
  if (tg) return tg

  // 6. Check start=ref_ in URL
  const start = String(launchParams.get("start") || "").trim()
  if (start.startsWith("ref_")) return start

  // 7. Parse tgWebAppData for start_param
  const initData = getInitDataFromLocation()
  const initDataStartParam = initData ? String(new URLSearchParams(initData).get("start_param") || "").trim() : ""
  if (initDataStartParam) return initDataStartParam

  // 8. Check ref=CODE in URL
  const ref = String(launchParams.get("ref") || "").trim().toUpperCase()
  return ref ? `ref_${ref}` : ""
}

export function getRuntimeBotUsername(): string {
  if (typeof window === 'undefined') return ''
  return String(window.__BANANO_MINIAPP_CONFIG__?.botUsername || '').trim().replace(/^@/, '')
}

export function buildTelegramMiniAppUrl(startParam = getStartParamFallback()): string {
  const username = getRuntimeBotUsername()
  if (!username) return ''
  const param = String(startParam || '').trim()
  return param
    ? `https://t.me/${username}?startapp=${encodeURIComponent(param)}`
    : `https://t.me/${username}?startapp`
}

export function getApiBasePath(): string {
  if (typeof window === 'undefined') {
    return '/mini-app/api'
  }
  const override = process.env.NEXT_PUBLIC_MINIAPP_API_BASE
  if (override) {
    return override.replace(/\/$/, '')
  }
  const path = window.location.pathname || '/mini-app/'
  const root = path.endsWith('/') ? path.slice(0, -1) : path
  if (root.includes('/mini-app')) {
    const idx = root.indexOf('/mini-app')
    return `${root.slice(0, idx)}/mini-app/api`
  }
  return '/mini-app/api'
}

function getUploadApiUrl(): string {
  const path = `${getApiBasePath()}/upload`
  if (typeof window === 'undefined') return path
  if (window.location.hostname.toLowerCase() === 'cdn.chillcreative.ru') {
    return 'https://tanyapi.chillcreative.ru/mini-app/api/upload'
  }
  return path
}

function isTemporaryMediaUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false
  try {
    const host = new URL(value).hostname.toLowerCase()
    return host === 'tempfile.aiquickdraw.com' || host.endsWith('.tempfile.aiquickdraw.com')
  } catch {
    return false
  }
}

function rewriteBackendUploadUrl(value: string): string {
  if (typeof window === 'undefined') return value
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase()
    if (host === 'tanyapi.chillcreative.ru' && url.pathname.startsWith('/uploads/feed/thumbs/')) {
      return `${window.location.origin}${url.pathname}${url.search}${url.hash}`
    }
  } catch {
    return value
  }
  return value
}

function restoreProviderUploadUrl(value: string | null | undefined): string {
  if (!value) return ''
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase()
    if (host === 'cdn.chillcreative.ru' && url.pathname.startsWith('/uploads/')) {
      return `https://tanyapi.chillcreative.ru${url.pathname}${url.search}${url.hash}`
    }
  } catch {
    return value
  }
  return value
}

function restoreProviderUploadUrls(values: string[]): string[] {
  return values.map((value) => restoreProviderUploadUrl(value)).filter(Boolean)
}

function rewriteTemporaryMedia(value: unknown): unknown {
  if (typeof value === 'string') return rewriteBackendUploadUrl(value)
  if (Array.isArray(value)) return value.map(rewriteTemporaryMedia)
  if (!value || typeof value !== 'object') return value

  const source = value as Record<string, unknown>
  const rewritten: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(source)) {
    rewritten[key] = rewriteTemporaryMedia(item)
  }

  const taskId = typeof source.task_id === 'string' ? source.task_id.trim() : ''
  if (!taskId) return rewritten
  const originalUrls = Array.isArray(source.result_urls)
    ? source.result_urls.filter((item): item is string => typeof item === 'string')
    : []
  const primaryUrl = typeof source.result_url === 'string' ? source.result_url : ''
  if (primaryUrl && !originalUrls.includes(primaryUrl)) originalUrls.unshift(primaryUrl)
  const proxyUrl = (index: number) =>
    `${getApiBasePath()}/media/${encodeURIComponent(taskId)}/${index}`

  rewritten.result_urls = originalUrls.map((url, index) =>
    isTemporaryMediaUrl(url) ? proxyUrl(index) : url
  )
  const primaryIndex = Math.max(0, originalUrls.indexOf(primaryUrl))
  if (isTemporaryMediaUrl(primaryUrl)) rewritten.result_url = proxyUrl(primaryIndex)
  if (isTemporaryMediaUrl(source.preview_url)) {
    const previewIndex = Math.max(0, originalUrls.indexOf(String(source.preview_url)))
    rewritten.preview_url = proxyUrl(previewIndex)
  }
  return rewritten
}

async function parseJson<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || ''
  const text = await response.text()
  let data: unknown

  try {
    if (!contentType.includes('application/json') && !/^\s*[\[{]/.test(text)) {
      throw new Error('Non-JSON response')
    }
    data = JSON.parse(text)
  } catch (error) {
    console.error('Mini App API returned invalid JSON', {
      status: response.status,
      url: response.url,
      contentType,
      preview: text.slice(0, 160),
      error,
    })
    throw new Error('Не удалось загрузить данные. Обновите mini app и попробуйте снова.')
  }

  const payload = data as { ok?: boolean; error?: string }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || 'Не удалось выполнить действие')
  }
  return rewriteTemporaryMedia(data) as T
}

async function postJson<T>(path: string, payload: Record<string, unknown>): Promise<T> {
  const nextPayload = { ...payload }
  const startParamFallback = getStartParamFallback()
  if (startParamFallback && !nextPayload.start_param_fallback) {
    nextPayload.start_param_fallback = startParamFallback
  }
  const response = await fetch(`${getApiBasePath()}/${path.replace(/^\/+/, '')}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(nextPayload),
    cache: 'no-store',
    credentials: 'same-origin',
  })
  return parseJson<T>(response)
}

export async function bootstrapApp(): Promise<BootstrapResponse> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  return postJson<BootstrapResponse>('bootstrap', { init_data: initData })
}

export async function createPayment(payload: {
  packageId: string
  provider: PaymentProvider
  promoCode?: string
}): Promise<CreatePaymentResponse> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  return postJson<CreatePaymentResponse>('create-payment', {
    init_data: initData,
    package_id: payload.packageId,
    provider: payload.provider,
    promo_code: payload.promoCode || '',
  })
}

export async function fetchTaskDetail(taskId: string): Promise<TaskDetail> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; task: TaskDetail }>('task-detail', {
    init_data: initData,
    task_id: taskId,
  })
  return response.task
}

const MEDIA_UPLOAD_TIMEOUT_MS = 900_000

const MEDIA_MIME_BY_EXTENSION: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  heic: 'image/heic',
  heif: 'image/heif',
  avif: 'image/avif',
  mp4: 'video/mp4',
  mov: 'video/quicktime',
  m4v: 'video/x-m4v',
  webm: 'video/webm',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  m4a: 'audio/mp4',
  aac: 'audio/aac',
  ogg: 'audio/ogg',
}

function normalizedMediaUploadFile(file: File): File {
  const declaredType = String(file.type || '').toLowerCase()
  if (declaredType && declaredType !== 'application/octet-stream') return file

  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const inferredType = MEDIA_MIME_BY_EXTENSION[extension]
  if (!inferredType) return file

  return new File([file], file.name, {
    type: inferredType,
    lastModified: file.lastModified,
  })
}

export function sendMiniAppClientLog(event: string, payload: Record<string, unknown> = {}) {
  if (typeof window === 'undefined') return
  try {
    const body = JSON.stringify({
      event,
      href: `${window.location.pathname || ''}${window.location.search || ''}`,
      search: window.location.search || '',
      hash_len: window.location.hash.length,
      has_tg: Boolean(window.Telegram),
      has_webapp: Boolean(window.Telegram?.WebApp),
      init_data_len: getInitData().length,
      ...payload,
    })
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' })
      if (navigator.sendBeacon(`${getApiBasePath()}/client-log`, blob)) return
    }
    void fetch(`${getApiBasePath()}/client-log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {})
  } catch {
    // best-effort diagnostics only
  }
}

function parseUploadJson(text: string, status: number): {
  ok: true
  url: string
  kind: 'image' | 'video' | 'audio'
  filename: string
  reference?: SavedReference | null
} {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error('Не удалось загрузить данные. Обновите mini app и попробуйте снова.')
  }

  const payload = data as {
    ok?: boolean
    error?: string
    url?: string
    kind?: 'image' | 'video' | 'audio'
    filename?: string
    reference?: SavedReference | null
  }
  if (status < 200 || status >= 300 || payload.ok === false) {
    throw new Error(payload.error || 'Не удалось выполнить действие')
  }
  if (!payload.url || !payload.kind || !payload.filename) {
    throw new Error('Не удалось загрузить данные. Обновите mini app и попробуйте снова.')
  }

  return {
    ok: true,
    url: payload.url,
    kind: payload.kind,
    filename: payload.filename,
    reference: payload.reference || null,
  }
}

function uploadFileWithXhr(
  formData: FormData,
  logPayload: Record<string, unknown>,
  startedAt: number,
): Promise<{
  ok: true
  url: string
  kind: 'image' | 'video' | 'audio'
  filename: string
  reference?: SavedReference | null
}> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', getUploadApiUrl())
    xhr.timeout = MEDIA_UPLOAD_TIMEOUT_MS
    xhr.responseType = 'text'
    xhr.setRequestHeader('Accept', 'application/json')

    xhr.onload = () => {
      sendMiniAppClientLog('upload-response', {
        ...logPayload,
        duration_ms: Date.now() - startedAt,
        status: xhr.status,
      })
      try {
        resolve(parseUploadJson(String(xhr.responseText || ''), xhr.status))
      } catch (error) {
        reject(error)
      }
    }
    xhr.onerror = () => {
      sendMiniAppClientLog('upload-network-error', {
        ...logPayload,
        duration_ms: Date.now() - startedAt,
        message: 'XMLHttpRequest network error',
      })
      reject(new Error('Сеть оборвала загрузку. Проверьте соединение и повторите.'))
    }
    xhr.ontimeout = () => {
      sendMiniAppClientLog('upload-network-error', {
        ...logPayload,
        duration_ms: Date.now() - startedAt,
        message: 'XMLHttpRequest timeout',
      })
      reject(new Error('Загрузка не завершилась за 15 минут. Проверьте сеть и повторите.'))
    }
    xhr.onabort = () => {
      sendMiniAppClientLog('upload-network-error', {
        ...logPayload,
        duration_ms: Date.now() - startedAt,
        message: 'XMLHttpRequest aborted',
      })
      reject(new Error('Загрузка была отменена. Повторите попытку.'))
    }
    xhr.send(formData)
  })
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Не удалось прочитать файл для загрузки.'))
    reader.onload = () => {
      const result = String(reader.result || '')
      const [, encoded = ''] = result.split(',', 2)
      if (!encoded) {
        reject(new Error('Не удалось подготовить файл для загрузки.'))
        return
      }
      resolve(encoded)
    }
    reader.readAsDataURL(file)
  })
}

async function uploadFileAsJson(
  fileKind: 'image_reference' | 'video_reference' | 'audio_reference' | 'assistant_audio' | 'trend_video_preview',
  file: File,
  initData: string,
  logPayload: Record<string, unknown>,
  startedAt: number,
) {
  sendMiniAppClientLog('upload-json-fallback-start', logPayload)
  const response = await fetch(getUploadApiUrl(), {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      init_data: initData,
      file_kind: fileKind,
      filename: file.name,
      content_type: file.type,
      data_base64: await fileToBase64(file),
    }),
    cache: 'no-store',
    credentials: 'same-origin',
  })
  sendMiniAppClientLog('upload-json-fallback-response', {
    ...logPayload,
    duration_ms: Date.now() - startedAt,
    status: response.status,
  })
  return parseUploadJson(await response.text(), response.status)
}

export async function uploadFile(
  fileKind: 'image_reference' | 'video_reference' | 'audio_reference' | 'assistant_audio' | 'trend_video_preview',
  file: File
): Promise<UploadedFile> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const normalizedFile = normalizedMediaUploadFile(file)
  const startedAt = Date.now()
  const uploadLogPayload = {
    file_kind: fileKind,
    file_name: normalizedFile.name,
    file_type: normalizedFile.type,
    file_size: normalizedFile.size,
  }
  sendMiniAppClientLog('upload-start', uploadLogPayload)
  const formData = new FormData()
  formData.append('init_data', initData)
  formData.append('file_kind', fileKind)
  formData.append('file', normalizedFile)

  if (typeof XMLHttpRequest !== 'undefined') {
    let data: Awaited<ReturnType<typeof uploadFileWithXhr>>
    try {
      data = await uploadFileWithXhr(formData, uploadLogPayload, startedAt)
    } catch (error) {
      data = await uploadFileAsJson(fileKind, normalizedFile, initData, uploadLogPayload, startedAt)
    }
    return {
      id: `file_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      name: data.filename,
      url: data.url,
      type: data.kind,
      size: normalizedFile.size,
      saved_reference_id: data.reference?.id || null,
      created_at: data.reference?.created_at || null,
      source: data.reference?.source,
    }
  }

  const controller = new AbortController()
  const timeoutId = globalThis.setTimeout(() => controller.abort(), MEDIA_UPLOAD_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch(getUploadApiUrl(), {
      method: 'POST',
      headers: { Accept: 'application/json' },
      body: formData,
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
    })
  } catch (error) {
    sendMiniAppClientLog('upload-network-error', {
      ...uploadLogPayload,
      duration_ms: Date.now() - startedAt,
      message: error instanceof Error ? error.message : String(error),
    })
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Загрузка не завершилась за 15 минут. Проверьте сеть и повторите.')
    }
    throw error
  } finally {
    globalThis.clearTimeout(timeoutId)
  }

  sendMiniAppClientLog('upload-response', {
    ...uploadLogPayload,
    duration_ms: Date.now() - startedAt,
    status: response.status,
  })

  const data = await parseJson<{
    ok: true
    url: string
    kind: 'image' | 'video' | 'audio'
    filename: string
    reference?: SavedReference | null
  }>(response)

  return {
    id: `file_${Date.now()}_${Math.random().toString(36).slice(2)}`,
    name: data.filename,
    url: data.url,
    type: data.kind,
    size: normalizedFile.size,
    saved_reference_id: data.reference?.id || null,
    created_at: data.reference?.created_at || null,
    source: data.reference?.source,
  }
}

export async function generateImage(payload: {
  model: string
  ratio: string
  quality: string
  nsfwChecker?: boolean
  nsfwEnabled?: boolean
  promptId?: number | null
  sourceFeedGenId?: number | null
  prompt: string
  references: string[]
}): Promise<{
  task: Task
  detail?: TaskDetail | null
  credits: number
}> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const response = await postJson<{
    ok: true
    status: 'queued' | 'done'
    task_id: string
    saved_url?: string
    credits: number
    cost: number
    model_label: string
    prompt_hidden?: boolean
    prompt_actions_allowed?: boolean
    source_feed_gen_id?: number | null
  }>('generate-image', {
    init_data: initData,
    img_service: payload.model,
    img_ratio: payload.ratio,
    img_quality: payload.quality,
    img_nsfw_checker: payload.nsfwChecker ?? false,
    nsfw_enabled: payload.nsfwEnabled ?? false,
    prompt: payload.prompt,
    prompt_id: payload.promptId || null,
    source_feed_gen_id: payload.sourceFeedGenId || null,
    reference_images: restoreProviderUploadUrls(payload.references),
  })

  const promptHidden = Boolean(response.prompt_hidden)

  const task: Task = {
    task_id: response.task_id,
    type: 'image',
    model: payload.model,
    model_label: response.model_label,
    aspect_ratio: payload.ratio,
    status: response.status === 'done' ? 'completed' : 'pending',
    result_url: response.saved_url || null,
    created_at: new Date().toISOString(),
    prompt_preview: promptHidden
      ? ''
      : payload.prompt.slice(0, 100) + (payload.prompt.length > 100 ? '...' : ''),
    cost: response.cost,
    prompt_hidden: promptHidden,
    prompt_actions_allowed: response.prompt_actions_allowed ?? !promptHidden,
  }

  return {
    task,
    detail:
      response.status === 'done'
        ? {
            ...task,
            prompt: promptHidden ? '' : payload.prompt,
            request_data: {
              reference_images: restoreProviderUploadUrls(payload.references),
              source_feed_gen_id: response.source_feed_gen_id || payload.sourceFeedGenId || null,
            },
          }
        : null,
    credits: response.credits,
  }
}

export async function fetchPrompts(payload: {
  source?: 'catalog' | 'top' | 'popular' | 'tag' | 'my'
  tag?: string
  category?: string
  page?: number
  limit?: number
} = {}): Promise<PromptItem[]> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; prompts: PromptItem[] }>('prompts', {
    init_data: initData,
    source: payload.source || 'catalog',
    tag: payload.tag || '',
    category: payload.category || '',
    page: payload.page || 1,
    limit: payload.limit || 24,
  })
  return response.prompts
}

export async function fetchPromptDetail(promptId: number): Promise<PromptItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; prompt: PromptItem }>('prompts/detail', {
    init_data: initData,
    prompt_id: promptId,
  })
  return response.prompt
}

export async function fetchPromptLink(promptId: number): Promise<string> {
  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')
  const response = await postJson<{ ok: true; link: string }>('prompts/link', {
    init_data: initData,
    prompt_id: promptId,
  })
  return response.link
}

export async function likePrompt(promptId: number): Promise<PromptItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; prompt: PromptItem }>('prompts/like', {
    init_data: initData,
    prompt_id: promptId,
  })
  return response.prompt
}

export async function submitPrompt(payload: {
  title: string
  description: string
  promptText: string
  previewUrl?: string
  model?: string
  tags?: string[]
  generationSettings?: TrendGenerationSettings
}): Promise<PromptItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; prompt: PromptItem }>('prompts/submit', {
    init_data: initData,
    title: payload.title,
    description: payload.description,
    prompt_text: payload.promptText,
    preview_url: payload.previewUrl || '',
    model: payload.model || '',
    tags: payload.tags || [],
    generation_settings: payload.generationSettings || {},
  })
  return response.prompt
}

export async function deactivatePrompt(promptId: number): Promise<PromptItem | null> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; prompt: PromptItem | null }>('prompts/deactivate', {
    init_data: initData,
    prompt_id: promptId,
  })
  return response.prompt
}

export async function fetchFeed(payload: {
  source?: 'recent' | 'top_day' | 'top'
  model?: string
  limit?: number
  offset?: number
} = {}): Promise<{ feed: FeedItem[]; models: Array<{ id: string; label: string }> }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{
    ok: true
    feed: FeedItem[]
    models?: Array<{ id: string; label: string }>
  }>('feed', {
    init_data: initData,
    source: payload.source || 'recent',
    model: payload.model || 'banana_pro',
    limit: payload.limit ?? 80,
    offset: payload.offset ?? 0,
  })
  return { feed: response.feed, models: response.models || [] }
}

export async function fetchFeedItem(genId: number): Promise<FeedItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; feed_item: FeedItem }>('feed/item', {
    init_data: initData,
    gen_id: genId,
  })
  return response.feed_item
}

export async function fetchMyFeed(limit = 80, offset = 0): Promise<FeedItem[]> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; feed: FeedItem[] }>('feed/my', {
    init_data: initData,
    limit,
    offset,
  })
  return response.feed
}

export async function fetchProfileFeed(
  referralCode: string,
  limit = 80,
  offset = 0
): Promise<{ profile: ProfileSummary; feed: FeedItem[] }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; profile: ProfileSummary; feed: FeedItem[] }>('feed/profile', {
    init_data: initData,
    referral_code: referralCode,
    limit,
    offset,
  })
  return { profile: response.profile, feed: response.feed }
}

export type FeedInteractionSurface = 'feed' | 'profile'

export async function likeFeedItem(
  genId: number,
  surface: FeedInteractionSurface = 'feed'
): Promise<FeedItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; feed_item: FeedItem }>('feed/like', {
    init_data: initData,
    gen_id: genId,
    surface,
  })
  return response.feed_item
}

export async function shareFeedItem(
  genId: number,
  surface: FeedInteractionSurface = 'feed'
): Promise<{ item: FeedItem; link: string; postLink: string; remixLink: string }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{
    ok: true
    feed_item: FeedItem
    link: string
    post_link?: string
    repeat_link?: string
    miniapp_link?: string
    miniapp_post_link?: string
    miniapp_repeat_link?: string
  }>('feed/share', {
    init_data: initData,
    gen_id: genId,
    surface,
  })
  const isImage = String(response.feed_item?.gen_type || '').toLowerCase() === 'image'
  const postLink =
    surface === 'profile'
      ? response.miniapp_post_link || response.miniapp_link || response.post_link || response.link
      : response.post_link || response.miniapp_post_link || response.link
  const remixLink =
    surface === 'profile'
      ? response.miniapp_repeat_link || response.repeat_link || postLink
      : response.repeat_link || response.miniapp_repeat_link || postLink
  const preferredLink = isImage ? remixLink : postLink
  return { item: response.feed_item, link: preferredLink, postLink, remixLink }
}

export async function fetchFeedComments(
  genId: number,
  limit = 40,
  surface: FeedInteractionSurface = 'feed'
): Promise<FeedComment[]> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; comments: FeedComment[] }>('feed/comments', {
    init_data: initData,
    gen_id: genId,
    limit,
    surface,
  })
  return response.comments
}

export async function addFeedComment(
  genId: number,
  text: string,
  surface: FeedInteractionSurface = 'feed'
): Promise<{ comment: FeedComment; commentsCount: number }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; comment: FeedComment; comments_count: number }>('feed/comment', {
    init_data: initData,
    gen_id: genId,
    text,
    surface,
  })
  return { comment: response.comment, commentsCount: response.comments_count }
}

export async function removeFeedItem(genId: number): Promise<void> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; removed: boolean }>('feed/remove', {
    init_data: initData,
    gen_id: genId,
  })
  if (!response.removed) {
    throw new Error('Не удалось убрать пост')
  }
}

export async function publishGeneration(
  taskId: string,
  options: {
    promptVisible?: boolean
    referencesVisible?: boolean
    blurred?: boolean
    publicationScope?: 'profile' | 'feed'
    adultContent?: boolean
  } = {}
): Promise<FeedItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; feed_item: FeedItem }>('generations/share', {
    init_data: initData,
    task_id: taskId,
    prompt_visible: Boolean(options.promptVisible),
    references_visible: Boolean(options.referencesVisible),
    feed_blurred: Boolean(options.blurred),
    publication_scope: options.publicationScope || 'feed',
    adult_content: Boolean(options.adultContent),
  })
  return response.feed_item
}

export async function setFeedItemBlurred(genId: number, blurred: boolean): Promise<FeedItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; feed_item: FeedItem }>('feed/blur', {
    init_data: initData,
    gen_id: genId,
    blurred,
  })
  return response.feed_item
}

export async function unpublishGeneration(taskId: string): Promise<void> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; removed: boolean }>('feed/remove', {
    init_data: initData,
    task_id: taskId,
  })
  if (!response.removed) {
    throw new Error('Не удалось убрать пост')
  }
}

export async function saveGenerationPrompt(taskId: string): Promise<void> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  await postJson<{ ok: true }>('generations/share-library', {
    init_data: initData,
    task_id: taskId,
  })
}

export async function removeGenerationPrompt(taskId: string): Promise<void> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  await postJson<{ ok: true; removed: boolean }>('generations/remove-library', {
    init_data: initData,
    task_id: taskId,
  })
}

export async function remixFeedItem(payload: {
  genId: number
  model: string
  ratio: string
  quality: string
  prompt?: string
  references?: string[]
}): Promise<{
  task: Task
  detail?: TaskDetail | null
  credits: number
}> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{
    ok: true
    status: 'queued' | 'done'
    task_id: string
    saved_url?: string
    credits: number
    cost: number
    model_label: string
    prompt_hidden: boolean
    prompt_actions_allowed: boolean
    source_feed_gen_id: number
  }>('feed/remix', {
    init_data: initData,
    gen_id: payload.genId,
    img_service: payload.model,
    img_ratio: payload.ratio,
    img_quality: payload.quality,
    prompt: payload.prompt || '',
    reference_images: restoreProviderUploadUrls(payload.references || []),
  })

  const task: Task = {
    task_id: response.task_id,
    type: 'image',
    model: payload.model,
    model_label: response.model_label,
    aspect_ratio: payload.ratio,
    status: response.status === 'done' ? 'completed' : 'pending',
    result_url: response.saved_url || null,
    created_at: new Date().toISOString(),
    prompt_preview: '',
    cost: response.cost,
    prompt_hidden: response.prompt_hidden,
    prompt_actions_allowed: response.prompt_actions_allowed,
  }

  return {
    task,
    detail:
      response.status === 'done'
        ? {
            ...task,
            prompt: '',
            request_data: {
              source_feed_gen_id: response.source_feed_gen_id,
              reference_images: restoreProviderUploadUrls(payload.references || []),
            },
          }
        : null,
    credits: response.credits,
  }
}

export async function executeMiniAppAction(action: string): Promise<void> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  await postJson<{ ok: true }>('action', {
    init_data: initData,
    action,
  })
}

export async function generateVideo(payload: {
  model: string
  scenario: ScenarioType
  ratio: string
  duration: number
  sourceFeedGenId?: number | null
  grokMode?: string
  grokResolution?: string
  veoGenerationType?: string
  veoTranslation?: boolean
  veoResolution?: string
  veoSeed?: number | null
  veoWatermark?: string
  klingNegativePrompt?: string
  klingCfgScale?: number
  omniResolution?: string
  omniSeed?: number | null
  omniAudioIds?: string[]
  omniCharacterIds?: string[]
  omniBaseVoice?: string
  omniVoiceName?: string
  omniVoiceDescription?: string
  omniExampleDialogue?: string
  omniCharacterName?: string
  omniCharacterAudioIds?: string[]
  prompt: string
  startImage: string | null
  references: string[]
  videoReferences: string[]
  audioReference?: string | null
}): Promise<{
  task: Task
  detail?: TaskDetail | null
  credits: number
}> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const startImage = restoreProviderUploadUrl(payload.startImage)
  const imageReferences = restoreProviderUploadUrls(payload.references)
  const videoReferences = restoreProviderUploadUrls(payload.videoReferences)
  const audioReference = restoreProviderUploadUrl(payload.audioReference)

  const response = await postJson<{
    ok: true
    status: 'queued' | 'done'
    task_id: string
    saved_url?: string
    task_type?: 'image' | 'video' | 'audio' | 'character'
    credits: number
    cost: number
    model_label: string
    prompt_hidden?: boolean
    prompt_actions_allowed?: boolean
    source_feed_gen_id?: number | null
  }>('generate-video', {
    init_data: initData,
    v_model: payload.model,
    v_type: payload.scenario,
    v_ratio: payload.ratio,
    v_duration: payload.duration,
    source_feed_gen_id: payload.sourceFeedGenId || null,
    grok_mode: payload.grokMode,
    grok_resolution: payload.grokResolution,
    veo_generation_type: payload.veoGenerationType,
    veo_translation: payload.veoTranslation,
    veo_resolution: payload.veoResolution,
    veo_seed: payload.veoSeed,
    veo_watermark: payload.veoWatermark,
    kling_negative_prompt: payload.klingNegativePrompt,
    kling_cfg_scale: payload.klingCfgScale,
    omni_resolution: payload.omniResolution,
    omni_seed: payload.omniSeed,
    omni_audio_ids: payload.omniAudioIds || [],
    omni_character_ids: payload.omniCharacterIds || [],
    omni_base_voice: payload.omniBaseVoice,
    omni_voice_name: payload.omniVoiceName,
    omni_voice_description: payload.omniVoiceDescription,
    omni_example_dialogue: payload.omniExampleDialogue,
    omni_character_name: payload.omniCharacterName,
    omni_character_audio_ids: payload.omniCharacterAudioIds || [],
    prompt: payload.prompt,
    v_image_url: startImage,
    reference_images: imageReferences,
    v_reference_videos: videoReferences,
    audio_url: audioReference,
    audio_references: audioReference ? [audioReference] : [],
  })

  const task: Task = {
    task_id: response.task_id,
    type: response.task_type || (payload.scenario === 'audio' ? 'audio' : payload.scenario === 'character' ? 'character' : 'video'),
    model: payload.model,
    model_label: response.model_label,
    aspect_ratio: payload.ratio,
    status: response.status === 'done' ? 'completed' : 'pending',
    result_url: response.saved_url || null,
    created_at: new Date().toISOString(),
    prompt_preview:
      payload.prompt.slice(0, 100) + (payload.prompt.length > 100 ? '...' : ''),
    cost: response.cost,
    duration: payload.duration,
    prompt_hidden: response.prompt_hidden,
    prompt_actions_allowed: response.prompt_actions_allowed,
  }

  return {
    task,
    detail:
      response.status === 'done'
        ? {
            ...task,
            prompt: payload.prompt,
            request_data: {
              reference_images: [
                ...(startImage ? [startImage] : []),
                ...imageReferences,
              ],
              v_reference_videos: videoReferences,
              audio_reference: audioReference || null,
              source_feed_gen_id: response.source_feed_gen_id || payload.sourceFeedGenId || null,
              omni_audio_ids: payload.omniAudioIds || [],
              omni_character_ids: payload.omniCharacterIds || [],
              omni_character_audio_ids: payload.omniCharacterAudioIds || [],
            },
          }
        : null,
    credits: response.credits,
  }
}

export async function askAIAssistant(payload: {
  message: string
  history: { role: 'user' | 'assistant'; text: string }[]
  audioUrl?: string | null
  audioContentType?: string | null
}): Promise<{ reply: string }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const response = await postJson<{ ok: true; reply: string }>('ai-assistant', {
    init_data: initData,
    message: payload.message,
    history: payload.history,
    audio_url: payload.audioUrl || '',
    audio_content_type: payload.audioContentType || '',
  })

  return { reply: response.reply }
}

export async function generateMotion(payload: {
  prompt: string
  imageUrl: string
  videoUrl: string
  mode: '720p' | '1080p'
  direction: 'video' | 'image'
  model: 'motion_control_v26' | 'motion_control_v30'
  videoDuration?: number
}): Promise<{
  task: Task
  detail?: TaskDetail | null
  credits: number
}> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const imageUrl = restoreProviderUploadUrl(payload.imageUrl)
  const videoUrl = restoreProviderUploadUrl(payload.videoUrl)

  const response = await postJson<{
    ok: true
    status: 'queued' | 'done'
    task_id: string
    saved_url?: string
    credits: number
    cost: number
    model_label: string
  }>('generate-motion', {
    init_data: initData,
    prompt: payload.prompt,
    motion_model: payload.model,
    motion_image_url: imageUrl,
    motion_video_url: videoUrl,
    motion_mode: payload.mode,
    motion_direction: payload.direction,
    ...(payload.videoDuration ? { motion_duration: payload.videoDuration } : {}),
  })

  const task: Task = {
    task_id: response.task_id,
    type: 'video',
    model: payload.model,
    model_label: response.model_label,
    aspect_ratio: '1:1',
    status: response.status === 'done' ? 'completed' : 'pending',
    result_url: response.saved_url || null,
    created_at: new Date().toISOString(),
    prompt_preview:
      payload.prompt.slice(0, 100) + (payload.prompt.length > 100 ? '...' : ''),
    cost: response.cost,
    duration: 5,
  }

  return {
    task,
    detail:
      response.status === 'done'
        ? {
            ...task,
            prompt: payload.prompt,
            request_data: {
              v_type: 'motion_control',
              motion_model: payload.model,
              motion_image_url: imageUrl,
              motion_video_url: videoUrl,
              motion_mode: payload.mode,
              motion_direction: payload.direction,
            },
          }
        : null,
    credits: response.credits,
  }
}

export async function photoToPrompt(payload: {
  imageUrl: string
  preserve?: string
  goal?: string
}): Promise<{
  prompt_en: string
  prompt_ru: string
  negative_prompt: string
  model_hint: string
  credits: number
  cost_credits: number
  price_rub: number
}> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const response = await postJson<{
    ok: true
    prompt_en: string
    prompt_ru: string
    negative_prompt: string
    model_hint: string
    credits: number
    cost_credits: number
    price_rub: number
  }>('photo-to-prompt', {
    init_data: initData,
    image_url: restoreProviderUploadUrl(payload.imageUrl),
    preserve: payload.preserve || '',
    goal: payload.goal || '',
  })

  return {
    prompt_en: response.prompt_en,
    prompt_ru: response.prompt_ru,
    negative_prompt: response.negative_prompt,
    model_hint: response.model_hint,
    credits: response.credits,
    cost_credits: response.cost_credits,
    price_rub: response.price_rub,
  }
}

export async function fetchPartnerOverview(): Promise<{
  is_partner: boolean
  referrals_count: number
  balance_rub: number
  prompt_repeat_balance_rub: number
  prompt_repeat_total_rub: number
  channel_url: string
  referral_link: string
  status: string
}> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const response = await postJson<{
    ok: true
    is_partner: boolean
    referrals_count: number
    balance_rub: number
    prompt_repeat_balance_rub: number
    prompt_repeat_total_rub: number
    channel_url: string
    referral_link: string
    status: string
  }>('partner-overview', {
    init_data: initData,
  })

  return {
    is_partner: response.is_partner,
    referrals_count: response.referrals_count,
    balance_rub: response.balance_rub,
    prompt_repeat_balance_rub: response.prompt_repeat_balance_rub || 0,
    prompt_repeat_total_rub: response.prompt_repeat_total_rub || 0,
    channel_url: response.channel_url || '',
    referral_link: response.referral_link,
    status: response.status,
  }
}

export async function saveProfileChannel(channelUrl: string): Promise<string> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; channel_url: string }>('profile/channel', {
    init_data: initData,
    channel_url: channelUrl,
  })
  return response.channel_url || ''
}
