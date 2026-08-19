'use client'

import { useEffect, useState } from 'react'
import { useApp } from '@/lib/app-context'
import { notifyFeedChanged } from '@/lib/feed-events'
import { cn } from '@/lib/utils'
import { 
  X, Image, Video, Clock, CheckCircle2, XCircle, 
  Banana, ExternalLink, Copy, RefreshCw, Headphones, UserRound, Images, BookOpen, Eye, EyeOff, ShieldAlert
} from 'lucide-react' 
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'
import {
  publishGeneration,
  removeGenerationPrompt,
  saveGenerationPrompt,
  unpublishGeneration,
} from '@/lib/api'
import { toast } from 'sonner'
import { copyTextToClipboard } from '@/lib/clipboard'

export function TaskDetailPanel() {
  const { taskDetail, isTaskDetailOpen, closeTaskDetail, updateTask } = useApp()
  const [publishBusy, setPublishBusy] = useState(false)
  const [libraryBusy, setLibraryBusy] = useState(false)
  const [feedPromptVisible, setFeedPromptVisible] = useState(false)
  const [feedReferencesVisible, setFeedReferencesVisible] = useState(false)
  const [feedBlurred, setFeedBlurred] = useState(false)
  const [publicationScope, setPublicationScope] = useState<'profile' | 'feed'>('feed')
  const [adultContent, setAdultContent] = useState(false)
  const [publicationEditorOpen, setPublicationEditorOpen] = useState(false)
  const [publicationLink, setPublicationLink] = useState<string | null>(null)

  const referenceCount =
    (taskDetail?.request_data?.reference_images?.length || 0) +
    (taskDetail?.request_data?.v_reference_videos?.length || 0)

  useEffect(() => {
    setFeedPromptVisible(Boolean(taskDetail?.feed_prompt_visible))
    setFeedReferencesVisible(Boolean(taskDetail?.feed_references_visible))
    setFeedBlurred(Boolean(taskDetail?.feed_blurred))
    setPublicationScope(taskDetail?.publication_scope === 'profile' ? 'profile' : 'feed')
    setAdultContent(Boolean(taskDetail?.is_adult_content))
    setPublicationEditorOpen(false)
    setPublicationLink(null)
  }, [
    taskDetail?.task_id,
    taskDetail?.feed_prompt_visible,
    taskDetail?.feed_references_visible,
    taskDetail?.feed_blurred,
    taskDetail?.publication_scope,
    taskDetail?.is_adult_content,
  ])

  const confirmPublication = (target: string) => {
    if (typeof window === 'undefined') return true
    return window.confirm(
      `Публикация в ${target}\n\n` +
        'Вы подтверждаете, что у вас есть права или согласие на исходники, результат и текст промпта.\n\n' +
        'Ответственность за опубликованный пользовательский контент несёт пользователь. Администрация бота не проводит предварительную модерацию и не отвечает за материалы, которые пользователи выкладывают самостоятельно.\n\n' +
        'Спорный материал может быть удалён по жалобе правообладателя или другого заинтересованного лица.'
    )
  }

  const handleCopyTaskId = async () => {
    if (!taskDetail || typeof navigator === 'undefined') return
    try {
      await navigator.clipboard.writeText(taskDetail.task_id)
    } catch {
      // Ignore clipboard failures in constrained webviews
    }
  }

  const handleCopyPrompt = async () => {
    if (!taskDetail?.prompt || taskDetail.prompt_hidden || typeof navigator === 'undefined') return
    try {
      await navigator.clipboard.writeText(taskDetail.prompt)
    } catch {
      // Ignore clipboard failures in constrained webviews
    }
  }

  const isPublished = Boolean(taskDetail?.is_profile_visible || taskDetail?.is_public_feed)

  const handlePublish = async () => {
    if (!taskDetail || publishBusy) return
    const target = publicationScope === 'profile' ? 'свой профиль' : 'ленту и свой профиль'
    if (!isPublished && !confirmPublication(target)) return
    setPublishBusy(true)
    try {
      const published = await publishGeneration(taskDetail.task_id, {
          promptVisible: feedPromptVisible,
          referencesVisible: feedReferencesVisible,
          blurred: feedBlurred,
          publicationScope,
          adultContent,
        })
        updateTask(taskDetail.task_id, {
          is_public_feed: published.publication_scope === 'feed',
          is_profile_visible: true,
          publication_scope: published.publication_scope,
          is_adult_content: Boolean(published.is_adult_content),
          feed_interactions_enabled: published.feed_interactions_enabled,
          feed_prompt_visible: feedPromptVisible,
          feed_references_visible: feedReferencesVisible,
          feed_blurred: Boolean(published.feed_blurred),
        })
        notifyFeedChanged(published)
        setPublicationLink(published.publication_link || null)
        setPublicationEditorOpen(false)
        toast.success(
          published.publication_scope === 'profile'
            ? 'Опубликовано только в профиле'
            : 'Опубликовано в ленте и профиле'
        )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось опубликовать')
    } finally {
      setPublishBusy(false)
    }
  }

  const handleUnpublish = async () => {
    if (!taskDetail || publishBusy || !isPublished) return
    setPublishBusy(true)
    try {
      await unpublishGeneration(taskDetail.task_id)
      updateTask(taskDetail.task_id, {
        is_public_feed: false,
        is_profile_visible: false,
        publication_scope: 'private',
        is_adult_content: false,
      })
      setPublicationLink(null)
      setPublicationEditorOpen(false)
      notifyFeedChanged()
      toast.success('Публикация убрана')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось убрать публикацию')
    } finally {
      setPublishBusy(false)
    }
  }

  const handleCopyPublicationLink = async () => {
    if (!publicationLink) return
    try {
      await copyTextToClipboard(publicationLink)
      toast.success('Ссылка скопирована')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось скопировать ссылку')
    }
  }

  const handleSavePrompt = async () => {
    if (!taskDetail || libraryBusy) return
    if (!taskDetail.is_prompt_library && !confirmPublication('ленту промптов')) return
    setLibraryBusy(true)
    try {
      if (taskDetail.is_prompt_library) {
        await removeGenerationPrompt(taskDetail.task_id)
        updateTask(taskDetail.task_id, { is_prompt_library: false })
        toast.success('Убрано из промптов')
      } else {
        await saveGenerationPrompt(taskDetail.task_id)
        updateTask(taskDetail.task_id, { is_prompt_library: true })
        toast.success('Промпт сохранён')
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить prompt')
    } finally {
      setLibraryBusy(false)
    }
  }

  const canPublishToFeed = Boolean(
    taskDetail &&
      (taskDetail.type === 'image' || taskDetail.type === 'video') &&
      taskDetail.prompt_actions_allowed !== false &&
      !taskDetail.prompt_hidden
  )
  const canSavePrompt = Boolean(
    taskDetail &&
      taskDetail.type === 'image' &&
      taskDetail.prompt_actions_allowed !== false &&
      !taskDetail.prompt_hidden
  )

  return (
    <AnimatePresence>
      {isTaskDetailOpen && taskDetail && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={closeTaskDetail}
            className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50"
          />

          {/* Panel */}
          <motion.div
            initial={{ opacity: 0, y: '100%' }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: '100%' }}
            transition={{ 
              type: 'spring', 
              damping: 30, 
              stiffness: 300,
              mass: 0.8,
            }}
            className={cn(
              "fixed bottom-0 left-0 right-0 z-50",
              "max-h-[85vh] overflow-auto",
              "glass-strong rounded-t-3xl border-t border-border/50",
              "safe-bottom"
            )}
          >
            {/* Handle */}
            <div className="sticky top-0 z-10 flex justify-center pt-3 pb-2 bg-inherit">
              <div className="w-10 h-1 rounded-full bg-border" />
            </div>

            {/* Header */}
            <div className="flex items-center justify-between px-5 pb-4">
              <h2 className="font-serif text-xl font-semibold text-foreground">
                Детали задачи
              </h2>
              <button
                onClick={closeTaskDetail}
                className="w-8 h-8 rounded-full bg-secondary/80 flex items-center justify-center hover:bg-secondary transition-colors"
              >
                <X className="w-4 h-4 text-muted-foreground" />
              </button>
            </div>

            {/* Content */}
            <div className="px-5 pb-6 space-y-5">
              {/* Preview */}
              {taskDetail.result_url && taskDetail.status === 'completed' && taskDetail.type === 'image' && (
                <div className="relative aspect-square rounded-2xl overflow-hidden bg-secondary/50">
                  <img
                    src={taskDetail.result_url}
                    alt="Результат"
                    className="w-full h-full object-cover"
                  />
                </div>
              )}

              {taskDetail.result_url && taskDetail.status === 'completed' && taskDetail.type === 'video' && (
                <div className="relative aspect-video rounded-2xl overflow-hidden bg-secondary/50">
                  <video
                    src={taskDetail.result_url}
                    className="w-full h-full object-cover"
                    controls
                    playsInline
                  />
                </div>
              )}

              {taskDetail.result_url && taskDetail.status === 'completed' && (taskDetail.type === 'audio' || taskDetail.type === 'character') && (
                <div className="rounded-2xl border border-border/50 bg-secondary/50 p-4">
                  <p className="mb-2 text-xs text-muted-foreground">
                    {taskDetail.type === 'audio' ? 'Audio ID' : 'Character ID'}
                  </p>
                  <code className="block break-all font-mono text-sm text-foreground">
                    {taskDetail.result_url}
                  </code>
                </div>
              )}

              {/* Pending state */}
              {taskDetail.status === 'pending' && (
                <div className="relative aspect-video rounded-2xl overflow-hidden bg-secondary/50 flex flex-col items-center justify-center">
                  <div className="w-16 h-16 rounded-2xl bg-gold/10 flex items-center justify-center mb-4">
                    <RefreshCw className="w-8 h-8 text-gold animate-spin" />
                  </div>
                  <p className="text-sm font-medium text-foreground mb-1">
                    Генерация в процессе
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Статус обновляется автоматически
                  </p>
                </div>
              )}

              {/* Info grid */}
              <div className="grid grid-cols-2 gap-3">
                <InfoItem 
                  label="Модель" 
                  value={taskDetail.model_label} 
                />
                <InfoItem 
                  label="Тип" 
                  value={
                    taskDetail.type === 'image'
                      ? 'Фото'
                      : taskDetail.type === 'audio'
                        ? 'Audio ID'
                        : taskDetail.type === 'character'
                          ? 'Character ID'
                          : 'Видео'
                  }
                  icon={taskDetail.type === 'image' ? Image : taskDetail.type === 'audio' ? Headphones : taskDetail.type === 'character' ? UserRound : Video}
                />
                <InfoItem 
                  label="Формат" 
                  value={taskDetail.aspect_ratio} 
                />
                <InfoItem 
                  label="Статус" 
                  value={
                    taskDetail.status === 'pending' ? 'В обработке' :
                    taskDetail.status === 'completed' ? 'Готово' : 'Ошибка'
                  }
                  icon={
                    taskDetail.status === 'pending' ? Clock :
                    taskDetail.status === 'completed' ? CheckCircle2 : XCircle
                  }
                  statusColor={
                    taskDetail.status === 'pending' ? 'text-gold' :
                    taskDetail.status === 'completed' ? 'text-success' : 'text-destructive'
                  }
                />
                <InfoItem 
                  label="Стоимость" 
                  value={`${taskDetail.cost}`}
                  icon={Banana}
                  statusColor="text-gold"
                />
                <InfoItem
                  label="Референсы"
                  value={`${taskDetail.request_data?.reference_images?.length || 0}`}
                />
                {taskDetail.request_data?.v_reference_videos && (
                  <InfoItem
                    label="Видео-референсы"
                    value={`${taskDetail.request_data.v_reference_videos.length}`}
                  />
                )}
                {taskDetail.duration && (
                  <InfoItem 
                    label="Длительность" 
                    value={`${taskDetail.duration} сек.`} 
                  />
                )}
              </div>

              {/* Task ID */}
              <div className="flex items-center gap-2 p-3 rounded-xl bg-secondary/50">
                <span className="text-xs text-muted-foreground">ID:</span>
                <code className="text-xs text-foreground font-mono flex-1 truncate">
                  {taskDetail.task_id}
                </code>
                <button
                  onClick={handleCopyTaskId}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                >
                  <Copy className="w-4 h-4" />
                </button>
              </div>

              {/* Prompt */}
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-foreground">Промпт</h3>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="h-8 px-3"
                    onClick={handleCopyPrompt}
                    disabled={!taskDetail.prompt || taskDetail.prompt_hidden}
                  >
                    <Copy className="mr-2 h-4 w-4" />
                    Скопировать
                  </Button>
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed p-3 rounded-xl bg-secondary/50 whitespace-pre-wrap break-words">
                  {taskDetail.prompt_hidden ? 'Описание автора уже использовано для этой работы.' : taskDetail.prompt || '—'}
                </p>
              </div>

              {/* References */}
              {taskDetail.request_data?.reference_images && taskDetail.request_data.reference_images.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-foreground mb-2">
                    Референсы ({taskDetail.request_data.reference_images.length})
                  </h3>
                  <div className="flex gap-2 overflow-x-auto pb-2">
                    {taskDetail.request_data.reference_images.map((url, i) => (
                      <div 
                        key={i}
                        className="w-20 h-20 rounded-xl overflow-hidden flex-shrink-0 bg-secondary/50"
                      >
                        <img src={url} alt="" className="w-full h-full object-cover" />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions */}
              {taskDetail.status === 'completed' && taskDetail.result_url && (
                <div className="space-y-2">
                  {canPublishToFeed && publicationEditorOpen ? (
                <div className="rounded-xl border border-border/50 bg-secondary/35 p-3">
                  <p className="mb-3 text-sm font-semibold text-foreground">Куда опубликовать?</p>
                  <div className="mb-3 grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      disabled={adultContent}
                      onClick={() => setPublicationScope('feed')}
                      className={cn(
                        'rounded-lg border px-3 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45',
                        publicationScope === 'feed'
                          ? 'border-cyan/40 bg-cyan/10 text-cyan'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      Лента и профиль
                    </button>
                    <button
                      type="button"
                      onClick={() => setPublicationScope('profile')}
                      className={cn(
                        'rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
                        publicationScope === 'profile'
                          ? 'border-cyan/40 bg-cyan/10 text-cyan'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      Только профиль
                    </button>
                  </div>
                  {taskDetail.type === 'image' ? (
                    <button
                      type="button"
                      onClick={() => {
                        setAdultContent((current) => {
                          const next = !current
                          if (next) {
                            setPublicationScope('profile')
                          }
                          return next
                        })
                      }}
                      className={cn(
                        'mb-3 flex w-full items-start gap-2 rounded-lg border p-3 text-left transition-colors',
                        adultContent
                          ? 'border-destructive/40 bg-destructive/10 text-destructive'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>
                        <span className="block text-xs font-semibold">Контент 18+</span>
                        <span className="mt-0.5 block text-[11px] leading-relaxed">
                          Публикуется только в профиле. Blur включается отдельно по вашему выбору.
                        </span>
                      </span>
                    </button>
                  ) : null}
                  <div className="grid grid-cols-3 gap-2">
                        <button
                          type="button"
                          onClick={() => setFeedPromptVisible((prev) => !prev)}
                          className={cn(
                            'flex h-10 items-center justify-center gap-2 rounded-lg border px-3 text-xs font-medium transition-colors',
                            feedPromptVisible
                              ? 'border-cyan/40 bg-cyan/10 text-cyan'
                              : 'border-border/50 bg-background/40 text-muted-foreground'
                          )}
                        >
                          {feedPromptVisible ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                          Prompt
                        </button>
                        <button
                          type="button"
                          disabled={referenceCount === 0}
                          onClick={() => setFeedReferencesVisible((prev) => !prev)}
                          className={cn(
                            'flex h-10 items-center justify-center gap-2 rounded-lg border px-3 text-xs font-medium transition-colors disabled:opacity-50',
                            feedReferencesVisible
                              ? 'border-cyan/40 bg-cyan/10 text-cyan'
                              : 'border-border/50 bg-background/40 text-muted-foreground'
                          )}
                        >
                          {feedReferencesVisible ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                          Рефы {referenceCount ? `(${referenceCount})` : ''}
                        </button>
                        <button
                          type="button"
                          onClick={() => setFeedBlurred((prev) => !prev)}
                          className={cn(
                            'flex h-10 items-center justify-center gap-2 rounded-lg border px-3 text-xs font-medium transition-colors',
                            feedBlurred
                              ? 'border-cyan/40 bg-cyan/10 text-cyan'
                              : 'border-border/50 bg-background/40 text-muted-foreground'
                          )}
                        >
                          {feedBlurred ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          Blur
                        </button>
                      </div>
                  <div className="mt-3 grid gap-2">
                    <Button type="button" disabled={publishBusy} onClick={handlePublish}>
                      {publishBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Images className="h-4 w-4" />}
                      {isPublished ? 'Сохранить публикацию' : 'Опубликовать'}
                    </Button>
                    {isPublished ? (
                      <Button type="button" variant="outline" disabled={publishBusy} onClick={handleUnpublish}>
                        Убрать публикацию
                      </Button>
                    ) : null}
                  </div>
                    </div>
                  ) : null}
                  {publicationLink ? (
                    <div className="grid grid-cols-2 gap-2 rounded-xl border border-border/50 bg-secondary/35 p-2">
                      <Button asChild type="button" variant="secondary" size="sm">
                        <a href={publicationLink} target="_blank" rel="noreferrer">
                          <ExternalLink className="h-4 w-4" />
                          Открыть
                        </a>
                      </Button>
                      <Button type="button" variant="secondary" size="sm" onClick={handleCopyPublicationLink}>
                        <Copy className="h-4 w-4" />
                        Скопировать
                      </Button>
                    </div>
                  ) : null}
                  {(canPublishToFeed || canSavePrompt) && (
                    <div className={cn('grid gap-2', canSavePrompt ? 'grid-cols-2' : 'grid-cols-1')}>
                      {canPublishToFeed ? (
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={publishBusy}
                        onClick={() => setPublicationEditorOpen((open) => !open)}
                      >
                        <Images className="h-4 w-4" />
                        {isPublished ? 'Настроить публикацию' : 'Опубликовать'}
                      </Button>
                      ) : null}
                      {canSavePrompt ? (
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={libraryBusy}
                        onClick={handleSavePrompt}
                      >
                        {libraryBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <BookOpen className="h-4 w-4" />}
                        {taskDetail.is_prompt_library ? 'Убрать из промптов' : 'В промпты'}
                      </Button>
                      ) : null}
                    </div>
                  )}
                  <Button
                    asChild
                    className="w-full bg-gold hover:bg-gold/90 text-primary-foreground"
                    size="lg"
                  >
                    <a href={taskDetail.result_url} target="_blank" rel="noreferrer">
                      <ExternalLink className="w-4 h-4 mr-2" />
                      Открыть оригинал
                    </a>
                  </Button>
                </div>
              )}

              {/* Time */}
              <p className="text-center text-xs text-muted-foreground">
                Создано: {new Date(taskDetail.created_at).toLocaleString('ru-RU')}
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

function InfoItem({ 
  label, 
  value, 
  icon: Icon,
  statusColor,
}: { 
  label: string
  value: string
  icon?: React.ComponentType<{ className?: string }>
  statusColor?: string
}) {
  return (
    <div className="p-3 rounded-xl bg-secondary/50">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <div className="flex items-center gap-1.5">
        {Icon && <Icon className={cn("w-4 h-4", statusColor || "text-foreground")} />}
        <span className={cn("text-sm font-medium", statusColor || "text-foreground")}>
          {value}
        </span>
      </div>
    </div>
  )
}
