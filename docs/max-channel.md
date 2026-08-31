# HappyFox MAX channel

MAX is a separate HappyFox delivery channel with its own users, balance, payment orders, referrals, FSM sessions, generation history and event receipts. It may reuse low-level AI provider clients and the HappyFox YooKassa merchant credentials, but it must never read or mutate Telegram user balances, Telegram transactions, Telegram referrals or Telegram FSM state.

## Live activation

The MAX runtime is fail-closed and is not registered unless:

```dotenv
MAX_ENABLED=1
MAX_ACCESS_TOKEN=...
MAX_WEBHOOK_SECRET=...
MAX_WEBHOOK_URL=https://api.example.com/max/webhook
MAX_WEBHOOK_PATH=/max/webhook
MAX_API_BASE=https://platform-api2.max.ru
MAX_BOT_NAME=your_bot_name
MAX_MINI_APP_URL=https://app.example.com/mini-app/
MAX_PAYMENT_RETURN_URL=https://max.ru/your_bot_name?start=max_payment
MAX_PAYMENT_RECONCILE_SECONDS=30
```

`MAX_WEBHOOK_URL` must be HTTPS and its path must match `MAX_WEBHOOK_PATH`. The runtime checks the current webhook subscriptions at startup and creates the expected subscription when it is missing. It does not automatically delete or replace unrelated subscriptions.

Production MAX uses Webhook. The registered update types are:

```text
bot_started
message_created
message_callback
```

Incoming requests must contain the configured secret in `X-Max-Bot-Api-Secret`. Event receipts are stored before execution so duplicate deliveries are idempotent; a failed handler releases the receipt and returns an error so MAX can retry.

## Runtime composition

```text
MAX Webhook
   │
   ▼
bot/max_api.py              transport / auth / callback answers / media upload
   │
   ▼
bot/max_channel.py          Update normalization + MAX FSM adapter
   ├── bot/max_store.py     MAX users / balance / sessions / history / dedupe
   ├── bot/max_payments.py  MAX YooKassa orders + referrals
   └── bot/max_generation.py durable generation jobs / provider lifecycle
                                  │
                                  └── shared low-level AI provider clients
```

`bot/max_runtime.py` is the composition root. It registers the webhook route, validates the live configuration, verifies/creates the MAX subscription, starts the isolated generation worker and starts YooKassa reconciliation.

## Creator flows

### Photo

```text
Home
→ Create photo
→ model
→ prompt + optional image reference
→ confirmation with live MAX price
→ isolated MAX balance debit
→ durable generation job
→ provider
→ result delivered back to MAX
```

Seedream 4.5 Edit and Grok image-to-image require an image reference. Other exposed image models can run without a reference when their provider supports text-to-image.

### Video

```text
Home
→ Create video
→ Text→Video / Photo→Video / Video→Video
→ model
→ prompt + required media
→ confirmation with live MAX price
→ isolated debit
→ durable generation job
→ provider
→ result upload/delivery back to MAX
```

The first live MAX runtime uses safe defaults for duration, 16:9, 720p and audio where supported. More granular settings can be added without changing the ledger or transport boundary.

## Billing

MAX YooKassa orders live in `max_payment_orders`. A successful provider response is never trusted by status alone. Before crediting, the runtime verifies:

- provider payment ID;
- RUB currency;
- exact local amount;
- local order ID in provider metadata;
- `product=happyfox-max`;
- `channel=max`;
- matching MAX user ID.

Credits are applied through the MAX ledger with an idempotency key derived from the local order. Reconciliation runs in the background and the user can also press `Проверить оплату`. A retry cannot credit the same order twice.

Telegram `transactions` are not used for MAX orders.

## Referrals

Bot deep links use the MAX format:

```text
https://max.ru/<botName>?start=ref_<max_user_id>
```

`bot_started.payload` records at most one referral edge per invited MAX user. Self-referrals and referral cycles are rejected. Signup rewards and purchase rewards are MAX ledger entries with idempotency keys.

The independent MAX pricing snapshot currently mirrors HappyFox economics:

- invited user signup bonus: 5 🐾;
- inviter signup bonus: 3 🐾;
- level 1 purchase reward: 30%;
- level 2 purchase reward: 7%;
- RUB rewards are converted to MAX 🐾 using `partner_exchange.rub_per_credit` from `data/max_price.json`.

These values are owned by `data/max_price.json`; changing Telegram referral constants does not silently change MAX.

## Dark-by-default contract

Production deployments may safely contain all MAX code with:

```dotenv
MAX_ENABLED=0
```

In that state no MAX route, worker, API client or webhook subscription is started. Enabling the channel is an explicit operations step after the MAX bot token/name and public webhook are configured.
