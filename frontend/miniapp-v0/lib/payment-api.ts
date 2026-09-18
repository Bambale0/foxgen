import type { CreatePaymentResponse, PaymentProvider } from './types'
import { getApiBasePath, getInitData, getMiniAppPlatform, getStartParamFallback } from './api'

export async function createPayment(payload: {
  packageId: string
  provider: PaymentProvider
  promoCode?: string
  customerEmail?: string
}): Promise<CreatePaymentResponse> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте Mini App из Telegram или MAX и попробуйте снова.')
  }

  const controller = new AbortController()
  const deadline = window.setTimeout(() => controller.abort(), 20_000)
  try {
    const response = await fetch(`${getApiBasePath()}/create-payment`, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        init_data: initData,
        platform: getMiniAppPlatform(),
        start_param_fallback: getStartParamFallback(),
        package_id: payload.packageId,
        provider: payload.provider,
        promo_code: payload.promoCode || '',
        customer_email: payload.customerEmail?.trim() || '',
      }),
      cache: 'no-store',
      credentials: 'same-origin',
    })

    const text = await response.text()
    let data: unknown
    try {
      data = JSON.parse(text)
    } catch {
      throw new Error('Платёжный сервис вернул некорректный ответ')
    }

    if (!data || typeof data !== 'object') {
      throw new Error('Платёжный сервис вернул некорректный ответ')
    }
    const statusPayload = data as { ok?: boolean; error?: unknown }
    if (!response.ok || statusPayload.ok === false) {
      throw new Error(typeof statusPayload.error === 'string'
        ? statusPayload.error : 'Не удалось создать платёж. Попробуйте снова.')
    }

    return data as CreatePaymentResponse
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('Платёжный сервис не ответил вовремя. Попробуйте снова.')
    }
    throw error
  } finally {
    window.clearTimeout(deadline)
  }
}
