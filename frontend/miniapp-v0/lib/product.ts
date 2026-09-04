export type ProductId = 'happyfox'

type ProductConfig = {
  id: ProductId
  brandName: string
  brandDescription: string
  brandLogo: string
  siteLogo: string
  telegramAppUrl: string
}

const MINIAPP_BASE_PATH = String(process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH || '/mini-app')
  .trim()
  .replace(/\/$/, '')

const TELEGRAM_BOT_USERNAME = String(
  process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || 'AlePolbot',
)
  .trim()
  .replace(/^@/, '')

if (!/^[A-Za-z0-9_]+$/.test(TELEGRAM_BOT_USERNAME)) {
  throw new Error('NEXT_PUBLIC_TELEGRAM_BOT_USERNAME must be a valid Telegram bot username')
}

const HAPPYFOX_PRODUCT: ProductConfig = {
  id: 'happyfox',
  brandName: 'HappyFox',
  brandDescription: 'HappyFox — создание фото, видео и AI-контента в Telegram',
  brandLogo: `${MINIAPP_BASE_PATH}/happyfox-icon.webp`,
  siteLogo: `${MINIAPP_BASE_PATH}/happyfox-brand.webp`,
  telegramAppUrl: `https://t.me/${TELEGRAM_BOT_USERNAME}?startapp`,
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
