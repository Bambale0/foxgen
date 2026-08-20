'use client'

export type MiniAppStartTarget =
  | { kind: 'ref'; referralCode: string }
  | { kind: 'profile'; referralCode: string; referralCodeForAttribution?: string }
  | { kind: 'feed'; genId: number; referralCodeForAttribution?: string }
  | { kind: 'remix'; genId: number; referralCodeForAttribution?: string }
  | { kind: 'prompt'; promptId: number; referralCodeForAttribution?: string }
  | { kind: 'task'; taskId: string }

function normalizeCode(value: string) {
  return value.trim().toUpperCase()
}

function splitReferral(payload: string) {
  const marker = '_ref_'
  const index = payload.indexOf(marker)
  if (index === -1) {
    return {
      value: payload.trim(),
      referralCodeForAttribution: '',
    }
  }
  return {
    value: payload.slice(0, index).trim(),
    referralCodeForAttribution: normalizeCode(payload.slice(index + marker.length)),
  }
}

function parsePositiveInt(value: string) {
  if (!/^\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

export function parseMiniAppStartParam(rawValue: string): MiniAppStartTarget | null {
  const raw = rawValue.trim()
  if (!raw) return null

  if (raw.startsWith('ref_')) {
    const referralCode = normalizeCode(raw.slice(4))
    return referralCode ? { kind: 'ref', referralCode } : null
  }

  if (raw.startsWith('profile_') || raw.startsWith('posts_')) {
    const payload = raw.slice(raw.indexOf('_') + 1)
    const { value, referralCodeForAttribution } = splitReferral(payload)
    const referralCode = normalizeCode(value)
    return referralCode
      ? {
          kind: 'profile',
          referralCode,
          referralCodeForAttribution: referralCodeForAttribution || referralCode,
        }
      : null
  }

  if (raw.startsWith('feed_') || raw.startsWith('remix_')) {
    const kind = raw.startsWith('remix_') ? 'remix' : 'feed'
    const payload = raw.slice(raw.indexOf('_') + 1)
    const { value, referralCodeForAttribution } = splitReferral(payload)
    const genId = parsePositiveInt(value)
    return genId ? { kind, genId, referralCodeForAttribution } : null
  }

  if (raw.startsWith('prompt_')) {
    const payload = raw.slice('prompt_'.length)
    const { value, referralCodeForAttribution } = splitReferral(payload)
    const promptId = parsePositiveInt(value)
    return promptId ? { kind: 'prompt', promptId, referralCodeForAttribution } : null
  }

  if (raw.startsWith('task_')) {
    const taskId = raw.slice('task_'.length).trim()
    return taskId ? { kind: 'task', taskId } : null
  }

  return null
}
