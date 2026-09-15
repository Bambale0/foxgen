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

## Active Feature Execution — dedicated MAX Mini App origin

### Task

Separate the MAX Mini App origin from Telegram so each messenger opens the shared HappyFox frontend through its own platform-specific public origin. Target MAX origin: `https://max.happy-fox.online/mini-app/`. Telegram remains on `https://app.happy-fox.online/mini-app/`.

### Baseline

- Repository: `Bambale0/foxgen`
- Base branch: `main`
- Baseline SHA: `a01bedc79767cbde4ad248cbf0bf95b6d6006a72`
- Working branch: `feat/max-dedicated-miniapp-domain`

### Fresh audit

Already exists:

- `MAX_MINI_APP_URL` is already a distinct runtime setting in `bot/max_api.py`.
- MAX uses native `open_app` buttons and reads the registered MAX bot/app name separately from Telegram.
- The shared frontend already contains platform-specific Telegram/MAX authentication handling and browser E2E coverage.
- Production deploy already publishes the exact verified frontend bundle and verifies Telegram/MAX startup compatibility.

Partial/problematic:

- `scripts/deploy_happyfox_dedicated.sh` currently overwrites `MAX_MINI_APP_URL` to the Telegram app origin on every deploy.
- `scripts/tune_happyfox_nginx.py` hardcodes the MAX webhook GET compatibility redirect to `https://app.happy-fox.online/mini-app/`.
- CI deploy passes only API/app/landing origins; there is no separately configurable MAX app origin.
- Documentation and examples describe one Mini App origin for both Telegram and MAX.

Missing:

- Dedicated production origin contract for MAX.
- Dedicated static webroot/nginx activation path for `max.happy-fox.online`.
- Release smoke that verifies MAX can serve the same exact revision from its own origin after activation.
- Regression tests preventing deploy from collapsing MAX back onto the Telegram origin.

### Intended outcome / acceptance criteria

1. Telegram stays on `https://app.happy-fox.online/mini-app/`.
2. MAX can use `https://max.happy-fox.online/mini-app/` without sharing Telegram's public origin.
3. Both origins serve the exact same verified frontend revision from the same HappyFox release.
4. MAX API/webhook remains on `https://api.happy-fox.online/max/webhook`.
5. Deploy is backward-compatible before DNS activation: until a dedicated MAX origin is enabled, production may continue using the current app origin.
6. After DNS/certificate activation, changing `HAPPYFOX_MAX_APP_ORIGIN` is sufficient to make deploy canonicalize `MAX_MINI_APP_URL` to the MAX origin.
7. No Telegram button or Telegram Mini App URL changes as part of this feature.
8. No cross-project/APIX changes.
9. Nginx activation is deterministic, TLS-verified, and does not disable certificate validation.
10. CI/regression covers split-origin topology and MAX/Telegram E2E remains green.

### No-hardcode decision

The hostname is an infrastructure default, not mutable business configuration. Production switching is controlled through `HAPPYFOX_MAX_APP_ORIGIN`; MAX runtime continues to consume the typed `MAX_MINI_APP_URL` environment setting. No product/business policy is hardcoded.

### Schema/API/UI

- Database: N/A.
- API schema: N/A.
- UI: same frontend and UX; only public MAX origin changes.
- Telegram: no intended change.
- MAX: launch/return links resolve to the MAX-specific origin after activation.

### Security / ownership

- MAX and Telegram identity/ledger isolation remains unchanged.
- TLS certificates remain mandatory.
- MAX auth validation remains server-side.
- No secrets are added to repository files.

### Observability / smoke

- Deploy summary must state Telegram Mini App origin and MAX Mini App origin separately.
- Public revision smoke must verify the exact commit from the MAX origin after it is enabled.
- Existing MAX connectivity/subscription smoke remains required.

### Test seams

- deployment-script contract;
- nginx tuning/config contract;
- MAX settings/runtime tests;
- Telegram + MAX browser startup E2E;
- exact-source Docker and public revision smoke.

### Implementation steps

1. [x] Read current `AGENTS.md`, MAX docs/settings, deploy workflow, deploy script, nginx tuner and existing tests.
2. [x] Audit existing split settings and identify deploy-time forced coupling.
3. [x] Create branch from current `main`.
4. [ ] Add a separately configurable MAX public app origin with safe backward-compatible default.
5. [ ] Publish the verified frontend artifact to a dedicated MAX webroot.
6. [ ] Add deterministic MAX-domain nginx activation tooling/template for use after DNS exists.
7. [ ] Parameterize MAX launch compatibility redirect and deployment smoke.
8. [ ] Update docs/examples/topology.
9. [ ] Add regression tests.
10. [ ] Run focused and full CI, including Telegram/MAX startup E2E.
11. [ ] Run standards/spec code review and resolve findings.
12. [ ] Merge only after exact-head CI is green. Do not activate the new public MAX origin until DNS/TLS are ready.
13. [ ] After user creates DNS, activate TLS/nginx for `max.happy-fox.online`, set the production MAX origin, deploy exact main SHA, and verify real MAX launch.

### Skills/guides

- `Bambale0/skills`: `implement`; repository-required TDD/code-review flow will be used for regression/review.
- `wondelai/skills`: `release-it` identified as relevant to deployment/release safety.
- `Bambale0/claw`: searched for relevant deployment/debug guidance; no more specific safe guide selected yet.
- `anthropics/skills`: searched narrowly for deployment/web-app guidance; no directly applicable skill selected, so none is being forced into the change.


---

## Active Bugfix — native Mini App bridge isolation

### Task

Finish the Telegram/MAX Mini App split on top of merged PR #254 without duplicating its domain/TLS/runtime machinery. Keep the current shared-origin behavior until MAX DNS/TLS is activated, then publish messenger-specific HTML variants from the same verified frontend artifact.

### Baseline

- Repository: `Bambale0/foxgen`
- Base branch: `main`
- Baseline SHA: `d70c76da9b34a03f4b4941aab8dfe877fdb0b9d9`
- Working branch: `fix/miniapp-native-bridge-isolation`
- Existing infrastructure owner: merged PR #254 (`feat(max): isolate Mini App on dedicated origin`)
- Superseded duplicate infrastructure work: PR #255 closed unmerged.

### Fresh audit

Already implemented by #254:

- Telegram Mini App origin `app.happy-fox.online`;
- optional dedicated MAX origin `max.happy-fox.online`;
- `HAPPYFOX_MAX_APP_ORIGIN` deploy parameter;
- separate MAX static webroot;
- DNS/TLS activation script;
- nginx MAX origin/redirect handling;
- runtime `MAX_MINI_APP_URL` canonicalization;
- revision/OPTIONS/POST/bootstrap smoke;
- backward-compatible shared-origin mode before activation.

Remaining gap:

- both published webroots still contained the same generic HTML, which loaded both Telegram SDK and MAX Bridge even after the origins were split;
- startup E2E did not require the foreign bridge to be absent.

### Intended outcome / acceptance criteria

1. Before split activation (`MAX_APP_ORIGIN == APP_ORIGIN`), the app bundle remains `shared` and contains both bridges so current MAX registration is not broken.
2. After split activation, `/var/www/happyfox-app/mini-app` is rendered `telegram` and contains Telegram SDK only.
3. After split activation, `/var/www/happyfox-max/mini-app` is rendered `max` and contains MAX Bridge only.
4. Both variants come from the same exact verified Docker-image frontend export and preserve the same revision.
5. Telegram startup E2E on Chromium and iPhone WebKit rejects MAX Bridge.
6. MAX startup E2E on Chromium and iPhone WebKit rejects Telegram SDK.
7. No duplicate domain/TLS/nginx activation mechanism is introduced.
8. No database/API/business-config changes are introduced.
9. Merge only after two-axis review and exact-head CI are green; canonical auto-deploy then verifies production.

### No-hardcode/configuration decision

No mutable business configuration is introduced. The existing #254 infrastructure switch `HAPPYFOX_MAX_APP_ORIGIN` remains the single source of truth for whether split-origin mode is active. Bridge variant selection is derived deterministically from that existing setting.

### Schema/API/UI/security

- Schema: N/A.
- Public API: unchanged.
- Product UI: unchanged.
- Telegram/MAX authorization: unchanged and remains server-side.
- Frontend release artifact: one source/one build; only published HTML bridge tags differ by channel.
- Instagram applicability: N/A; Instagram does not use Telegram/MAX Mini App bridges.

### Observability and verification

- deployment verifies bridge tags directly in the published static roots;
- public revision smoke from #254 remains unchanged;
- existing backend bootstrap/auth logs remain the signal for invalid or missing signed launch data;
- CI covers renderer unit contracts and real Telegram/MAX startup journeys.

### Implementation progress

1. [x] Re-read current `AGENTS.md` and #254 deploy/docs/tests.
2. [x] Close duplicate PR #255 rather than layering a second infrastructure mechanism.
3. [x] Create a fresh branch from current main.
4. [x] Add idempotent `shared|telegram|max` static HTML renderer.
5. [x] Make canonical production deploy choose shared mode before activation and isolated variants after activation.
6. [x] Add production bridge-tag assertions.
7. [x] Strengthen Telegram startup E2E to use Telegram-only HTML and reject MAX Bridge.
8. [x] Strengthen MAX startup E2E to use MAX-only HTML and reject Telegram SDK.
9. [x] Add renderer/deploy regression tests.
10. [x] Update MAX channel documentation.
11. [x] Run Standards review against fixed current main and resolve findings.
12. [x] Run Spec review against user requirement and resolve findings.
13. [ ] Run exact-head CI to green.
14. [ ] Merge PR.
15. [ ] Verify canonical production deploy and current preactivation shared mode remain healthy.
16. [ ] After DNS/TLS activation, verify real Telegram + MAX native launches on their separate origins.

### Skills/guides

- `Bambale0/skills`: diagnosing-bugs, TDD, code-review, resolving-merge-conflicts guidance already applied in this incident/workflow.
- `Bambale0/claw`: evidence-first debugger guidance.
- `wondelai/skills`: release discipline for exact-SHA and staged activation.
- `anthropics/skills`: searched previously for directly applicable Mini App host/bridge guidance; none selected because no specific matching skill was found.


### Code review — Standards axis

Fixed point: `main` at `d70c76da9b34a03f4b4941aab8dfe877fdb0b9d9`.

Findings resolved before final CI:

1. MAX startup E2E initially imported the renderer but still served the legacy `.e2e-server`, so it did not actually exercise the MAX-only bundle. Fixed to render/copy into a dedicated `.e2e-max/mini-app` root.
2. The first MAX E2E rewrite accidentally dropped the existing guarantee that MAX Bridge loads before Next runtime. The test was restored to a minimal diff and preserves that ordering assertion.
3. The renderer initially attempted to enforce bridge counts on every exported HTML file. That could fail on unrelated static HTML with no messenger bridge. It now skips non-bridge HTML while remaining strict for every bridge-bearing Mini App document.
4. Documentation/source-line escaping defects introduced during editing were normalized before CI.

Standards result: **clean; 0 unresolved findings**.

### Code review — Spec axis

Checked against the user's requirement and merged #254:

- Telegram remains on `app.happy-fox.online`.
- Dedicated MAX origin remains owned by #254; no duplicate DNS/TLS/nginx mechanism exists in this PR.
- Before activation, `MAX_APP_ORIGIN == APP_ORIGIN` deterministically keeps the shared bundle with both bridges.
- After activation, the same verified artifact is rendered Telegram-only on the Telegram root and MAX-only on the MAX root.
- Telegram and MAX native startup paths remain unchanged.
- No database, API, pricing, payment, provider, or cross-project behavior changes.

Spec result: **clean; 0 unresolved findings**.

### Final pre-CI gate

The next immutable branch head is the merge candidate. Full PR CI must pass on that exact SHA. Do not edit this ledger merely to copy the CI run number after success, because that would create a new untested head.
