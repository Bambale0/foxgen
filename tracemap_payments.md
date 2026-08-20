# Trace Map: Payments

## 1. Supported payment surfaces

### Telegram bot

- package and provider selection in `bot/handlers/freekassa_payments.py`
- legacy Stars/CryptoBot/Lava callbacks in `bot/handlers/payments.py`
- promo code input
- Telegram Stars pre-checkout + successful payment events

### Mini App

- `POST /mini-app/api/create-payment`
- old internal provider value `yookassa` is a compatibility alias that executes FreeKassa only

### Providers

- `FreeKassa` — card/SBP hosted checkout
- `CryptoBot`
- `Lava`
- `Telegram Stars`
- legacy `T-Bank`

YooKassa SDK and production client were removed.

## 2. Core payment flow

`user selects package`
-> package resolved from `data/price.json`
-> local transaction created in `transactions`
-> provider-specific invoice/session created
-> pending transaction stored with provider metadata
-> user completes payment externally
-> webhook or reconciliation confirms result
-> idempotent completion
-> credits added
-> referral/partner side effects
-> UI notification / balance refresh

## 3. Provider completion map

### FreeKassa

- `/freekassa/webhook`
- `/webhook/freekassa`

Flow:

-> parse POST form-data
-> validate source IP when enabled
-> validate merchant ID
-> validate MD5 signature with Secret word 2
-> resolve local merchant order ID
-> compare exact expected amount
-> persist FreeKassa `intid`
-> duplicate completion guard
-> `_complete_transaction`
-> answer plain `YES`

Checkout URL:

-> SCI parameters `m`, `oa`, `currency`, `o`, `s`
-> signature with Secret word 1
-> hosted `https://pay.fk.money/` page

### CryptoBot

`/cryptobot/webhook`
-> signature validation
-> invoice/order correlation
-> duplicate completion guard
-> `_complete_transaction`

### Lava

`/lava/webhook`
-> JSON parse
-> HMAC validation
-> provider status verification
-> success/failure branch
-> duplicate completion guard
-> `_complete_transaction`

### Telegram Stars

`pre_checkout_query` / `successful_payment`
-> payload parsing
-> order resolution
-> transaction completion

## 4. Reconciliation loops

### FreeKassa reconcile

Cleanup context registered from `bot/handlers/freekassa_payments.py`:

- enabled only when `FREEKASSA_API_KEY` is configured
- polls pending `freekassa` transactions every five minutes
- uses `/v1/orders` by merchant `paymentId`
- resolves paid, failed and pending states

Old Mini App rows with provider=`yookassa` are handled by the FreeKassa-only compatibility adapter.

### Lava reconcile

Background loop in `bot/main.py`:

- rechecks provider state for pending Lava payments
- closes stale pendings safely

## 5. Promo/referral side effects

On successful completion system may:

- apply promo bonus credits
- set `has_paid`
- trigger referral purchase logic
- update partner totals/balance

## 6. Main DB tables

- `transactions`
- `users`
- `promo_codes`
- `promo_redemptions`
- `referrals`
- `partner_withdrawals`

## 7. Invariants

- same order must not complete twice
- provider webhook retry must be safe
- balance increment must happen only after verified completion
- callback merchant, signature and amount must match
- failed payment must not unlock credits
- provider/order correlation must survive delayed callback
- FreeKassa receives `YES` only after successful processing or an already-completed order

## 8. Operational watchpoints

- merchant ID or secret words not configured
- Nginx does not forward `X-Real-IP`
- Result URL in merchant cabinet points to an obsolete path
- provider sends callback before backend sees transaction
- payment already completed via webhook before reconcile loop
- optional API key is missing, so manual status polling is unavailable
