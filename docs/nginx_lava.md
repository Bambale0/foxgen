# Lava Top routing — HappyFox note

Historical Nginx/Lava instructions from the imported NEUROMIX runtime are not the HappyFox source of truth.

HappyFox Lava Top uses the existing application payment handlers/webhooks configured through HappyFox environment. Production reverse-proxy routes must match the current application/runtime and `.env.happyfox.example`, not copied Tanya paths.

Instagram uses Lava Top only as one of two visible top-up providers, with package -> card/SBP flow. Telegram payment configuration remains independent and can keep CryptoBot.

For current operations use:

- `environment.md` — `LAVA_*` configuration;
- `production-deployment.md` — reverse-proxy/deploy boundary;
- `troubleshooting.md` — Lava/Instagram diagnostics;
- `../tracemap_payments.md` — payment lifecycle.

Never reuse imported Tanya `LAVA_OFFER_ID_*` values for HappyFox.
