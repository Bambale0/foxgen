'use client'

import { miniAppApi } from './api'
import type { PublicationComment } from './types'

export const socialApi = {
  comments(publicationId: string, surface: 'feed' | 'profile' = 'feed', limit = 50, offset = 0) {
    return miniAppApi.request<{ items: PublicationComment[] }>(
      `/publications/${encodeURIComponent(publicationId)}/comments?surface=${surface}&limit=${limit}&offset=${offset}`,
    )
  },

  addComment(publicationId: string, body: string, surface: 'feed' | 'profile' = 'feed') {
    return miniAppApi.request<PublicationComment>(
      `/publications/${encodeURIComponent(publicationId)}/comments`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ surface, body }),
      },
    )
  },
}
