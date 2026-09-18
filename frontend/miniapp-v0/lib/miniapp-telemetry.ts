'use client'

import { getApiBasePath, getMiniAppPlatform } from './api'

export type MiniAppTelemetryEvent =
  | 'launch-live'
  | 'launch-locked'
  | 'launch-retry'
  | 'launch-auth-rejected'

type MiniAppTelemetryExtra = {
  status?: number
  init_data_len?: number
}

/**
 * Privacy-safe launch diagnostics for the statically hosted Mini App bundle.
 *
 * The payload mirrors the backend `/mini-app/api/client-log` field whitelist:
 * event name, platform, current path, launch-data length and bridge presence.
 * Signed launch data, Telegram identifiers and message contents are never sent.
 * Reporting is fire-and-forget and must never block or break the launch path.
 */
export function reportMiniAppEvent(
  event: MiniAppTelemetryEvent,
  extra: MiniAppTelemetryExtra = {},
): void {
  if (typeof window === 'undefined') return

  try {
    const runtimeWindow = window as Window & { Telegram?: { WebApp?: unknown }; WebApp?: unknown }
    const payload = {
      event,
      source: getMiniAppPlatform(),
      href: window.location.pathname,
      hash_len: String(window.location.hash || '').length,
      has_tg: Boolean(runtimeWindow.Telegram),
      has_webapp: Boolean(runtimeWindow.Telegram?.WebApp || runtimeWindow.WebApp),
      init_data_len: extra.init_data_len ?? 0,
      status: extra.status ?? 0,
    }

    void fetch(`${getApiBasePath()}/client-log`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      cache: 'no-store',
      credentials: 'same-origin',
      keepalive: true,
    }).catch(() => {})
  } catch {
    // Diagnostics must never break the Mini App launch path.
  }
}
