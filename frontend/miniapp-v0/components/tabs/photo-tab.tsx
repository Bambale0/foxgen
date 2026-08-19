'use client'

import { useState } from 'react'
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
    <div className="px-4 space-y-6">
      <div className="text-center mb-6">
        <h2 className="font-serif text-xl font-semibold text-foreground mb-1">
          Генерация фото
        </h2>
        <p className="text-sm text-muted-foreground">
          Создавайте уникальные изображения с AI
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
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
            <div className="p-4 rounded-xl bg-destructive/10 border border-destructive/30">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          {lastРезультат ? (
            <ResultCard 
              task={lastРезультат}
              onClose={() => setLastРезультат(null)}
            />
          ) : (
            <div className="glass rounded-2xl border border-border/50 p-5">
              <p className="text-xs uppercase tracking-[0.18em] text-gold/80 mb-2">Результат</p>
              <h3 className="font-serif text-lg text-foreground mb-2">Готово к запуску</h3>
              <p className="text-sm text-muted-foreground">
                Выберите модель, добавьте prompt и при необходимости загрузите референсы. Очередь, ошибки и готовый результат появятся здесь.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
