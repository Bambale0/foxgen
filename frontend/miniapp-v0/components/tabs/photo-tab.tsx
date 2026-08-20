'use client'

import { useState } from 'react'
import { Image as ImageIcon, Sparkles } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { ImageGeneratorForm } from '../forms/image-generator-form'
import { ResultCard } from '../result-card'
import type { Task, UploadedFile } from '@/lib/types'
import { generateImage, remixFeedItem, uploadFile } from '@/lib/api'

export function PhotoTab() {
  const { state, addTask, setCredits, setTaskDetail, selectTask, addSavedReference, promptPreset, setPromptPreset } = useApp()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [lastРезультат, setLastРезультат] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (data: {
    model: string
    ratio: string
    quality: string
    count: number
    nsfwChecker: boolean
    nsfwEnabled: boolean
    promptId?: number | null
    sourceFeedGenId?: number | null
    prompt: string
    references: string[]
  }) => {
    if (state.mode !== 'live') {
      setError('Откройте Mini App через Telegram, чтобы запустить генерацию.')
      return
    }
    setIsSubmitting(true)
    setError(null)
    try {
      let lastTask: Task | null = null
      let latestCredits = state.user.credits

      for (let index = 0; index < data.count; index += 1) {
        const result = data.sourceFeedGenId
          ? await remixFeedItem({
              genId: data.sourceFeedGenId,
              model: data.model,
              ratio: data.ratio,
              quality: data.quality,
              prompt: data.prompt,
              references: data.references,
            })
          : await generateImage({
              model: data.model,
              ratio: data.ratio,
              quality: data.quality,
              nsfwChecker: data.nsfwChecker,
              nsfwEnabled: data.nsfwEnabled,
              promptId: data.promptId,
              sourceFeedGenId: data.sourceFeedGenId,
              prompt: data.prompt,
              references: data.references,
            })
        addTask(result.task)
        latestCredits = result.credits
        lastTask = result.task
        if (result.detail) {
          setTaskDetail(result.detail)
        }
      }

      setCredits(latestCredits)
      if (lastTask) {
        setLastРезультат(lastTask)
        selectTask(lastTask)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось запустить фото')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleUploadReference = async (file: File): Promise<UploadedFile> => {
    if (state.mode !== 'live') {
      throw new Error('Откройте Mini App через Telegram, чтобы загрузить референс.')
    }
    const uploaded = await uploadFile('image_reference', file)
    addSavedReference(uploaded)
    return uploaded
  }

  return (
    <div className="space-y-4 px-3 pb-3 sm:px-4 lg:px-6">
      <div className="flex items-start justify-between gap-4 px-0.5 pt-1">
        <div>
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-gold/20 bg-gold/[0.07] px-2.5 py-1 text-[9px] font-black uppercase tracking-[0.14em] text-gold">
            <ImageIcon className="h-3 w-3" />
            Фото
          </div>
          <h2 className="text-2xl font-black tracking-[-0.035em] text-foreground">Создайте изображение</h2>
          <p className="mt-1 max-w-xl text-xs leading-relaxed text-muted-foreground">
            Выберите модель, задайте формат и опишите идею. Референсы можно добавить при необходимости.
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

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)] xl:gap-6">
        <ImageGeneratorForm
          models={state.imageModels}
          onSubmit={handleSubmit}
          onUploadReference={handleUploadReference}
          savedReferences={state.savedReferences}
          promptPreset={promptPreset}
          onPromptPresetConsumed={() => setPromptPreset(null)}
          isSubmitting={isSubmitting}
          credits={state.user.credits}
        />

        <div className="space-y-4">
          {error && (
            <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          {lastРезультат ? (
            <ResultCard
              task={lastРезультат}
              onClose={() => setLastРезультат(null)}
            />
          ) : (
            <div className="fox-surface-accent rounded-[22px] p-5">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-gold/20 bg-gold/[0.08]">
                <Sparkles className="h-5 w-5 text-gold" />
              </div>
              <p className="mb-2 text-[9px] font-black uppercase tracking-[0.16em] text-gold">Результат</p>
              <h3 className="text-lg font-bold text-foreground">Готово к запуску</h3>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                После запуска здесь появится статус задачи и готовое изображение. Все параметры сохраняются в истории.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
