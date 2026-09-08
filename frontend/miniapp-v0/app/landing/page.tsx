import type { Metadata } from 'next'
import Image from 'next/image'
import {
  ArrowRight,
  AudioLines,
  Check,
  Image as ImageGlyph,
  Layers3,
  Sparkles,
  Video,
  WandSparkles,
} from 'lucide-react'

import {
  BRAND_DESCRIPTION,
  BRAND_LOGO,
  BRAND_NAME,
  BRAND_PUBLIC_SITE_URL,
  BRAND_SITE_LOGO,
  INSTAGRAM_URL,
  TELEGRAM_APP_URL,
  TELEGRAM_CHANNEL_URL,
} from '@/lib/brand'
import { ReferralAwareLink } from '@/components/landing-referral-link'

const SEO_TITLE = 'HappyFox — нейросеть для фото, видео и музыки в Telegram'
const SEO_DESCRIPTION =
  'Создавайте и редактируйте фото, оживляйте изображения, генерируйте видео и музыку с AI прямо в Telegram. HappyFox объединяет нейросети в одном понятном боте.'

export const metadata: Metadata = {
  metadataBase: new URL(BRAND_PUBLIC_SITE_URL),
  title: SEO_TITLE,
  description: SEO_DESCRIPTION,
  applicationName: BRAND_NAME,
  category: 'technology',
  alternates: {
    canonical: '/',
  },
  keywords: [
    'нейросеть для фото',
    'генерация видео из фото',
    'AI фотосессия',
    'редактирование фото нейросетью',
    'создать видео нейросетью',
    'нейросеть Telegram',
    'AI бот Telegram',
    'генерация музыки AI',
    'партнёрская программа нейросети',
  ],
  openGraph: {
    type: 'website',
    locale: 'ru_RU',
    url: '/',
    siteName: BRAND_NAME,
    title: SEO_TITLE,
    description: SEO_DESCRIPTION,
    images: [
      {
        url: BRAND_SITE_LOGO,
        alt: `${BRAND_NAME} — AI-студия в Telegram`,
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: SEO_TITLE,
    description: SEO_DESCRIPTION,
    images: [BRAND_SITE_LOGO],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-image-preview': 'large',
      'max-snippet': -1,
      'max-video-preview': -1,
    },
  },
}

const capabilities = [
  {
    title: 'Фото',
    description: 'Нейрофотосессии, замена фона, образа и деталей, генерация и редактирование по референсу.',
    icon: ImageGlyph,
  },
  {
    title: 'Видео',
    description: 'Видео по тексту или фото: от короткой анимации до полноценного AI-ролика.',
    icon: Video,
  },
  {
    title: 'Музыка',
    description: 'Создание треков и аудио без переходов между разными сервисами.',
    icon: AudioLines,
  },
  {
    title: 'AI-инструменты',
    description: 'Промпты, оживление фото, аватары и другие готовые сценарии в одном интерфейсе.',
    icon: WandSparkles,
  },
]

const scenarios = [
  {
    eyebrow: 'AI-фотосессия',
    title: 'Новый образ из обычного фото',
    description: 'Загрузите снимок и получите серию изображений в нужном стиле без студии и сложного промптинга.',
  },
  {
    eyebrow: 'Редактирование фото',
    title: 'Изменить волосы, одежду или фон',
    description: 'Напишите, что поменять: например, сделать волосы светлыми, заменить образ или перенести сцену в другое место.',
  },
  {
    eyebrow: 'Фото → видео',
    title: 'Оживить изображение',
    description: 'Добавьте движение, атмосферу и камеру. HappyFox проведёт фото через подходящий видео-сценарий.',
  },
  {
    eyebrow: 'Текст → видео',
    title: 'Создать ролик с нуля',
    description: 'Опишите сцену обычными словами и получите AI-видео без монтажа в нескольких приложениях.',
  },
]

const steps = [
  ['1', 'Выберите задачу', 'Фото, видео, музыка или готовый AI-инструмент.'],
  ['2', 'Опишите результат', 'Напишите идею и при необходимости добавьте своё фото или референс.'],
  ['3', 'Получите готовый файл', 'HappyFox ведёт генерацию до результата и возвращает его прямо в Telegram.'],
]

const highlights = [
  'Всё работает прямо в Telegram',
  'Можно загружать свои фото и референсы',
  'Понятные сценарии вместо десятка настроек',
]

const partnerBenefits = [
  {
    number: '01',
    title: 'Персональная ссылка',
    description: 'Делитесь HappyFox в канале, соцсетях, сообществе или напрямую со своей аудиторией.',
  },
  {
    number: '02',
    title: 'Два уровня вознаграждений',
    description: 'Начисления учитывают покупки ваших приглашённых пользователей и рефералов второго уровня.',
  },
  {
    number: '03',
    title: 'Статистика и выплаты',
    description: 'В партнёрском кабинете видны приглашения, начисления, доступный баланс и статус выплат.',
  },
]

const PARTNER_PROGRAM_URL = `${BRAND_PUBLIC_SITE_URL}/#partners`

const externalLinkProps = {
  target: '_blank',
  rel: 'noopener noreferrer',
} as const

function TelegramBrandIcon({ className = 'size-5' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      data-brand-icon="telegram"
      fill="currentColor"
    >
      <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.3-.07-.45-.52-.17l-9.5 5.98-4.1-1.32c-.88-.25-.9-.86.2-1.3L19.8 4.54c.73-.33 1.43.18 1.15 1.3l-2.72 12.8c-.19.91-.74 1.13-1.5.7l-4.14-3.05-2 1.93c-.23.23-.42.42-.81.42Z" />
    </svg>
  )
}

function InstagramBrandIcon({ className = 'size-5' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      data-brand-icon="instagram"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.4" cy="6.6" r="1" fill="currentColor" stroke="none" />
    </svg>
  )
}

const structuredData = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'WebSite',
      '@id': `${BRAND_PUBLIC_SITE_URL}/#website`,
      url: `${BRAND_PUBLIC_SITE_URL}/`,
      name: BRAND_NAME,
      description: SEO_DESCRIPTION,
      inLanguage: 'ru-RU',
    },
    {
      '@type': 'SoftwareApplication',
      '@id': `${BRAND_PUBLIC_SITE_URL}/#app`,
      name: BRAND_NAME,
      description: BRAND_DESCRIPTION,
      url: `${BRAND_PUBLIC_SITE_URL}/`,
      applicationCategory: 'MultimediaApplication',
      operatingSystem: 'Telegram',
      image: `${BRAND_PUBLIC_SITE_URL}${BRAND_SITE_LOGO}`,
      sameAs: [TELEGRAM_CHANNEL_URL, INSTAGRAM_URL],
      potentialAction: {
        '@type': 'UseAction',
        target: TELEGRAM_APP_URL,
      },
    },
  ],
}

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-background text-foreground">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(structuredData).replace(/</g, '\\u003c'),
        }}
      />

      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[42rem] bg-[radial-gradient(circle_at_50%_0%,rgba(255,106,0,0.2),transparent_58%)]"
      />

      <header className="relative z-10 mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-5 sm:px-6 lg:flex-nowrap lg:px-8">
        <ReferralAwareLink
          kind="bot"
          className="flex items-center gap-3"
          aria-label={`${BRAND_NAME} — открыть бота в Telegram`}
        >
          <span className="relative h-20 w-20 shrink-0 sm:h-24 sm:w-24">
            <Image
              src={BRAND_SITE_LOGO}
              alt={`${BRAND_NAME} — AI-студия в Telegram`}
              fill
              priority
              sizes="(min-width: 640px) 96px, 80px"
              className="object-contain"
            />
          </span>
        </ReferralAwareLink>

        <nav className="hidden items-center gap-7 text-sm text-muted-foreground lg:flex" aria-label="Основная навигация">
          <a href="#scenarios" className="transition-colors hover:text-foreground">Сценарии</a>
          <a href="#features" className="transition-colors hover:text-foreground">Возможности</a>
          <a href="#how" className="transition-colors hover:text-foreground">Как работает</a>
          <a href="#examples" className="transition-colors hover:text-foreground">Примеры</a>
          <a href="#partners" className="font-semibold text-primary transition-colors hover:text-primary/80">Партнёрам</a>
        </nav>

        <div className="order-3 flex w-full items-center gap-2 sm:order-none sm:w-auto">
          <ReferralAwareLink
            kind="bot"
            className="inline-flex min-h-10 flex-1 items-center justify-center rounded-xl border border-[#229ED9]/45 bg-card/70 px-3 text-xs font-semibold text-foreground transition-colors hover:border-[#229ED9]/70 hover:bg-[#229ED9]/10 sm:flex-none sm:px-4 sm:text-sm"
          >
            <TelegramBrandIcon className="mr-2 size-4 text-[#229ED9]" />
            Попробовать ТГ
          </ReferralAwareLink>
          <ReferralAwareLink
            kind="web"
            className="inline-flex min-h-10 flex-1 items-center justify-center rounded-xl border border-primary/35 bg-primary px-3 text-xs font-semibold text-primary-foreground shadow-[0_10px_30px_rgba(255,106,0,0.18)] transition-transform hover:-translate-y-0.5 sm:flex-none sm:px-4 sm:text-sm"
          >
            <Sparkles className="mr-2 size-4" aria-hidden="true" />
            Попробовать на сайте
          </ReferralAwareLink>
        </div>
      </header>

      <section className="relative z-10 mx-auto grid w-full max-w-6xl gap-12 px-4 pb-20 pt-12 sm:px-6 sm:pt-20 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:px-8 lg:pb-28 lg:pt-24">
        <div className="max-w-2xl">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary">
            <Sparkles className="size-3.5" aria-hidden="true" />
            AI-студия прямо в Telegram
          </div>

          <h1 className="max-w-3xl font-serif text-5xl font-semibold leading-[0.98] tracking-[-0.045em] sm:text-6xl lg:text-7xl">
            Создавайте фото и видео
            <span className="text-primary"> нейросетями без десятка сервисов</span>
          </h1>

          <p className="mt-6 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
            Нейрофотосессии, редактирование фото, оживление изображений, AI-видео и музыка — в одном понятном боте. Опишите идею обычными словами и получите результат в Telegram.
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <ReferralAwareLink
              kind="bot"
              className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-primary px-6 font-semibold text-primary-foreground shadow-[0_16px_50px_rgba(255,106,0,0.22)] transition-transform hover:-translate-y-0.5"
            >
              <TelegramBrandIcon className="mr-2 size-5" />
              Создать в Telegram
              <ArrowRight className="ml-2 size-4" aria-hidden="true" />
            </ReferralAwareLink>
            <a
              href={INSTAGRAM_URL}
              {...externalLinkProps}
              className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-border bg-card/70 px-6 font-medium text-foreground backdrop-blur transition-colors hover:border-primary/35"
            >
              Смотреть работы
              <InstagramBrandIcon className="ml-2 size-5" />
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
          <ReferralAwareLink
            kind="web"
            aria-label="Попробовать HappyFox на сайте из демо"
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
                    <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">AI-студия</p>
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
                  Редактирование по фото
                </div>
                <div className="mt-3 min-h-24 rounded-xl border border-border/70 bg-background/70 p-3 text-sm leading-6 text-foreground/90">
                  Сделай волосы светлыми, сохрани лицо, естественный свет и реалистичную текстуру фотографии.
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-xl border border-border/60 bg-background/55 p-3">
                    <p className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Референс</p>
                    <p className="mt-1 text-sm font-medium">1 фото</p>
                  </div>
                  <div className="rounded-xl border border-border/60 bg-background/55 p-3">
                    <p className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Результат</p>
                    <p className="mt-1 text-sm font-medium">Высокое качество</p>
                  </div>
                </div>
                <div className="mt-3 flex min-h-11 items-center justify-center rounded-xl bg-primary font-semibold text-primary-foreground shadow-[0_10px_30px_rgba(255,106,0,0.16)]">
                  <Sparkles className="mr-2 size-4" aria-hidden="true" />
                  Создать
                </div>
              </div>
            </div>
          </ReferralAwareLink>
        </div>
      </section>

      <section id="scenarios" className="relative z-10 border-y border-border/60 bg-card/25">
        <div className="mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 lg:px-8 lg:py-24">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Что можно сделать</p>
            <h2 className="mt-3 font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">Начните с результата, а не с выбора модели</h2>
            <p className="mt-4 text-base leading-7 text-muted-foreground">
              Выберите понятный сценарий. HappyFox сам оставляет техническую сложность нейросетей внутри.
            </p>
          </div>

          <div className="mt-10 grid gap-3 md:grid-cols-2">
            {scenarios.map(({ eyebrow, title, description }) => (
              <article key={title} className="rounded-[1.5rem] border border-border/65 bg-background/65 p-6 shadow-sm backdrop-blur transition-colors hover:border-primary/35">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">{eyebrow}</p>
                <h3 className="mt-3 font-serif text-2xl font-semibold sm:text-3xl">{title}</h3>
                <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="features" className="relative z-10 mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Возможности</p>
          <h2 className="mt-3 font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">Одна AI-студия для разного контента</h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">Не нужно регистрироваться в нескольких нейросервисах и заново разбираться в каждом интерфейсе.</p>
        </div>

        <div className="mt-10 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {capabilities.map(({ title, description, icon: Icon }) => (
            <article key={title} className="group rounded-[1.5rem] border border-border/65 bg-card/55 p-5 shadow-sm backdrop-blur transition-colors hover:border-primary/35">
              <span className="grid size-11 place-items-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
                <Icon className="size-5" aria-hidden="true" />
              </span>
              <h3 className="mt-6 font-serif text-2xl font-semibold">{title}</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="how" className="relative z-10 border-y border-border/60 bg-card/25">
        <div className="mx-auto grid w-full max-w-6xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[0.8fr_1.2fr] lg:items-start lg:px-8 lg:py-24">
          <div className="max-w-xl">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Как это работает</p>
            <h2 className="mt-3 font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">Три шага до готового результата</h2>
            <p className="mt-4 text-base leading-7 text-muted-foreground">Обычный Telegram, понятные действия и минимум технических терминов.</p>
          </div>

          <ol className="grid gap-3">
            {steps.map(([number, title, description]) => (
              <li key={number} className="grid grid-cols-[auto_1fr] gap-4 rounded-[1.5rem] border border-border/65 bg-background/65 p-5">
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

      <section id="partners" className="relative z-10 mx-auto w-full max-w-6xl scroll-mt-6 px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <div className="overflow-hidden rounded-[2rem] border border-primary/30 bg-[linear-gradient(135deg,rgba(255,106,0,0.18),rgba(20,20,20,0.92)_48%,rgba(255,106,0,0.08))] p-6 shadow-[0_28px_90px_rgba(0,0,0,0.28)] sm:p-10 lg:p-12">
          <div className="grid gap-10 lg:grid-cols-[0.95fr_1.05fr] lg:items-start">
            <div className="max-w-xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Партнёрская программа</p>
              <h2 className="mt-3 font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">Зарабатывайте вместе с HappyFox</h2>
              <p className="mt-4 text-base leading-7 text-muted-foreground">
                Для авторов, каналов, сообществ и тех, кто рекомендует полезные AI-инструменты. Делитесь своей персональной ссылкой и получайте вознаграждение с покупок приглашённых пользователей.
              </p>
              <p className="mt-4 text-sm leading-6 text-foreground/85">
                После заявки и ручного одобрения откроются активная реферальная ссылка, статистика и выплаты.
              </p>

              <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:items-center">
                <ReferralAwareLink
                  kind="bot"
                  className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-primary px-6 font-semibold text-primary-foreground shadow-[0_16px_50px_rgba(255,106,0,0.22)] transition-transform hover:-translate-y-0.5"
                >
                  <TelegramBrandIcon className="mr-2 size-5" />
                  Открыть HappyFox
                  <ArrowRight className="ml-2 size-4" aria-hidden="true" />
                </ReferralAwareLink>
                <a
                  href={PARTNER_PROGRAM_URL}
                  data-partner-program-link="share"
                  className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-border/70 bg-background/55 px-5 text-sm font-medium text-foreground transition-colors hover:border-primary/40"
                >
                  Ссылка на программу
                </a>
              </div>

              <p className="mt-4 text-xs leading-5 text-muted-foreground">
                В Mini App откройте раздел «Партнёры» и отправьте заявку на активацию.
              </p>
              <p className="mt-3 break-all text-xs text-primary/90">happy-fox.online/#partners</p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
              {partnerBenefits.map(({ number, title, description }) => (
                <article key={number} className="rounded-[1.5rem] border border-border/65 bg-background/65 p-5 backdrop-blur">
                  <div className="flex items-start gap-4">
                    <span className="grid size-10 shrink-0 place-items-center rounded-2xl border border-primary/25 bg-primary/10 text-xs font-bold text-primary">
                      {number}
                    </span>
                    <div>
                      <h3 className="font-serif text-xl font-semibold">{title}</h3>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="examples" className="relative z-10 mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <div className="overflow-hidden rounded-[2rem] border border-primary/25 bg-[linear-gradient(135deg,rgba(255,106,0,0.15),rgba(20,20,20,0.88)_52%,rgba(255,106,0,0.06))] p-6 sm:p-10 lg:p-12">
          <div className="grid gap-8 lg:grid-cols-[1fr_0.8fr] lg:items-end">
            <div className="max-w-2xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Работы и идеи</p>
              <h2 className="mt-3 font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">Посмотрите, что можно сделать с HappyFox</h2>
              <p className="mt-4 max-w-xl text-base leading-7 text-muted-foreground">
                В Instagram публикуем примеры готовых работ и визуальные сценарии. В Telegram собрана база промптов, которые можно брать за основу и адаптировать под свои задачи.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
              <a
                href={TELEGRAM_CHANNEL_URL}
                {...externalLinkProps}
                className="group flex min-h-20 items-center justify-between rounded-2xl border border-border/70 bg-background/70 px-5 py-4 transition-colors hover:border-primary/40"
              >
                <span className="flex items-center gap-4">
                  <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-[#229ED9] text-white shadow-sm">
                    <TelegramBrandIcon className="size-7" />
                  </span>
                  <span>
                    <span className="block text-xs text-muted-foreground">Telegram</span>
                    <span className="mt-1 block font-semibold text-foreground">База промптов</span>
                  </span>
                </span>
                <ArrowRight className="size-5 text-primary transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </a>
              <a
                href={INSTAGRAM_URL}
                {...externalLinkProps}
                className="group flex min-h-20 items-center justify-between rounded-2xl border border-border/70 bg-background/70 px-5 py-4 transition-colors hover:border-primary/40"
              >
                <span className="flex items-center gap-4">
                  <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-[radial-gradient(circle_at_30%_107%,#fdf497_0%,#fdf497_5%,#fd5949_45%,#d6249f_60%,#285AEB_90%)] text-white shadow-sm">
                    <InstagramBrandIcon className="size-7" />
                  </span>
                  <span>
                    <span className="block text-xs text-muted-foreground">Instagram</span>
                    <span className="mt-1 block font-semibold text-foreground">Примеры работ</span>
                  </span>
                </span>
                <ArrowRight className="size-5 text-primary transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </a>
            </div>
          </div>
        </div>
      </section>

      <section className="relative z-10 mx-auto w-full max-w-6xl px-4 pb-20 sm:px-6 lg:px-8 lg:pb-28">
        <div className="rounded-[2rem] border border-border/70 bg-card/55 p-6 text-center sm:p-10 lg:p-12">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Начать</p>
          <h2 className="mx-auto mt-3 max-w-3xl font-serif text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">Есть идея или фото? Отправьте его HappyFox</h2>
          <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-muted-foreground">Откройте бота, выберите нужный сценарий и переходите сразу к созданию.</p>
          <ReferralAwareLink
            kind="bot"
            className="mt-7 inline-flex min-h-12 items-center justify-center rounded-2xl bg-primary px-7 font-semibold text-primary-foreground shadow-[0_16px_50px_rgba(255,106,0,0.22)] transition-transform hover:-translate-y-0.5"
          >
            <TelegramBrandIcon className="mr-2 size-5" />
            Открыть HappyFox в Telegram
            <ArrowRight className="ml-2 size-4" aria-hidden="true" />
          </ReferralAwareLink>
        </div>
      </section>

      <footer className="relative z-10 border-t border-border/60">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-7 text-sm text-muted-foreground sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div>
            <span className="font-serif text-base font-semibold text-foreground">{BRAND_NAME}</span>
            <span className="ml-3 hidden sm:inline">AI-студия для фото, видео и музыки в Telegram</span>
          </div>
          <nav className="flex flex-wrap gap-x-5 gap-y-3" aria-label="Социальные ссылки">
            <a href="#partners" className="inline-flex items-center gap-2 font-medium text-primary transition-colors hover:text-primary/80">
              Партнёрам
            </a>
            <ReferralAwareLink kind="bot" className="inline-flex items-center gap-2 transition-colors hover:text-foreground">
              <span className="grid size-7 place-items-center rounded-lg bg-[#229ED9] text-white"><TelegramBrandIcon className="size-4" /></span>
              Telegram-бот
            </ReferralAwareLink>
            <a href={TELEGRAM_CHANNEL_URL} {...externalLinkProps} className="inline-flex items-center gap-2 transition-colors hover:text-foreground">
              <span className="grid size-7 place-items-center rounded-lg bg-[#229ED9] text-white"><TelegramBrandIcon className="size-4" /></span>
              База промптов
            </a>
            <a href={INSTAGRAM_URL} {...externalLinkProps} className="inline-flex items-center gap-2 transition-colors hover:text-foreground">
              <span className="grid size-7 place-items-center rounded-lg bg-[radial-gradient(circle_at_30%_107%,#fdf497_0%,#fd5949_45%,#d6249f_60%,#285AEB_90%)] text-white"><InstagramBrandIcon className="size-4" /></span>
              Instagram
            </a>
          </nav>
        </div>
      </footer>
    </main>
  )
}
