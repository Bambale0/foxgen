# Documentation policy

FoxGen documentation is maintained as part of executable product changes, not as an after-the-fact narrative.

## Authority order

When sources disagree, resolve in this order:

1. Alembic migrations/database constraints for deployed schema history;
2. domain/application code for legal business behavior;
3. tests for explicit expected invariants;
4. runtime router/dispatcher wiring for what is actually reachable;
5. environment/Compose/workflow files for deployment configuration;
6. documentation.

Documentation must then be corrected. The lower authority does not override executable behavior.

## Current-state vs roadmap

Current-state documentation must describe only code reachable/merged in `main`.

Examples:

- a Python module existing in the tree is not enough if its router is not registered;
- an open PR is not production behavior;
- a catalog model is not a paid production model unless readiness/admission gates allow it;
- a planned Telegram menu button is not an implemented product flow;
- a backend admin contract is not evidence of a finished public Mini App UI.

Known but unresolved differences belong in `known-limitations.md` and a tracked issue/PR when appropriate.

## Required updates by change type

### API

Update:

- `api-reference.md`;
- auth/security docs if trust boundary changes;
- README when user/operator-facing capability changes.

### Telegram/FSM

Update:

- `telegram-flows.md`;
- `state-gap-audit.md` for new state classes/gaps;
- input lifecycle doc when media ownership changes.

### Database/state

Update:

- `database-schema.md`;
- `architecture.md`;
- state/reconciliation/billing docs as relevant;
- rollback notes.

### Provider/model

Update:

- `model-matrix.md`;
- API/Telegram docs for new modes;
- pricing docs when commercial availability changes.

### Billing/payment

Update:

- `billing.md`;
- schema/API/admin docs;
- reconciliation/operator runbook.

### Admin

Update:

- `admin-capability-matrix.md`;
- `admin-control-plane.md`;
- `api-reference.md`;
- Telegram docs when `/admin` changes;
- `known-limitations.md` if transport parity changes.

### Deployment/configuration

Update:

- `configuration.md`;
- `.env.example`;
- `deploy/production.env.example`;
- `production-deploy.md`;
- `github-environment-setup.md`;
- operations runbook.

## Language and terminology

Code identifiers/routes/env vars stay exact. Prose should be clear and operational, avoiding ambiguous marketing claims.

Use these meanings consistently:

- `production_ready` — registry contract/readiness condition, not proof the model is runtime-enabled/priced/funded;
- `succeeded` — generation fully archived and delivered, not merely provider-complete;
- `submission_unknown` — provider billing side effect is ambiguous; never shorthand for retry;
- `delivery_unknown` — Telegram send side effect is ambiguous; never shorthand for resend;
- `admin web/operator surface` — internal backend surface, not public Mini App;
- `planned` — visible/roadmapped but not implemented end-to-end.

## Security redaction in documentation

Examples must use placeholders. Never copy real:

- Telegram tokens;
- API/HMAC keys;
- production SSH private keys;
- database/Redis/storage credentials;
- user media URLs with live signatures;
- actual private admin session tokens.

If a real credential was accidentally published, rotate it; editing documentation is not sufficient containment.

## Link policy

Prefer relative links between repository docs so branches/PR previews work. External provider docs can be linked when a contract change specifically depends on them, but executable provider tests/contracts remain the local implementation source.

## Historical documents

Audits can remain when useful, but must clearly state whether they are historical and what their current completion status is. Do not leave old "remaining" sections that contradict merged code.

## Review checklist

A documentation PR/change should verify:

- all referenced paths exist;
- route names match registered routers;
- env var names match `Settings`/Compose;
- state lists match current enums/check constraints;
- open PR behavior is not described as merged;
- repo visibility/deployment assumptions are current;
- public Mini App scope is explicit;
- known limitations are not hidden;
- runbook commands are safe for the named environment.

## Baseline refresh

The complete documentation refresh performed after admin-control-plane PR #54 establishes this policy and a full index under `docs/README.md`. Future changes should be incremental and keep the baseline synchronized rather than requiring another large catch-up audit.