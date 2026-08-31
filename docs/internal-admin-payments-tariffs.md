# Historical internal admin payments/tariffs contract

This document described an older `/internal/admin/*` integration for Tanya Admin. The current HappyFox runtime does not expose that documented control-plane contract and it must not be used as a production runbook.

Current payment source of truth:

- `bot/handlers/payments.py` and provider handlers/services;
- `data/price.json` + current pricing helpers;
- `tracemap_payments.md`;
- `environment.md`;
- regression tests.

Current channel rule:

```text
Instagram top-up: YooKassa + Lava Top
Telegram payment UI: configured Telegram providers, including CryptoBot when enabled
```

Any future administrative recheck/reprocess/tariff-publish API must be implemented and tested explicitly before documentation claims those endpoints exist.

For current read-only internal API see `internal-admin-api.md` (`/internal/v1/health`, `/internal/v1/stats`).
