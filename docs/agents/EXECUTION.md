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

## Active Feature — Telegram/MAX Mini App host split

### Task

Keep Telegram Mini App on `https://app.happy-fox.online/mini-app/` and prepare MAX Mini App for `https://max.happy-fox.online/mini-app/` so each messenger launches its own native Mini App bridge correctly while the product UI/backend stay shared.

### Baseline

- Repository: `Bambale0/foxgen`
- Base branch: `main`
- Baseline SHA: `a01bedc79767cbde4ad248cbf0bf95b6d6006a72`
- Working branch: `feat/split-telegram-max-miniapp-hosts`
- Superseded investigation: PR #252 was closed unmerged after confirming a frontend bootstrap patch alone could not explain Telegram choosing an external browser before page JavaScript executes.

### Fresh audit

What already exists:

- Telegram bot buttons use native `web_app=WebAppInfo(...)` and the Telegram app origin `app.happy-fox.online`.
- MAX already has a separate `MAX_MINI_APP_URL` runtime setting and native `open_app` buttons.
- Telegram and MAX currently share one static frontend export and one backend API.
- The shared HTML currently loads both Telegram SDK and MAX Bridge.
- Production CI already runs Telegram and MAX startup E2E on Chromium and iPhone WebKit.
- Production deploy publishes exact-SHA static assets and reconciles Telegram/MAX channel runtime.

What is partial:

- MAX's separate URL setting currently resolves to the same `app.happy-fox.online` Mini App as Telegram.
- Nginx has MAX launch compatibility on the shared app domain.
- Existing startup E2E validates each bridge but did not require the other messenger bridge to be absent.

What is missing:

- dedicated `max.happy-fox.online` static/API ingress;
- channel-specific published HTML variants from the same verified build;
- an activation mechanism that is safe before DNS exists;
- durable post-deploy reconciliation after the split is enabled;
- explicit documentation/rollback for the separate launch hosts.

Reusable components:

- current Next.js static export;
- `MAX_MINI_APP_URL` setting and MAX `open_app` buttons;
- shared backend `/mini-app/api/` routes;
- exact-SHA production image as the immutable static bundle source;
- existing Telegram/MAX browser startup E2E.

### Intended outcome and acceptance criteria

1. Telegram canonical Mini App remains `https://app.happy-fox.online/mini-app/`.
2. MAX canonical Mini App becomes `https://max.happy-fox.online/mini-app/` after DNS/TLS activation.
3. Both hosts publish the same exact verified frontend revision and use the same HappyFox backend API.
4. Telegram host loads `/mini-app/telegram-web-app.js` and does not load MAX Bridge.
5. MAX host loads `https://st.max.ru/js/max-web-app.js` and does not load Telegram SDK.
6. Before the MAX subdomain is provisioned, merging/deploying this preparation does not change the current production MAX launch host.
7. After one-time server provisioning, successful future production deploys automatically reconcile both channel-specific variants.
8. MAX `/mini-app/api/` reaches the shared backend and unsupported/invalid bootstrap requests fail closed at the application seam rather than nginx 404/405.
9. MAX launch redirect and runtime setting point to the dedicated MAX origin after activation.
10. Telegram and MAX startup E2E pass on Chromium and iPhone WebKit using their isolated static variants.

### No-hardcode/configuration decision

- Canonical product domains are infrastructure invariants and are documented in deploy/provisioning surfaces.
- Activation is not controlled by source edits: the server-side `/etc/foxgen-happyfox/max-miniapp.env` file is the explicit operations switch created only after DNS/TLS provisioning.
- No prices, prompts, provider/model choices, business thresholds, secrets or mutable commercial configuration are added.

### Schema/API/UI changes

- Database/schema: none.
- Public backend API contract: unchanged.
- Telegram UI: unchanged.
- MAX UI: unchanged; launch origin changes after activation.
- Frontend codebase: one source remains; deployment renders channel-specific bridge variants.

### Permissions/security scope

- Telegram signed `initData` and MAX signed launch data continue to be validated by their existing backend paths.
- The split does not make client-side bridge detection an authorization boundary.
- No credentials are committed. TLS provisioning uses Certbot on the production host and the activation file contains only public origin/root configuration.
- Dedicated MAX nginx CSP permits MAX bridge/frame origins without adding Telegram bridge execution to the MAX host.

### Observability plan

- Existing production bootstrap/auth logs remain the backend signal for missing launch data.
- Activation script validates live HTML bridge isolation, exact revision, MAX bootstrap ingress, bot health and MAX launch redirect.
- The post-deploy reconciliation workflow records exact commit and whether the server-side split is active or intentionally remains no-op.

### Verification layers

- Unit/domain behavior: channel renderer contract tests.
- Database/repository integration: N/A; no data change.
- Authorization/ownership: existing channel auth remains unchanged; backend regression required.
- Migrations: N/A.
- External adapter contract: MAX native `open_app`/registered Mini App URL and Telegram native WebApp button remain their platform launch mechanisms.
- Workflow/idempotency/retry: activation is rerunnable from the immutable exact-SHA Docker image; provisioning is DNS/TLS-gated.
- API integration: dedicated MAX nginx proxies `/mini-app/api/` to the same backend.
- Telegram bot behavior: existing inline WebApp target retained; isolated startup E2E required.
- MAX bot behavior: existing `open_app` retained; isolated startup E2E required.
- Mini App behavior/E2E: Telegram and MAX Chromium + iPhone WebKit startup must each assert absence of the other bridge.
- Instagram applicability: N/A; Instagram does not use Telegram/MAX Mini App launch bridges.
- Smoke/deployability: exact-source Docker plus no-op preactivation deploy and live postactivation checks.
- Observability/audit: activation health/revision/bridge/redirect checks plus existing backend logs.
- No-hardcode/admin configurability: server activation config is an infrastructure switch; no business config introduced.
- Documentation: `docs/miniapp-channel-hosts.md` and `docs/max-channel.md` updated.

### Implementation progress

1. [x] Audit current Telegram/MAX launch code, runtime settings, deploy scripts, nginx tuning and startup E2E.
2. [x] Close speculative PR #252 without merging.
3. [x] Create branch from current `main`.
4. [x] Add `shared`/`telegram`/`max` static renderer with bridge-count validation.
5. [x] Add server-side activation that is a no-op while MAX split config is absent.
6. [x] Make activation source both variants from the exact verified Docker image so reruns are idempotent.
7. [x] Add one-time DNS/TLS/nginx provisioning for `max.happy-fox.online`.
8. [x] Add post-production-deploy reconciliation workflow.
9. [x] Make nginx tuning preserve a configured dedicated MAX redirect across future deploys.
10. [x] Strengthen Telegram startup E2E to use Telegram-only published HTML and reject MAX Bridge.
11. [x] Strengthen MAX startup E2E to use MAX-only published HTML and reject Telegram SDK.
12. [x] Add unit/contract coverage for renderer, activation transition and nginx redirect durability.
13. [x] Document topology, one-time activation, release invariants and rollback.
14. [ ] Run two-axis code review against `main` and resolve findings.
15. [ ] Run exact-head PR CI to green.
16. [ ] Merge through PR and verify canonical production deploy remains healthy in preactivation/no-op mode.
17. [ ] After DNS exists: provision `max.happy-fox.online`, activate current verified main SHA, update MAX Partner Mini App URL, and verify a real MAX launch plus Telegram launch.

### Skills/guides used

- `Bambale0/skills`: `ask-matt`, `diagnosing-bugs`, `tdd`, `code-review`, `resolving-merge-conflicts`.
- `Bambale0/claw`: debugger guidance used for evidence-first production diagnosis.
- `wondelai/skills`: release guidance used for exact-SHA, staged activation and rollback discipline.
- `anthropics/skills`: searched for directly relevant Telegram/MAX Mini App host-splitting guidance; no applicable skill was identified, so no unrelated skill was forced into the task.

### Risks and follow-up

- DNS/TLS and the MAX Partner Mini App URL cannot be activated until `max.happy-fox.online` exists publicly; the repository is deliberately designed to remain in shared transition mode until then.
- A production deploy after split activation briefly publishes the generic app bundle before the post-deploy reconciliation workflow re-renders the Telegram-only variant; the MAX dedicated root is not removed by the canonical deploy and remains available until reconciliation updates it to the new exact SHA.
- Tomorrow's final acceptance requires real-client launch checks in both Telegram and MAX because CI can validate bridge/startup contracts but cannot impersonate the messenger's platform-side Mini App registration.
