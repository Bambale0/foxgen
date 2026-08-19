export type ProductId = 'happyfox' | 'neuromix'

type ProductConfig = {
  id: ProductId
  brandName: string
  brandDescription: string
  brandLogo: string
}

const PRODUCTS: Record<ProductId, ProductConfig> = {
  happyfox: {
    id: 'happyfox',
    brandName: 'HappyFox',
    brandDescription: 'HappyFox — создание фото, видео и AI-контента в Telegram',
    brandLogo: '/happyfox-logo.webp',
  },
  neuromix: {
    id: 'neuromix',
    brandName: 'NEUROMIX',
    brandDescription: 'NEUROMIX — студия генерации фото и видео с помощью AI',
    brandLogo: '/icon.svg',
  },
}

function resolveProductId(): ProductId {
  const configured = String(process.env.NEXT_PUBLIC_PRODUCT_ID || 'happyfox').trim().toLowerCase()
  if (configured === 'neuromix' || configured === 'happyfox') return configured
  throw new Error(`Unsupported NEXT_PUBLIC_PRODUCT_ID=${configured}`)
}

export const PRODUCT = PRODUCTS[resolveProductId()]
