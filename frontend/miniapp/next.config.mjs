/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  basePath: '/mini-app',
  assetPrefix: '/mini-app',
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
}

export default nextConfig
