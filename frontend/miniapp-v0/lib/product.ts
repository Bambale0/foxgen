export type ProductId = 'happyfox'

type ProductConfig = {
  id: ProductId
  brandName: string
  brandDescription: string
  brandLogo: string
  brandIcon: string
}

const MINIAPP_BASE_PATH = String(process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH || '/mini-app')
  .trim()
  .replace(/\/$/, '')

const HAPPYFOX_PRODUCT: ProductConfig = {
  id: 'happyfox',
  brandName: 'HappyFox',
  brandDescription: 'HappyFox — создание фото, видео и AI-контента в Telegram',
  brandLogo: `${MINIAPP_BASE_PATH}/happyfox-logo.webp`,
  brandIcon: `${MINIAPP_BASE_PATH}/happyfox-icon-512.png`,
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
