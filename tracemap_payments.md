# HappyFox payment tracemap

## Shared ledger

HappyFox has one user/balance/transaction domain. Telegram and Instagram do not maintain separate balances.

```text
payment UI/handoff
 -> package/provider
 -> create transaction/invoice
 -> provider payment URL
 -> signed/authenticated provider callback/webhook
 -> idempotent transaction success
 -> credit shared HappyFox balance
 -> generation can spend that balance
```

## Telegram payment surface

Telegram uses its configured payment menu and existing provider handlers.

Potential configured integrations include:

```text
YooKassa
Lava Top
CryptoBot
Telegram Stars
other retained provider adapters where enabled
```

**CryptoBot remains a Telegram provider when configured.** Instagram payment UX must not remove it globally.

## Instagram payment handoff

Instagram paid creator flows need a linked HappyFox user.

```text
Instagram identity
 -> one-time iglink token
 -> Telegram /start iglink_<token>
 -> bind channel identity to users.id
 -> shared balance/history
```

Instagram-specific top-up chooser intentionally exposes only:

```text
YooKassa
Lava Top
```

### YooKassa

```text
Instagram handoff
 -> YooKassa
 -> package
 -> existing buy_yookassa_<package> handler
 -> YooKassa checkout
 -> existing webhook/finalization
 -> shared balance
```

### Lava Top

```text
Instagram handoff
 -> Lava Top
 -> package
 -> Card or SBP
 -> existing Lava handler
 -> existing webhook/finalization
 -> shared balance
```

HappyFox Lava offers are environment-owned and must not reuse imported Tanya offer IDs.

## Resume after payment

```text
payment success
 -> user returns to Instagram Direct
 -> Continue / Продолжить
 -> resolve linked HappyFox user
 -> read current balance
 -> resume saved photo/video flow if sufficient
```

The Instagram channel does not trust a client-side “paid” flag; it rechecks the shared ledger.

## Photo billing

First successful Instagram photo:

```text
promotion reserve -> no paid charge -> provider/result -> promotion consume
```

Terminal free-photo provider failure:

```text
promotion release -> gift preserved
```

Later photo:

```text
confirm 2.5 🐾
 -> prepare durable job
 -> deduct once
 -> provider
 -> success
```

Terminal provider failure -> refund once.

## Video billing

Video is always paid.

```text
Video selected
 -> top-up/paywall before reference upload
 -> Continue after balance is sufficient
 -> reference + prompt
 -> dynamic Seedance 2.5 price confirmation
 -> prepare job
 -> deduct once
 -> provider
```

No free-video entitlement exists.

## Idempotency invariants

```text
[ ] provider payment success cannot credit twice
[ ] generation cannot charge twice on retry
[ ] paid terminal failure cannot refund twice
[ ] free promotion cannot reserve/consume twice concurrently
[ ] duplicate Instagram webhook cannot create duplicate business side effect
[ ] account relinking cannot recreate first-free-photo entitlement
```

## Relevant modules

```text
bot/handlers/payments.py
bot/handlers/instagram_account_link.py
bot/services/yookassa_service.py
bot/services/lava_service.py
bot/channel_link.py
bot/channel_identity.py
bot/channel_promotions.py
bot/instagram_generation.py
bot/database.py
```

## Security

- payment/provider secrets remain environment-only;
- webhook signatures/auth are validated by provider-specific code;
- transaction/provider payment IDs must be idempotent;
- Instagram Meta webhook HMAC is independent from payment provider webhook security;
- never infer payment success from an Instagram message alone.
