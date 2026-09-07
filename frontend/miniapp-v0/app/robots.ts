import type { MetadataRoute } from 'next'

import { BRAND_PUBLIC_SITE_URL } from '@/lib/brand'

export const dynamic = 'force-static'

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: ['/mini-app/api/', '/mini-app/landing/'],
      },
    ],
    sitemap: `${BRAND_PUBLIC_SITE_URL}/sitemap.xml`,
    host: BRAND_PUBLIC_SITE_URL,
  }
}
