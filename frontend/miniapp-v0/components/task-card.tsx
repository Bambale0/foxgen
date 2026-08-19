'use client'

import { useApp } from '@/lib/app-context'
import type { Task } from '@/lib/types'
import { cn, isHttpUrl } from '@/lib/utils'
import { Image, Video, Clock, CheckCircle2, XCircle, Headphones, UserRound } from 'lucide-react'
import { motion } from 'framer-motion'

interface TaskCardProps {
  task: Task
  index: number
}

export function TaskCard({ task, index }: TaskCardProps) {
  const { selectTask } = useApp()

  const formatTime = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(minutes / 60)

    if (minutes < 60) return `${minutes} мин. назад`
    if (hours < 24) return `${hours} ч. назад`
    return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  }

  const statusConfig = {
    pending: {
      icon: Clock,
      label: 'В обработке',
      className: 'bg-gold/15 text-gold border-gold/30',
    },
    completed: {
      icon: CheckCircle2,
      label: 'Готово',
      className: 'bg-success/15 text-success border-success/30',
    },
    failed: {
      icon: XCircle,
      label: 'Ошибка',
      className: 'bg-destructive/15 text-destructive border-destructive/30',
    },
  }

  const status = statusConfig[task.status]
  const StatusIcon = status.icon
  const TypeIcon = task.type === 'image' ? Image : task.type === 'audio' ? Headphones : task.type === 'character' ? UserRound : Video
  const thumbnailUrl =
    task.type === 'image' && task.status === 'completed' && isHttpUrl(task.result_url)
      ? task.result_url
      : null

  return (
    <motion.button
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.3 }}
      onClick={() => selectTask(task)}
      className={cn(
        "w-full group relative overflow-hidden rounded-2xl text-left",
        "bg-card/55 border border-border/50",
        "transition-all duration-300 ease-out",
        "hover:bg-card hover:border-border hover:shadow-lg hover:shadow-background/50",
        "active:scale-[0.99]",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "text-left"
      )}
    >
      <div className={cn(
        "relative aspect-[4/3] w-full overflow-hidden",
        "bg-secondary/80 flex items-center justify-center",
        task.status === 'pending' && "pulse-soft"
      )}>
        {thumbnailUrl ? (
          <img 
            src={thumbnailUrl}
            alt="" 
            className="w-full h-full object-cover"
          />
        ) : (
          <TypeIcon className={cn(
            "w-7 h-7",
            task.type === 'image' ? "text-gold/70" : task.type === 'audio' || task.type === 'character' ? "text-success/70" : "text-cyan/70"
          )} />
        )}
      </div>

      <div className="min-w-0 p-2.5">
        <div className="mb-1 flex items-center gap-1.5">
          <span className="truncate text-[10px] font-medium text-muted-foreground">
            {task.model_label}
          </span>
          <span className="h-1 w-1 rounded-full bg-border" />
          <span className="text-[10px] text-muted-foreground">
            {task.aspect_ratio}
          </span>
        </div>

        <p className="mb-2 line-clamp-1 text-xs text-foreground">
          {task.prompt_preview}
        </p>

        <div className="flex items-center justify-between gap-1">
          <span className={cn(
            "inline-flex min-w-0 items-center gap-1 rounded-full border px-1.5 py-0.5",
            "text-[9px] font-medium",
            status.className,
            task.status === 'pending' && "animate-pulse"
          )}>
            <StatusIcon className="w-3 h-3" />
            {status.label}
          </span>

          <span className="truncate text-[9px] text-muted-foreground">
            {formatTime(task.created_at)}
          </span>
        </div>
      </div>
    </motion.button>
  )
}
