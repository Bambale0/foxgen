import type { Metadata } from 'next'
import Image from 'next/image'
import {
  ArrowRight,
  AudioLines,
  Check,
  ImageIcon,
  Layers3,
  Sparkles,
  Video,
  WandSparkles,
} from 'lucide-react'

import { BRAND_DESCRIPTION, BRAND_LOGO, BRAND_NAME, TELEGRAM_APP_URL } from '@/lib/brand'

export const metadata: Metadata = {
  title: `${BRAND_NAME} — AI-контент в Telegram`,
  description: BRAND_DESCRIPTION,
}

const capabilities = [
  {
    title: 'Фото',
    description: 'Создание и редактирование изображений по идее или референсу.',
    icon: ImageIcon,
  },
  {
    title: 'Видео',
    description: 'Генерация роликов из текста и фото в одном понятном сценарии.',
    icon: Video,
  },
  {
    title: 'Музыка',
    description: 'Треки и аудио без переходов между разными сервисами.',
    icon: AudioLines,
  },
  {
    title: 'AI-сервисы',
    description: 'Промпты, аватары, оживление фото и другие инструменты рядом.',
    icon: WandSparkles,
  },
]

const steps = [
  ['1', 'Выбери задачу', 'Фото, видео, музыка или готовый AI-инструмент.'],
  ['2', 'Опиши идею', 'Добавь промпт и, если нужно, загрузи референс.'],
  ['3', 'Получи результат', 'HappyFox ведёт генерацию до готового контента в Telegram.'],
]

const highlights = [
  'Фото и видео в одном интерфейсе',
  'Работа с референсами',
  'Готовые сценарии без лишних настроек',
]

const telegramLinkProps = {
  href: TELEGRAM_APP_URL,
  target: '_blank',
  rel: 'noreferrer',
} as const

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-background text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[38rem] bg-[radial-gradient(circle_at_50%_0%,rgba(255,106,0,0.18),transparent_58%)]"
      />

      <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-5 sm:px-6 lg:px-8">
        <a
          {...telegramLinkProps}
          className="flex items-center gap-3"
          aria-label={`${BRAND_NAME} — открыть приложение в Telegram`}
        >
          <span className="relative size-11 overflow-hidden rounded-2xl border border-border/70 bg-card shadow-[0_12px_40px_rgba(255,106,0,0.12)]">
            <Image src={BRAND_LOGO} alt="" fill priority sizes="44px" className="object-cover" />
          </span>
          <span>
            <span className="block font-serif text-xl font-semibold leading-none">{BRAND_NAME}</span>
            <span className="mt-1 block text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
              AI creation studio
            </span>
          </span>
        </a>

        <nav className="hidden items-center gap-7 text-sm text-muted-foreground md:flex" aria-label="Основная навигация">
          <a href="#features" className="transition-colors hover:text-foreground">Возможности</a>
          <a href="#how" className="transition-colors hover:text-foreground">Как работает</a>
        </nav>

        <a
          {...telegramLinkProps}
          className="inline-flex min-h-10 items-center justify-center rounded-xl border border-primary/35 bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-[0_10px_30px_rgba(255,106,0,0.18)] transition-transform hover:-translate-y-0.5"
        >
          Открыть
          <ArrowRight className="ml-2 size-4" aria-hidden="true" />
        </a>
      </header>

      <section className="relative z-10 mx-auto grid w-full max-w-6xl gap-12 px-4 pb-20 pt-12 sm:px-6 sm:pt-20 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:px-8 lg:pb-28 lg:pt-24">
        <div className="max-w-2xl">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary">
            <Sparkles className="size-3.5" aria-hidden="true" />
            Всё для AI-контента в одном месте
          </div>

          <h1 className="max-w-3xl font-serif text-5xl font-semibold leading-[0.98] tracking-[-0.045em] sm:text-6xl lg:text-7xl">
            Фото, видео и музыка —
            <span className="text-primary"> в одном HappyFox</span>
          </h1>

          <p className="mt-6 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
            Опиши идею, добавь референс и выбери сценарий. HappyFox соберёт генерацию без лишних интерфейсов и вернёт готовый результат прямо в Telegram.
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <a
              {...telegramLinkProps}
              className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-primary px-6 font-semibold text-primary-foreground shadow-[0_16px_50px_rgba(255,106,0,0.22)] transition-transform hover:-translate-y-0.5"
            >
              Открыть HappyFox
              <ArrowRight className="ml-2 size-4" aria-hidden="true" />
            </a>
            <a
              href="#features"
              className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-border bg-card/70 px-6 font-medium text-foreground backdrop-blur transition-colors hover:border-primary/35"
            >
              Посмотреть возможности
            </a>
          </div>

          <ul className="mt-7 grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
            {highlights.map((item) => (
              <li key={item} className="flex items-center gap-2">
                <span className="grid size-5 shrink-0 place-items-center rounded-full bg-primary/12 text-primary">
                  <Check className="size-3" aria-hidden="true" />
                </span>
                {item}
              </li>
            ))}
          </ul>
        </div>

        <div className="relative mx-auto w-full max-w-[31rem] lg:justify-self-end">
          <div aria-hidden="true" className="absolute -inset-8 rounded-[3rem] bg-primary/10 blur-3xl" />
          <a
            {...telegramLinkProps}
            aria-label="Открыть HappyFox в Telegram из демо"
            className="relative block rounded-[2rem] border border-border/70 bg-card/80 p-3 shadow-[0_28px_90px_rgba(0,0,0,0.45)] backdrop-blur-xl transition-transform hover:-translate-y-1"
          >
            <div className="rounded-[1.55rem] border border-border/60 bg-background/90 p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="relative size-9 overflow-hidden rounded-xl border border-border/70">
                    <Image src={BRAND_LOGO} alt="" fill sizes="36px" className="object-cover" />
                  </span>
                  <div>
                    <p className="font-serif font-semibold">{BRAND_NAME}</p>
                    <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Студия</p>
                  </div>
                </div>
                <span className="rounded-full border border-primary/25 bg-primary/10 px-2.5 py-1 text-[10px] font-semibold text-primary">AI</span>
              </div>

              <div className="mt-5 grid grid-cols-3 gap-2 rounded-2xl border border-border/60 bg-card/60 p-1.5 text-center text-xs">
                <span className="rounded-xl bg-primary px-3 py-2 font-semibold text-primary-foreground">Фото</span>
                <span className="rounded-xl px-3 py-2 text-muted-foreground">Видео</span>
                <span className="rounded-xl px-3 py-2 text-muted-foreground">Сервисы</span>
              </div>

              <div className="mt-3 rounded-2xl border border-border/70 bg-card/70 p-4">
                <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <Layers3 className="size-3.5 text-primary" aria-hidden="true" />
                  Новая генерация
                </div>
                <div className="mt-3 min-h-24 rounded-xl border border-border/70 bg-background/70 p-3 text-sm leading-6 text-foreground/90">
                  Кинематографичный портрет в мягком вечернем свете, детальная фактура, естественные цвета…
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-xl border border-border/60 bg-background/55 p-3">
                    <p className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Формат</p>
                    <p className="mt-1 text-sm font-medium">4:5</p>
                  </div>
                  <div className="rounded-xl border border-border/60 bg-background/55 p-3">
                    <p className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Качество</p>
                    <p className="mt-1 text-sm font-medium">Высокое</p>
                  </div>
                </div>
                <div className="mt-3 flex min-h-11 items-center justify-center rounded-xl bg-primary font-semibold text-primary-foreground shadow-[0_10px_30px_rgba(255,106,0,0.16)]">
                  <Sparkles className="mr-2 size-4" aria-hidden="true" />
                  Создать
                </div>
              </div>
            </div>
          </a>
        </div>
      </section>

      <section id="features" className="relative z-10 border-y border-border/60 bg-card/25">
        <div className="mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 lg:px-8 lg:py-24">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Возможности</p>
            <h2 className="mt-3 font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">От идеи до готового контента</h2>
            <p className="mt-4 text-base leading-7 text-muted-foreground">Один знакомый интерфейс вместо набора отдельных AI-сервисов.</p>
          </div>

          <div className="mt-10 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {capabilities.map(({ title, description, icon: Icon }) => (
              <article key={title} className="group rounded-[1.5rem] border border-border/65 bg-background/65 p-5 shadow-sm backdrop-blur transition-colors hover:border-primary/35">
                <span className="grid size-11 place-items-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <h3 className="mt-6 font-serif text-2xl font-semibold">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="how" className="relative z-10 mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <div className="grid gap-12 lg:grid-cols-[0.8fr_1.2fr] lg:items-start">
          <div className="max-w-xl">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Как это работает</p>
            <h2 className="mt-3 font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">Три шага — и можно создавать</h2>
            <p className="mt-4 text-base leading-7 text-muted-foreground">HappyFox оставляет сложность моделей внутри и показывает только то, что нужно для результата.</p>
          </div>

          <ol className="grid gap-3">
            {steps.map(([number, title, description]) => (
              <li key={number} className="grid grid-cols-[auto_1fr] gap-4 rounded-[1.5rem] border border-border/65 bg-card/55 p-5">
                <span className="grid size-10 place-items-center rounded-2xl bg-primary text-sm font-bold text-primary-foreground">{number}</span>
                <div>
                  <h3 className="font-serif text-xl font-semibold">{title}</h3>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="relative z-10 mx-auto w-full max-w-6xl px-4 pb-20 sm:px-6 lg:px-8 lg:pb-28">
        <div className="overflow-hidden rounded-[2rem] border border-primary/25 bg-[linear-gradient(135deg,rgba(255,106,0,0.15),rgba(20,20,20,0.88)_52%,rgba(255,106,0,0.06))] p-6 sm:p-10 lg:p-12">
          <div className="grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
            <div className="max-w-2xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">HappyFox</p>
              <h2 className="mt-3 font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">Твоя AI-студия уже внутри Telegram</h2>
              <p className="mt-4 max-w-xl text-base leading-7 text-muted-foreground">Открой HappyFox, выбери нужный сценарий и переходи сразу к созданию.</p>
            </div>
            <a
              {...telegramLinkProps}
              className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-primary px-6 font-semibold text-primary-foreground shadow-[0_16px_50px_rgba(255,106,0,0.22)] transition-transform hover:-translate-y-0.5"
            >
              Открыть HappyFox
              <ArrowRight className="ml-2 size-4" aria-hidden="true" />
            </a>
          </div>
        </div>
      </section>

      <footer className="relative z-10 border-t border-border/60">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-4 py-7 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
          <span className="font-serif text-base font-semibold text-foreground">{BRAND_NAME}</span>
          <span>Создание фото, видео и AI-контента в Telegram</span>
        </div>
      </footer>
    </main>
  )
}
