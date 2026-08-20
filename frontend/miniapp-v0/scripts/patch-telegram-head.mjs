import { readdirSync, readFileSync, statSync, writeFileSync, copyFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const outDir = join(process.cwd(), 'out')
const localTelegramJs = 'telegram-web-app.js'
const localTelegramSrc = `/mini-app/${localTelegramJs}`
const telegramScript = `<script defer src="${localTelegramSrc}"></script>`
const inlineMiniappCss = process.env.MINIAPP_INLINE_CSS === '1'
const assetVersion =
  process.env.MINIAPP_ASSET_VERSION ||
  new Date().toISOString().replace(/\D/g, '').slice(0, 14)

const telegramEarlyScriptPattern =
  /<script\b(?=[^>]*\bid=(["'])telegram-early-ready\1)[^>]*>[\s\S]*?<\/script>/gi
const telegramSdkScriptPattern =
  /<script\b(?=[^>]*\bsrc=(["'])https:\/\/telegram\.org\/js\/telegram-web-app\.js\1)[^>]*>\s*<\/script>/gi
const localTelegramScriptPattern =
  /<script\b(?=[^>]*\bsrc=(["'])\/mini-app\/telegram-web-app\.js\1)[^>]*>\s*<\/script>/gi
const telegramSdkPreloadPattern =
  /<link\b(?=[^>]*\brel=(["'])preload\1)(?=[^>]*\bhref=(["'])https:\/\/telegram\.org\/js\/telegram-web-app\.js\2)[^>]*\/?>/gi
const scriptTagPattern = /<script\b(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/gi
const charsetPattern = /<head><meta\b[^>]*(?:charset|charSet)=(["'])utf-8\1[^>]*\/?>/i
const stylesheetPattern =
  /<link\b(?=[^>]*\brel=(["'])stylesheet\1)(?=[^>]*\bhref=(["'])(\/mini-app\/_next\/static\/css\/[^"']+\.css)\2)[^>]*\/?>/i

function htmlFiles(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = join(dir, entry)
    const stat = statSync(fullPath)

    if (stat.isDirectory()) {
      return htmlFiles(fullPath)
    }

    return entry.endsWith('.html') ? [fullPath] : []
  })
}

function removeQueuedTelegramScripts(html) {
  return html.replace(scriptTagPattern, (tag) => {
    if (!tag.includes('self.__next_s')) {
      return tag
    }

    return tag.includes(localTelegramSrc) || tag.includes(localTelegramJs) || tag.includes('telegram-early-ready') ? '' : tag
  })
}

function inlineMiniappStyles(html) {
  if (!inlineMiniappCss) {
    return html
  }

  const stylesheetMatch = html.match(stylesheetPattern)
  const stylesheetTag = stylesheetMatch?.[0]
  const stylesheetHref = stylesheetMatch?.[3]

  if (!stylesheetTag || !stylesheetHref) {
    return html
  }

  const cssPath = join(outDir, stylesheetHref.replace(/^\/mini-app\//, ''))
  const css = readFileSync(cssPath, 'utf8').replace(/<\/style/gi, '<\\/style')
  const inlineStyle = `<style data-miniapp-inline-css="${stylesheetHref}">${css}</style>`

  if (html.includes(inlineStyle)) {
    return html
  }

  return html.replace(stylesheetTag, `${stylesheetTag}${inlineStyle}`)
}

function versionStaticAssets(html) {
  return html.replace(
    /(\/mini-app\/_next\/static\/[^"']+\.(?:js|css))(?!\?v=)/g,
    `$1?v=${assetVersion}`,
  )
}

// Copy local telegram-web-app.js into out/ so it is served from the same origin
const publicTelegramJs = join(process.cwd(), 'public', localTelegramJs)
const outTelegramJs = join(outDir, localTelegramJs)
if (existsSync(publicTelegramJs)) {
  copyFileSync(publicTelegramJs, outTelegramJs)
  console.log(`Copied ${localTelegramJs} to ${outTelegramJs}`)
} else {
  console.warn(`⚠ Missing ${publicTelegramJs} — local Telegram SDK file not found`)
}

let patched = 0

for (const file of htmlFiles(outDir)) {
  const html = readFileSync(file, 'utf8')
  telegramEarlyScriptPattern.lastIndex = 0

  const earlyScript = html.match(telegramEarlyScriptPattern)?.[0]

  if (!earlyScript) {
    throw new Error(`Cannot find telegram-early-ready script in ${file}`)
  }

  const stripped = removeQueuedTelegramScripts(
    html
      .replace(telegramSdkPreloadPattern, '')
      .replace(telegramSdkScriptPattern, '')
      .replace(localTelegramScriptPattern, '')
      .replace(telegramEarlyScriptPattern, ''),
  )

  if (!stripped.includes('<head>')) {
    throw new Error(`Cannot find <head> in ${file}`)
  }

  const telegramHeadScripts = `${telegramScript}${earlyScript}`
  const charsetMatch = stripped.match(charsetPattern)
  const nextHtmlWithTelegram = charsetMatch
    ? stripped.replace(charsetMatch[0], `${charsetMatch[0]}${telegramHeadScripts}`)
    : stripped.replace('<head>', `<head>${telegramHeadScripts}`)
  const nextHtml = versionStaticAssets(inlineMiniappStyles(nextHtmlWithTelegram))

  if (nextHtml !== html) {
    writeFileSync(file, nextHtml)
    patched += 1
  }
}

console.log(
  `Patched Telegram head scripts in ${patched} HTML files. inline css: ${inlineMiniappCss ? 'on' : 'off'}. asset version: ${assetVersion}.`,
)
