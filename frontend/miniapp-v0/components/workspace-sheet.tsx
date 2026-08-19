'use client'

import { useMemo, useRef, useState } from 'react'
import { Bot, BriefcaseBusiness, Copy, Headphones, ImagePlus, Loader2, Mic, PanelTopOpen, Send, Sparkles, Square, Wand2 } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import { askAIAssistant, fetchPartnerOverview, photoToPrompt, uploadFile } from '@/lib/api'
import type { WorkspacePanel } from '@/lib/types'

type ChatRole = 'assistant' | 'user'
type ChatMessage = {
  id: string
  role: ChatRole
  text: string
}

const workspaceConfig: Record<
  WorkspacePanel,
  { title: string; description: string; icon: typeof Sparkles }
> = {
  assistant: {
    title: 'Помощник',
    description: 'Подскажет модель, настройки и поможет с запросом.',
    icon: Bot,
  },
  'photo-prompt': {
    title: 'Промпт по фото',
    description: 'Анализ фото и prompt для похожей генерации.',
    icon: Wand2,
  },
  partners: {
    title: 'Партнёрская программа',
    description: 'Ваша ссылка, рефералы и партнёрский баланс.',
    icon: BriefcaseBusiness,
  },
  support: {
    title: 'Поддержка',
    description: 'Помощь по задачам, оплате и результатам.',
    icon: Headphones,
  },
  more: {
    title: 'Ещё',
    description: 'Быстрые переходы к полезным разделам студии.',
    icon: PanelTopOpen,
  },
}

const assistantStarters = [
  'Какую модель взять для рекламного фото?',
  'Мне нужно видео до 15 секунд',
  'Помоги улучшить мой запрос',
]

export function WorkspaceSheet() {
  const { activeWorkspace, closeWorkspace, setActiveTab, openWorkspace } = useApp()
  const config = activeWorkspace ? workspaceConfig[activeWorkspace] : null
  const Icon = config?.icon || Sparkles

  return (
    <Sheet open={Boolean(activeWorkspace)} onOpenChange={(open) => !open && closeWorkspace()}>
      <SheetContent side="bottom" className="h-[86vh] rounded-t-[28px] border-border/50 bg-background/95 px-0">
        <SheetHeader className="px-5 pt-3 text-left">
          <div className="mb-2">
            <div className="mb-3 h-1 w-10 rounded-full bg-border/80" />
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-gold/20 bg-gold/10">
                <Icon className="h-4 w-4 text-gold" />
              </div>
              <div className="min-w-0">
                <SheetTitle className="font-serif text-2xl leading-tight text-foreground">
                  {config?.title}
                </SheetTitle>
                <SheetDescription className="mt-1 max-w-xl text-sm leading-5 text-muted-foreground">
                  {config?.description}
                </SheetDescription>
              </div>
            </div>
          </div>
        </SheetHeader>

        <div className="h-[calc(86vh-92px)] overflow-auto px-5 pb-6">
          {activeWorkspace === 'assistant' && <AssistantChat starters={assistantStarters} />}
          {activeWorkspace === 'photo-prompt' && (
            <PhotoPromptPanel
              onOpenPhoto={() => {
                closeWorkspace()
                setActiveTab(1)
              }}
            />
          )}
          {activeWorkspace === 'partners' && <PartnersPanel />}
          {activeWorkspace === 'support' && <SupportPanel />}
          {activeWorkspace === 'more' && (
            <MorePanel
              onPhoto={() => {
                closeWorkspace()
                setActiveTab(1)
              }}
              onVideo={() => {
                closeWorkspace()
                setActiveTab(2)
              }}
              onAssistant={() => openWorkspace('assistant')}
              onPartners={() => openWorkspace('partners')}
              onSupport={() => openWorkspace('support')}
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function AssistantChat({ starters }: { starters: string[] }) {
  const { state, setActiveTab, closeWorkspace } = useApp()
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const inputRef = useRef('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'assistant-1',
      role: 'assistant',
      text: `Я помогу быстро выбрать модель и собрать сильный запрос. Сейчас у вас ${state.user.credits}🍌. Что хотите сделать: фото, видео или доработать идею?`,
    },
  ])

  const updateInput = (value: string) => {
    inputRef.current = value
    setInput(value)
  }

  const sendMessage = async (text: string, audioFile?: File | null) => {
    const content = text.trim()
    if ((!content && !audioFile) || isLoading) return

    if (audioFile) {
      if (audioFile.size > 10 * 1024 * 1024) {
        toast.error('Аудио слишком большое', { description: 'Максимум 10MB.' })
        return
      }
    }

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      text: audioFile
        ? content
          ? `${content}\n🎙 Голосовое сообщение`
          : '🎙 Голосовое сообщение'
        : content,
    }

    const nextHistory = [...messages, userMessage].slice(-6)
    setMessages(nextHistory)
    updateInput('')
    setIsLoading(true)

    try {
      let audioUrl = ''
      if (audioFile) {
        const uploaded = await uploadFile('assistant_audio', audioFile)
        audioUrl = uploaded.url
      }

      const historyForApi = nextHistory.map((m) => ({
        role: m.role,
        text: m.text,
      }))

      const { reply } = await askAIAssistant({
        message: content,
        history: historyForApi,
        audioUrl,
        audioContentType: audioFile?.type || null,
      })

      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        text: reply,
      }

      setMessages((prev) => [...prev, assistantMessage].slice(-6))
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Не удалось получить ответ'
      toast.error('Помощник недоступен', { description: errorMessage })

      // Показываем готовый ответ, если помощник временно недоступен.
      const fallbackReply = content
        ? buildFallbackReply(content, state.user.credits)
        : 'Не удалось обработать голосовое. Попробуйте записать короче или отправить текстом.'
      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        text: fallbackReply,
      }
      setMessages((prev) => [...prev, assistantMessage].slice(-6))
    } finally {
      setIsLoading(false)
    }
  }

  const recordingExtension = (mimeType: string) => {
    const normalized = mimeType.split(';', 1)[0].toLowerCase()
    if (normalized.includes('ogg')) return 'ogg'
    if (normalized.includes('mp4')) return 'm4a'
    if (normalized.includes('mpeg') || normalized.includes('mp3')) return 'mp3'
    if (normalized.includes('wav')) return 'wav'
    return 'webm'
  }

  const startRecording = async () => {
    if (isLoading || isRecording) return
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      toast.error('Запись недоступна', { description: 'Браузер не дал доступ к микрофону.' })
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = [
        'audio/ogg;codecs=opus',
        'audio/webm;codecs=opus',
        'audio/mp4',
      ].find((type) => MediaRecorder.isTypeSupported(type)) || ''
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)

      chunksRef.current = []
      recorderRef.current = recorder
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onerror = () => {
        stream.getTracks().forEach((track) => track.stop())
        recorderRef.current = null
        setIsRecording(false)
        toast.error('Не удалось записать аудио')
      }
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop())
        recorderRef.current = null
        setIsRecording(false)

        const chunks = chunksRef.current
        chunksRef.current = []
        if (!chunks.length) {
          toast.error('Запись пустая')
          return
        }

        const type = recorder.mimeType || mimeType || 'audio/webm'
        const blob = new Blob(chunks, { type })
        const file = new File(
          [blob],
          `assistant-voice-${Date.now()}.${recordingExtension(type)}`,
          { type }
        )
        await sendMessage(inputRef.current, file)
      }

      recorder.start()
      setIsRecording(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Разрешите доступ к микрофону'
      toast.error('Микрофон недоступен', { description: message })
    }
  }

  const stopRecording = () => {
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.stop()
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {starters.map((starter) => (
          <button
            key={starter}
            type="button"
            onClick={() => sendMessage(starter)}
            disabled={isLoading}
            className="rounded-full border border-border/50 bg-secondary/20 px-3 py-2 text-xs text-foreground transition-colors hover:bg-secondary/40 disabled:opacity-50"
          >
            {starter}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {messages.map((message) => (
          <div
            key={message.id}
            className={cn(
              'max-w-[92%] rounded-2xl border px-4 py-3 text-sm leading-6',
              message.role === 'assistant'
                ? 'border-cyan/20 bg-cyan/10 text-foreground'
                : 'ml-auto border-gold/20 bg-gold/10 text-foreground'
            )}
          >
            {message.text}
          </div>
        ))}
        {isLoading && (
          <div className="flex max-w-[92%] items-center gap-2 rounded-2xl border border-cyan/20 bg-cyan/10 px-4 py-3 text-sm text-foreground">
            <Loader2 className="h-4 w-4 animate-spin text-cyan" />
            <span className="text-muted-foreground">Думаю…</span>
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
        <textarea
          value={input}
          onChange={(event) => updateInput(event.target.value)}
          rows={3}
          disabled={isLoading}
          placeholder="Например: нужен ролик для карточки товара, вертикальный формат, спокойное движение камеры"
          className="w-full resize-none rounded-2xl border border-border/50 bg-background/60 px-4 py-3 text-sm text-foreground outline-none disabled:opacity-50"
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            variant={isRecording ? 'destructive' : 'outline'}
            size="icon"
            onClick={isRecording ? stopRecording : startRecording}
            disabled={isLoading}
            title={isRecording ? 'Остановить и отправить' : 'Записать голос'}
            className={cn(
              'h-10 w-10 border-border/50',
              !isRecording && 'bg-background/40 hover:bg-background/60'
            )}
          >
            {isRecording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            <span className="sr-only">
              {isRecording ? 'Остановить и отправить' : 'Записать голос'}
            </span>
          </Button>
          <Button
            onClick={() => sendMessage(input)}
            disabled={isLoading || isRecording || !input.trim()}
            className="min-w-[150px] flex-1 bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
          >
            {isLoading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            {isLoading ? 'Думаю…' : 'Отправить'}
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              closeWorkspace()
              setActiveTab(1)
            }}
            className="flex-1 border-border/50 bg-background/40 hover:bg-background/60 sm:flex-none"
          >
            Открыть Фото
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              closeWorkspace()
              setActiveTab(2)
            }}
            className="flex-1 border-border/50 bg-background/40 hover:bg-background/60 sm:flex-none"
          >
            Открыть Видео
          </Button>
        </div>
      </div>
    </div>
  )
}

function buildFallbackReply(input: string, credits: number) {
  const text = input.toLowerCase()

  if (text.includes('15') || text.includes('видео')) {
    return `Для ролика до 15 секунд лучше начать с Kling 3.0 или Kling v3. Если нужен более выразительный результат, берите Kling 3.0. Если важнее скорость и аккуратный бюджет, подойдет Kling v3. Сразу выбирайте формат, длительность и коротко опишите движение камеры.`
  }

  if (text.includes('реклам') || text.includes('товар') || text.includes('карточк')) {
    return `Для рекламного фото я бы начал с Nano Banana Pro, а если нужно точнее править исходник — с Seedream 4.5 Edit. В запросе лучше отдельно прописать ракурс, свет, материал, фон и что именно должно выглядеть дороже.`
  }

  if (text.includes('улучш') || text.includes('запрос') || text.includes('prompt')) {
    return `Хороший запрос лучше строить так: что в кадре, какой ракурс, какой свет, какая атмосфера и что важно не потерять. Если хотите, напишите вашу идею одной фразой, а я превращу её в более сильный вариант.`
  }

  if (text.includes('баланс') || text.includes('сколько')) {
    return `Сейчас у вас ${credits}🍌. Если задача тестовая, начните с одного варианта и короткого запроса. Когда понравится направление, можно усиливать качество, длительность или количество результатов.`
  }

  return `Понял задачу. Я бы сейчас уточнил три вещи: что должно быть в центре внимания, какой нужен формат и какое настроение вы хотите получить. После этого выбор модели и настройка запуска становятся намного точнее.`
}

function PhotoPromptPanel({ onOpenPhoto }: { onOpenPhoto: () => void }) {
  const { setCredits } = useApp()
  const [reference, setReference] = useState<{ name: string; url: string } | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [preserve, setPreserve] = useState('композицию, лицо/объект, свет, цвета и стиль')
  const [goal, setGoal] = useState('максимально похожее изображение для повторной генерации')
  const [isUploading, setIsUploading] = useState(false)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const photoUploadAttemptRef = useRef(0)
  const [result, setРезультат] = useState<{
    prompt_en: string
    prompt_ru: string
    negative_prompt: string
    model_hint: string
  } | null>(null)

  async function handleUpload(file: File) {
    const attemptId = ++photoUploadAttemptRef.current
    const localPreviewUrl = URL.createObjectURL(file)
    setIsUploading(true)
    setРезультат(null)
    setReference(null)
    setPreviewUrl((current) => {
      if (current?.startsWith('blob:')) URL.revokeObjectURL(current)
      return localPreviewUrl
    })

    try {
      const uploaded = await uploadFile('image_reference', file)
      if (photoUploadAttemptRef.current !== attemptId) return
      setReference({
        name: uploaded.name,
        url: uploaded.url,
      })
      setPreviewUrl(uploaded.url)
      toast.success('Фото загружено')
    } catch (error) {
      if (photoUploadAttemptRef.current !== attemptId) return
      setReference(null)
      setPreviewUrl((current) => current === localPreviewUrl ? null : current)
      const message = error instanceof Error ? error.message : 'Не удалось загрузить фото'
      toast.error('Ошибка загрузки', { description: message })
    } finally {
      if (photoUploadAttemptRef.current === attemptId) setIsUploading(false)
      URL.revokeObjectURL(localPreviewUrl)
    }
  }

  async function analyzePhoto() {
    if (!reference) {
      toast.error('Сначала загрузите фото')
      return
    }

    setIsAnalyzing(true)
    setРезультат(null)

    try {
      const data = await photoToPrompt({
        imageUrl: reference.url,
        preserve,
        goal,
      })
      setРезультат(data)
      setCredits(data.credits)
      toast.success('Промпт собран', { description: 'Списано 1 ₽ (0,1 🍌).' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось собрать промпт'
      toast.error('Ошибка анализа', { description: message })
    } finally {
      setIsAnalyzing(false)
    }
  }

  async function copyText(text: string, label: string) {
    await navigator.clipboard.writeText(text)
    toast.success(`${label} скопирован`)
  }

  return (
    <div className="space-y-5 pb-10">
      <div className="rounded-[1.75rem] border border-gold/20 bg-gradient-to-br from-gold/[0.12] via-card/70 to-cyan/[0.08] p-5">
        <p className="text-[11px] uppercase tracking-[0.18em] text-gold">Разбор фото</p>
        <h3 className="mt-2 font-serif text-2xl text-foreground">Фото → точный prompt</h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Загрузите референс. AI разберёт кадр и соберёт промпт для генерации похожего изображения:
          композиция, объект, свет, стиль, цвета и важные детали.
        </p>
        <p className="mt-3 inline-flex rounded-full border border-gold/25 bg-gold/10 px-3 py-1.5 text-xs font-medium text-gold">
          Стоимость: 1 ₽ · 0,1 🍌
        </p>
      </div>

      <div className="rounded-[1.75rem] border border-border/60 bg-card/45 p-4">
        <label className="relative block cursor-pointer overflow-hidden">
          <input
            type="file"
            accept="image/*"
            className="relative z-10 mb-3 block w-full cursor-pointer rounded-lg border border-border/60 bg-background/80 px-3 py-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-60 file:mr-3 file:rounded-md file:border-0 file:bg-gold file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
            disabled={isUploading || isAnalyzing}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (!file) return
              handleUpload(file)
              event.target.value = ''
            }}
          />

          <div className="rounded-2xl border border-dashed border-border/70 bg-background/45 px-4 py-6 text-center transition-colors hover:border-gold/40">
            <ImagePlus className="mx-auto mb-3 h-8 w-8 text-gold" />
            <p className="font-medium text-foreground">
              {isUploading ? 'Загружаю фото…' : reference ? reference.name : 'Загрузить референс'}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Лучше использовать чёткий кадр без сильного блюра и лишних объектов.
            </p>
          </div>
        </label>

        {previewUrl && (
          <div className="mt-4 overflow-hidden rounded-2xl border border-border/50">
            <img src={previewUrl} alt="Референс" className="h-64 w-full object-cover" />
          </div>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
            Что сохранить
          </p>
          <textarea
            value={preserve}
            onChange={(event) => setPreserve(event.target.value)}
            rows={3}
            className="mt-3 w-full resize-none rounded-2xl border border-border/50 bg-background/50 px-4 py-3 text-sm text-foreground outline-none"
          />
        </div>

        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
            Какой результат нужен
          </p>
          <textarea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            rows={3}
            className="mt-3 w-full resize-none rounded-2xl border border-border/50 bg-background/50 px-4 py-3 text-sm text-foreground outline-none"
          />
        </div>
      </div>

      <Button
        onClick={analyzePhoto}
        disabled={!reference || isUploading || isAnalyzing}
        className="h-14 w-full rounded-2xl bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
      >
        {isAnalyzing ? (
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        ) : (
          <Wand2 className="mr-2 h-5 w-5" />
        )}
        {isAnalyzing ? 'Анализирую фото…' : 'Собрать точный промпт · 1 ₽'}
      </Button>

      {result && (
        <div className="space-y-3">
          <PromptРезультатCard
            title="Prompt EN"
            text={result.prompt_en}
            onCopy={() => copyText(result.prompt_en, 'Prompt EN')}
          />
          <PromptРезультатCard
            title="Prompt RU"
            text={result.prompt_ru}
            onCopy={() => copyText(result.prompt_ru, 'Prompt RU')}
          />
          <PromptРезультатCard
            title="Negative prompt"
            text={result.negative_prompt}
            onCopy={() => copyText(result.negative_prompt, 'Negative prompt')}
          />

          <div className="rounded-2xl border border-cyan/20 bg-cyan/10 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-cyan/80">Рекомендация</p>
            <p className="mt-2 text-sm leading-6 text-foreground">{result.model_hint}</p>
          </div>

          <div className="flex gap-3">
            <Button
              variant="outline"
              onClick={() => copyText(result.prompt_en, 'Prompt EN')}
              className="flex-1 border-border/50 bg-background/40 hover:bg-background/60"
            >
              <Copy className="mr-2 h-4 w-4" />
              Скопировать
            </Button>
            <Button onClick={onOpenPhoto} className="flex-1 bg-gold text-primary-foreground hover:bg-gold/90">
              Открыть фото
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function PromptРезультатCard({
  title,
  text,
  onCopy,
}: {
  title: string
  text: string
  onCopy: () => void
}) {
  return (
    <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs uppercase tracking-[0.16em] text-gold/80">{title}</p>
        <button
          type="button"
          onClick={onCopy}
          className="rounded-full border border-border/50 bg-background/40 px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-background/70"
        >
          Копировать
        </button>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-foreground">{text}</p>
    </div>
  )
}


function PartnersPanel() {
  const [isLoading, setIsLoading] = useState(false)
  const [partner, setPartner] = useState<{
    is_partner: boolean
    referrals_count: number
    balance_rub: number
    referral_link: string
    status: string
  } | null>(null)

  async function loadPartnerData() {
    setIsLoading(true)
    try {
      const data = await fetchPartnerOverview()
      setPartner(data)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить партнёрку'
      toast.error('Партнёрская программа недоступна', { description: message })
    } finally {
      setIsLoading(false)
    }
  }

  useMemo(() => {
    if (!partner && !isLoading) {
      loadPartnerData()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const referralLink = partner?.referral_link || ''
  const statusLabel = partner?.status === 'partner' ? 'Партнёр' : 'Базовый'

  return (
    <div className="space-y-4 pb-8">
      {isLoading && !partner && (
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin text-gold" />
            Загружаю данные…
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Статус</p>
          <p className="mt-1 truncate font-serif text-lg text-foreground">{statusLabel}</p>
        </div>

        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Рефералов</p>
          <p className="mt-1 font-serif text-lg text-foreground">
            {partner?.referrals_count ?? '—'}
          </p>
        </div>

        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Баланс</p>
          <p className="mt-1 font-serif text-lg text-foreground">
            {partner ? `${partner.balance_rub} ₽` : '—'}
          </p>
        </div>
      </div>

      <div className="rounded-[1.5rem] border border-gold/20 bg-gold/10 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-gold/80">
              Ваша ссылка
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              Делитесь ей с клиентами и авторами.
            </p>
          </div>

          <Button
            variant="outline"
            onClick={loadPartnerData}
            disabled={isLoading}
            className="shrink-0 border-border/50 bg-background/40 hover:bg-background/60"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Обновить'}
          </Button>
        </div>

        <div className="mt-4 rounded-2xl border border-border/50 bg-background/45 p-3">
          <p className="break-all text-sm leading-6 text-foreground">
            {referralLink || 'Ссылка пока недоступна'}
          </p>
        </div>

        <Button
          disabled={!referralLink}
          onClick={() => {
            navigator.clipboard.writeText(referralLink)
            toast.success('Реферальная ссылка скопирована')
          }}
          className="mt-4 h-12 w-full rounded-2xl bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
        >
          <Copy className="mr-2 h-4 w-4" />
          Скопировать ссылку
        </Button>
      </div>

      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
          Как это работает
        </p>
        <div className="mt-3 space-y-2">
          {[
            'Пользователь переходит по вашей ссылке.',
            'Мы привязываем приглашение к вашему профилю.',
            'Статистика и баланс обновляются в этом разделе.',
          ].map((item, index) => (
            <div key={item} className="flex gap-3 rounded-xl bg-background/35 px-3 py-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gold/10 text-xs text-gold">
                {index + 1}
              </span>
              <p className="text-sm leading-5 text-foreground">{item}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SupportPanel() {
  const tips = [
    'Проверьте, хватает ли баланса для выбранной модели и длительности.',
    'Если задача долго выполняется, откройте её детали и обновите статус.',
    'Для редактирования и анимации обязательно добавьте исходный файл.',
  ]

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <p className="text-xs text-muted-foreground">Перед обращением</p>
        <div className="mt-3 space-y-2">
          {tips.map((tip) => (
            <div key={tip} className="rounded-xl border border-border/40 bg-background/30 px-3 py-3 text-sm text-foreground">
              {tip}
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-2xl border border-cyan/20 bg-cyan/10 p-4">
        <p className="text-xs text-muted-foreground">Сообщение в поддержку</p>
        <p className="mt-2 text-sm leading-6 text-foreground">
          Здравствуйте. Нужна помощь по задаче. Укажу номер задачи, выбранную модель и коротко опишу, что ожидал получить.
        </p>
        <Button
          onClick={() => toast.success('Текст скопирован')}
          className="mt-4 bg-cyan text-background hover:bg-cyan/90"
        >
          Скопировать текст
        </Button>
      </div>
    </div>
  )
}

function MorePanel({
  onPhoto,
  onVideo,
  onAssistant,
  onPartners,
  onSupport,
}: {
  onPhoto: () => void
  onVideo: () => void
  onAssistant: () => void
  onPartners: () => void
  onSupport: () => void
}) {
  const actions = [
    { label: 'Фото', description: 'Перейти к генерации изображений', action: onPhoto },
    { label: 'Видео', description: 'Перейти к генерации роликов', action: onVideo },
    { label: 'Помощник', description: 'Подскажет модель и улучшит запрос', action: onAssistant },
    { label: 'Партнёрам', description: 'Посмотреть выгоду и материалы', action: onPartners },
    { label: 'Поддержка', description: 'Собрать обращение и не забыть детали', action: onSupport },
  ]

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {actions.map((item) => (
        <button
          key={item.label}
          type="button"
          onClick={item.action}
          className="rounded-2xl border border-border/50 bg-secondary/20 p-4 text-left transition-colors hover:bg-secondary/40"
        >
          <p className="font-medium text-foreground">{item.label}</p>
          <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>
        </button>
      ))}
    </div>
  )
}
