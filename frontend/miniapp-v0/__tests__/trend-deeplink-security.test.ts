import type { PromptItem } from '../lib/types'
import { isVideoTrendItem } from '../lib/trend-settings'

const publicVideoTrend = {
  id: 1126,
  title: 'Закрытый тренд',
  description: 'Публичное описание',
  prompt_text: '',
  category: 'video',
  tags: ['trend', 'trend-video'],
  uses_count: 0,
  likes: 0,
  model: null,
  generation_settings: { kind: 'video', ratio: '9:16' },
  author_id: 1,
  status: 'approved',
} as unknown as PromptItem

describe('shared trend deeplink privacy', () => {
  it('does not classify a redacted shared trend as a generic video repeat', () => {
    expect(isVideoTrendItem(publicVideoTrend, [])).toBe(false)
  })

  it('keeps full admin trend settings classifiable as video', () => {
    const adminTrend = {
      ...publicVideoTrend,
      prompt_text: 'private template prompt',
      model: 'seedance_2',
      generation_settings: {
        kind: 'video',
        user_input: 'photo',
        model: 'seedance_2',
        ratio: '9:16',
      },
    } as PromptItem

    expect(isVideoTrendItem(adminTrend, [])).toBe(true)
  })
})
