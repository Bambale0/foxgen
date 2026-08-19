/** @type {import('next').NextConfig} */
const exportMode = process.env.NEXT_EXPORT === '1'
const miniAppBasePath = process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH || '/mini-app'

const nextConfig = {
  images: {
    unoptimized: true,
  },
  output: exportMode ? 'export' : undefined,
  trailingSlash: exportMode,
  basePath: exportMode ? miniAppBasePath : '',
  assetPrefix: exportMode ? miniAppBasePath : undefined,
}

export default nextConfig
