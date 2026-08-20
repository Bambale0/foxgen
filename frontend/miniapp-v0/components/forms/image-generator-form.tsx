'use client'

import { useState, useMemo, useEffect, useCallback } from 'react'
import type { ImageModel, PromptPreset, UploadedFile } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ModelSelect } from './model-select'
import { RatioSelect } from './ratio-select'
import { QualitySelect } from './quality-select'
import { UploadArea } from './upload-area'
import { Banana, Sparkles, Loader2, AlertCircle, Palette, Shirt, Mountain, Sparkle, ScanFace } from 'lucide-react'

interface ImageGeneratorFormProps {
  models: ImageModel[]
  onSubmit: (data: {
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
  }) => Promise<void>
  onUploadReference?: (file: File) => Promise<UploadedFile>
  savedReferences?: UploadedFile[]
  promptPreset?: PromptPreset | null
  onPromptPresetConsumed?: () => void
  isSubmitting: boolean
  credits: number
}

export function ImageGeneratorForm({ 
  models, 
  onSubmit, 
  onUploadReference,
  savedReferences = [],
  promptPreset,
  onPromptPresetConsumed,
  isSubmitting,
  credits,
}: ImageGeneratorFormProps) {
  const [selectedModel, setSelectedModel] = useState(models[0]?.id || '')
  const [selectedRatio, setSelectedRatio] = useState('1:1')
  const [selectedQuality, setSelectedQuality] = useState('basic')
  const [selectedCount, setSelectedCount] = useState(1)
  const [nsfwChecker, setNsfwChecker] = useState(false)
  const [nsfwEnabled, setNsfwEnabled] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [selectedPromptId, setSelectedPromptId] = useState<number | null>(null)
  const [sourceFeedGenId, setSourceFeedGenId] = useState<number | null>(null)
  const [remixTitle, setRemixTitle] = useState('')
  const [references, setReferences] = useState<UploadedFile[]>([])
  const [activeChanges, setActiveChanges] = useState<Set<string>>(new Set())

  const model = useMemo(() => models.find(m => m.id === selectedModel), [models, selectedModel])

  const unitCost = Number(
    (selectedQuality ? model?.quality_costs?.[selectedQuality] : undefined) ?? (model?.cost || 0)
  )
  const cost = unitCost * selectedCount
  const canAfford = credits >= cost
  const isFeedRemix = sourceFeedGenId !== null
  const needsReference = Boolean(model?.requires_reference) && references.length === 0
  const referencesUploading = references.some((reference) => reference.uploading)
  const hasPrompt = prompt.trim().length > 0 || isFeedRemix
  const isValid = hasPrompt && canAfford && !needsReference && !referencesUploading

  const CHANGE_CHIPS = [
    {
      id: 'hair',
      icon: Palette,
      label: 'Причёску',
      hint: 'измени причёску, длину или цвет...',
      insert: 'Измени только причёску: ',
    },
    {
      id: 'clothes',
      icon: Shirt,
      label: 'Одежду',
      hint: 'смени одежду на...',
      insert: 'Замени одежду на ',
    },
    {
      id: 'background',
      icon: Mountain,
      label: 'Фон',
      hint: 'поменяй фон на...',
      insert: 'Замени фон на ',
    },
    {
      id: 'style',
      icon: Sparkle,
      label: 'Стиль',
      hint: 'измени стиль на...',
      insert: 'Измени стиль на ',
    },
    {
      id: 'details',
      icon: ScanFace,
      label: 'Детали',
      hint: 'добавь/убери детали...',
      insert: 'Добавь детали: ',
    },
  ] as const

  useEffect(() => {
    if (!promptPreset) return
    setPrompt(promptPreset.prompt)
    setSelectedPromptId(promptPreset.promptId || null)
    setSourceFeedGenId(promptPreset.sourceFeedGenId || null)
    setRemixTitle(promptPreset.sourceFeedGenId ? promptPreset.title : '')
    setActiveChanges(new Set())
    if (promptPreset.model && models.some((item) => item.id === promptPreset.model)) {
      setSelectedModel(promptPreset.model)
    }
    if (promptPreset.ratio) {
      setSelectedRatio(promptPreset.ratio)
    }
    setReferences(promptPreset.initialReferences || [])
    onPromptPresetConsumed?.()
  }, [models, onPromptPresetConsumed, promptPreset])

  useEffect(() => {
    if (!model) return
    if (!model.ratios.includes(selectedRatio)) {
      setSelectedRatio(model.ratios[0] || '1:1')
    }
    const bananaQualities = ['1K', '2K', '4K']
    if (
      (model.qualities?.length && !model.qualities.includes(selectedQuality)) ||
      ((model.id === 'banana_pro' || model.id === 'banana_2') &&
        !bananaQualities.includes(selectedQuality))
    ) {
      const q = model.id === 'banana_pro' || model.id === 'banana_2' ? '2K' : model.qualities![0]
      setSelectedQuality(q)
    }
    if (!(model.supports_nsfw_checker || model.id === 'seedream_edit' || model.id === 'flux_pro')) {
      setNsfwChecker(false)
    }
    if (!(model.supports_nsfw_mode || model.id === 'grok_imagine_i2i')) {
      setNsfwEnabled(false)
    }
  }, [model, selectedQuality, selectedRatio])

  const toggleChange = (chipId: string, insert: string) => {
    const isActive = activeChanges.has(chipId)
    setActiveChanges((prev) => {
      const next = new Set(prev)
      if (isActive) next.delete(chipId)
      else next.add(chipId)
      return next
    })
    setPrompt((current) => {
      if (isActive) return current.replace(insert, '').trimStart()
      if (current.includes(insert)) return current
      return current.trim() ? `${insert}${current}` : insert
    })
  }

  const handleReferencesChange = (nextReferences: UploadedFile[]) => {
    setReferences(nextReferences)
  }

  const handleSubmit = useCallback(async () => {
    if (!isValid) return
    await onSubmit({
      model: selectedModel,
      ratio: selectedRatio,
      quality: selectedQuality,
      count: selectedCount,
      nsfwChecker,
      nsfwEnabled,
      promptId: selectedPromptId,
      sourceFeedGenId,
      prompt,
      references: references.map(r => r.url),
    })
    setPrompt('')
    setSelectedPromptId(null)
    setSourceFeedGenId(null)
    setRemixTitle('')
    setReferences([])
    setActiveChanges(new Set())
  }, [
    isValid,
    onSubmit,
    selectedModel,
    selectedRatio,
    selectedQuality,
    selectedCount,
    nsfwChecker,
    nsfwEnabled,
    selectedPromptId,
    sourceFeedGenId,
    prompt,
    references,
  ])

  return (
    <div className="space-y-4">
      <div className="glass rounded-2xl border border-border/50 p-4 space-y-4">
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Модель</label>
          <ModelSelect
            models={models.map(m => ({
              id: m.id,
              label: m.label,
              description: m.description,
              cost: m.cost,
            }))}
            value={selectedModel}
            onChange={setSelectedModel}
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Формат</label>
            <RatioSelect
              ratios={model?.ratios || ['1:1']}
              value={selectedRatio}
              onChange={setSelectedRatio}
            />
          </div>
          {(model?.id === 'banana_pro' || model?.id === 'banana_2') ? (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Качество</label>
              <QualitySelect
                qualities={['1K', '2K', '4K']}
                value={selectedQuality}
                onChange={setSelectedQuality}
              />
            </div>
          ) : model?.qualities?.length ? (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Качество</label>
              <QualitySelect
                qualities={model.qualities!}
                value={selectedQuality}
                onChange={setSelectedQuality}
              />
            </div>
          ) : (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Режим</label>
              <div className="rounded-xl border border-border/50 bg-secondary/40 px-4 py-3 text-sm text-muted-foreground">
                Стандартный режим модели
              </div>
            </div>
          )}
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">Количество</label>
            <div className="flex flex-wrap gap-2">
              {[1, 2, 4, 6].map((count) => (
                <button
                  key={count}
                  type="button"
                  onClick={() => setSelectedCount(count)}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-xs font-medium transition-all duration-200",
                    selectedCount === count
                      ? "border-gold/50 bg-gold/15 text-gold"
                      : "border-border/50 bg-secondary/50 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  )}
                >
                  {count}x
                </button>
              ))}
            </div>
          </div>

          {(model?.supports_nsfw_checker || model?.id === 'seedream_edit' || model?.id === 'flux_pro') && (
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">Фильтр контента</label>
              <button
                type="button"
                onClick={() => setNsfwChecker((prev) => !prev)}
                className={cn(
                  "w-full rounded-xl border px-4 py-3 text-left text-sm transition-all duration-200",
                  nsfwChecker
                    ? "border-cyan/40 bg-cyan/10 text-cyan"
                    : "border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                )}
              >
                {nsfwChecker ? 'NSFW checker включён' : 'NSFW checker выключен'}
              </button>
            </div>
          )}
        </div>

        {(model?.supports_nsfw_mode || model?.id === 'grok_imagine_i2i') && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-foreground">NSFW режим</label>
            <button
              type="button"
              onClick={() => setNsfwEnabled((prev) => !prev)}
              className={cn(
                "w-full rounded-xl border px-4 py-3 text-left text-sm transition-all duration-200",
                nsfwEnabled
                  ? "border-cyan/40 bg-cyan/10 text-cyan"
                  : "border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
              )}
            >
              {nsfwEnabled ? 'NSFW режим включён' : 'NSFW режим выключен'}
            </button>
          </div>
        )}

        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-foreground">{model?.label}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {model?.description}
              </p>
            </div>
            <div className="rounded-full border border-cyan/20 bg-cyan/10 px-3 py-1 text-xs text-cyan">
              До {model?.max_references || 0} референсов
            </div>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-xl bg-background/40 px-3 py-2 text-muted-foreground">
              Режим: <span className="text-foreground">{model?.requires_reference ? 'Edit / reference' : 'Text / image mix'}</span>
            </div>
            <div className="rounded-xl bg-background/40 px-3 py-2 text-muted-foreground">
              Формат: <span className="text-foreground">{selectedRatio} • {selectedCount}x</span>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">
            Референсы
            {model?.requires_reference && (
              <span className="text-destructive ml-1">*</span>
            )}
          </label>
          <UploadArea
            files={references}
            onFilesChange={handleReferencesChange}
            maxFiles={model?.max_references || 4}
            accept="image/*"
            required={model?.requires_reference}
            onUpload={onUploadReference}
            libraryFiles={savedReferences.filter((item) => item.type === 'image')}
            libraryLabel="Сохранённые фото-референсы"
          />
          <p className="text-xs text-muted-foreground">
            {isFeedRemix
              ? references.length > 0
                ? 'Выбранные файлы заменят или дополнят исходные референсы перед повтором.'
                : 'Можно запустить без нового файла: исходные приватные референсы восстановятся автоматически.'
              : model?.requires_reference
                ? 'Для этой модели нужен хотя бы один исходник или референс.'
                : 'Можно добавить референсы для стиля, композиции или сохранения деталей.'}
          </p>
        </div>

        <div className="space-y-2">
          {isFeedRemix && (
            <div className="rounded-2xl border border-gold/25 bg-gold/10 p-4 space-y-3">
              <div>
                <p className="text-sm font-medium text-foreground">
                  {remixTitle || 'Повторить образ из ленты'}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  Можно заменить цвет волос, одежду, фон и другие детали перед запуском.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {CHANGE_CHIPS.map((chip) => {
                  const Icon = chip.icon
                  const isActive = activeChanges.has(chip.id)
                  return (
                    <button
                      key={chip.id}
                      type="button"
                      onClick={() => toggleChange(chip.id, chip.insert)}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-200',
                        isActive
                          ? 'border-gold/50 bg-gold/20 text-gold shadow-sm'
                          : 'border-border/50 bg-background/50 text-muted-foreground hover:border-gold/30 hover:text-foreground'
                      )}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {chip.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )}
          <label className="text-sm font-medium text-foreground">Промпт</label>
          <Textarea
            value={prompt}
            onChange={(e) => {
              setPrompt(e.target.value)
              if (selectedPromptId) {
                setSelectedPromptId(null)
              }
            }}
            placeholder={isFeedRemix
              ? 'Выберите, что изменить, и допишите детали. Остальное будет сохранено.'
              : 'Опишите сцену, стиль, свет, камеру, детали персонажей и желаемый результат...'}
            className={cn(
              "min-h-[140px] resize-none",
              "bg-secondary/50 border-border/50",
              "focus:border-gold/50 focus:ring-gold/20",
              "placeholder:text-muted-foreground/50"
            )}
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {isFeedRemix
                ? prompt.trim().length > 0
                  ? 'Промпт из ленты готов к запуску'
                  : 'Промпт скрыт автором, запуск доступен'
                : selectedPromptId
                  ? 'Используется промпт из библиотеки'
                  : prompt.trim().length > 0
                    ? 'Промпт готов к запуску'
                    : 'Пустой prompt не отправится'}
            </span>
            <span>{prompt.length} симв.</span>
          </div>
        </div>
      </div>

      <div className="glass rounded-2xl p-4 space-y-4">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-xl bg-secondary/40 p-3">
            <p className="text-muted-foreground mb-1">Сводка</p>
            <p className="text-foreground font-medium">{model?.label}</p>
            <p className="text-muted-foreground mt-1">
              {selectedRatio}
              {model?.qualities?.length ? ` • ${selectedQuality}` : ''}
              {' • '}
              {selectedCount}x
            </p>
          </div>
          <div className="rounded-xl bg-secondary/40 p-3">
            <p className="text-muted-foreground mb-1">Файлы</p>
            <p className="text-foreground font-medium">{references.length} / {model?.max_references || 0}</p>
            <p className="text-muted-foreground mt-1">
              {model?.requires_reference ? 'Минимум 1 обязателен' : 'Опционально'}
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">Стоимость</span>
          <div className="flex items-center gap-1.5">
            <Banana className="w-4 h-4 text-gold" />
            <span className="text-lg font-semibold text-gold">{cost}</span>
          </div>
        </div>

        {!canAfford && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-destructive/10 border border-destructive/30">
            <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0" />
            <p className="text-xs text-destructive">
              Недостаточно бананов. Пополните баланс.
            </p>
          </div>
        )}

        {needsReference && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-gold/10 border border-gold/30">
            <AlertCircle className="w-4 h-4 text-gold flex-shrink-0" />
            <p className="text-xs text-gold">
              Загрузите референс для этой модели
            </p>
          </div>
        )}

        {referencesUploading && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-secondary/60 border border-border/50">
            <Loader2 className="w-4 h-4 animate-spin text-cyan flex-shrink-0" />
            <p className="text-xs text-muted-foreground">
              Дождитесь окончания загрузки референса.
            </p>
          </div>
        )}

        <Button
          onClick={handleSubmit}
          disabled={!isValid || isSubmitting}
          className={cn(
            "w-full h-12 text-base font-semibold",
            "bg-gold hover:bg-gold/90 text-primary-foreground",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-5 h-5 mr-2 animate-spin" />
              Запускаю...
            </>
          ) : (
            <>
              <Sparkles className="w-5 h-5 mr-2" />
              {isFeedRemix ? 'Повторить образ' : 'Запустить фото'}
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
