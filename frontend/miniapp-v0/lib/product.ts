export type ProductId = 'happyfox'

type ProductConfig = {
  id: ProductId
  brandName: string
  brandDescription: string
  brandLogo: string
  siteLogo: string
  publicSiteUrl: string
  telegramAppUrl: string
  telegramChannelUrl: string
  instagramUrl: string
}

export const MINIAPP_BASE_PATH = String(process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH || '/mini-app')
  .trim()
  .replace(/\/$/, '')

export const TELEGRAM_BOT_USERNAME = String(
  process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || 'AlePolbot',
)
  .trim()
  .replace(/^@/, '')

const TELEGRAM_CHANNEL_USERNAME = String(
  process.env.NEXT_PUBLIC_TELEGRAM_CHANNEL_USERNAME || 'PolyakovaAll',
)
  .trim()
  .replace(/^@/, '')

const INSTAGRAM_USERNAME = String(
  process.env.NEXT_PUBLIC_INSTAGRAM_USERNAME || 'polyakovaall',
)
  .trim()
  .replace(/^@/, '')

export const TELEGRAM_START_PARAM = String(
  process.env.NEXT_PUBLIC_TELEGRAM_START_PARAM || 'ref_M9SHFF25',
).trim()

const PUBLIC_SITE_URL = String(
  process.env.NEXT_PUBLIC_PUBLIC_SITE_URL || 'https://happy-fox.online',
)
  .trim()
  .replace(/\/+$/, '')

if (!/^[A-Za-z0-9_]+$/.test(TELEGRAM_BOT_USERNAME)) {
  throw new Error('NEXT_PUBLIC_TELEGRAM_BOT_USERNAME must be a valid Telegram bot username')
}

if (!/^[A-Za-z0-9_]+$/.test(TELEGRAM_CHANNEL_USERNAME)) {
  throw new Error('NEXT_PUBLIC_TELEGRAM_CHANNEL_USERNAME must be a valid Telegram username')
}

if (!/^[A-Za-z0-9._]+$/.test(INSTAGRAM_USERNAME)) {
  throw new Error('NEXT_PUBLIC_INSTAGRAM_USERNAME must be a valid Instagram username')
}

if (!/^[A-Za-z0-9_-]{1,64}$/.test(TELEGRAM_START_PARAM)) {
  throw new Error('NEXT_PUBLIC_TELEGRAM_START_PARAM must be a valid Telegram start parameter')
}

try {
  const url = new URL(PUBLIC_SITE_URL)
  if (url.protocol !== 'https:') {
    throw new Error('PUBLIC_SITE_URL must use https')
  }
} catch (error) {
  throw new Error('NEXT_PUBLIC_PUBLIC_SITE_URL must be a valid https URL', { cause: error })
}

const HAPPYFOX_PRODUCT: ProductConfig = {
  id: 'happyfox',
  brandName: 'HappyFox',
  brandDescription:
    'HappyFox — AI-студия в Telegram для генерации и редактирования фото, видео, музыки и другого контента с помощью нейросетей.',
  brandLogo: `${MINIAPP_BASE_PATH}/happyfox-brand.webp`,
  siteLogo: `${MINIAPP_BASE_PATH}/happyfox-brand.webp`,
  publicSiteUrl: PUBLIC_SITE_URL,
  telegramAppUrl: `https://t.me/${TELEGRAM_BOT_USERNAME}?start=${encodeURIComponent(TELEGRAM_START_PARAM)}`,
  telegramChannelUrl: `https://t.me/${TELEGRAM_CHANNEL_USERNAME}`,
  instagramUrl: `https://www.instagram.com/${INSTAGRAM_USERNAME}/`,
}

function resolveProductId(): ProductId {
  const configured = String(process.env.NEXT_PUBLIC_PRODUCT_ID || 'happyfox').trim().toLowerCase()
  if (configured !== 'happyfox') {
    throw new Error(
      `Unsupported NEXT_PUBLIC_PRODUCT_ID=${configured}; Bambale0/foxgen is HappyFox-only`,
    )
  }
  return 'happyfox'
}

resolveProductId()
export const PRODUCT = HAPPYFOX_PRODUCT
