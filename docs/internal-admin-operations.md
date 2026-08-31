# Historical internal admin operations contract

This file described an older Tanya Admin operations API. It is not a current HappyFox production contract unless the endpoint exists in current runtime code and has current tests.

Current operational sources:

- `runbook.md`;
- `production-deployment.md`;
- `troubleshooting.md`;
- GitHub Actions CI/deploy workflows;
- `internal-admin-api.md` for current read-only `/internal/v1` routes.

Do not restart containers, run maintenance commands or mutate production state through an undocumented historical `/internal/admin/*` endpoint.

Any future HappyFox operations API must be explicit about authorization, confirmation, idempotency, audit trail and rollback semantics before rollout.
