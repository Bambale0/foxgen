# HappyFox production cutover

HappyFox is now a standalone product in `Bambale0/foxgen` based on the exact proven source snapshot `Bambale0/banano_kling@36f92a0504f849c0c591652a880410e33a1c89aa`.

The previous experimental FoxGen tree is preserved at `legacy/foxgen-pre-tanyapi-20260820`.

## Hard isolation rules

HappyFox production must never reuse NEUROMIX/Tanya product credentials or data-plane identifiers.

Required separate values:

- Telegram `BOT_TOKEN`;
- public `WEBHOOK_HOST`;
- `MINI_APP_URL` and `MINIAPP_FRONTEND_DOMAIN`;
- PostgreSQL database/user;
- Redis DB/prefix (`foxgen_happyfox` recommended);
- KIE/provider webhook secret;
- internal API secret;
- payment credentials when using an external payment provider;
- public media/static origin;
- Telegram admin IDs.

`python scripts/validate_happyfox_env.py .env .env.postgres` is a mandatory fail-closed preflight. It rejects known NEUROMIX/Tanya domains, SQLite production, a shared legacy Redis prefix, missing provider/webhook secrets and incomplete selected-payment-provider credentials.

## Server preparation

The existing FoxGen production SSH target can be reused. Keep the checkout isolated at `/root/foxgen` (or the repository production variable `DEPLOY_PATH`).

1. Back up the previous FoxGen data and `.env`.
2. Create a dedicated PostgreSQL database/user for HappyFox.
3. Allocate a dedicated Redis database and set `REDIS_PREFIX=foxgen_happyfox`.
4. Build `.env` from `.env.happyfox.example`; never copy the NEUROMIX `.env` wholesale.
5. Configure the HappyFox backend and Mini App DNS/TLS before the first deployment.
6. Set the GitHub production variable `MINIAPP_FRONTEND_DOMAIN` to the HappyFox Mini App hostname only.
7. Run the validator before changing any running service.

## Deployment

The GitHub workflow `.github/workflows/deploy-production.yml` deploys only a verified `main` SHA after `CI` succeeds (or an explicitly requested manual `main` SHA).

The remote deployment is intentionally split into two guarded wrappers:

- `scripts/deploy_happyfox.sh` — validates product/data-plane isolation, then invokes the proven tanyapi Docker deployment lifecycle with HappyFox service/container identities;
- `scripts/deploy_happyfox_miniapp.sh` — requires an explicit non-Tanya frontend domain, forces `NEXT_PUBLIC_PRODUCT_ID=happyfox`, and invokes the proven static Next.js deployment script.

Expected runtime identities:

- Compose project: `foxgen-happyfox`;
- container: `foxgen-happyfox-bot`;
- rollback service (if intentionally installed): `foxgen-happyfox.service`;
- product id: `happyfox`.

## Acceptance smoke

After deploy:

```bash
cd /root/foxgen
python scripts/validate_happyfox_env.py .env .env.postgres
docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' foxgen-happyfox-bot
curl -fsS "$WEBHOOK_HOST/health"
curl -fsS "https://$MINIAPP_FRONTEND_DOMAIN/mini-app/revision.txt"
```

Then open the HappyFox bot in Telegram and verify:

1. `/start` shows HappyFox copy and opens only the HappyFox Mini App.
2. Telegram auth/bootstrap succeeds.
3. Create image/video flows render their actual backend options.
4. Upload/reference flow works.
5. A low-cost generation reaches history/result delivery.
6. Balance/payment surface uses the HappyFox account only.
7. Feed/profile/support/partner surfaces load without NEUROMIX branding or URLs.

Do not cut over DNS or bot menu to this build until the GitHub deployment status `foxgen/production-deploy` is successful for the intended exact SHA.
