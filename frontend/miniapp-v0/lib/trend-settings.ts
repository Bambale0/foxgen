import type {
  ImageModel,
  PromptItem,
  ScenarioType,
  TrendGenerationSettings,
  VideoModel,
} from './types'

const SCENARIOS = new Set<ScenarioType>([
  'text',
  'imgtxt',
  'video',
  'avatar',
  'audio',
  'character',
])

function legacyTagValue(tags: string[], key: string): string {
  const normalizedKey = key.toLowerCase()
  for (const rawTag of tags) {
    const tag = String(rawTag || '').trim().toLowerCase()
    if (tag.startsWith(`${normalizedKey}:`)) return tag.slice(normalizedKey.length + 1)
    if (tag.startsWith(`${normalizedKey}-`)) return tag.slice(normalizedKey.length + 1)
  }
  return ''
}

function firstImageQuality(model?: ImageModel): string {
  if (!model) return 'basic'
  if (model.id === 'banana_pro' || model.id === 'banana_2') return '2K'
  return model.qualities?.[0] || 'basic'
}

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function isVideoTrendItem(
  trend: PromptItem,
  videoModels: VideoModel[],
): boolean {
  const tags = new Set((trend.tags || []).map((tag) => String(tag).toLowerCase()))

  // Public shared trend payloads deliberately carry no executable prompt/model.
  // Treat those as templates so app-context falls through to the locked trend
  // runner instead of opening the generic video repeat form.
  if (tags.has('trend') && !String(trend.prompt_text || '').trim() && !trend.model) {
    return false
  }

  const settings = trend.generation_settings
  if (settings?.kind === 'video') return true
  return (
    trend.category === 'video' ||
    tags.has('trend-video') ||
    videoModels.some((model) => model.id === trend.model)
  )
}

export function resolveTrendSettings(
  trend: PromptItem,
  imageModels: ImageModel[],
  videoModels: VideoModel[],
): TrendGenerationSettings {
  const stored = trend.generation_settings || ({} as Partial<TrendGenerationSettings>)
  const tags = trend.tags || []
  const video = isVideoTrendItem(trend, videoModels)

  if (!video) {
    const model =
      imageModels.find((item) => item.id === stored.model) ||
      imageModels.find((item) => item.id === trend.model) ||
      imageModels[0]
    const ratio =
      model?.ratios.includes(String(stored.ratio || ''))
        ? String(stored.ratio)
        : model?.ratios[0] || '1:1'
    const allowedQualities =
      model?.id === 'banana_pro' || model?.id === 'banana_2'
        ? ['1K', '2K', '4K']
        : model?.qualities || []
    const configuredQuality = String(stored.quality || '')
    const quality = allowedQualities.includes(configuredQuality)
      ? configuredQuality
      : firstImageQuality(model)
    const configuredCount = finiteNumber(stored.count)

    return {
      kind: 'image',
      user_input: 'photo',
      model: model?.id || String(stored.model || trend.model || 'banana_pro'),
      ratio,
      quality,
      count: Math.min(6, Math.max(1, Math.trunc(configuredCount || 1))),
      nsfw_checker: Boolean(stored.nsfw_checker),
      nsfw_enabled: Boolean(stored.nsfw_enabled),
    }
  }

  const model =
    videoModels.find((item) => item.id === stored.model) ||
    videoModels.find((item) => item.id === trend.model) ||
    videoModels.find((item) => item.supports.includes('imgtxt')) ||
    videoModels[0]
  const legacyScenario = legacyTagValue(tags, 'trend-scenario')
  const rawScenario = String(stored.scenario || legacyScenario || 'imgtxt') as ScenarioType
  const configuredScenario = SCENARIOS.has(rawScenario) ? rawScenario : 'imgtxt'
  const scenario = model?.supports.includes('imgtxt')
    ? 'imgtxt'
    : model?.supports.includes(configuredScenario)
      ? configuredScenario
      : model?.supports[0] || 'text'
  const ratio =
    model?.ratios.includes(String(stored.ratio || ''))
      ? String(stored.ratio)
      : model?.ratios[0] || '16:9'
  const legacyDuration = finiteNumber(legacyTagValue(tags, 'trend-duration'))
  const configuredDuration = finiteNumber(stored.duration) || legacyDuration
  const duration =
    configuredDuration && model?.durations.includes(configuredDuration)
      ? configuredDuration
      : model?.durations[0] || 5
  const imageGenerationType =
    model?.veo_generation_types?.find((value) => value.toUpperCase().includes('IMAGE')) ||
    model?.veo_generation_types?.[0] ||
    'IMAGE_2_VIDEO'

  return {
    kind: 'video',
    user_input: 'photo',
    model: model?.id || String(stored.model || trend.model || 'v3_pro'),
    scenario,
    ratio,
    duration,
    grok_mode: String(stored.grok_mode || model?.grok_modes?.[0] || 'normal'),
    grok_resolution: String(stored.grok_resolution || model?.grok_resolutions?.[0] || '480p'),
    veo_generation_type: String(stored.veo_generation_type || imageGenerationType),
    veo_translation: stored.veo_translation ?? true,
    veo_resolution: String(stored.veo_resolution || model?.veo_resolutions?.[0] || '720p'),
    veo_seed: finiteNumber(stored.veo_seed),
    veo_watermark: String(stored.veo_watermark || ''),
    kling_negative_prompt: String(stored.kling_negative_prompt || ''),
    kling_cfg_scale: finiteNumber(stored.kling_cfg_scale) ?? 0.5,
    omni_resolution: String(stored.omni_resolution || model?.omni_resolutions?.[0] || '720p'),
    omni_seed: finiteNumber(stored.omni_seed),
    omni_audio_ids: Array.isArray(stored.omni_audio_ids) ? stored.omni_audio_ids : [],
    omni_character_ids: Array.isArray(stored.omni_character_ids) ? stored.omni_character_ids : [],
    omni_base_voice: String(stored.omni_base_voice || model?.omni_base_voices?.[0] || 'achernar'),
    omni_voice_name: String(stored.omni_voice_name || ''),
    omni_voice_description: String(stored.omni_voice_description || ''),
    omni_example_dialogue: String(stored.omni_example_dialogue || ''),
    omni_character_name: String(stored.omni_character_name || ''),
    omni_character_audio_ids: Array.isArray(stored.omni_character_audio_ids)
      ? stored.omni_character_audio_ids
      : [],
  }
}
