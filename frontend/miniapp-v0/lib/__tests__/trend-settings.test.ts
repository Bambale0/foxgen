import { isVideoTrendItem, resolveTrendSettings } from '../trend-settings'
import type { PromptItem, VideoModel } from '../types'

describe('trend-settings', () => {
  const videoModels: VideoModel[] = [
    {
      id: 'seedance_2',
      label: 'Seedance 2.0',
      description: 'Video model',
      durations: [5, 10],
      ratios: ['16:9', '9:16'],
      supports: ['imgtxt', 'text'],
      costs: { '5': 10, '10': 20 },
      max_image_references: 4,
      max_video_references: 0,
    },
  ]

  const trend: PromptItem = {
    id: 42,
    title: 'Video trend',
    description: 'Seedance preset',
    prompt_text: 'Create a cinematic clip',
    category: 'video',
    tags: ['trend', 'trend-video'],
    uses_count: 0,
    likes: 0,
    preview_url: 'https://example.test/video.mp4',
    model: 'seedance_2',
    generation_settings: {
      kind: 'video',
      user_input: 'photo',
      model: 'seedance_2',
      scenario: 'imgtxt',
      ratio: '9:16',
      duration: 10,
    },
    author_id: 1,
    status: 'approved',
  }

  it('detects video trends even when they are also tagged as generic trends', () => {
    expect(isVideoTrendItem(trend, videoModels)).toBe(true)
  })

  it('restores ratio and duration from generation_settings for video trends', () => {
    const settings = resolveTrendSettings(trend, [], videoModels)

    expect(settings.kind).toBe('video')
    expect(settings.model).toBe('seedance_2')
    expect(settings.scenario).toBe('imgtxt')
    expect(settings.ratio).toBe('9:16')
    expect(settings.duration).toBe(10)
  })
})
