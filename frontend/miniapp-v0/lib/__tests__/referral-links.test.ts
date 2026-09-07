import {
  buildBrowserMiniAppUrl,
  buildTelegramBotUrl,
  normalizeStartParam,
  resolveLandingStartParam,
} from '@/lib/referral-links'

describe('landing referral links', () => {
  it('uses the configured referral when the landing has no attribution query', () => {
    expect(resolveLandingStartParam(new URLSearchParams())).toBe('ref_M9SHFF25')
    expect(buildTelegramBotUrl()).toBe('https://t.me/AlePolbot?start=ref_M9SHFF25')
    expect(buildBrowserMiniAppUrl()).toBe('/mini-app/?startapp=ref_M9SHFF25')
  })

  it('preserves direct start and startapp contracts before plain ref', () => {
    expect(resolveLandingStartParam(new URLSearchParams('startapp=feed_42_ref_partner7&ref=ignored'))).toBe('feed_42_ref_partner7')
    expect(resolveLandingStartParam(new URLSearchParams('start=ref_partner7&ref=ignored'))).toBe('ref_PARTNER7')
  })

  it('normalizes ref query codes and rejects malformed start parameters', () => {
    expect(resolveLandingStartParam(new URLSearchParams('ref=partner7'))).toBe('ref_PARTNER7')
    expect(normalizeStartParam('ref_partner7')).toBe('ref_PARTNER7')
    expect(normalizeStartParam('bad value with spaces')).toBe('')
  })

  it('falls back to a persisted referral only when no explicit query is present', () => {
    expect(resolveLandingStartParam(new URLSearchParams(), 'ref_saved7')).toBe('ref_SAVED7')
    expect(resolveLandingStartParam(new URLSearchParams('ref=fresh8'), 'ref_saved7')).toBe('ref_FRESH8')
  })
})
