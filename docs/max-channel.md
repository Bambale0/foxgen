# HappyFox MAX channel

MAX is a HappyFox delivery channel with **Telegram-parity UX** and its own native identity/state/ledger boundary.

The user-facing product contract is intentionally the same as Telegram wherever MAX supports the same interaction primitive. MAX must never fake Telegram identities or reuse Telegram FSM/balance tables merely to achieve visual parity.

## UX source of truth

Telegram Bot is the reference contract for MAX screens and navigation.

For every applicable user-facing change, MAX must mirror Telegram:

- screen purpose and order;
- visible button labels, grouping and order;
- creator step order;
- model/options visibility;
- back/home/cancel/confirm behavior;
- validation and retry copy;
- balance/top-up navigation;
- result actions and post-generation navigation.

Current main-menu contract:

```text
🚀 Открыть Mini App
🖼 Создать фото          🎬 Создать видео
🎯 Motion Control        ✍️ Промпт по описанию
🎞 Промпт по видео       🤖 AI-помощник
📚 Библиотека промптов   🖼 Лента
🍌 Баланс                💬 Поддержка
🤝 Партнёрам             ⋯ Ещё
```

A platform limitation may change transport mechanics, but not the intended user outcome. Any unavoidable difference must be covered by an explicit equivalent fallback and regression test.

## Isolation boundary

MAX keeps its own:

- native MAX `user_id` identities;
- balance and ledger;
- payment orders;
- referrals;
- persisted wizard sessions;
- generation history/event receipts;
- administrator roles.

MAX may reuse channel-neutral provider clients, durable generation services, prompt-analysis services and HappyFox merchant credentials where the product contract allows it.

It must never read or mutate Telegram user balances, Telegram transactions, Telegram referrals or Telegram FSM state.

## Production topology

```text
Landing:      https://happy-fox.online/
Mini App:     https://app.happy-fox.online/mini-app/
API:          https://api.happy-fox.online
MAX webhook:  https://api.happy-fox.online/max/webhook
```

The dedicated `happyfox` host owns the application/data plane. `apix` is a Telegram transport relay only and is not a MAX or HappyFox application host.

## Live activation

The MAX runtime is fail-closed and is not registered unless:

```dotenv
MAX_ENABLED=1
MAX_ACCESS_TOKEN=...
MAX_WEBHOOK_SECRET=...
MAX_WEBHOOK_URL=https://api.happy-fox.online/max/webhook
MAX_WEBHOOK_PATH=/max/webhook
MAX_API_BASE=https://platform-api2.max.ru
MAX_BOT_NAME=your_bot_name
MAX_MINI_APP_URL=https://app.happy-fox.online/mini-app/
MAX_PAYMENT_RETURN_URL=https://max.ru/your_bot_name?start=max_payment
MAX_PAYMENT_RECONCILE_SECONDS=30
```

`MAX_WEBHOOK_URL` must be HTTPS and its path must match `MAX_WEBHOOK_PATH`.

Production MAX uses Webhook with:

```text
bot_started
message_created
message_callback
```

Incoming requests require the configured secret in `X-Max-Bot-Api-Secret`. Event receipts are claimed before execution so duplicate deliveries remain idempotent.

## Runtime composition

```text
MAX Webhook
   │
   ▼
bot/max_api.py                  transport / auth / callback answers / media
   │
   ▼
bot/max_admin_channel.py        production composition surface
   │
   ├─ bot/max_creation_parity.py Telegram creator-step parity
   ├─ bot/max_parity_channel.py  main/balance/feed/prompt-analysis parity
   ├─ bot/max_product_channel.py product screens/services
   ├─ bot/max_seedance25.py      dedicated Seedance 2.5 wizard
   ├─ bot/max_store.py           MAX users / balance / sessions / dedupe
   ├─ bot/max_payments.py        MAX YooKassa orders + referrals
   └─ bot/max_generation.py      durable generation lifecycle
                                      │
                                      └─ shared provider clients
```

`bot/max_runtime.py` is the composition root.

## Creator flows

### Photo

MAX follows the Telegram creator order:

```text
Home
→ Create photo
→ model
→ references / skip
→ ratio / quality / count settings
→ prompt
→ confirmation
→ isolated MAX balance debit
→ durable generation job(s)
→ provider
→ result delivered to MAX
```

Seedream 4.5 Edit and Grok image-to-image require an image reference. Multiple-image count is represented as multiple independently durable MAX jobs so each provider execution retains its own charge/refund lifecycle.

### Video

MAX follows the Telegram creator order:

```text
Home
→ Create video
→ model
→ source type
→ required media/references
→ duration / ratio / model-specific settings
→ prompt
→ confirmation
→ isolated debit
→ durable generation job
→ provider
→ result delivered to MAX
```

Seedance 2.5 keeps its dedicated full settings/media FSM, but it is entered from the same model-first Telegram navigation contract.

## Prompt analysis

`Промпт по описанию` and `Промпт по видео` reuse the shared HappyFox analysis services but use MAX-native sessions and MAX-native idempotent balance movements.

If analysis fails after debit, the MAX ledger receives one idempotent refund for that analysis event.

## Billing

MAX YooKassa orders live in `max_payment_orders`. Before crediting, reconciliation verifies:

- provider payment ID;
- RUB currency;
- exact local amount;
- local order ID in provider metadata;
- `product=happyfox-max`;
- `channel=max`;
- matching MAX user ID.

Credits are applied through the MAX ledger with an idempotency key derived from the local order. Telegram `transactions` are not used for MAX orders.

User-facing balance terminology follows the current Telegram screen contract (`🍌`) even though the underlying MAX ledger is isolated.

## Referrals

Bot deep links use:

```text
https://max.ru/<botName>?start=ref_<max_user_id>
```

`bot_started.payload` records at most one referral edge per invited MAX user. Self-referrals and referral cycles are rejected. Signup and purchase rewards are MAX-ledger entries with idempotency keys.

Economics remain owned by `data/max_price.json`; UX parity does not mean silently sharing Telegram database state.

## Release gate

MAX parity is a release invariant. Before merge/deploy, regression coverage must verify at least:

1. main-menu visible labels/order;
2. every main-menu callback is actionable;
3. photo: model → refs → settings → prompt → confirm;
4. video: model → type → media → settings → prompt → confirm;
5. specialized wizards such as Seedance 2.5 remain reachable;
6. prompt analysis uses MAX balance and refunds failures once;
7. MAX never mutates Telegram balance/FSM tables;
8. production runtime composes the parity layer;
9. Mini App URL remains `https://app.happy-fox.online/mini-app/`.

## Dark-by-default contract

Production deployments may safely contain all MAX code with:

```dotenv
MAX_ENABLED=0
```

In that state no MAX route, worker, API client or webhook subscription starts. Enabling the channel is an explicit operations step after the MAX bot token/name and public webhook are configured.
