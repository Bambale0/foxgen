import type { ModelDefinition, RemixSource, TabId } from './types'

export type DeepLinkIntent =
  | { kind: 'model'; value: string }
  | { kind: 'generation'; value: string }
  | { kind: 'profile'; value: string }
  | { kind: 'post'; value: string }
  | { kind: 'remix'; value: string }

const PREFIXES = [
  ['generation_', 'generation'],
  ['profile_', 'profile'],
  ['model_', 'model'],
  ['remix_', 'remix'],
  ['post_', 'post'],
] as const

export function parseDeepLinkIntent(param: string): DeepLinkIntent | null {
  const value = param.trim()
  if (!value) return null
  for (const [prefix, kind] of PREFIXES) {
    if (!value.startsWith(prefix)) continue
    const payload = value.slice(prefix.length).trim()
    if (!payload) return null
    return { kind, value: payload }
  }
  return null
}

export function tabForDeepLink(intent: DeepLinkIntent): TabId {
  if (intent.kind === 'model' || intent.kind === 'remix') return 'create'
  if (intent.kind === 'generation') return 'works'
  if (intent.kind === 'profile') return 'profile'
  return 'services'
}

function firstMediaUrl(source: RemixSource, prefix: string) {
  return source.media.find((item) => item.content_type.startsWith(prefix))?.url ?? null
}

export function remixInputSeed(model: ModelDefinition, source: RemixSource): Record<string, unknown> {
  const properties = model.input_schema?.properties ?? {}
  const result: Record<string, unknown> = {}

  if ('prompt' in properties && source.prompt) result.prompt = source.prompt

  const imageUrl = firstMediaUrl(source, 'image/')
  const videoUrl = firstMediaUrl(source, 'video/')
  const audioUrl = firstMediaUrl(source, 'audio/')

  const candidates: Array<[string, string | null, boolean]> = [
    ['image_url', imageUrl, false],
    ['image_input', imageUrl, false],
    ['image_urls', imageUrl, true],
    ['input_urls', imageUrl, true],
    ['reference_image_urls', imageUrl, true],
    ['video_url', videoUrl, false],
    ['video_urls', videoUrl, true],
    ['reference_video_urls', videoUrl, true],
    ['audio_url', audioUrl, false],
    ['reference_audio_urls', audioUrl, true],
  ]

  for (const [name, url, array] of candidates) {
    if (!url || !(name in properties)) continue
    result[name] = array ? [url] : url
    break
  }

  return result
}
