import { readdirSync, readFileSync, statSync, writeFileSync, copyFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const outDir = join(process.cwd(), 'out')
const localTelegramJs = 'telegram-web-app.js'
const localTelegramSrc = `/mini-app/${localTelegramJs}`
const maxBridgeSrc = 'https://st.max.ru/js/max-web-app.js'
const inlineMiniappCss = process.env.MINIAPP_INLINE_CSS === '1'
const assetVersion =
  process.env.MINIAPP_ASSET_VERSION ||
  new Date().toISOString().replace(/\D/g, '').slice(0, 14)

const bridgeLoaderScriptPattern =
  /<script\b(?=[^>]*\bid=(["'])miniapp-bridge-loader\1)[^>]*>[\s\S]*?<\/script>/gi
const earlyScriptPattern =
  /<script\b(?=[^>]*\bid=(["'])miniapp-early-ready\1)[^>]*>[\s\S]*?<\/script>/gi
const telegramSdkScriptPattern =
  /<script\b(?=[^>]*\bsrc=(["'])https:\/\/telegram\.org\/js\/telegram-web-app\.js(?:\?[^"']*)?\1)[^>]*>\s*<\/script>/gi
const localTelegramScriptPattern =
  /<script\b(?=[^>]*\bsrc=(["'])\/mini-app\/telegram-web-app\.js\1)[^>]*>\s*<\/script>/gi
const maxBridgeScriptPattern =
  /<script\b(?=[^>]*\bsrc=(["'])https:\/\/st\.max\.ru\/js\/max-web-app\.js\1)[^>]*>\s*<\/script>/gi
const telegramSdkPreloadPattern =
  /<link\b(?=[^>]*\brel=(["'])preload\1)(?=[^>]*\bhref=(["'])https:\/\/telegram\.org\/js\/telegram-web-app\.js(?:\?[^"']*)?\2)[^>]*\/?>/gi
const scriptTagPattern = /<script\b(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/gi
const charsetPattern = /<head><meta\b[^>]*(?:charset|charSet)=(["'])utf-8\1[^>]*\/?>/i
const stylesheetPattern =
  /<link\b(?=[^>]*\brel=(["'])stylesheet\1)(?=[^>]*\bhref=(["'])(\/mini-app\/_next\/static\/[^"']+\.css)\2)[^>]*\/?>/i
const nextRuntimeScriptPattern = /<script\b[^>]*\bsrc=(["'])\/mini-app\/_next\/static\/[^"']+\.js(?:\?[^"']*)?\1[^>]*>/i

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

function removeQueuedBridgeScripts(html) {
  return html.replace(scriptTagPattern, (tag) => {
    if (!tag.includes('self.__next_s')) {
      return tag
    }

    return tag.includes(localTelegramSrc) ||
      tag.includes(localTelegramJs) ||
      tag.includes(maxBridgeSrc) ||
      tag.includes('miniapp-bridge-loader') ||
      tag.includes('miniapp-early-ready')
      ? ''
      : tag
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

function assertBridgeStartupContract(html, file, bridgeLoaderScript, earlyScript) {
  const loaderIndex = html.indexOf(bridgeLoaderScript)
  if (loaderIndex < 0) {
    throw new Error(`Mini App bridge loader is missing from ${file}`)
  }

  const earlyIndex = html.indexOf(earlyScript)
  if (earlyIndex < loaderIndex) {
    throw new Error(`Mini App bootstrap must follow the bridge loader in ${file}`)
  }

  const firstNextRuntime = html.match(nextRuntimeScriptPattern)
  if (firstNextRuntime?.index != null && loaderIndex > firstNextRuntime.index) {
    throw new Error(`Mini App bridge loader must run before Next.js runtime scripts in ${file}`)
  }
  if (firstNextRuntime?.index != null && earlyIndex > firstNextRuntime.index) {
    throw new Error(`Mini App bootstrap must run before Next.js runtime scripts in ${file}`)
  }

  if (!bridgeLoaderScript.includes(localTelegramSrc)) {
    throw new Error(`Mini App bridge loader is missing Telegram SDK source in ${file}`)
  }
  if (!bridgeLoaderScript.includes(maxBridgeSrc)) {
    throw new Error(`Mini App bridge loader is missing MAX Bridge source in ${file}`)
  }
  if (!bridgeLoaderScript.includes('document.write')) {
    throw new Error(`Mini App bridge loader must synchronously load the selected bridge in ${file}`)
  }

  localTelegramScriptPattern.lastIndex = 0
  maxBridgeScriptPattern.lastIndex = 0
  if (localTelegramScriptPattern.test(html)) {
    throw new Error(`Telegram SDK must not be loaded unconditionally in ${file}`)
  }
  if (maxBridgeScriptPattern.test(html)) {
    throw new Error(`MAX Bridge must not be loaded unconditionally in ${file}`)
  }

  if (/TelegramWebviewProxy|window\.webkit|window\.external\.notify/.test(earlyScript)) {
    throw new Error(`Mini App bootstrap must not bypass platform SDKs in ${file}`)
  }
}

// The Telegram SDK is served locally so Telegram WebView startup never depends
// on a second external origin. The early bridge loader chooses exactly one
// platform SDK from signed launch parameters before application bundles run.
const publicTelegramJs = join(process.cwd(), 'public', localTelegramJs)
const outTelegramJs = join(outDir, localTelegramJs)
if (existsSync(publicTelegramJs)) {
  copyFileSync(publicTelegramJs, outTelegramJs)
  console.log(`Copied ${localTelegramJs} to ${outTelegramJs}`)
} else {
  throw new Error(`Missing ${publicTelegramJs} — local Telegram SDK file not found`)
}

let patched = 0

for (const file of htmlFiles(outDir)) {
  const html = readFileSync(file, 'utf8')
  bridgeLoaderScriptPattern.lastIndex = 0
  earlyScriptPattern.lastIndex = 0

  const bridgeLoaderScript = html.match(bridgeLoaderScriptPattern)?.[0]
  const earlyScript = html.match(earlyScriptPattern)?.[0]

  if (!bridgeLoaderScript) {
    throw new Error(`Cannot find miniapp-bridge-loader script in ${file}`)
  }
  if (!earlyScript) {
    throw new Error(`Cannot find miniapp-early-ready script in ${file}`)
  }

  const stripped = removeQueuedBridgeScripts(
    html
      .replace(telegramSdkPreloadPattern, '')
      .replace(telegramSdkScriptPattern, '')
      .replace(localTelegramScriptPattern, '')
      .replace(maxBridgeScriptPattern, '')
      .replace(bridgeLoaderScriptPattern, '')
      .replace(earlyScriptPattern, ''),
  )

  if (!stripped.includes('<head>')) {
    throw new Error(`Cannot find <head> in ${file}`)
  }

  const bridgeHeadScripts = `${bridgeLoaderScript}${earlyScript}`
  const charsetMatch = stripped.match(charsetPattern)
  const nextHtmlWithBridge = charsetMatch
    ? stripped.replace(charsetMatch[0], `${charsetMatch[0]}${bridgeHeadScripts}`)
    : stripped.replace('<head>', `<head>${bridgeHeadScripts}`)
  const nextHtml = versionStaticAssets(inlineMiniappStyles(nextHtmlWithBridge))

  assertBridgeStartupContract(nextHtml, file, bridgeLoaderScript, earlyScript)

  if (nextHtml !== html) {
    writeFileSync(file, nextHtml)
    patched += 1
  }
}

console.log(
  `Patched Mini App platform bridge loader in ${patched} HTML files. inline css: ${inlineMiniappCss ? 'on' : 'off'}. asset version: ${assetVersion}.`,
)
