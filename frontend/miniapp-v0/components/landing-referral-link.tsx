'use client'

import type { AnchorHTMLAttributes, PropsWithChildren } from 'react'
import { useEffect, useState } from 'react'

import {
  buildBrowserMiniAppUrl,
  buildTelegramBotUrl,
  isReferralStartParam,
  REFERRAL_STORAGE_KEY,
  resolveExplicitLandingStartParam,
  resolveLandingStartParam,
} from '@/lib/referral-links'

type ReferralLinkKind = 'bot' | 'web'

type ReferralAwareLinkProps = PropsWithChildren<
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & {
    kind: ReferralLinkKind
  }
>

function hrefFor(kind: ReferralLinkKind, startParam?: string): string {
  return kind === 'bot'
    ? buildTelegramBotUrl(startParam)
    : buildBrowserMiniAppUrl(startParam)
}

export function ReferralAwareLink({
  kind,
  children,
  target,
  rel,
  ...props
}: ReferralAwareLinkProps) {
  const [href, setHref] = useState(() => hrefFor(kind))

  useEffect(() => {
    let storedReferral = ''
    try {
      storedReferral = window.localStorage.getItem(REFERRAL_STORAGE_KEY) || ''
    } catch {}

    const params = new URLSearchParams(window.location.search)
    const explicitStartParam = resolveExplicitLandingStartParam(params)
    const startParam = resolveLandingStartParam(params, storedReferral)

    if (isReferralStartParam(explicitStartParam)) {
      try {
        window.localStorage.setItem(REFERRAL_STORAGE_KEY, explicitStartParam)
      } catch {}
    } else if (storedReferral && startParam !== storedReferral) {
      try {
        window.localStorage.removeItem(REFERRAL_STORAGE_KEY)
      } catch {}
    }

    setHref(hrefFor(kind, startParam))
  }, [kind])

  return (
    <a
      {...props}
      href={href}
      data-referral-link={kind}
      target={kind === 'bot' ? '_blank' : target}
      rel={kind === 'bot' ? 'noopener noreferrer' : rel}
    >
      {children}
    </a>
  )
}
