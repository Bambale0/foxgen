# HappyFox frontend/CDN management note

The old `cdn.sh` Tanya/NEUROMIX profile workflow is not the canonical HappyFox production deployment path.

HappyFox Mini App is released from the same verified `foxgen/main` SHA as the backend through the current CI/deploy workflows.

Current public Mini App:

```text
https://alena.chillcreative.ru/mini-app/
```

Use:

- `miniapp-frontend-deployment.md`;
- `production-deployment.md`;
- `production_auto_deploy.md`;
- `../frontend/miniapp-v0/README.md`;
- current `.github/workflows/*`.

Do not use old `/etc/banano-miniapp` profiles, Tanya source paths, `tanyapi` branch rules or legacy CDN domains as HappyFox production instructions.

If a future HappyFox CDN manager is adopted, document its exact profile paths, source branch, rollback and revision validation as a new HappyFox-specific contract rather than reviving the legacy workflow implicitly.
