'use client'

import type { ComponentType } from 'react'
import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Banana, CreditCard, Gift, Loader2, Mail, Receipt, Sparkles, Star, X } from 'lucide-react'
import { useApp } from '@/lib/app-context'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { bootstrapApp } from '@/lib/api'
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

function normalizeCustomerEmail(value: string) {
  return value.trim().toLowerCase()
}

function isValidCustomerEmail(value: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value)
}

export function BalanceSheet() {
  const { state, isBalanceOpen, closeBalance, refreshTasks } = useApp()
  const { paymentPackages, user, recentTasks, mode } = state
  const emailInputRef = useRef<HTMLInputElement>(null)
  const [loadingPayment, setLoadingPayment] = useState<string | null>(null)
  const [customerEmail, setCustomerEmail] = useState('')

  const normalizedCustomerEmail = normalizeCustomerEmail(customerEmail)
  const customerEmailValid = isValidCustomerEmail(normalizedCustomerEmail)
  const totalSpent = recentTasks.reduce((sum, task) => sum + task.cost, 0)
  const imageTasks = recentTasks.filter((task) => task.type === 'image').length
  const videoTasks = recentTasks.filter((task) => task.type === 'video').length

  useEffect(() => {
    if (!isBalanceOpen) return

    let cancelled = false
    void bootstrapApp()
      .then((data) => {
        const savedEmail = normalizeCustomerEmail(
          String((data as typeof data & { payment_email?: string }).payment_email || ''),
        )
        if (!cancelled && isValidCustomerEmail(savedEmail)) {
          setCustomerEmail((current) => current.trim() ? current : savedEmail)
        }
      })
      .catch(() => {
        // Payment can still proceed: the backend also falls back to the saved account email.
      })

    return () => {
      cancelled = true
    }
  }, [isBalanceOpen])

  const focusCustomerEmail = () => {
    window.setTimeout(() => {
      emailInputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      emailInputRef.current?.focus()
    }, 50)
  }

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
        // Call through the WebApp object so Telegram keeps the native method context.
        webApp.openInvoice?.(url, (status) => resolve(status || 'unknown'))
      } catch {
        openExternalPayment(url)
        resolve('opened')
      }
    })
  }

  const handleTopup = async (packageId: string, provider: PaymentProvider = 'telegram_stars') => {
    const selectedPackage = paymentPackages.find((item) => item.id === packageId)
    if (!selectedPackage) return

    const loadingKey = `${packageId}:${provider}`
    setLoadingPayment(loadingKey)
    try {
      const payment = await createPayment({
        packageId,
        provider,
        customerEmail: provider === 'lava' && customerEmailValid
          ? normalizedCustomerEmail
          : undefined,
      })
      if (payment.provider === 'telegram_stars' && payment.invoice_url) {
        const status = await openTelegramInvoice(payment.invoice_url)
        if (status === 'paid') {
          toast.success('Оплата Stars прошла', {
            description: `Начисляем ${payment.credits}🍌. Баланс обновится автоматически.`,
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
        toast.message('Открыта страница оплаты')
        return
      }

      throw new Error('Платёжная ссылка не получена')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось создать платёж'
      toast.error(message)
      if (provider === 'lava' && message.toLowerCase().includes('почт')) {
        focusCustomerEmail()
      }
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
            className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, y: '100%' }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 280, mass: 0.8 }}
            className="fixed bottom-0 left-0 right-0 z-50 max-h-[88vh] overflow-auto rounded-t-3xl border-t border-border/50 glass-strong safe-bottom"
          >
            <div className="sticky top-0 z-10 bg-inherit px-5 pt-3 pb-3">
              <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-border" />
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-gold/80">Баланс и пакеты</p>
                  <h2 className="font-serif text-xl font-semibold text-foreground">Пополнение баланса</h2>
                </div>
                <button
                  onClick={closeBalance}
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary/80 transition-colors hover:bg-secondary"
                  aria-label="Закрыть пополнение"
                >
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
            </div>

            <div className="space-y-5 px-5 pb-6">
              <div className="rounded-2xl border border-gold/20 bg-gold/10 p-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Доступно сейчас</p>
                    <div className="mt-1 flex items-center gap-2">
                      <Banana className="h-5 w-5 text-gold" />
                      <span className="text-2xl font-semibold text-gold">{user.credits}</span>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">Welcome-бонус для новых пользователей: 5🍌</p>
                  </div>
                  <div className="rounded-2xl border border-cyan/20 bg-background/30 px-4 py-3 text-right">
                    <p className="text-xs text-muted-foreground">Режим</p>
                    <p className="text-sm font-medium text-foreground">{mode === 'live' ? 'Онлайн' : 'Telegram'}</p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <StatCard icon={Sparkles} label="Всего запусков" value={`${recentTasks.length}`} />
                <StatCard icon={Receipt} label="Потрачено" value={`${totalSpent}🍌`} />
                <StatCard icon={Gift} label="Фото" value={`${imageTasks}`} />
                <StatCard icon={CreditCard} label="Видео" value={`${videoTasks}`} />
              </div>

              <label className="block space-y-2" htmlFor="payment-customer-email">
                <span className="text-sm font-medium text-foreground">Почта для карты и СБП</span>
                <div className="relative">
                  <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    ref={emailInputRef}
                    id="payment-customer-email"
                    type="email"
                    value={customerEmail}
                    onChange={(event) => setCustomerEmail(event.target.value)}
                    placeholder="name@example.com"
                    autoComplete="email"
                    inputMode="email"
                    className={cn(
                      'h-11 w-full rounded-xl border bg-secondary/40 pl-10 pr-3 text-sm text-foreground outline-none',
                      customerEmail && !customerEmailValid
                        ? 'border-destructive/60 focus:border-destructive'
                        : 'border-border/50 focus:border-gold/50',
                    )}
                  />
                </div>
                <span className="block text-xs text-muted-foreground">
                  Сохраним адрес в вашем аккаунте и автоматически подставим при следующих оплатах.
                </span>
                {customerEmail && !customerEmailValid ? (
                  <span className="block text-xs text-destructive">Проверьте формат почты.</span>
                ) : null}
              </label>

              <div>
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="font-serif text-lg text-foreground">Пакеты бананов</h3>
                  <span className="text-xs text-muted-foreground">Быстрый выбор пакета</span>
                </div>

                <div className="space-y-3">
                  {paymentPackages.map((pkg) => {
                    const pricePerBanana = Math.round(pkg.price_rub / pkg.credits)
                    const starsPrice = pkg.price_stars ?? pkg.price_rub
                    const lavaConfigured = Boolean(pkg.lava_offer_id)
                    const starsLoading = loadingPayment === `${pkg.id}:telegram_stars`
                    const lavaLoading = loadingPayment === `${pkg.id}:lava`
                    return (
                      <div
                        key={pkg.id}
                        className={cn(
                          'rounded-2xl border p-4 transition-all duration-200',
                          pkg.popular
                            ? 'border-gold/40 bg-gold/10'
                            : 'border-border/50 bg-secondary/20'
                        )}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <div className="flex items-center gap-2">
                              <h4 className="text-base font-semibold text-foreground">{pkg.name}</h4>
                              {pkg.popular && (
                                <span className="rounded-full border border-gold/30 bg-gold/15 px-2 py-0.5 text-[10px] font-medium text-gold">
                                  Popular
                                </span>
                              )}
                            </div>
                            <p className="mt-1 text-sm text-muted-foreground">{pkg.description}</p>
                            <p className="mt-2 text-xs text-muted-foreground">
                              {pkg.credits}🍌 • около {pricePerBanana}₽ за банан
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">
                              Stars: {starsPrice}⭐
                            </p>
                          </div>
                          <div className="text-right">
                            <p className="text-xl font-semibold text-foreground">{pkg.price_rub}₽</p>
                            <p className="text-xs text-muted-foreground">{pkg.credits} бананов</p>
                          </div>
                        </div>

                        <div className="mt-4 grid grid-cols-2 gap-2">
                          <Button
                            onClick={() => handleTopup(pkg.id, 'lava')}
                            disabled={Boolean(loadingPayment)}
                            className="col-span-2 w-full bg-gold text-primary-foreground hover:bg-gold/90"
                          >
                            {lavaLoading ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                              <CreditCard className="mr-2 h-4 w-4" />
                            )}
                            Карта / СБП
                          </Button>
                          <Button
                            onClick={() => handleTopup(pkg.id, 'telegram_stars')}
                            disabled={Boolean(loadingPayment)}
                            className="col-span-2 w-full bg-secondary text-foreground hover:bg-secondary/80"
                          >
                            {starsLoading ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                              <Star className="mr-2 h-4 w-4" />
                            )}
                            Stars
                          </Button>
                          {lavaConfigured ? (
                            <p className="col-span-2 px-1 text-center text-[11px] text-muted-foreground">
                              Доступна оплата банковской картой и через СБП.
                            </p>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <Button
                  onClick={() => toast.success('Статистика обновлена', { description: 'Карточки выше показывают расходы, баланс и активность по задачам.' })}
                  variant="outline"
                  className="border-border/50 bg-secondary/20 text-foreground hover:bg-secondary/40"
                >
                  Обновить статистику
                </Button>
                <Button
                  onClick={() => handleTopup(paymentPackages[0]?.id || 'mini', 'lava')}
                  className="bg-gold hover:bg-gold/90 text-primary-foreground"
                >
                  Пополнить картой / СБП
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
    <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
      <div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-background/40">
        <Icon className="h-4 w-4 text-gold" />
      </div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-base font-semibold text-foreground">{value}</p>
    </div>
  )
}
