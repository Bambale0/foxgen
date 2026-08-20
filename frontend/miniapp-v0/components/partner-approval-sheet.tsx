'use client'

import { useCallback, useEffect, useState } from 'react'
import { BriefcaseBusiness, CheckCircle2, Copy, Loader2, RefreshCw, Send, ShieldCheck, XCircle } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useApp } from '@/lib/app-context'
import { executeMiniAppAction, fetchPartnerOverview } from '@/lib/api'

type PartnerStatus = 'available' | 'pending' | 'rejected' | 'partner' | 'approved' | string

type PartnerOverview = {
  is_partner: boolean
  referrals_count: number
  balance_rub: number
  referral_link: string
  status: PartnerStatus
}

function statusLabel(status: PartnerStatus, isPartner: boolean) {
  if (isPartner || status === 'partner' || status === 'approved') return 'Партнёр'
  if (status === 'pending') return 'На проверке'
  if (status === 'rejected') return 'Отклонено'
  return 'Не активирован'
}

export function PartnerApprovalSheet() {
  const { activeWorkspace, closeWorkspace } = useApp()
  const [partner, setPartner] = useState<PartnerOverview | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const isOpen = activeWorkspace === 'partners'
  const status = partner?.status || 'available'
  const isApproved = Boolean(
    partner?.is_partner || status === 'partner' || status === 'approved'
  )
  const isPending = status === 'pending'
  const isRejected = status === 'rejected'

  const loadPartnerData = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await fetchPartnerOverview()
      setPartner(data)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить партнёрский кабинет'
      toast.error('Партнёрская программа недоступна', { description: message })
    } finally {
      setIsLoading(false)
    }
  }, [])

  async function submitApplication() {
    if (isSubmitting) return
    setIsSubmitting(true)
    try {
      await executeMiniAppAction('partner_apply')
      toast.success('Заявка отправлена', {
        description: 'Администратор получил заявку и ссылку на ваш Telegram-аккаунт.',
      })
      await loadPartnerData()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось отправить заявку'
      toast.error('Заявка не отправлена', { description: message })
    } finally {
      setIsSubmitting(false)
    }
  }

  useEffect(() => {
    if (!isOpen) return
    void loadPartnerData()
  }, [isOpen, loadPartnerData])

  const referralLink = isApproved ? partner?.referral_link || '' : ''

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && closeWorkspace()}>
      <SheetContent side="bottom" className="h-[86vh] rounded-t-[28px] border-border/50 bg-background/95 px-0">
        <SheetHeader className="px-5 pt-3 text-left">
          <div className="mb-2">
            <div className="mb-3 h-1 w-10 rounded-full bg-border/80" />
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-gold/20 bg-gold/10">
                <BriefcaseBusiness className="h-4 w-4 text-gold" />
              </div>
              <div className="min-w-0">
                <SheetTitle className="font-serif text-2xl leading-tight text-foreground">
                  Партнёрская программа
                </SheetTitle>
                <SheetDescription className="mt-1 max-w-xl text-sm leading-5 text-muted-foreground">
                  Кабинет, реферальная ссылка, статистика и выплаты после одобрения администратора.
                </SheetDescription>
              </div>
            </div>
          </div>
        </SheetHeader>

        <div className="h-[calc(86vh-92px)] overflow-auto px-5 pb-8">
          {isLoading && !partner ? (
            <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin text-gold" />
                Загружаю статус партнёрского кабинета…
              </div>
            </div>
          ) : isApproved ? (
            <ApprovedPartnerCabinet
              partner={partner}
              referralLink={referralLink}
              isLoading={isLoading}
              onRefresh={loadPartnerData}
            />
          ) : (
            <PartnerApplicationGate
              status={status}
              isPending={isPending}
              isRejected={isRejected}
              isLoading={isLoading}
              isSubmitting={isSubmitting}
              onApply={submitApplication}
              onRefresh={loadPartnerData}
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function PartnerApplicationGate({
  status,
  isPending,
  isRejected,
  isLoading,
  isSubmitting,
  onApply,
  onRefresh,
}: {
  status: PartnerStatus
  isPending: boolean
  isRejected: boolean
  isLoading: boolean
  isSubmitting: boolean
  onApply: () => Promise<void>
  onRefresh: () => Promise<void>
}) {
  const Icon = isPending ? ShieldCheck : isRejected ? XCircle : Send
  const title = isPending
    ? 'Заявка на рассмотрении'
    : isRejected
      ? 'Заявка отклонена'
      : 'Активируйте партнёрскую ссылку'
  const description = isPending
    ? 'Администратор уже получил заявку и ссылку на ваш Telegram-аккаунт. До решения реферальная ссылка не активна.'
    : isRejected
      ? 'Партнёрский кабинет пока не активирован. Вы можете отправить заявку повторно — администратор рассмотрит её заново.'
      : 'Для новых партнёров доступ включается после ручной проверки. Нажмите кнопку — администратору придёт заявка с вашим Telegram-профилем.'

  return (
    <div className="space-y-4">
      <div className="rounded-[1.75rem] border border-gold/20 bg-gradient-to-br from-gold/[0.12] via-card/70 to-cyan/[0.08] p-5">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-gold/20 bg-gold/10">
            <Icon className="h-5 w-5 text-gold" />
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-gold">
              {statusLabel(status, false)}
            </p>
            <h3 className="mt-1 font-serif text-2xl text-foreground">{title}</h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
          </div>
        </div>

        {isPending ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => void onRefresh()}
            disabled={isLoading}
            className="mt-5 h-12 w-full rounded-2xl border-border/50 bg-background/40 hover:bg-background/60"
          >
            {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            Проверить статус
          </Button>
        ) : (
          <Button
            type="button"
            onClick={() => void onApply()}
            disabled={isSubmitting}
            className="mt-5 h-12 w-full rounded-2xl bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
          >
            {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
            {isRejected ? 'Подать заявку повторно' : 'Активировать ссылку'}
          </Button>
        )}
      </div>

      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
          Как проходит активация
        </p>
        <div className="mt-3 space-y-2">
          {[
            'Вы отправляете заявку из партнёрского кабинета.',
            'Администратор получает уведомление и открывает ваш Telegram-аккаунт.',
            'После одобрения открываются кабинет, статистика и активная реферальная ссылка.',
          ].map((item, index) => (
            <div key={item} className="flex gap-3 rounded-xl bg-background/35 px-3 py-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gold/10 text-xs text-gold">
                {index + 1}
              </span>
              <p className="text-sm leading-5 text-foreground">{item}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ApprovedPartnerCabinet({
  partner,
  referralLink,
  isLoading,
  onRefresh,
}: {
  partner: PartnerOverview | null
  referralLink: string
  isLoading: boolean
  onRefresh: () => Promise<void>
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-4">
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
          <div>
            <p className="font-medium text-foreground">Партнёрский кабинет активирован</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Реферальная ссылка активна и может закреплять новых пользователей.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Статус</p>
          <p className="mt-1 truncate font-serif text-lg text-foreground">Партнёр</p>
        </div>
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Рефералов</p>
          <p className="mt-1 font-serif text-lg text-foreground">{partner?.referrals_count ?? '—'}</p>
        </div>
        <div className="rounded-2xl border border-border/50 bg-secondary/20 p-3">
          <p className="text-[11px] text-muted-foreground">Баланс</p>
          <p className="mt-1 font-serif text-lg text-foreground">
            {partner ? `${partner.balance_rub} ₽` : '—'}
          </p>
        </div>
      </div>

      <div className="rounded-[1.5rem] border border-gold/20 bg-gold/10 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-gold/80">Ваша ссылка</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Делитесь ей — новые пользователи закрепляются за вами по правилам партнёрки.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => void onRefresh()}
            disabled={isLoading}
            className="shrink-0 border-border/50 bg-background/40 hover:bg-background/60"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span className="sr-only">Обновить</span>
          </Button>
        </div>

        <div className="mt-4 rounded-2xl border border-border/50 bg-background/45 p-3">
          <p className="break-all text-sm leading-6 text-foreground">
            {referralLink || 'Ссылка временно недоступна'}
          </p>
        </div>

        <Button
          disabled={!referralLink}
          onClick={() => {
            void navigator.clipboard.writeText(referralLink)
            toast.success('Реферальная ссылка скопирована')
          }}
          className="mt-4 h-12 w-full rounded-2xl bg-gold text-primary-foreground hover:bg-gold/90 disabled:opacity-50"
        >
          <Copy className="mr-2 h-4 w-4" />
          Скопировать ссылку
        </Button>
      </div>

      <div className="rounded-2xl border border-border/50 bg-secondary/20 p-4">
        <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Как это работает</p>
        <div className="mt-3 space-y-2">
          {[
            'Пользователь переходит по вашей активной ссылке.',
            'Система закрепляет его за вами после антифрод-проверок.',
            'Покупки рефералов обновляют партнёрский баланс и статистику.',
          ].map((item, index) => (
            <div key={item} className="flex gap-3 rounded-xl bg-background/35 px-3 py-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gold/10 text-xs text-gold">
                {index + 1}
              </span>
              <p className="text-sm leading-5 text-foreground">{item}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
