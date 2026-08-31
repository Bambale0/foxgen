# HappyFox backend container

Production backend is deployed as the HappyFox Docker runtime from verified `foxgen/main`.

Canonical runtime identity:

```text
Compose project: foxgen-happyfox
Container:       foxgen-happyfox-bot
Product:         happyfox
```

CI builds an exact-source production image and verifies runtime imports before production deploy.

Do not use old `banano-kling`, Tanya checkout or NEUROMIX Compose identifiers as HappyFox production defaults.

Production deployment should be performed by `.github/workflows/deploy-production.yml` after main CI success. Host-specific Compose/env paths belong to deployment configuration.

Data requirements:

- PostgreSQL HappyFox database;
- isolated Redis prefix/DB;
- persistent HappyFox uploads/media paths;
- external secrets through env, never baked into image.

Instagram code is included in the same image. It registers routes/worker only when `INSTAGRAM_ENABLED=1`; no separate Instagram container is required.

See `production-deployment.md`, `environment.md`, `architecture.md`.
