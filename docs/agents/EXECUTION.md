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

- `Bambale0/skills`: `skills/engineering/ask-matt/SKILL.md`, `skills/engineering/code-review/SKILL.md`
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
6. [x] Rewrite `AGENTS.md` using Start as the baseline and HappyFox constraints as repository-specific extensions.
7. [x] Review the diff for lost Foxgen constraints and accidental Start-only concepts.
8. [x] Open PR #250.
9. [x] Earlier exact-head CI #1305 succeeded for `914025df758c1c9694b4e158df89107ee5cd0391`; later policy edits intentionally invalidated that SHA as the merge candidate.
10. [x] Run the `Bambale0/skills` `code-review` flow against fixed point `main` on both Standards and Spec axes; resolve findings.
11. [ ] Run full exact-SHA CI for the final review-clean branch head. The authoritative evidence is the GitHub check attached to that immutable head SHA; do not edit this ledger after it passes merely to copy the run number, because that would create a new untested SHA.
12. [ ] Merge PR #250 after review + final-head CI are green.
13. [ ] Verify canonical HappyFox auto-deploy, deployed revision, health, and channel reconciliation.
14. [ ] Record post-merge/deploy verification in the PR/deployment record without mutating the already-tested source solely to embed its own CI result.

### Review evidence

Static review after the AGENTS rewrite confirmed:

- the file begins with the 100% compliance contract;
- no Start-only multi-company/vertical-pack concepts are present;
- HappyFox branding remains explicit;
- MAX/Telegram/Mini App parity remains explicit;
- Instagram applicability is explicit;
- APIX remains transport-only;
- Foxgen project isolation is explicit;
- all four mandatory engineering/skill sources are named;
- no runtime code, schema, API, secret, provider, pricing, or deployment behavior changed.

### Code review — Standards axis

Fixed point: `main` at `cfa94e102fe745b26623fbc12c582ddefc0e9ac1`.

Reviewed the PR diff against the repository instruction contract, Start-derived engineering baseline, documentation guidance, and the reviewer skill's smell baseline.

Findings:

1. **Hard documentation/process finding — resolved:** the execution ledger still named an obsolete intermediate SHA (`b1528f90...`) as the pending exact-head CI target after later commits had moved the branch. This violated the live-ledger/current-evidence requirement. The stale reference is replaced with historical evidence plus an explicit final-head CI gate.
2. **Hard evidence finding — resolved:** the ledger listed `ask-matt` but not the `code-review` skill actually used for this review. The reviewed-skill list is updated.
3. Code-smell baseline: N/A for runtime code because the PR changes only Markdown process documentation. No material documentation duplication or contradictory release rule remains after the clarified canonical auto-deploy exception.

Standards result after fixes: **clean; 0 unresolved findings**.

### Code review — Spec axis

Originating requirements:

- adapt the stronger `Bambale0/start` AGENTS workflow to HappyFox rather than blindly copying Start-specific product rules;
- place an explicit 100% AGENTS-compliance rule at the beginning;
- always use the repository's AGENTS instructions;
- use a branch, invoke the reviewer skill, drive checks/review to green, merge through PR, then allow canonical auto-deploy instead of direct changes to `main`;
- do not require a separate confirmation for the canonical exact-SHA production checkout reset when it occurs inside that approved reviewed/green auto-deploy path.

Result:

- 100% compliance contract: implemented at the top of `AGENTS.md`;
- Start engineering workflow: adapted;
- HappyFox-specific branding, project isolation, APIX transport-only boundary, observability, parity, and production invariants: retained;
- direct-to-main changes: explicitly prohibited;
- reviewer skill gate: explicit;
- exact-head CI gate: explicit;
- canonical auto-deploy authorization: explicit and narrowly scoped;
- manual/destructive reset outside canonical deploy: still prohibited without explicit approval;
- Start-only multi-company/vertical-pack concepts: not introduced.

Spec result: **clean; 0 unresolved findings**.

### Risks

- Blindly copying Start would introduce irrelevant multi-company/tenant concepts; adaptation must preserve only generally useful engineering rules.
- Replacing Foxgen's current file could accidentally weaken HappyFox parity, production-isolation, or connected-agent skill rules; these must be retained explicitly.
- Overly broad process rules can become contradictory; the final file should state precedence and applicability clearly.

### Follow-ups

None planned beyond keeping this ledger as the repository's execution-history location when `CONTEXT.md` is absent.


### User-approved release workflow

The user explicitly clarified the required engineering path:

`branch → reviewer skill → green review/checks → PR merge → canonical auto-deploy`.

Direct changes to `main` are not allowed for ordinary engineering work. The canonical deploy workflow's exact-SHA synchronization, including its existing `git reset --hard "$EXPECTED_SHA"`, is authorized without a separate confirmation when it runs only as part of this reviewed, green, exact-SHA auto-deploy path. Manual/destructive resets outside that path remain prohibited without specific approval.

The current execution environment does not expose the parallel `Agent` sub-agent tool referenced by the `code-review` skill. The two required review axes will therefore be executed independently in this session against the same fixed point and reported separately; this platform limitation must not be represented as the literal parallel-subagent implementation.


---

## Active Bugfix — Telegram Mini App launch context

### Task

Fix HappyFox Telegram Mini App launches that started falling out of Telegram WebView context, opening as a normal browser page and triggering browser authentication.

### Baseline

- Repository: `Bambale0/foxgen`
- Original production/main baseline investigated: `cfa94e102fe745b26623fbc12c582ddefc0e9ac1`
- Current main policy baseline reviewed during the task: `a01bedc79767cbde4ad248cbf0bf95b6d6006a72`
- Working branch: `fix/telegram-miniapp-browser-auth`
- PR: #252

### Fresh audit and runtime evidence

What already exists:

- Telegram main-menu Mini App button is a real `InlineKeyboardButton(..., web_app=WebAppInfo(...))`, not a plain URL.
- HappyFox intentionally keeps the Telegram chat menu as commands and opens Mini App from explicit inline WebApp buttons.
- Browser authentication is an intentional fallback when Telegram `initData` is absent.
- Shared Telegram/MAX Mini App frontend already has startup browser E2E and production static-export checks.

Observed production symptom:

- Production Mini App bootstrap requests returned 401 with `Missing init_data`.
- The frontend then called the browser-auth fallback endpoint.
- The deployed bot and repository were on the same revision, so stale container/source drift was ruled out.

Regression source narrowed to:

- the shared MAX bootstrap introduced on 2026-09-13 loaded the MAX bridge before preserving Telegram launch parameters;
- shared platform detection checked MAX before Telegram;
- this allowed shared bridge startup to consume/alter launch context before Telegram `tgWebAppData` had been safely captured.

Reusable seams:

- Mini App `<head>` bootstrap order;
- `getMiniAppPlatform()` and launch-data recovery;
- static export patcher contract;
- Chromium + iPhone WebKit Telegram/MAX startup E2E.

### Intended outcome and acceptance criteria

1. Telegram launch parameters are captured before the MAX bridge loads.
2. Telegram launch data has priority when Telegram and MAX bridge signals coexist.
3. Telegram `initData` can be recovered from the immutable pre-MAX launch snapshot.
4. MAX Mini App startup remains functional.
5. Browser-auth remains available only as fallback for genuine non-Mini-App browser opens.
6. No mutable business configuration is hardcoded.
7. Telegram and MAX startup E2E pass on Chromium and iPhone WebKit.
8. Backend regression, dependency audit, callback load, static export, and production Docker verification pass for the exact PR head.
9. PR is merged through the normal reviewed/green path and canonical exact-SHA auto-deploy is verified.

### No-hardcode/configuration decision

N/A. This is a launch-context regression fix. No prices, providers, routing policy, feature flags, secrets, or mutable operational values are introduced.

### Schema/API/UI changes

- Database/schema: none.
- Public API: none.
- User-visible UI: no intended visual change; Telegram Mini App should remain inside the Telegram WebView instead of entering browser-auth fallback.
- MAX: no intended behavioral regression.

### Permissions/security scope

- Telegram `initData` validation remains server-side and unchanged.
- The change does not weaken authorization or treat client-side launch data as authority beyond the existing signed Telegram validation path.
- No secrets or raw auth payloads are added to logs or source.

### Observability

Existing production telemetry was used first and identified the exact failing boundary: `/mini-app/api/bootstrap` received no `init_data`, then browser-auth fallback executed.

No new backend telemetry is required for this minimal frontend startup-order fix because the current logs already distinguish successful Mini App bootstrap from missing-initData/browser-auth fallback. Post-deploy verification must confirm the fallback is no longer reached for a normal Telegram launch.

### Verification layers

- Unit/domain behavior: N/A — no domain rule changed.
- Database/repository integration: N/A — no DB change.
- Authorization/ownership: existing signed Telegram initData validation unchanged; regression suite applies.
- Migrations: N/A.
- External adapter contract: Telegram WebApp launch semantics verified against official Telegram Mini Apps documentation; MAX bridge compatibility retained.
- Workflow/idempotency/retry: N/A.
- API integration: existing Mini App bootstrap regression suite.
- Telegram bot behavior: inline WebApp button source verified; Telegram startup browser E2E required.
- MAX bot behavior: shared frontend compatibility; MAX startup browser E2E required.
- Mini App behavior/E2E: Chromium + iPhone WebKit startup and critical browser journeys required.
- Instagram applicability: N/A — channel does not use Telegram/MAX WebApp launch bridges.
- Smoke/deployability: production static export + exact-source Docker + deployed revision/health check required.
- Observability/audit: production logs inspected before patch; post-deploy log verification required.
- No-hardcode/admin configurability: N/A — no mutable business setting.
- Documentation: this execution-ledger entry records diagnosis, scope, verification, and rollout.

### Implementation progress

1. [x] Read repository instructions and relevant architecture/deployment/runtime code.
2. [x] Inspect production logs before editing and confirm missing `initData` → browser-auth fallback.
3. [x] Verify Telegram buttons use `web_app=WebAppInfo`, ruling out a plain URL regression.
4. [x] Trace the regression to shared Telegram/MAX bootstrap ordering and platform priority.
5. [x] Review mandatory skill sources; apply diagnosis/regression/review guidance.
6. [x] Capture an immutable pre-MAX launch snapshot after Telegram SDK load and before MAX bridge load.
7. [x] Prefer Telegram launch data over MAX when both are observable.
8. [x] Recover Telegram initData from pre-MAX snapshot/session storage before fallback.
9. [x] Add regression contracts for Telegram-before-MAX script/platform order and snapshot preservation.
10. [x] Keep MAX startup path and payment behavior intact.
11. [x] Open PR #252.
12. [x] Exact-head CI reached green for backend regression, dependency audit, callback load, frontend lint/unit/build/static export, critical browser journeys, Telegram Chromium/iPhone WebKit startup, and MAX Chromium/iPhone WebKit startup on intermediate head `cbff60e1eb7408bdef28bdc141d82b8194583e77`; the later ledger/policy-sync commit requires a fresh final-head CI before merge.
13. [ ] Production Docker image verification on final immutable PR head.
14. [ ] Standards/spec review on final diff against current `main`.
15. [ ] Merge PR #252 after final-head CI/review are green.
16. [ ] Verify canonical HappyFox auto-deploy exact SHA, service health, served Mini App startup order, and production launch telemetry.

### Skills/guides reviewed

- `Bambale0/skills`: `diagnosing-bugs`, `tdd`, `code-review`, `resolving-merge-conflicts`.
- `Bambale0/claw`: debugger guidance (`dev_agents_pack/.github/agents/12-debugger.md`).
- `wondelai/skills`: `release-it` guidance used for release/verification discipline.
- `anthropics/skills`: searched for relevant Telegram/WebApp/debugging guidance; no directly applicable skill was identified, so no unrelated skill was forced into the fix.

### Risks and follow-up

- The real Telegram client launch cannot be fabricated server-side; CI can validate the WebApp startup contract, while post-deploy production telemetry plus a real Telegram open provides the final runtime signal.
- The shared frontend serves both Telegram and MAX; parity E2E is therefore a release blocker for this change.
