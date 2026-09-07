import type { MetadataRoute } from 'next'

import { BRAND_PUBLIC_SITE_URL } from '@/lib/brand'

export const dynamic = 'force-static'

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: `${BRAND_PUBLIC_SITE_URL}/`,
      changeFrequency: 'weekly',
      priority: 1,
    },
  ]
}
