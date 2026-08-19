'use client'

import { getApiBasePath, getInitData, getStartParamFallback, uploadFile } from './api'
import type { UploadedFile } from './types'

export type Seedance25Scenario = 'text' | 'first_frame' | 'first_last' | 'multimodal'
export type Seedance25Resolution = '480p' | '720p'
export type Seedance25OutputFormat = 'mp4' | 'mov'

const DIRECT_VIDEO_UPLOAD_BYTES = 45 * 1024 * 1024
const VIDEO_CHUNK_BYTES = 7 * 1024 * 1024
const MAX_VIDEO_BYTES = 200 * 1024 * 1024

export interface Seedance25GeneratePayload {
  scenario: Seedance25Scenario
  prompt: string
  ratio: 'adaptive' | '16:9' | '9:16' | '1:1' | '4:3' | '3:4' | '21:9'
  duration: number
  resolution: Seedance25Resolution
  outputFormat: Seedance25OutputFormat
  generateAudio: boolean
  returnLastFrame: boolean
  webSearch: boolean
  nsfwChecker: boolean
  firstFrameUrl?: string | null
  lastFrameUrl?: string | null
  referenceImages?: string[]
  referenceVideos?: string[]
  referenceAudios?: string[]
}

export interface Seedance25GenerateResponse {
  ok: true
  status: 'queued'
  task_id: string
  credits: number
  cost: number
  model_label: string
  admin_free: boolean
  resolution: Seedance25Resolution
  duration: number
  aspect_ratio: string
  scenario: Seedance25Scenario
}

interface Seedance25UploadAssemblyResponse {
  ok: true
  url: string
  kind: 'video'
  filename: string
  reference?: {
    id?: string | number | null
    created_at?: string | null
    source?: string | null
  } | null
}

async function parseJsonResponse<T>(response: Response, fallback: string): Promise<T> {
  const text = await response.text()
  let data: any = null
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error(fallback)
  }
  if (!response.ok || data?.ok === false) {
    throw new Error(data?.error || fallback)
  }
  return data as T
}

export async function uploadSeedance25Video(file: File): Promise<UploadedFile> {
  if (file.size <= 0) throw new Error('Видео пустое.')
  if (file.size > MAX_VIDEO_BYTES) throw new Error('Seedance 2.5 принимает видео до 200 MB.')

  if (file.size <= DIRECT_VIDEO_UPLOAD_BYTES) {
    return uploadFile('seedance25_video_reference' as any, file)
  }

  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')

  const contentType = file.type || (file.name.toLowerCase().endsWith('.mov') ? 'video/quicktime' : 'video/mp4')
  const chunkUrls: string[] = []
  const chunkCount = Math.ceil(file.size / VIDEO_CHUNK_BYTES)

  try {
    for (let index = 0; index < chunkCount; index += 1) {
      const start = index * VIDEO_CHUNK_BYTES
      const end = Math.min(file.size, start + VIDEO_CHUNK_BYTES)
      const blob = file.slice(start, end, contentType)
      const chunkFile = new File(
        [blob],
        `${file.name}.part-${String(index + 1).padStart(3, '0')}-of-${String(chunkCount).padStart(3, '0')}`,
        { type: contentType, lastModified: file.lastModified },
      )
      const uploaded = await uploadFile('seedance25_video_chunk' as any, chunkFile)
      chunkUrls.push(uploaded.url)
    }

    const response = await fetch(`${getApiBasePath()}/generate-video`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
      credentials: 'same-origin',
      body: JSON.stringify({
        init_data: initData,
        start_param_fallback: getStartParamFallback(),
        v_model: 'seedance_2_5',
        seedance25_upload_only: true,
        seedance25_chunk_urls: chunkUrls,
        seedance25_original_filename: file.name,
        seedance25_original_size: file.size,
      }),
    })
    const data = await parseJsonResponse<Seedance25UploadAssemblyResponse>(
      response,
      'Не удалось собрать большое видео Seedance 2.5.',
    )
    return {
      id: data.reference?.id ? String(data.reference.id) : `seedance25_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      name: data.filename,
      url: data.url,
      type: 'video',
      size: file.size,
      saved_reference_id: data.reference?.id ? String(data.reference.id) : null,
      created_at: data.reference?.created_at || null,
      source: data.reference?.source || 'miniapp_seedance25',
    }
  } catch (error) {
    // The backend removes all uploaded chunks once it receives the assembly
    // manifest. If a network failure happens before that point, generic upload
    // cleanup will remove temporary chunk files later.
    throw error
  }
}

export async function generateSeedance25(
  payload: Seedance25GeneratePayload,
): Promise<Seedance25GenerateResponse> {
  const initData = getInitData()
  if (!initData) throw new Error('Откройте Mini App из Telegram и попробуйте снова.')

  const response = await fetch(`${getApiBasePath()}/generate-video`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
    credentials: 'same-origin',
    body: JSON.stringify({
      init_data: initData,
      start_param_fallback: getStartParamFallback(),
      v_model: 'seedance_2_5',
      v_type:
        payload.scenario === 'text'
          ? 'text'
          : payload.scenario === 'multimodal'
            ? 'video'
            : 'imgtxt',
      seedance25_scenario: payload.scenario,
      prompt: payload.prompt,
      v_ratio: payload.ratio,
      v_duration: payload.duration,
      seedance25_resolution: payload.resolution,
      seedance25_output_format: payload.outputFormat,
      seedance25_generate_audio: payload.generateAudio,
      seedance25_return_last_frame: payload.returnLastFrame,
      seedance25_web_search: payload.webSearch,
      seedance25_nsfw_checker: payload.nsfwChecker,
      seedance25_first_frame_url: payload.firstFrameUrl || null,
      seedance25_last_frame_url: payload.lastFrameUrl || null,
      reference_images: payload.referenceImages || [],
      v_reference_videos: payload.referenceVideos || [],
      seedance25_reference_audio_urls: payload.referenceAudios || [],
    }),
  })

  return parseJsonResponse<Seedance25GenerateResponse>(
    response,
    'Seedance 2.5 API вернул некорректный ответ.',
  )
}
