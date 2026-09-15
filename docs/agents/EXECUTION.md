# Agent execution ledger

## Active Feature Execution

### Task

Adapt `AGENTS.md` in `Bambale0/foxgen` from the stronger repository-instruction baseline used by `Bambale0/start`, while preserving HappyFox-specific constraints.

### Baseline

- Repository: `Bambale0/foxgen`
- Base branch: `main`
- Baseline SHA: `cfa94e102fe745b26623fbc12c582ddefc0e9ac1`
- Working branch: `docs/adapt-agents-from-start`

### Fresh audit

What already exists:

- A production `AGENTS.md` with global engineering, observability, skill-discovery, safety, HappyFox branding, and MAX/Telegram/Mini App parity rules.
- HappyFox repository documentation in `README.md` and `docs/`.
- Exact-SHA CI/CD with backend regression, dependency audit, Mini App lint/build/unit/E2E, Telegram/MAX browser startup checks, and production Docker verification.
- Production source-of-truth documentation in `docs/production-deployment.md`.
- PostgreSQL as the production relational data plane and Redis for FSM/cache/runtime coordination.

What is partial:

- The current `AGENTS.md` contains some of the Start/AuRoom shared baseline, but the stronger Start feature-preflight, execution-ledger, verification-layer, and completion-gate rules are not organized as the primary repository workflow.
- The mandatory skill source set is spread across multiple sections rather than one explicit playbook.
- The file does not begin with an explicit 100% compliance rule.

What is missing:

- An explicit top-level rule that every applicable `AGENTS.md` requirement must be followed and that work cannot be called complete when an applicable requirement is unverified.
- A Foxgen-adapted version of Start's feature preflight and live execution ledger.
- A single coherent HappyFox-specific architecture/control-plane/release section based on Start's engineering baseline.
- An explicit project-isolation rule preventing accidental work in neighboring repositories such as APIX/KSU/Tanyapi unless requested.

Reusable material:

- `Bambale0/start/AGENTS.md` for the stronger engineering workflow.
- Existing Foxgen `AGENTS.md` for connected-agent skill access, HappyFox naming, safety, observability, and release parity.
- `Bambale0/skills/skills/engineering/ask-matt/SKILL.md` as the primary engineering-flow router.
- `Bambale0/claw/AGENTS.md` for repository/skill discovery discipline.
- `wondelai/skills/technical-documentation/SKILL.md` for documentation structure and fact verification.

### Skills/guides reviewed

- `Bambale0/skills`: `skills/engineering/ask-matt/SKILL.md`
- `Bambale0/claw`: `AGENTS.md`
- `wondelai/skills`: `technical-documentation/SKILL.md`
- `anthropics/skills`: searched for relevant repository-instruction/documentation guidance; no directly applicable skill was identified, so no unrelated skill is being forced into the change.

### Intended outcome and acceptance criteria

1. `AGENTS.md` begins with an explicit 100% compliance requirement.
2. The file is structurally based on the stronger Start workflow, adapted to HappyFox rather than copied blindly.
3. HappyFox-specific constraints remain explicit:
   - HappyFox is the only public brand.
   - MAX bot, Telegram bot, and Mini App release parity is mandatory.
   - Instagram applicability is evaluated when shared-core behavior changes.
   - HappyFox application/data plane remains on the dedicated HappyFox production host; APIX is only the documented Telegram transport relay.
   - Work scoped to Foxgen does not modify neighboring repositories unless the user explicitly asks.
4. Skill discovery includes `Bambale0/skills` as primary plus `Bambale0/claw`, `wondelai/skills`, and `anthropics/skills`.
5. Feature work requires a fresh audit, live execution ledger, no-hardcode gate, observability plan, test seams, verification layers, exact-SHA CI evidence, and final review.
6. No product code, runtime configuration, secrets, schema, API, or deployment behavior changes.
7. Documentation remains internally consistent and reviewable.

### No-hardcode/configuration decision

Not applicable to runtime behavior. This change defines engineering process only and adds no mutable business configuration.

### Schema/API/UI changes

None.

### Permissions/security scope

No authorization or tenant/runtime security behavior changes. The instructions strengthen server-side authorization and secret-handling expectations.

### Observability plan

No runtime code changes. The adapted file preserves and strengthens observability-first requirements for future engineering work.

### Test seams

For this documentation-only change:

- factual consistency check against current repository docs and CI;
- Git diff review;
- PR CI on the exact commit;
- no runtime smoke is required solely because Markdown instructions changed, unless repository CI runs it automatically.

### Migration/rollout plan

No database or runtime migration. Merge the documentation change through the normal PR path after exact-commit CI is green.

### Implementation steps

1. [x] Read current Foxgen `AGENTS.md`.
2. [x] Read Start `AGENTS.md`.
3. [x] Review relevant repository docs, CI, deployment, dependencies, and tests.
4. [x] Review mandatory skill sources.
5. [x] Create this execution ledger before editing `AGENTS.md`.
6. [ ] Rewrite `AGENTS.md` using Start as the baseline and HappyFox constraints as repository-specific extensions.
7. [ ] Review the diff for lost Foxgen constraints and accidental Start-only concepts.
8. [ ] Open PR.
9. [ ] Verify CI for the exact PR commit.
10. [ ] Complete code/documentation review and merge if all gates are green.
11. [ ] Record final verification here.

### Risks

- Blindly copying Start would introduce irrelevant multi-company/tenant concepts; adaptation must preserve only generally useful engineering rules.
- Replacing Foxgen's current file could accidentally weaken HappyFox parity, production-isolation, or connected-agent skill rules; these must be retained explicitly.
- Overly broad process rules can become contradictory; the final file should state precedence and applicability clearly.

### Follow-ups

None planned beyond keeping this ledger as the repository's execution-history location when `CONTEXT.md` is absent.
