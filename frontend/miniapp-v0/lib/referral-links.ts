import {
  MINIAPP_BASE_PATH,
  TELEGRAM_BOT_USERNAME,
  TELEGRAM_START_PARAM,
} from './product'

const START_PARAM_RE = /^[A-Za-z0-9_-]{1,64}$/
export const REFERRAL_STORAGE_KEY = 'happyfox_ref_start_param'

export function normalizeStartParam(raw: string | null | undefined): string {
  const value = String(raw || '').trim()
  if (!value || !START_PARAM_RE.test(value)) return ''
  if (/^ref_/i.test(value)) {
    const code = value.slice(4).trim()
    return code ? `ref_${code.toUpperCase()}` : ''
  }
  return value
}

function normalizeRefCode(raw: string | null | undefined): string {
  const value = String(raw || '').trim().replace(/^ref_/i, '')
  if (!value || !/^[A-Za-z0-9_-]{1,60}$/.test(value)) return ''
  return `ref_${value.toUpperCase()}`
}

export function resolveLandingStartParam(
  params: URLSearchParams,
  storedReferral = '',
): string {
  for (const key of ['startapp', 'start']) {
    const direct = normalizeStartParam(params.get(key))
    if (direct) return direct
  }

  const referral = normalizeRefCode(params.get('ref'))
  if (referral) return referral

  const stored = normalizeStartParam(storedReferral)
  if (stored.startsWith('ref_')) return stored

  return TELEGRAM_START_PARAM
}

export function buildTelegramBotUrl(startParam = TELEGRAM_START_PARAM): string {
  const normalized = normalizeStartParam(startParam) || TELEGRAM_START_PARAM
  return `https://t.me/${TELEGRAM_BOT_USERNAME}?start=${encodeURIComponent(normalized)}`
}

export function buildBrowserMiniAppUrl(startParam = TELEGRAM_START_PARAM): string {
  const normalized = normalizeStartParam(startParam) || TELEGRAM_START_PARAM
  return `${MINIAPP_BASE_PATH}/?startapp=${encodeURIComponent(normalized)}`
}

export function isReferralStartParam(startParam: string): boolean {
  return normalizeStartParam(startParam).startsWith('ref_')
}
