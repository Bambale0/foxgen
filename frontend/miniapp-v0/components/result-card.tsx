'use client'

import { useState } from 'react'
import type { Task } from '@/lib/types'
import { cn } from '@/lib/utils'
import { CheckCircle2, Clock, X, ExternalLink, Copy, AlertCircle, Maximize2 } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'

interface ResultCardProps {
  task: Task
  onClose: () => void
}

export function ResultCard({ task, onClose }: ResultCardProps) {
  const [viewerOpen, setViewerOpen] = useState(false)

  const isPending = task.status === 'pending'
  const isCompleted = task.status === 'completed'
  const isFailed = task.status === 'failed'

  const handleCopy = async () => {
    if (typeof navigator === 'undefined') return
    try {
      await navigator.clipboard.writeText(task.task_id)
    } catch {
      // Ignore clipboard failures in constrained webviews.
    }
  }

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 20, scale: 0.95 }}
        className={cn(
          'relative rounded-2xl p-5',
          'glass border',
          isPending ? 'border-gold/30' : isCompleted ? 'border-success/30' : 'border-destructive/30'
        )}
      >
        <button
          onClick={onClose}
          className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full bg-secondary/80 transition-colors hover:bg-secondary"
        >
          <X className="h-4 w-4 text-muted-foreground" />
        </button>

        <div className="mb-4 flex items-center gap-3 pr-9">
          <div
            className={cn(
              'flex h-10 w-10 items-center justify-center rounded-xl',
              isPending ? 'bg-gold/15' : isCompleted ? 'bg-success/15' : 'bg-destructive/15'
            )}
          >
            {isPending ? (
              <Clock className="h-5 w-5 animate-pulse text-gold" />
            ) : isFailed ? (
              <AlertCircle className="h-5 w-5 text-destructive" />
            ) : (
              <CheckCircle2 className="h-5 w-5 text-success" />
            )}
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              {isPending ? 'Задача принята' : isFailed ? 'Ошибка запуска' : 'Результат готов'}
            </h3>
            <p className="text-xs text-muted-foreground">
              {isPending
                ? 'Результат придёт в чат и появится в истории'
                : isFailed
                  ? 'Проверьте prompt, файлы и попробуйте снова'
                  : task.type === 'image'
                    ? 'Нажмите на изображение для полного просмотра'
                    : task.type === 'audio'
                      ? 'Audio ID готов к использованию'
                      : task.type === 'character'
                        ? 'Character ID готов к использованию'
                    : 'Видео можно открыть и воспроизвести'}
            </p>
          </div>
        </div>

        <div className="mb-4 flex items-center gap-2 rounded-xl bg-secondary/50 p-3">
          <span className="text-xs text-muted-foreground">ID:</span>
          <code className="flex-1 truncate font-mono text-xs text-foreground">
            {task.task_id}
          </code>
          <button
            onClick={handleCopy}
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            <Copy className="h-4 w-4" />
          </button>
        </div>

        {isCompleted && task.result_url && task.type === 'image' && (
          <button
            type="button"
            onClick={() => setViewerOpen(true)}
            className="group relative mb-4 flex max-h-[70vh] min-h-64 w-full items-center justify-center overflow-hidden rounded-xl border border-border/50 bg-background/60"
          >
            <img
              src={task.result_url}
              alt="Generated result"
              className="max-h-[70vh] w-full object-contain"
            />
            <span className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-full border border-border/50 bg-background/75 px-3 py-1.5 text-xs text-foreground opacity-90 backdrop-blur">
              <Maximize2 className="h-3.5 w-3.5" />
              Открыть
            </span>
          </button>
        )}

        {isCompleted && task.result_url && task.type === 'video' && (
          <div className="relative mb-4 aspect-video overflow-hidden rounded-xl">
            <video
              src={task.result_url}
              className="h-full w-full object-contain bg-background"
              controls
              playsInline
            />
          </div>
        )}

        {isCompleted && task.result_url && (task.type === 'audio' || task.type === 'character') && (
          <div className="mb-4 rounded-xl border border-border/50 bg-secondary/50 p-3">
            <p className="mb-1 text-xs text-muted-foreground">
              {task.type === 'audio' ? 'Audio ID' : 'Character ID'}
            </p>
            <code className="block break-all font-mono text-sm text-foreground">
              {task.result_url}
            </code>
          </div>
        )}

        {isPending && (
          <div className="relative mb-4 flex aspect-video flex-col items-center justify-center overflow-hidden rounded-xl bg-secondary/50">
            <div className="relative h-16 w-16">
              <div className="absolute inset-0 rounded-full border-2 border-gold/20" />
              <div className="absolute inset-0 animate-spin rounded-full border-2 border-gold border-t-transparent" />
            </div>
            <p className="mt-4 text-xs text-muted-foreground">
              Статус обновляется автоматически
            </p>
          </div>
        )}

        {isCompleted && task.result_url && task.result_url.startsWith('http') && (
          <Button asChild className="w-full bg-gold text-primary-foreground hover:bg-gold/90">
            <a href={task.result_url} target="_blank" rel="noreferrer">
              <ExternalLink className="mr-2 h-4 w-4" />
              Открыть оригинал
            </a>
          </Button>
        )}
      </motion.div>

      <AnimatePresence>
        {viewerOpen && task.result_url && task.type === 'image' && (
          <motion.div
            className="fixed inset-0 z-[100] flex flex-col bg-black/95"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="flex items-center justify-between gap-3 px-4 py-3 safe-top">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-white">Полный просмотр</p>
                <p className="truncate text-xs text-white/55">{task.model_label}</p>
              </div>
              <button
                type="button"
                onClick={() => setViewerOpen(false)}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/10 text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex min-h-0 flex-1 items-center justify-center px-2 py-2">
              <img
                src={task.result_url}
                alt="Generated result full"
                className="max-h-full max-w-full object-contain"
              />
            </div>

            <div className="grid grid-cols-2 gap-3 px-4 pb-4 safe-bottom">
              <Button
                variant="outline"
                onClick={() => setViewerOpen(false)}
                className="border-white/20 bg-white/10 text-white hover:bg-white/15"
              >
                Закрыть
              </Button>
              <Button asChild className="bg-gold text-background hover:bg-gold/90">
                <a href={task.result_url} target="_blank" rel="noreferrer">
                  Оригинал
                </a>
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
