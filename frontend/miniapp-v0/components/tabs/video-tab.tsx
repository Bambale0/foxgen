'use client'

import { useEffect, useMemo, useState } from 'react'
import { Sparkles, Video as VideoIcon } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { VideoGeneratorForm } from '../forms/video-generator-form'
import { Seedance25PublicForm } from '../forms/seedance25-public-form'
import { ResultCard } from '../result-card'
import type { Task, ScenarioType, UploadedFile } from '@/lib/types'
import type { Seedance25GenerateResponse } from '@/lib/seedance25-api'
import { generateVideo, uploadFile } from '@/lib/api'

export function VideoTab() {
  const {
    state,
    addTask,
    setCredits,
    setTaskDetail,
    selectTask,
    addSavedReference,
    videoPromptPreset,
    setVideoPromptPreset,
    refreshTasks,
  } = useApp()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [lastРезультат, setLastРезультат] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [videoMode, setVideoMode] = useState<'regular' | 'seedance25'>('seedance25')
  const [seedanceQueued, setSeedanceQueued] = useState<Seedance25GenerateResponse | null>(null)

  const seedance25Model = useMemo(
    () => state.videoModels.find((item) => item.id === 'seedance_2_5'),
    [state.videoModels],
  )
  const isSeedanceRepeat = Boolean(
    videoPromptPreset?.model === 'seedance_2_5' && videoPromptPreset.sourceFeedGenId,
  )
  const regularVideoModels = useMemo(
    () => state.videoModels.filter((item) => item.id !== 'seedance_2_5'),
    [state.videoModels],
  )
  const formVideoModels = isSeedanceRepeat ? state.videoModels : regularVideoModels
  const canUseSeedance25 = Boolean(seedance25Model)
  const effectiveMode = canUseSeedance25 ? videoMode : 'regular'

  useEffect(() => {
    if (!canUseSeedance25 || !videoPromptPreset) return
    // A remix preset must keep sourceFeedGenId all the way to generateVideo().
    // The dedicated Seedance form is for fresh generations and intentionally has
    // no feed-repeat contract, so use the generic form only for this repeat case.
    setVideoMode(
      videoPromptPreset.model === 'seedance_2_5' && videoPromptPreset.sourceFeedGenId
        ? 'regular'
        : videoPromptPreset.model === 'seedance_2_5'
          ? 'seedance25'
          : 'regular',
    )
  }, [canUseSeedance25, videoPromptPreset])

  const handleSubmit = async (data: {
    model: string
    scenario: ScenarioType
    ratio: string
    duration: number
    sourceFeedGenId?: number | null
    grokMode: string
    grokResolution: string
    veoGenerationType: string
    veoTranslation: boolean
    veoResolution: string
    veoSeed: number | null
    veoWatermark: string
    klingNegativePrompt: string
    klingCfgScale: number
    omniResolution: string
    omniSeed: number | null
    omniAudioIds: string[]
    omniCharacterIds: string[]
    omniBaseVoice: string
    omniVoiceName: string
    omniVoiceDescription: string
    omniExampleDialogue: string
    omniCharacterName: string
    omniCharacterAudioIds: string[]
    prompt: string
    startImage: string | null
    references: string[]
    videoReferences: string[]
    audioReference: string | null
  }) => {
    if (state.mode !== 'live') {
      const modeError = new Error('Откройте Mini App через Telegram, чтобы запустить генерацию.')
      setError(modeError.message)
      throw modeError
    }
    setIsSubmitting(true)
    setError(null)
    try {
      const result = await generateVideo(data)
      addTask(result.task)
      setCredits(result.credits)
      setLastРезультат(result.task)
      if (result.detail) {
        setTaskDetail(result.detail)
      }
      selectTask(result.task)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось запустить видео')
      throw e
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleUploadImageReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      throw new Error('Откройте Mini App через Telegram, чтобы загрузить референс.')
    }
    const uploaded = await uploadFile('image_reference', file)
    addSavedReference(uploaded)
    return uploaded
  }

  const handleUploadVideoReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      throw new Error('Откройте Mini App через Telegram, чтобы загрузить видео.')
    }
    const uploaded = await uploadFile('video_reference', file)
    addSavedReference(uploaded)
    return uploaded
  }

  const handleUploadAudioReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      throw new Error('Откройте Mini App через Telegram, чтобы загрузить аудио.')
    }
    const uploaded = await uploadFile('audio_reference', file)
    addSavedReference(uploaded)
    return uploaded
  }

  const handleSeedanceQueued = async (result: Seedance25GenerateResponse) => {
    setSeedanceQueued(result)
    setCredits(result.credits)
    try {
      await refreshTasks()
    } catch {
      // Dedicated Seedance webhook/polling still completes the task in Telegram.
    }
  }

  return (
    <div className="min-w-0 space-y-4 overflow-x-hidden px-3 pb-3 sm:px-4 lg:px-6">
      <div className="flex items-start justify-between gap-4 px-0.5 pt-1">
        <div>
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-gold/20 bg-gold/[0.07] px-2.5 py-1 text-[9px] font-black uppercase tracking-[0.14em] text-gold">
            <VideoIcon className="h-3 w-3" />
            Видео
          </div>
          <h2 className="text-2xl font-black tracking-[-0.035em] text-foreground">Создайте видео</h2>
          <p className="mt-1 max-w-xl text-xs leading-relaxed text-muted-foreground">
            Выберите подходящую модель, сценарий и длительность. Для image-to-video добавьте стартовый кадр.
          </p>
        </div>
        <div className="shrink-0 pt-1 text-right">
          <div className="text-[9px] font-bold uppercase tracking-[0.13em] text-muted-foreground">Шаг 1 из 3</div>
          <div className="mt-2 flex justify-end gap-1">
            <span className="h-1 w-5 rounded-full bg-gold" />
            <span className="h-1 w-3 rounded-full bg-white/10" />
            <span className="h-1 w-3 rounded-full bg-white/10" />
          </div>
        </div>
      </div>

      {canUseSeedance25 ? (
        <div className="mx-auto mb-4 max-w-xl space-y-2">
          <div className="px-1 text-[9px] font-black uppercase tracking-[0.16em] text-muted-foreground">
            Быстрый выбор модели
          </div>
          <div className="fox-surface grid grid-cols-2 gap-2 rounded-[18px] p-1.5">
            <button
              type="button"
              onClick={() => setVideoMode('seedance25')}
              className={`rounded-[14px] px-3 py-3 text-xs font-semibold transition-all ${
                effectiveMode === 'seedance25' && !isSeedanceRepeat
                  ? 'border border-gold/45 bg-gold/[0.12] text-gold shadow-[0_0_18px_rgba(255,106,0,0.10)]'
                  : 'border border-transparent text-muted-foreground hover:bg-gold/[0.05] hover:text-foreground'
              }`}
            >
              <span className="block text-[9px] font-black uppercase tracking-[0.16em] text-gold">NEW</span>
              <span className="mt-0.5 block text-sm text-foreground">Seedance 2.5</span>
            </button>
            <button
              type="button"
              onClick={() => setVideoMode('regular')}
              className={`rounded-[14px] px-3 py-3 text-xs font-medium transition-all ${
                effectiveMode === 'regular' || isSeedanceRepeat
                  ? 'border border-white/[0.08] bg-secondary text-foreground'
                  : 'border border-transparent text-muted-foreground hover:bg-secondary/60 hover:text-foreground'
              }`}
            >
              <span className="block text-[9px] uppercase tracking-[0.14em] opacity-70">Каталог</span>
              <span className="mt-0.5 block text-sm">Другие модели</span>
            </button>
          </div>
        </div>
      ) : null}

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)] xl:gap-6">
        {effectiveMode === 'seedance25' && seedance25Model && !isSeedanceRepeat ? (
          <Seedance25PublicForm
            model={seedance25Model}
            credits={state.user.credits}
            isAdmin={state.user.isAdmin}
            onQueued={handleSeedanceQueued}
            onSavedReference={addSavedReference}
          />
        ) : (
          <VideoGeneratorForm
            models={formVideoModels}
            onSubmit={handleSubmit}
            onUploadImageReference={handleUploadImageReference}
            onUploadVideoReference={handleUploadVideoReference}
            onUploadAudioReference={handleUploadAudioReference}
            savedImageReferences={state.savedReferences.filter((item) => item.type === 'image')}
            savedVideoReferences={state.savedReferences.filter((item) => item.type === 'video')}
            savedAudioReferences={state.savedReferences.filter((item) => item.type === 'audio')}
            promptPreset={videoPromptPreset}
            onPromptPresetConsumed={() => setVideoPromptPreset(null)}
            isSubmitting={isSubmitting}
            credits={state.user.credits}
          />
        )}

        <div className="space-y-4">
          {error && (effectiveMode === 'regular' || isSeedanceRepeat) ? (
            <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          ) : null}

          {effectiveMode === 'seedance25' && !isSeedanceRepeat ? (
            <div className="fox-surface-accent rounded-[22px] p-5">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-gold/20 bg-gold/[0.08]">
                <Sparkles className="h-5 w-5 text-gold" />
              </div>
              <p className="mb-2 text-[9px] font-black uppercase tracking-[0.16em] text-gold">Очередь Seedance</p>
              <h3 className="text-lg font-bold text-foreground">Seedance 2.5</h3>
              {seedanceQueued ? (
                <div className="mt-2 space-y-2 text-sm">
                  <p>Задача отправлена в Kie.ai.</p>
                  <p className="break-all font-mono text-[10px] text-muted-foreground">{seedanceQueued.task_id}</p>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {seedanceQueued.admin_free
                      ? 'Для администратора списание отключено.'
                      : `Списано ${seedanceQueued.cost} кредитов.`}{' '}
                    Результат придёт в Telegram. Если callback задержится, включён polling fallback.
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  Здесь появится ID последней задачи. Итоговое видео бот пришлёт автоматически.
                </p>
              )}
            </div>
          ) : lastРезультат ? (
            <ResultCard
              task={lastРезультат}
              onClose={() => setLastРезультат(null)}
            />
          ) : (
            <div className="fox-surface-accent rounded-[22px] p-5">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-gold/20 bg-gold/[0.08]">
                <VideoIcon className="h-5 w-5 text-gold" />
              </div>
              <p className="mb-2 text-[9px] font-black uppercase tracking-[0.16em] text-gold">Результат</p>
              <h3 className="text-lg font-bold text-foreground">Видео-панель</h3>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                После запуска здесь появятся очередь, task id и превью ролика. Все параметры сохраняются в истории.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
