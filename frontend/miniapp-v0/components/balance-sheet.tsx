'use client'

import type { ComponentType } from 'react'
import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Coins, CreditCard, Gift, Loader2, Receipt, Sparkles, Star, X } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { createPayment } from '@/lib/payment-api'
import type { PaymentProvider } from '@/lib/types'

type TelegramPaymentBridge = {
  openInvoice?: (url: string, callback?: (status: string) => void) => void
  openLink?: (url: string, options?: { try_instant_view?: boolean }) => void
}

function getTelegramPaymentBridge(): TelegramPaymentBridge | null {
  if (typeof window === 'undefined') return null
  return ((window as Window & {
    Telegram?: { WebApp?: TelegramPaymentBridge }
  }).Telegram?.WebApp || null)
}

function pawLabel(amount: number): string {
  const absolute = Math.abs(Math.trunc(amount))
  const lastTwo = absolute % 100
  const last = absolute % 10
  if (lastTwo >= 11 && lastTwo <= 14) return 'лапок'
  if (last === 1) return 'лапка'
  if (last >= 2 && last <= 4) return 'лапки'
  return 'лапок'
}

function formatPaws(amount: number): string {
  return `${amount} ${pawLabel(amount)}`
}

export function BalanceSheet() {
  const { state, isBalanceOpen, closeBalance, refreshTasks } = useApp()
  const { paymentPackages, user, recentTasks, mode } = state
  const [loadingPayment, setLoadingPayment] = useState<string | null>(null)

  const totalSpent = recentTasks.reduce((sum, task) => sum + task.cost, 0)
  const imageTasks = recentTasks.filter((task) => task.type === 'image').length
  const videoTasks = recentTasks.filter((task) => task.type === 'video').length

  const openExternalPayment = (url: string) => {
    const webApp = getTelegramPaymentBridge()

    if (webApp?.openLink) {
      try {
        webApp.openLink(url)
        return
      } catch {
        // Continue to browser fallbacks for old or partially supported clients.
      }
    }

    const opened = window.open(url, '_blank', 'noopener,noreferrer')
    if (!opened) {
      window.location.assign(url)
    }
  }

  const openTelegramInvoice = (url: string) => {
    const webApp = getTelegramPaymentBridge()
    if (!webApp?.openInvoice) {
      openExternalPayment(url)
      return Promise.resolve('opened')
    }

    return new Promise<string>((resolve) => {
      try {
        webApp.openInvoice?.(url, (status) => resolve(status || 'unknown'))
      } catch {
        openExternalPayment(url)
        resolve('opened')
      }
    })
  }

  const handleTopup = async (packageId: string, provider: PaymentProvider = 'yookassa') => {
    const selectedPackage = paymentPackages.find((item) => item.id === packageId)
    if (!selectedPackage) return

    const loadingKey = `${packageId}:${provider}`
    setLoadingPayment(loadingKey)
    try {
      const payment = await createPayment({ packageId, provider })
      if (payment.provider === 'telegram_stars' && payment.invoice_url) {
        const status = await openTelegramInvoice(payment.invoice_url)
        if (status === 'paid') {
          toast.success('Оплата Stars прошла', {
            description: `Начисляем ${formatPaws(payment.credits)}. Баланс обновится автоматически.`,
          })
          await refreshTasks()
        } else if (status === 'cancelled') {
          toast.message('Оплата отменена')
        } else if (status === 'failed') {
          toast.error('Оплата Stars не прошла')
        } else {
          toast.message('Счёт Stars открыт', {
            description: 'После оплаты баланс обновится в Mini App.',
          })
        }
        return
      }

      if (payment.payment_url) {
        openExternalPayment(payment.payment_url)
        toast.message(
          payment.provider === 'yookassa'
            ? 'Открыта безопасная оплата ЮKassa'
            : 'Открыта страница оплаты',
          {
            description: 'После успешной оплаты баланс обновится автоматически.',
          },
        )
        return
      }

      throw new Error('Платёжная ссылка не получена')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось создать платёж'
      toast.error(message)
    } finally {
      setLoadingPayment(null)
    }
  }

  return (
    <AnimatePresence>
      {isBalanceOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={closeBalance}
            className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md"
          />

          <motion.div
            initial={{ opacity: 0, y: '100%' }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 280, mass: 0.8 }}
            className="glass-strong safe-bottom fixed bottom-0 left-0 right-0 z-50 max-h-[90vh] overflow-auto rounded-t-[30px] border-t border-gold/20 shadow-[0_-30px_90px_rgba(0,0,0,0.65)]"
          >
            <div className="sticky top-0 z-10 bg-[#090909]/95 px-4 pb-3 pt-3 backdrop-blur-2xl sm:px-5">
              <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-white/15" />
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.18em] text-gold">Баланс</p>
                  <h2 className="mt-0.5 text-xl font-bold tracking-[-0.025em] text-foreground">Пополнение лапок</h2>
                </div>
                <button
                  type="button"
                  onClick={closeBalance}
                  className="flex h-9 w-9 items-center justify-center rounded-full border border-white/[0.07] bg-white/[0.04] transition-colors hover:border-gold/25 hover:bg-gold/[0.08]"
                  aria-label="Закрыть пополнение"
                >
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
            </div>

            <div className="space-y-5 px-4 pb-7 sm:px-5">
              <div className="fox-surface-accent rounded-[24px] p-4 sm:p-5">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Ваш баланс</p>
                    <div className="mt-1 flex items-center gap-2.5">
                      <span className="text-xl" aria-hidden="true">🐾</span>
                      <span className="text-3xl font-black tabular-nums tracking-[-0.04em] text-foreground">{user.credits}</span>
                    </div>
                    <p className="mt-2 text-[10px] text-muted-foreground">1 лапка = 10 ₽</p>
                  </div>
                  <div className="rounded-2xl border border-gold/20 bg-black/25 px-4 py-3 text-right">
                    <p className="text-[9px] uppercase tracking-[0.12em] text-muted-foreground">Статус</p>
                    <p className="mt-1 text-sm font-bold text-foreground">{mode === 'live' ? 'Онлайн' : 'Telegram'}</p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2.5">
                <StatCard icon={Sparkles} label="Всего запусков" value={`${recentTasks.length}`} />
                <StatCard icon={Receipt} label="Потрачено" value={`${totalSpent} 🐾`} />
                <StatCard icon={Gift} label="Фото" value={`${imageTasks}`} />
                <StatCard icon={CreditCard} label="Видео" value={`${videoTasks}`} />
              </div>

              <div className="fox-surface rounded-[18px] border border-gold/15 p-3.5">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gold/[0.1]">
                    <CreditCard className="h-4 w-4 text-gold" />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-foreground">ЮKassa • карта / СБП</p>
                    <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                      Оплата проходит на защищённой странице ЮKassa. Лапки начисляются только после подтверждения платежа сервером.
                    </p>
                  </div>
                </div>
              </div>

              <div>
                <div className="mb-3 flex items-end justify-between gap-3">
                  <div>
                    <p className="text-[9px] font-black uppercase tracking-[0.16em] text-gold">Пополнить баланс</p>
                    <h3 className="mt-0.5 text-lg font-bold text-foreground">Пакеты лапок</h3>
                  </div>
                  <span className="text-[10px] text-muted-foreground">Выберите пакет</span>
                </div>

                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                  {paymentPackages.map((pkg) => {
                    const pricePerPaw = Math.round(pkg.price_rub / pkg.credits)
                    const starsPrice = pkg.price_stars ?? pkg.price_rub
                    const hasLava = Boolean(pkg.lava_offer_id || pkg.lava_currency)
                    const lavaLabel = pkg.lava_currency?.toUpperCase() === 'EUR' ? 'EUR' : 'Lava'
                    const starsLoading = loadingPayment === `${pkg.id}:telegram_stars`
                    const lavaLoading = loadingPayment === `${pkg.id}:lava`
                    const yookassaLoading = loadingPayment === `${pkg.id}:yookassa`
                    return (
                      <div
                        key={pkg.id}
                        className={cn(
                          'relative overflow-hidden rounded-[20px] border p-3.5 transition-all duration-200',
                          pkg.popular
                            ? 'fox-surface-accent border-gold/45'
                            : 'fox-surface border-white/[0.07]',
                        )}
                      >
                        {pkg.popular && (
                          <span className="absolute right-2 top-2 rounded-full border border-gold/35 bg-gold/[0.12] px-1.5 py-0.5 text-[8px] font-black uppercase tracking-[0.1em] text-gold">
                            Хит
                          </span>
                        )}

                        <div className="pr-8">
                          <h4 className="text-sm font-bold text-foreground">{pkg.name}</h4>
                          <p className="mt-1 line-clamp-2 min-h-[30px] text-[9px] leading-relaxed text-muted-foreground">{pkg.description}</p>
                        </div>

                        <div className="mt-4 flex items-end justify-between gap-2">
                          <div>
                            <div className="flex items-center gap-1.5 text-gold">
                              <span className="text-sm" aria-hidden="true">🐾</span>
                              <span className="text-lg font-black tabular-nums">{pkg.credits}</span>
                            </div>
                            <p className="mt-0.5 text-[8px] text-muted-foreground">≈ {pricePerPaw} ₽ / лапку</p>
                          </div>
                          <div className="text-right">
                            <p className="text-sm font-black text-foreground">{pkg.price_rub} ₽</p>
                            <p className="text-[8px] text-muted-foreground">{starsPrice} ⭐</p>
                          </div>
                        </div>

                        <div className="mt-3 space-y-1.5">
                          <Button
                            onClick={() => handleTopup(pkg.id, 'yookassa')}
                            disabled={Boolean(loadingPayment)}
                            size="sm"
                            className="w-full"
                          >
                            {yookassaLoading ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <CreditCard className="h-3.5 w-3.5" />
                            )}
                            ЮKassa
                          </Button>
                          {hasLava ? (
                            <Button
                              onClick={() => handleTopup(pkg.id, 'lava')}
                              disabled={Boolean(loadingPayment)}
                              variant="outline"
                              size="sm"
                              className="w-full"
                            >
                              {lavaLoading ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Coins className="h-3.5 w-3.5" />
                              )}
                              {lavaLabel}
                            </Button>
                          ) : null}
                          <Button
                            onClick={() => handleTopup(pkg.id, 'telegram_stars')}
                            disabled={Boolean(loadingPayment)}
                            variant="secondary"
                            size="sm"
                            className="w-full"
                          >
                            {starsLoading ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Star className="h-3.5 w-3.5" />
                            )}
                            Stars
                          </Button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="grid gap-2.5 md:grid-cols-2">
                <Button
                  onClick={() => toast.success('Статистика обновлена', { description: 'Карточки выше показывают расходы, баланс и активность по задачам.' })}
                  variant="outline"
                >
                  Обновить статистику
                </Button>
                <Button
                  onClick={() => handleTopup(paymentPackages[0]?.id || 'mini', 'yookassa')}
                  disabled={Boolean(loadingPayment)}
                >
                  Оплатить через ЮKassa
                </Button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: ComponentType<{ className?: string }>
  label: string
  value: string
}) {
  return (
    <div className="fox-surface rounded-[18px] p-3.5">
      <div className="mb-2 flex h-8 w-8 items-center justify-center rounded-xl border border-gold/15 bg-gold/[0.07]">
        <Icon className="h-3.5 w-3.5 text-gold" />
      </div>
      <p className="text-[9px] text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-bold tabular-nums text-foreground">{value}</p>
    </div>
  )
}
