'use client'

import { getApiBasePath, getInitData, getStartParamFallback } from './api'
import type { Task, TaskDetail } from './types'

interface RunTrendResponse {
  ok: true
  status: 'queued' | 'done'
  task_id: string
  task_type: 'image' | 'video' | 'audio' | 'character'
  saved_url?: string | null
  credits: number
  cost: number
  model: string
  model_label: string
  aspect_ratio: string
  duration?: number | null
  prompt_hidden: true
  prompt_actions_allowed: false
  trend_id: number
}

export interface RunTrendResult {
  task: Task
  detail?: TaskDetail | null
  credits: number
}

async function parseResponse(response: Response): Promise<RunTrendResponse> {
  const text = await response.text()
  let payload: RunTrendResponse | { ok?: false; error?: string }
  try {
    payload = JSON.parse(text) as RunTrendResponse | { ok?: false; error?: string }
  } catch {
    throw new Error('Сервер вернул некорректный ответ. Обновите Mini App.')
  }

  if (!response.ok || payload.ok !== true) {
    throw new Error(
      'error' in payload && payload.error
        ? payload.error
        : 'Не удалось запустить тренд',
    )
  }
  return payload
}

export async function runTrend(
  trendId: number,
  referenceUrls: string[],
): Promise<RunTrendResult> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте Mini App из Telegram и попробуйте снова.')
  }

  const payload: Record<string, unknown> = {
    init_data: initData,
    trend_id: trendId,
    reference_urls: referenceUrls,
  }
  const startParam = getStartParamFallback()
  if (startParam) payload.start_param_fallback = startParam

  const response = await fetch(`${getApiBasePath()}/trends/run`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
    credentials: 'same-origin',
  })
  const data = await parseResponse(response)

  const task: Task = {
    task_id: data.task_id,
    type: data.task_type,
    model: data.model,
    model_label: data.model_label,
    aspect_ratio: data.aspect_ratio,
    status: data.status === 'done' ? 'completed' : 'pending',
    result_url: data.saved_url || null,
    created_at: new Date().toISOString(),
    prompt_preview: '',
    cost: data.cost,
    duration: data.duration ?? null,
    prompt_hidden: true,
    prompt_actions_allowed: false,
  }

  return {
    task,
    detail:
      data.status === 'done'
        ? {
            ...task,
            prompt: '',
            request_data: {
              reference_images: referenceUrls,
              trend_id: data.trend_id,
            },
          }
        : null,
    credits: data.credits,
  }
}
