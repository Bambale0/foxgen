# AGENTS.md — FoxGen repository instructions

## Mission
Build FoxGen as a production-grade multimodal generation platform through small, reviewable pull requests.

## Required discovery
Before editing, inspect README, open epics, nearby code, tests, configuration examples, migrations and CI.
Обязательно обновляй и сопровождай документацию при изменении поведения, API, схем или деплоя.

## Engineering rules
- Do not invent KIE.ai model IDs, request fields or callback payloads. Verify them against official documentation and add a contract test.
- Keep Telegram handlers thin. Business logic belongs in domain/application services.
- Every FSM state must define success, back, cancel, timeout, invalid-input and stale-callback behavior.
- Use PostgreSQL for durable business data and Redis for ephemeral FSM, cache, locks and queues.
- All money changes must use an immutable ledger and transactional idempotency.
- External calls require explicit timeouts, normalized errors and bounded retries.
- Never commit secrets, production data or real user media.
- Add or update tests for every behavior change.
- Run `make ci` before opening or updating a PR.

## Delivery
Use conventional commits. PR descriptions must include scope, tests, migration impact, rollback and linked issue.
