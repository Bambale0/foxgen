import {
  buildBrowserMiniAppUrl,
  buildTelegramBotUrl,
  isLegacyDefaultReferral,
  normalizeStartParam,
  resolveExplicitLandingStartParam,
  resolveLandingStartParam,
} from '@/lib/referral-links'

describe('landing referral links', () => {
  it('uses the configured referral when the landing has no attribution query', () => {
    expect(resolveLandingStartParam(new URLSearchParams())).toBe('ref_AZLRXW6L')
    expect(buildTelegramBotUrl()).toBe('https://t.me/AlePolbot?start=ref_AZLRXW6L')
    expect(buildBrowserMiniAppUrl()).toBe(
      'https://app.happy-fox.online/mini-app/?startapp=ref_AZLRXW6L',
    )
  })

  it('preserves direct start and startapp contracts before plain ref', () => {
    expect(
      resolveLandingStartParam(
        new URLSearchParams('startapp=feed_42_ref_partner7&ref=ignored'),
      ),
    ).toBe('feed_42_ref_partner7')
    expect(
      resolveLandingStartParam(new URLSearchParams('start=ref_partner7&ref=ignored')),
    ).toBe('ref_PARTNER7')
  })

  it('normalizes ref query codes and rejects malformed start parameters', () => {
    expect(resolveLandingStartParam(new URLSearchParams('ref=partner7'))).toBe('ref_PARTNER7')
    expect(normalizeStartParam('ref_partner7')).toBe('ref_PARTNER7')
    expect(normalizeStartParam('bad value with spaces')).toBe('')
  })

  it('falls back to a persisted referral only when no explicit query is present', () => {
    expect(resolveLandingStartParam(new URLSearchParams(), 'ref_saved7')).toBe('ref_SAVED7')
    expect(resolveLandingStartParam(new URLSearchParams('ref=fresh8'), 'ref_saved7')).toBe(
      'ref_FRESH8',
    )
  })

  it('ignores the former site default when it is still persisted in the browser', () => {
    expect(isLegacyDefaultReferral('ref_M9SHFF25')).toBe(true)
    expect(resolveLandingStartParam(new URLSearchParams(), 'ref_M9SHFF25')).toBe(
      'ref_AZLRXW6L',
    )
  })

  it('separates explicit attribution from the configured default', () => {
    expect(resolveExplicitLandingStartParam(new URLSearchParams())).toBe('')
    expect(resolveExplicitLandingStartParam(new URLSearchParams('ref=partner42'))).toBe(
      'ref_PARTNER42',
    )
  })

  it('keeps the referral when the website button crosses to the app domain', () => {
    expect(buildBrowserMiniAppUrl('ref_partner42')).toBe(
      'https://app.happy-fox.online/mini-app/?startapp=ref_PARTNER42',
    )
  })
})
