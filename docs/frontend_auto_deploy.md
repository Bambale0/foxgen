# Frontend auto-deploy — HappyFox note

The old NEUROMIX/Tanya frontend auto-deploy procedure has been retired for `Bambale0/foxgen`.

HappyFox Mini App is part of the exact-SHA `main` release path:

```text
PR -> main CI -> merge -> main CI -> Deploy HappyFox production
```

Canonical sources:

- `../README.md`
- `development-deployment.md`
- `production-deployment.md`
- `production_auto_deploy.md`
- `../frontend/miniapp-v0/README.md`
- `.github/workflows/ci.yml`
- `.github/workflows/deploy-production.yml`

Do not use old `tanyapi`, `cdn.chillcreative.ru`, `cdn.sh`, Tanya frontend profiles or NEUROMIX checkout paths as HappyFox production instructions.

The current public HappyFox Mini App is documented as `https://alena.chillcreative.ru/mini-app/`; host-specific deployment paths remain runtime/environment configuration.
