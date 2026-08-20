'use client'

import {
  Wand2,
  Pencil,
  Play,
  HeadphonesIcon,
  Users,
  MoreHorizontal,
  ArrowRight,
  Mic2,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

const primaryServices = [
  {
    id: 'prompt-by-photo',
    icon: Wand2,
    title: 'Промпт по фото',
    description: 'Загрузите референс — AI соберёт точный prompt для похожей генерации.',
    badge: '1 ₽ · 0,1 🍌',
    tone: 'gold',
  },
  {
    id: 'avatar',
    icon: Mic2,
    title: 'Avatar',
    description: 'Говорящий аватар: загрузите фото персонажа и аудио.',
    badge: 'Фото + аудио',
    tone: 'cyan',
  },
  {
    id: 'edit-photo',
    icon: Pencil,
    title: 'Изменить фото',
    description: 'Правки по исходнику: фон, стиль, детали, одежда, настроение.',
    badge: 'Правки',
    tone: 'cyan',
  },
  {
    id: 'animate',
    icon: Play,
    title: 'Оживить фото',
    description: 'Переход к видео-сценариям: стартовый кадр, движение, камера.',
    badge: 'Анимация',
    tone: 'success',
  },
]

const secondaryServices = [
  {
    id: 'support',
    icon: HeadphonesIcon,
    title: 'Поддержка',
    description: 'Помощь по задачам, оплате и результатам.',
  },
  {
    id: 'partners',
    icon: Users,
    title: 'Партнёрам',
    description: 'Рефералка, материалы и условия.',
  },
  {
    id: 'more',
    icon: MoreHorizontal,
    title: 'Ещё',
    description: 'Дополнительные разделы и переходы.',
  },
]

const toneClass: Record<string, string> = {
  gold: 'border-gold/25 bg-gold/[0.07] text-gold',
  cyan: 'border-cyan/25 bg-cyan/[0.07] text-cyan',
  success: 'border-success/25 bg-success/[0.07] text-success',
  accent: 'border-accent/25 bg-accent/[0.07] text-accent',
}

interface ServiceGridProps {
  activeServiceId: string
  onServiceClick: (serviceId: string) => void
}

export function ServiceGrid({ activeServiceId, onServiceClick }: ServiceGridProps) {
  return (
    <div className="space-y-5">
      <div className="relative overflow-hidden rounded-[1.75rem] border border-gold/20 bg-gradient-to-br from-gold/[0.12] via-card/70 to-cyan/[0.08] p-5">
        <div className="absolute -right-12 -top-12 h-32 w-32 rounded-full bg-gold/20 blur-3xl" />
        <div className="absolute -left-10 bottom-0 h-24 w-24 rounded-full bg-cyan/15 blur-3xl" />

        <div className="relative">
          <p className="text-[11px] uppercase tracking-[0.18em] text-gold">
            Инструменты
          </p>
          <h2 className="mt-2 font-serif text-2xl font-semibold text-foreground">
            Сервисы
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Быстрые инструменты для подготовки промптов, редактирования, анимации и поддержки.
          </p>
        </div>
      </div>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-serif text-lg text-foreground">Основные</h3>
          <span className="text-xs text-muted-foreground">4 сценария</span>
        </div>

        <div className="grid gap-3">
          {primaryServices.map((service, index) => {
            const Icon = service.icon
            const selected = activeServiceId === service.id

            return (
              <motion.button
                key={service.id}
                type="button"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.04 }}
                onClick={() => onServiceClick(service.id)}
                className={cn(
                  'group relative overflow-hidden rounded-[1.5rem] border p-4 text-left',
                  'transition-all duration-300 active:scale-[0.99]',
                  selected
                    ? 'border-gold/45 bg-card/80'
                    : 'border-border/55 bg-card/45 hover:border-border hover:bg-card/70'
                )}
              >
                <div className="flex items-start gap-4">
                  <div
                    className={cn(
                      'flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border',
                      toneClass[service.tone]
                    )}
                  >
                    <Icon className="h-5 w-5" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-serif text-lg leading-6 text-foreground">
                          {service.title}
                        </p>
                        <p className="mt-1 text-sm leading-5 text-muted-foreground">
                          {service.description}
                        </p>
                      </div>
                      <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-1 group-hover:text-gold" />
                    </div>

                    <span className="mt-3 inline-flex rounded-full border border-border/50 bg-background/45 px-3 py-1 text-[11px] text-muted-foreground">
                      {service.badge}
                    </span>
                  </div>
                </div>
              </motion.button>
            )
          })}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-serif text-lg text-foreground">Помощь и разделы</h3>

        <div className="rounded-[1.5rem] border border-border/55 bg-card/40">
          {secondaryServices.map((service, index) => {
            const Icon = service.icon

            return (
              <button
                key={service.id}
                type="button"
                onClick={() => onServiceClick(service.id)}
                className={cn(
                  'flex w-full items-center gap-3 px-4 py-4 text-left transition-colors hover:bg-secondary/30',
                  index !== secondaryServices.length - 1 && 'border-b border-border/45'
                )}
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border/50 bg-secondary/35">
                  <Icon className="h-4 w-4 text-muted-foreground" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground">{service.title}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{service.description}</p>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            )
          })}
        </div>
      </section>
    </div>
  )
}
