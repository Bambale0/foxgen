export type ProductId = 'happyfox'

type ProductConfig = {
  id: ProductId
  brandName: string
  brandDescription: string
  brandLogo: string
}

const HAPPYFOX_PRODUCT: ProductConfig = {
  id: 'happyfox',
  brandName: 'HappyFox',
  brandDescription: 'HappyFox — создание фото, видео и AI-контента в Telegram',
  brandLogo: '/happyfox-logo.webp',
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
