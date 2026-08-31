# HappyFox Mini App installation note

Historical NEUROMIX/Tanya automatic installer steps in this file are retired for HappyFox.

HappyFox frontend source is `frontend/miniapp-v0`; build validation is performed by repository CI and production is deployed from the exact verified `main` SHA.

Use:

- `miniapp-frontend-deployment.md` for current Mini App release expectations;
- `production-deployment.md` for production rollout;
- `environment.md` for public/backend URLs and product config;
- `.github/workflows/ci.yml` and `.github/workflows/deploy-production.yml` as executable source of truth.

Do not install HappyFox using old Tanya source directories, `tanyapi` branch assumptions, legacy CDN profiles or copied NEUROMIX `.env` files.
