# Active: Neironych migration across HappyFox Telegram, MAX and VK

User scope: all currently available models from the Neironych partner guide in Telegram, MAX, VK, and applicable Mini App entry points. Do not touch KSU, newvk:8443, or other projects.

## Fresh audit, 2026-10-02

- Foxgen baseline: 13b06e4bec505a867956306a110adc0efad2d125 (main), feature branch feat/neironych-all-channels-20261002.
- VK baseline: 2abe490ea8c3022ce0b2f7d5eb19e691cd01b528 (master), same feature branch name in Bambale0/alenavk.
- Public /v1/models has nine IDs: glm-5.3-flash, gpt-5.6-luna, grok-4.5, gpt-image-2.5-sunburst, nano-banana-2, nano-banana-pro, grok-imagine-video-1.5, seedance-2.0, seedance-2.5. Source hashes and model/pricing snapshots are recorded under docs/providers. Only live IDs with an implemented contract may be enabled; examples of disabled models are not availability evidence.
- Existing Foxgen media products: banana_2, banana_pro, flux_pro, grok_imagine_v15, seedance_2, seedance_2_5. Existing VK equivalents use nano_banana_2, nano_banana_pro, gpt_image_2, grok_imagine_v15, seedance_2; VK lacks Seedance 2.5 and native text-model selection.
- Reuse existing generation task tables, channel-owned identities/ledgers, task/refund/delivery machinery, and authenticated settings. Do not create a second money ledger or copy the Telegram balance into MAX/VK.
- Canonical Foxgen has no Neironych adapter. An earlier uncommitted prototype outside the currently permitted work area is NOT a release; recreate the reviewed implementation in the permitted /root worktrees. Do not bypass file access policy to recover that prototype.
- Production foxgen-happyfox-bot is healthy. No Neironych partner key was found in verified HappyFox runtime variables. Model discovery is public and is not an authenticated generation smoke.
- VK service alenavk-vk-bot.service is active on the checked production host, /srv/alenavk, listener 1778. Its checkout is dirty (main.py, vk_bot_lp.py, runtime settings test, and an untracked env loader). Preserve that state. Exact-SHA deploy is blocked until runtime drift has an approved reconciliation path; do not reset or overwrite it.
- No overlapping open PRs found in either repository.
- Mutable retail prices are not partner procurement costs. Preserve existing tariffs. New products without an approved tariff must fail closed, not borrow a different model's price.

## Design and test seams

A channel-neutral happyfox_neironych Python package owns the nine exact model contracts, validated request builders, safe HTTP client, idempotent request lifecycle, and result validation. Foxgen imports the same package shipped in its source; VK pins its dependency to an exact reviewed source commit. Only the provider package is packaged, never bot state or database backups.

Adapters persist the exact provider payload and idempotency key before submission in existing durable task metadata. Recovery polls a saved video ID or repeats only the same video key/body. Uncertain synchronous image/text submissions are held for reconciliation, never retried with a new key or silently routed to KIE. Terminal rejection may use the existing once-only refund path. Result persistence precedes delivery; delivery errors do not create another generation.

Enablement, model selection and tariff overrides use the existing authenticated settings/control plane with actor metadata; secrets use protected environment or _FILE settings, never ordinary settings tables. Missing key keeps the migration disabled. Existing routes stay intact for models outside the nine-ID scope.

Tests at public seams: provider builders/client with mock transport; durable submission/recovery and concurrency; channel generation/assistant entry points; protected admin writes; catalog/bootstrap/keyboard behavior; existing full channel regression and browser gates. No test claims live provider success without a real authenticated call.

## Acceptance and release gates

1. Nine current models have correct executable contracts and available user/admin selection.
2. Telegram/MAX/VK integration preserves charge/refund, references, history and final delivery; Mini App shares the same routes.
3. Invalid combinations fail before a paid provider call; unknown outcomes never trigger duplicate charges/submissions.
4. Images are decoded with real MIME/extension; protected video is downloaded with same-origin auth, no redirects, bounded streaming, then stored locally.
5. Unit, adapter, workflow, DB, authorization, channel, full CI and two-axis review gates pass before merge. Canonical deployment only after key/tariff/runtime-drift preflight.
6. Post-deploy exact revision, health, channels and correlated generation telemetry are verified before calling migration complete.

## Verification applicability

Unit/contract, task DB integration, retries/idempotency, authorization, TG/MAX/VK, Mini App, observability, configuration and documentation: required. Schema migrations: avoid new tables; use existing metadata/settings. Instagram: retain existing routes unless the shared provider change necessarily applies; do not assume it is unaffected without tests. Paid/live smoke: blocked pending a HappyFox-scoped key. Deployment: blocked by key provisioning and VK runtime drift; no manual production edits.

Guidance read/applied: Bambale0/skills to-spec, TDD, code-review; Bambale0/claw api-integrator and release-hardening; wondelai/skills pragmatic-programmer; anthropics/skills webapp-testing and API error/key handling guidance. No external skill repository is copied into either product.

## Progress

- Fresh audit and acceptance criteria recorded before production code.
- Provider contract package implemented for all nine live model IDs with bounded HTTP, exact persisted idempotency, protected video download and local artifact verification.
- HappyFox routing is DB-backed/audited and fail-closed; deploy remains disabled until an operator enables media/text.
- Telegram + Mini App image/video entry points use the existing HappyFox task/wallet rows; MAX uses the existing durable MAX job row and the same provider lifecycle.
- Shared AI Assistant can route Telegram/MAX/Mini App text requests to any of the three live text models; audio remains on the existing provider because the partner guide does not advertise audio input for these text contracts.
- Seedance 2.5 public/admin flows route only capabilities represented exactly by the partner contract. return-last-frame, non-MP4 output, web-search, NSFW checker, audio-off, or other incompatible combinations retain the existing provider.
- Production secret is now provisioned and syntactically validated on the HappyFox host; provider routing is still disabled until reviewed code deploys.
- Verification so far: 63 dedicated Neironych tests green; relevant focused/parity regression suite 127 passed in exact CI normalizer order; full backend suite 467 passed / 27 skipped after the same normalizers; changed-delta Ruff clean; compileall clean; provider wheel built and contains only happyfox_neironych + dist-info. No paid provider generation was used for pre-release smoke.
- Two-axis pre-merge review found a material MAX finance issue: an uncertain synchronous provider outcome was being refunded even though the paid request could have succeeded. Fixed: MAX marks the job held, does not refund and does not resubmit; a delivery failure after a persisted result now retries delivery without refund/regeneration. Regression coverage added.
- Verification after review fix: 64 dedicated Neironych tests green and changed-delta Ruff/diff checks clean.
- Next: push the review-fix head, rerun exact-head CI and complete Standards/Spec review; merge/deploy only after all gates are green, then enable audited routing and verify production telemetry before VK promotion.

---

# Active: Telegram green buttons + DB-backed animated custom-emoji icons

Baseline: rewritten public main `f818b937674643843e8884fe83030ff150d95b8d`, branch `feat/telegram-green-animated-menu`, PR #286.

Fresh audit: production was still on the pre-theme revision, so Telegram emitted legacy dark inline buttons and the old fallback path answered `/emoji_id 😃` as Unicode instead of returning a Telegram custom-emoji document ID. aiogram 3.31.0 supports native inline-button `style` and `icon_custom_emoji_id`. Keyboards are created both in `bot/keyboards.py` and directly in handlers, so factory-only theming would be incomplete.

Acceptance: every outgoing Telegram `InlineKeyboardMarkup` passes through one request-session middleware. Normal actions/navigation use `style="success"`; cancel/delete/remove/reject/ban/disable/clear/reset actions use `style="danger"`; explicitly configured styles stay unchanged. Existing callback data, URLs, WebApp targets and row layouts are preserved. Custom emoji are mapped by literal Unicode prefix (for example `🏠`) to Telegram `custom_emoji_id`; the static prefix is removed only when the custom icon is present. Plain Unicode remains the safe fallback.

Control plane / no-hardcode: routine custom-emoji mappings are stored in the existing DB-backed `bot_settings` key `telegram_button_emoji_ids` with `updated_by_telegram_id` and `updated_at`. Admin-only commands: `/emoji_id` extracts true Telegram custom-emoji IDs, `/emoji_map` shows the active mapping, `/emoji_set <prefix>` stores/updates a mapping without redeploy, and `/emoji_unset <prefix>` removes it. `HAPPYFOX_TELEGRAM_MENU_EMOJI_IDS` remains only an emergency/bootstrap fallback when no DB setting exists. No production IDs are committed.

Architecture: global Bot API request middleware is the single theming seam; the earlier approach that wrapped every keyboard factory was removed to avoid shotgun edits and keep handlers/factories unchanged. DB reads are cached for 5 seconds and fail open to the environment fallback so a temporary settings read failure cannot block message delivery.

Observability: invalid config emits `telegram_button_custom_emoji_config_invalid*`; DB read failures emit `telegram_button_custom_emoji_setting_read_failed` with exception context. No secret values are logged.

Review evidence: Bambale0/skills `code-review` fixed point is `main`; Bambale0/claw `09-code-reviewer` and `release-hardening` were applied. Codex review P1 (normalizer helper mismatch) was addressed, then made obsolete by removing factory-level theming; P2 findings were addressed by moving mappings into the DB-backed admin control plane and classifying clear/reset actions as danger. Wondelai `working-with-legacy-code` guidance supported keeping the change behind one tested seam. Anthropic `webapp-testing` guidance is covered by the repository Playwright CI rather than a separate ad-hoc browser harness.

Parity: Telegram-only visual capability. MAX has no equivalent Telegram Bot API style/custom-emoji fields; business/callback outcomes are unchanged. Mini App and Instagram behavior are unchanged. Release CI still verifies MAX + Telegram + Mini App startup/browser compatibility.

Verification evidence so far: local production-compatible aiogram smoke verified `success`/`danger` serialization and custom emoji serialization; focused compile + Ruff clean; focused theme/custom-emoji suite 13 passed; prior focused suite before review fixes 16 passed; frontend lint had 0 errors, 20 suites / 86 tests passed, production build succeeded; `npm audit --omit=dev --audit-level=high` reports 0 vulnerabilities after Next.js 16.3.8; `pip-audit --strict` reports no known vulnerabilities after urllib3 2.8.0. Exact-head CI run `36782622585` on `9311179359542cc055bf1177f92608e1d0a5cbd2` completed green: Python dependency audit, Backend regression, Callback load test, Mini App build/browser E2E (Telegram + MAX + Chromium + iPhone WebKit + native launch recovery), and Production Docker image all succeeded. This evidence is now recorded before the final docs-only head re-run required for exact-head release gating.

Deployment/rollback: normal path only — exact-head CI green → reviewed PR merge → canonical main auto-deploy → verify exact production SHA, health, Telegram webhook/channel reconciliation and logs. Rollback is the canonical deploy of the previous verified main SHA; no schema migration is required.

---

# Active: optional landing gate on unified production origin

Baseline: main d2dcb28a283b84450fc3c23b2eead7bf14d81a48, branch fix/optional-production-landing-20260927.

Production evidence after the domain-origin fix: the canonical deploy built and recreated `foxgen-happyfox-bot` on `vpncreative2026`; health and Mini App revision both report `d2dcb28a283b84450fc3c23b2eead7bf14d81a48`, Telegram webhook reconciliation and MAX subscription/commands succeeded on `https://alena.xn--e1aikcel5c5a.online`. The workflow still exited non-zero after nginx because the deploy script treated the shared origin as a dedicated marketing landing and required `/` to contain a Telegram link plus canonical `robots.txt`/`sitemap.xml`. Actual production contract is `/ -> 302 /mini-app/`, `/mini-app/ -> 200`, health 200, while robots/sitemap are not served there.

Acceptance: `HAPPYFOX_LANDING_ORIGIN` is optional. When unset, deployment must skip landing-only marketing/SEO gates and validate API/App/MAX/Mini App/channel reconciliation only. When explicitly configured, the existing dedicated landing CTA/robots/sitemap checks remain mandatory. No referral, payment, balance, database schema, generation, Telegram or MAX business behavior changes.

Antifraud/payment applicability: N/A; this is deployment verification only. Telegram/MAX/Mini App compatibility remains required. Instagram behavior N/A.

Verification: test-first source contracts for optional landing semantics; full exact-head CI; two-axis review against main; PR merge; exact-main CI; canonical deploy must complete green; then verify production SHA, health, Mini App revision, Telegram webhook and MAX subscription/commands.

---

# Active: production origin drift in canonical deploy

Baseline: main 1881b8eff1d634d62cd5c68b3432e229f495df85, branch fix/production-origin-deploy-20260927.

Fresh audit: GitHub Environment currently supplies API_ORIGIN, APP_ORIGIN and MAX_APP_ORIGIN as `https://alena.xn--e1aikcel5c5a.online` (human-readable: `https://alena.нейроныч.online`). The referral release itself passed exact-SHA CI and the deploy reached image build/container recreation, but the canonical deploy script/workflow still hardcode legacy `happy-fox.online` as the landing origin. The deploy therefore failed during post-deploy smoke with DNS resolution errors for a retired domain even though the current production origin variables were correct.

Acceptance: canonical deploy must take landing/API/app/MAX origins from protected GitHub Environment/runtime configuration; no retired HappyFox domain may be a release-critical fallback; if landing is not separately configured it follows APP_ORIGIN; public smoke and deployment summary use the effective landing variable; exact-SHA release path, database, Telegram relay and channel behavior stay unchanged.

Risk/impact: deployment-only/configuration-path change. No payment/referral/balance schema or user data mutation. Production deploy is expected to rerun the already-green main revision after the workflow fix. Rollback is reverting the workflow/script commit; no data rollback needed.

Observability: deployment logs already print effective non-secret origins and exact SHA. Post-deploy verification must confirm health/revision on the configured current origin and that Telegram/MAX reconciliation succeeds.

Verification plan: regression-test workflow/script source contracts first; Ruff/compile where applicable; full CI; two-axis review against main using AGENTS.md + this section as spec; merge via PR; canonical deploy; verify exact deployed revision and channel reconciliation. Paid payment smoke is N/A.

Skills/guides: Bambale0/skills ask-matt + code-review; Bambale0/claw payment/release safety checklist. wondelai/skills and anthropics/skills searched for directly applicable deploy-origin guidance; no narrower matching skill found.

---

# Active: referral purchase cashback parity — Telegram + MAX

Baseline: main 18e02aabe9ea2bc0f5d9c8981bf59b274c7628b7, branch feat/referral-credit-every-purchase-20260927.

Fresh audit: registration rewards are already deferred in both Telegram and MAX, and every new user keeps the existing 5-credit welcome balance. The remaining mismatch is that the inviter's configured 3-credit reward is currently paid only on the referred user's first purchase. Telegram completes payments atomically through `complete_payment_atomic`; MAX completes orders atomically through `MaxYooKassaService.complete_order` and `apply_max_balance_delta`. Existing L1/L2 partner purchase commissions are already idempotent and must remain unchanged.

Acceptance: referral registration pays the inviter 0 credits; referred users keep the existing welcome balance; every distinct verified successful purchase by a direct referral pays the inviter `inviter_bonus_credits` (currently 3); duplicate/replayed completion of the same Telegram transaction or MAX order pays no duplicate cashback; Telegram and MAX keep their separate identity/wallet ledgers; existing 30%/7% partner commissions remain unchanged; public copy says cashback is paid after every purchase.

Antifraud/integrity: existing self-referral, one-time binding and cycle protections remain; Telegram payment status claim is the idempotency boundary for one cashback per completed transaction; MAX uses a per-order `max_transactions.idempotency_key`; no frontend identity is trusted; no new hardcoded mutable amount is introduced.

Verification plan: focused Telegram/MAX payment regressions first, changed-file Ruff/compile, full safe backend suite, two-axis review against main, exact-head CI, merge, canonical exact-SHA deploy, then production revision/health plus read-only verification of the effective business rules and referral/payment telemetry. No paid live transaction will be created without an explicit test payment mechanism.

Skills/guides: Bambale0/skills ask-matt + code-review; repository AGENTS.md. Bambale0/claw and wondelai/skills were searched for referral/payment-idempotency guidance with no more specific matching skill found. anthropics/skills was searched; no applicable backend/referral skill found.

---

# Active: fix/telegram-rich-message-prompts — rich_message prompts were silently dropped

Baseline: main 196f0f4c8e51e03651db2fbe3ee97049001488e9, branch fix/telegram-rich-message-prompts.

Incident (2026-09-19/20, admin user_id=962098909): prompts sent as Telegram formatted text arrived as `Message.rich_message` without `text`/`caption`/`entities`; telemetry showed `route=message:rich_message handler=-`, no reply, no generation task (last task for the user was 2026-08-28). Control case confirmed the seam: plain text from another admin produced a task. Separate incident the same day: the Telegram webhook was hijacked to a third-party domain and restored via `scripts/ensure_telegram_webhook.py` (runtime only, no code change).

Audit: no `rich_message` handling existed anywhere in `bot/`, `tests/`, `scripts/` (0 grep matches). All prompt/menu text handlers are `F.text` based, including the `common.py` fallback. aiogram 3.31 exposes `RichMessage`/`RichBlock*` types with a strict schema; there is no built-in plain-text conversion.

Intended outcome: formatted-text prompts reach the existing `F.text` handlers with no per-handler edits; media-only rich messages are logged instead of silently dropped; extraction failures never crash the update.

Design decisions: single update-level outer middleware normalizes `Message.text` in place (`object.__setattr__`, verified to flip `content_type` to `TEXT`); raw `rich_message` preserved for forensics; telemetry middleware stays first so the raw content type remains visible; block kinds are read from the aiogram `RichBlockType` enum so a Bot API rename fails tests loudly; no new env/config keys, no hardcode.

Observability: `telegram_rich_message_normalized` (info, chars/blocks/update_id/release), `telegram_rich_message_without_text` (warning), `telegram_rich_message_normalization_failed` (error, update continues untouched).

Test seams: `tests/test_telegram_rich_message.py` (11 tests: reported admin payload, nested rich-text leaves, containers — list/table/details/blockquote/divider/thinking, media-only, caption, passthrough for non-rich and non-message updates, failure isolation, registration order in `bot/main.py`).

Parity: Telegram-only defect (Bot API `rich_message`); MAX uses its own contract, Mini App unaffected; Instagram N/A.

Steps: 1) branch from verified main ✓; 2) failing behavior tests against the reported payload ✓; 3) extractor + middleware ✓; 4) register in `bot/main.py` after telemetry, before routers ✓; 5) focused tests + Ruff + compile ✓; 6) docs (troubleshooting #25) ✓; 7) full local regression suite (running); 8) commit, run `code-review` skill against main, open PR, wait for exact-head CI.

Verification so far: focused suite 11 passed; adjacent regressions (`test_telegram_telemetry.py`, `test_admin_command_priority.py`, `test_callback_ack.py`) 13 passed; `ruff check` clean; compile clean; `git diff --check` pending with commit.

Remaining: full suite result, standards/spec review axes, PR, exact-head CI, post-merge deploy verification (revision, health, real rich-message smoke).

---

# Superseding product decision — Telegram quick-command system menu (2026-09-25)

The earlier native-launch work below is retained as historical implementation context, but its Telegram system-menu acceptance criterion is superseded. The Telegram native chat menu now uses the command list, not a Web App button. The Mini App remains available from the bot main keyboard. Registered quick commands are photo, video, music, motion, feed, trends, balance, and start; prompts remains a legacy alias; quick action commands must interrupt stale FSM/AI-assistant state and route directly to the requested product flow. Deployment reconciliation must preserve the commands menu rather than restoring the previous Mini App launcher.

# Active: Mini App native launch recovery for Telegram and MAX

Update 2026-09-18 follow-up: user retest on Telegram Desktop still showed the auth gate on the deployed 4bac0c11 release. Fresh logs prove the new Mini App document loads with Telegram.WebApp present and tgWebAppData length 603, but /mini-app/api/bootstrap reaches backend as Missing init_data. Backend already accepts X-Telegram-Init-Data as a fallback transport in _miniapp_payload, so this follow-up sends signed init_data in both the existing JSON body and that header. Auth remains backend-verified; no billing/referral/provider/config behavior changes. Verification so far: focused Mini App auth/gate Jest passed 4 suites / 32 tests; full Mini App Jest passed 19 suites / 84 tests; Mini App lint passed with 0 errors and the same 5 pre-existing hook warnings; production static export build passed; git diff --check passed.

Baseline: main 22a9becf293fb969597a4fcb7ce6d58af894d30b, branch fix/miniapp-native-launch-domains. The previous miniapp recovery stash from fix/miniapp-auto-auth-recovery was applied to a fresh main branch and kept isolated from the payment-release branch.

Fresh audit: production `MAX_MINI_APP_URL` and `MAX_PAYMENT_RETURN_URL` already point to `https://max.happy-fox.online/mini-app/`; public `https://max.happy-fox.online/mini-app/` serves the static app and revision.txt matches current production. Telegram's default chat menu button was still configured as `commands`, so opening from the native system menu could land users in a normal browser/login gate without `tgWebAppData`. The frontend already had Telegram native retry handling in the preserved recovery work, but stale cached MAX launch data was not cleared after backend auth refusal. Product-copy normalizers also needed idempotent support for the new Mini App menu and versioned WebApp URL so CI can normalize safely.

Acceptance: Telegram system menu opens the configured Mini App URL as a native `web_app` while bot commands remain registered. Telegram and MAX native WebViews do not show the browser login widget while launch data is still expected; failed native auth clears cached stale launch data and retries through the platform bridge. MAX keeps the dedicated `max.happy-fox.online` Mini App URL. Production WebApp launch URLs include the immutable release parameter when `HAPPYFOX_RELEASE` is available to break retained WebView documents. CI covers Telegram startup, MAX startup, and native launch recovery on Chromium and iPhone WebKit. No payment ledger, balance, provider, webhook, or tariff behavior is changed.

Verification so far: frontend focused Jest 4 suites/19 tests plus timeout body regression passed; full Mini App Jest passed 19 suites/72 tests; frontend lint passed with 0 errors and 5 pre-existing warnings; production static export build passed. CI-style backend copy with product normalization passed py_compile for changed Python entrypoints, 22 focused HappyFox menu/deploy/bundled-miniapp tests, and full safe regression with 368 passed, 1 skipped, 1 deselected. Browser E2E in Playwright Docker passed Telegram startup, MAX startup, and native launch recovery on Android Chromium and iOS WebKit. Changed-file Ruff and `git diff --check` passed. Review fixes addressed telemetry query leakage, canonical deploy menu reconciliation, legacy normalizer invocation conversion, and stalled bootstrap deadlines. Final two-axis review reports no remaining blockers. Final CI-mode Ruff failure from the product video UI normalizer was fixed by making its generated bottom import Ruff-clean.

Remaining: full PR workflow, exact-head GitHub CI, required review, merge, canonical deploy, then production verification that `getChatMenuButton` returns `web_app`, both Mini App domains expose the deployed revision, and MAX remains on the `max` subdomain.

Update 2026-09-18: production still shows users stuck on the Telegram Mini App auth gate after PR #263. Fresh evidence: public health/static revisions are on `e9566d012c9ece44839238f41b7f48a694a793a5`; Telegram `getChatMenuButton` is `web_app`; MAX connectivity is healthy. Runtime logs show browser/Yandex opens of `/mini-app/?startapp=...` without signed launch data and Telegram Desktop native launches with `init_data_len=603` followed by repeated 401 bootstrap responses. Scope for this hotfix: keep backend auth strict, do not change billing/referrals/provider behavior, make the native recovery CTA reopen through Telegram bridge instead of a plain external anchor, and improve privacy-safe launch diagnostics so `Telegram.WebApp` bridge presence is visible. No schema/config/admin change. Verification target: focused Telegram gate Jest, Mini App auth recovery tests, lint/build if feasible, then PR/CI/deploy path.

Hotfix progress: implemented native reopen recovery in telegram-open-gate. Telegram native uses Telegram.WebApp.openTelegramLink; MAX native uses WebApp.openMaxLink/openLink with the current Mini App origin. Automatic native retry now stops once a visible launch error is present, preventing repeated 401 bootstrap loops. Privacy-safe telemetry now reports Telegram.WebApp bridge presence without signed launch data. Review findings resolved: removed generated next-env.d.ts churn and added MAX bridge parity coverage. Verification: focused Mini App auth/gate Jest passed 4 suites / 30 tests; full Mini App Jest passed 19 suites / 82 tests; Mini App lint passed with 0 errors and 5 pre-existing hook warnings; production static export build passed; npm audit --omit=dev --audit-level=high found 0 vulnerabilities; git diff --check passed.

CI follow-up: PR #264 exact-head CI exposed that stopping auto-retry for every visible error regressed native recovery for transient bootstrap failures. Narrowed the stop condition to launch credential/auth-data errors, moved 401 auth refusal to a distinct data-login error, and added coverage that transient bootstrap errors still auto-retry. Fresh verification: focused auth/gate Jest passed 4 suites / 31 tests; full Mini App Jest passed 19 suites / 83 tests; Mini App lint passed with 0 errors and the same 5 pre-existing hook warnings; production static export build passed; native launch recovery E2E passed on Android Chromium and iPhone WebKit from a fresh .e2e-server export; git diff --check passed.

---

# Active: MAX subscription release guard

Baseline: main aca01a755fd5eedb4b4828b7ea0873d094ef8897, PR259 deployed through canonical workflow35358516055. Real payment terminal replays passed both webhook aliases for Telegram succeeded and MAX canceled, with unchanged balances/outbox. Readiness/revisions/migration3 passed. Postflight found two subscriptions on the verified HappyFox MAX bot: canonical plus a legacy Alena URL. Existing check_max_connectivity only validates JSON shape/commands, allowing a false successful deployment. Legacy binding is removed only from this verified HappyFox bot, exact URL guarded, subscription metadata backed up privately; no other bot/project/data touched.

Acceptance: deploy verifier requires exactly one subscription matching configured MAX_WEBHOOK_URL; rejects missing/malformed/foreign/duplicate entries; checks remain read-only and never delete arbitrary subscriptions. Reuse existing connectivity CLI and canonical deploy call. TDD through public check() with mocked native API; changed-file Ruff/compile; exact-head CI, two-axis review, reviewed PR merge and canonical deploy. No DB migration/new policy/config/credentials. Telegram/Mini App/Instagram behavior unchanged; compatibility covered by full CI. Skills retained: primary ask-matt/TDD/code-review, claw QA, wondelai release-it, anthropics webapp-testing. Native payment buyers/cabinet remain external pending. Telegram's last_error is historical504 from2026-09-17T22:39:25Z, preceding this release; pending0 and direct/relay auth gates401 are healthy. Do not erase diagnostic history or claim a fresh native update/payment without evidence.

---

# Active: unified YooKassa payment recovery

Baseline main: d74bf7a856ce64e7e06057ca8edcdc28e2932b85. Branch: fix/unified-yookassa-payments.

Fresh audit: existing Telegram atomic completion has a lost-claim bug; MAX has separate orders and polling, no common webhook dispatch. Checkout persists Telegram orders after provider creation. Existing notification code lacks a durable delivery status. Reuse local ledgers, provider adapters, migration registry, admin tariffs and channel clients. Do not merge identities or balances without a proven account link. Payment cabinet URL cannot be read with Basic Auth. Concurrent unrelated auth work is isolated.

Acceptance: one canonical webhook accepts both channels, routes by local provider ID, validates succeeded/identity/amount/currency, credits once, retries transient failures, and delivers to the correct channel through an outbox. Checkout cannot return a usable invoice without a durable local order. MAX credits/referrals/status are atomic. Error contract, frontend deadlines/lint, import wiring and readiness are repaired. Business settings gain validated administrative configuration without silently changing existing balances or payout units.

Public test seams: HTTP webhook and checkout, completion service with ledger/balance assertions, outbox channel delivery, provider contract, migration SQL, browser payment UI. Tests include authorization, foreign metadata, duplicate/concurrent processing, waiting_for_capture, temporary failure and notification retry. PostgreSQL concurrency is tested in an isolated database when available; SQLite compatibility remains covered. Telegram/MAX/Mini App regression and browser E2E required. Instagram inherits Telegram payment fixes; no live messages or paid smoke. Expand-only migrations, old tables retained; rollback preserves outbox/schema. Telemetry records order/channel/result and delivery state, no credentials.

Verification layers: unit/provider/HTTP/ownership/idempotency/migrations/outbox required; backend and frontend regression/build/browser required; external paid/native smoke N/A without sandbox accounts; exact-SHA CI required before merge. No new business constants: use validated existing tariff/control-plane settings. Existing channel wallet isolation remains explicit.

Steps:
1. Regression and repair lost claims, final-success verification and durable checkout.
2. Common webhook dispatch and durable payment delivery migration/worker.
3. Atomic MAX completion and channel business configuration parity.
4. Frontend contracts/deadline/lint, import and readiness repairs.
5. Focused/full tests, two-axis review against main, PR and exact-head CI.
6. Canonical release only after gates, then production revision/telemetry verification.

Progress: preflight recorded before production edits. Skills: local diagnosing-bugs/frontend-ux-audit; primary engineering ask-matt/code-review; claw QA checklist; wondelai release-it; anthropics webapp-testing. Skills repositories updated outside project. Production remains untouched.

Verification (implementation): normalized backend 360 passed, 1 PostgreSQL test skipped without isolated URL, 1 load test deselected; dedicated real PostgreSQL 16 concurrent completions per Telegram/MAX passed. Frontend Jest 15 suites/52 tests passed, lint zero errors with 7 pre-existing source warnings, production build passed. Critical browser flow and Telegram/MAX startup passed Chromium and iPhone WebKit. Two-axis final reviewers report 0 unresolved findings; subsequent containment/referrer-outbox refinements are covered by focused tests. Existing backend CI owns a disposable PostgreSQL container for its concurrency test; no workflow authorization change is required. Historical audit and recovery runbook committed.

External acceptance: merchant cabinet URL/events unavailable to Basic Auth; successful native live payments/messages N/A without test buyer accounts. Production unchanged. PR [#259](https://github.com/Bambale0/foxgen/pull/259) created. Exact local CI-mode normalized regression: 361 passed, 1 load deselected, including disposable PostgreSQL. Exact code-head two-axis review: 0 unresolved findings. Initial GitHub regression found a test-fixture startup race: socket-only initdb server was mistaken for final PostgreSQL readiness. Fixture now requires TCP readiness; no production runtime change. Exact updated-head CI pending; do not claim deployed or exhaustive absence of bugs.

---

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

Finish Telegram/MAX Mini App launch isolation on top of merged PR #254 without duplicating its domain/TLS/runtime machinery. The same frontend must choose exactly one native messenger bridge before application bootstrap, both on today's shared origin and on tomorrow's dedicated MAX origin.

### Baseline

- Repository: `Bambale0/foxgen`
- Base branch: `main`
- Baseline SHA: `d70c76da9b34a03f4b4941aab8dfe877fdb0b9d9`
- Working branch: `fix/miniapp-native-bridge-isolation`
- Existing infrastructure owner: merged PR #254.
- Superseded duplicate infrastructure work: PR #255 closed unmerged.

### Fresh audit

PR #254 already owns the separate MAX origin, webroot, DNS/TLS activation, nginx, `HAPPYFOX_MAX_APP_ORIGIN`, runtime URL canonicalization and production smoke. The remaining launch bug is inside the shared frontend: static HTML loaded Telegram SDK and MAX Bridge together before application bootstrap.

The first implementation in this branch tried to remove the foreign bridge from the built HTML after export. Browser E2E proved that approach invalid: Next hydration restored the bridge from its serialized layout tree. That implementation was removed rather than merged.

### Final design / acceptance criteria

1. Source layout contains one early `miniapp-bridge-loader`, not two direct SDK tags.
2. The loader runs synchronously before `telegram-early-ready` and before Next runtime.
3. Telegram launch parameters (`tgWebApp*`) select only `/mini-app/telegram-web-app.js`.
4. MAX launch parameters (`WebApp*`) select only `https://st.max.ru/js/max-web-app.js`.
5. `max.happy-fox.online` forces MAX bridge after dedicated-origin activation.
6. On the current shared `app.happy-fox.online` origin, MAX continues to work because its launch parameters select MAX while Telegram launch parameters select Telegram.
7. Static export patching preserves the loader and removes queued/direct duplicate bridge tags.
8. Telegram and MAX startup E2E each reject the foreign bridge on Chromium and iPhone WebKit while retaining their existing initData/ordering assertions.
9. PR #254 deployment/domain/TLS logic remains unchanged.
10. No database/API/business-config/cross-project changes.

### No-hardcode/configuration decision

The dedicated MAX hostname is an existing #254 infrastructure invariant. Messenger selection itself is derived from the platform's signed-launch parameter namespace; no mutable business configuration, secret, price, provider or policy is introduced.

### Schema/API/UI/security

- Schema: N/A.
- Public API: unchanged.
- Product UI: unchanged.
- Server-side Telegram/MAX auth: unchanged.
- Deployment topology: unchanged from #254.
- Instagram applicability: N/A.

### Observability / verification

- static export patcher fails if the loader is absent, ordered after Next, missing either platform launch contract, or if direct dual bridge tags survive;
- Telegram/MAX browser E2E verify actual DOM bridge selection and initData bootstrap;
- existing production revision/health/MAX redirect smoke from #254 remains authoritative.

### Implementation progress

1. [x] Re-read current AGENTS and merged #254.
2. [x] Close duplicate PR #255.
3. [x] Create fresh branch from current main and open PR #256.
4. [x] Discover via browser E2E that post-export tag removal is restored by Next hydration; delete that approach.
5. [x] Add launch-aware synchronous bridge loader to source layout.
6. [x] Update static export patcher to preserve/assert loader ordering and remove direct/queued duplicate bridge tags.
7. [x] Telegram startup E2E rejects MAX Bridge while preserving existing SDK/initData/order assertions.
8. [x] MAX startup E2E rejects Telegram SDK while preserving existing Bridge/initData/order assertions.
9. [x] Keep #254 deploy/domain/TLS code unchanged.
10. [x] Update frontend contract tests and MAX documentation.
11. [x] Re-run Standards review on the final design and resolve findings.
12. [x] Re-run Spec review on the final design and resolve findings.
13. [ ] Run exact-head full CI to green, including Docker.
14. [ ] Merge PR #256.
15. [ ] Verify main CI, canonical auto-deploy, exact revision and current shared-origin native launches.
16. [ ] After user creates DNS: activate `max.happy-fox.online`, set MAX partner URL, and verify real-client launches on both separate origins.

### Skills/guides

- `Bambale0/skills`: diagnosing-bugs, TDD, code-review, resolving-merge-conflicts.
- `Bambale0/claw`: evidence-first debugger guidance.
- `wondelai/skills`: exact-SHA/staged-release discipline.
- `anthropics/skills`: searched for directly applicable Mini App host/bridge guidance; no specific matching skill selected.

### Code review — Standards axis

Fixed point: `main` at `d70c76da9b34a03f4b4941aab8dfe877fdb0b9d9`.

Findings and resolutions:

1. The post-export renderer design was invalid because Next hydration restored the removed foreign bridge. Telegram startup E2E exposed this before merge. The renderer, its deploy integration and its dedicated test were deleted.
2. The replacement is source-level: the layout contains one synchronous bridge loader and no unconditional external Telegram/MAX script tags.
3. The static-export patcher now treats the loader as part of the startup contract, removes queued/direct duplicate bridge scripts and requires loader + bootstrap to precede Next runtime.
4. Existing Telegram and MAX startup assertions for initData and SDK/Bridge ordering are preserved; only foreign-bridge absence was added.
5. PR #254 deploy/domain/TLS implementation is unchanged, avoiding a second source of truth.
6. Client-side platform choice is not an authorization boundary; existing server-side signed launch-data validation remains unchanged.

Standards result: **clean; 0 unresolved findings**.

### Code review — Spec axis

Checked against the user's requested end state:

- Telegram remains on `app.happy-fox.online`.
- MAX can remain on that shared origin today and move to `max.happy-fox.online` after DNS/TLS activation.
- On the shared origin, Telegram and MAX are distinguished by their native launch-parameter namespaces before either SDK is loaded.
- On the dedicated MAX host, hostname additionally forces MAX Bridge.
- Exactly one messenger bridge is loaded for a native launch.
- Product UI/backend stay shared.
- No APIX/Tanyapi/other-project change is introduced.
- No manual source edit will be required tomorrow; #254 already owns the MAX origin switch.

Spec result: **clean; 0 unresolved findings**.

### Final pre-CI gate

Earlier CI runs were intentionally invalidated by implementation changes. The next branch head is the only merge candidate. Full PR CI must pass on that exact SHA, including backend regression, dependency audit, callback load, Telegram/MAX Chromium+WebKit startup and production Docker verification. Do not edit this ledger merely to copy the successful run number afterward.


---

# Active: referral purchase bonus gate + Mini App Telegram initData recovery

Baseline: main ae122a7399e1c7be2938621125e7b4b3820b732f, branch fix/referral-purchase-bonus-gate.

Fresh audit before production code: Telegram/Mini App/MAX share HappyFox business rules from `bot/business_rules_defaults.json`, where new users get 5 credits and inviter bonus is 3 credits. Telegram referral attach paths in `bot/services/referral_service.py` still insert `referrals.bonus_credits=3` and immediately credit the referrer. Legacy `bot/database.py::process_referral` also immediately credits the referrer. Payment completion in `bot/database.py::complete_payment_atomic` already runs atomically and idempotently, credits buyer balance, updates has_paid, and records partner purchase commissions, so it is the right seam for first-purchase referral gift. MAX has an isolated ledger in `bot/max_payments.py`; `register_max_referral` currently credits both invited user and referrer on signup, while `MaxYooKassaService._award_purchase_referrals` already awards purchase commissions idempotently through `max_transactions`. Mini App frontend sends `init_data` in bootstrap body, but auth recovery clears cached init data, early launch snapshots and Telegram SDK `initParams` after HTTP 401. Production client logs show Telegram launch context exists client-side (`init_data_len` present) while backend reports missing init data, so recovery must preserve live launch snapshots and support SDK/session initParams extraction.

Partial/missing: partner/user copy still says 15 bananas and immediate inviter signup reward. Referral gift for inviter is not gated on referred user's first purchase. MAX parity for the new referral rule is missing. Frontend auth recovery lacks coverage for Telegram SDK/session initParams and removes recovery sources that native WebViews may need. No schema migration is required because Telegram can use existing `referrals.bonus_credits` as the one-time gift marker and MAX can use existing transaction idempotency keys.

Reusable seams: `complete_payment_atomic` for Telegram YooKassa/CryptoBot order completion; `referrals.bonus_credits` for first-purchase gift idempotency; `apply_max_balance_delta` idempotency keys for MAX; existing Mini App Jest auth recovery tests; existing payment system and MAX payment tests; existing telemetry `launch-auth-rejected`/client-log path.

Risks and controls: do not double-credit legacy referrers whose `referrals.bonus_credits` is already positive; preserve partner percentage commissions; keep MAX isolated from Telegram ledger; do not trust frontend identity; do not log signed init data; preserve backend validation of Telegram initData; no mutable business value is newly hardcoded because bonus values come from business rules. Instagram uses shared Telegram payment/user ledger where applicable and should inherit `complete_payment_atomic`; no Instagram-specific UI change.

Acceptance criteria: New user gift copy says 5 лапок. Referral attach does not credit inviter immediately and notifies that gift arrives after first purchase. First completed payment by a referred Telegram user credits inviter exactly once using `inviter_bonus_credits`, alongside existing partner purchase commissions. Duplicate/replayed payment completion does not duplicate the gift. MAX referral signup does not credit inviter immediately; first MAX purchase credits inviter gift exactly once and still awards L1/L2 purchase commissions. Mini App native Telegram recovery can recover initData from live URL, early snapshots, Telegram SDK `initParams`, and `__telegram__initParams`, and clearing refused cached credentials does not delete live launch snapshots. Tests cover both business and frontend recovery regressions; CI/PR/deploy follow the repository path.

Planned verification layers: focused backend pytest for Telegram referral gift and MAX referral purchase; focused frontend Jest for Mini App initData recovery; changed Python compile/Ruff; Mini App lint/build; safe regression subset; browser startup/E2E when feasible; exact-head GitHub CI after PR; post-deploy health/revision/menu/MAX/webhook smoke if merged.

Progress: implemented deferred referral gift for Telegram and MAX. Referral attach now records `bonus_credits=0` and does not credit the inviter. Telegram `complete_payment_atomic` awards `inviter_bonus_credits` exactly once on the referred user's first completed payment by updating `referrals.bonus_credits` from 0 and crediting the referrer balance/history. MAX signup now gifts only the invited user; MAX first purchase awards the inviter gift through an idempotent `max_transactions` key and keeps L1/L2 purchase commissions. User-facing copy says new users get 5 лапок and inviter gift comes after first purchase.

Progress: implemented Mini App Telegram native recovery hardening. `getInitData()` now also reads Telegram SDK init params from `Telegram.WebView.initParams`, `Telegram.WebApp.initParams`, `sessionStorage.__telegram__initParams` and `sessionStorage.initParams`. Native auth recovery clears refused cached init data while preserving live launch snapshots, so Telegram WebViews are not stranded after a transient 401/missing-body path.

Verification evidence: focused backend regressions passed in Docker Python 3.12: `tests/test_payment_system_contract.py::test_telegram_referral_inviter_gift_is_awarded_after_first_purchase_once` and `tests/test_max_payments.py::test_max_referrals_award_signup_and_first_purchase_rewards_in_max_credits` — 2 passed. Focused Mini App auth recovery Jest passed 3 suites / 20 tests. Full Mini App Jest passed 19 suites / 75 tests when mounted from repo root. Mini App lint and production build passed; lint had 5 pre-existing React hook warnings. Python compile for changed backend/scripts passed. Ruff on the committed Python delta passed. CI-like backend check in a temporary worktree with `apply_visible_copy_fixes.py` and `apply_happyfox_product_copy.py` passed: 369 passed, 1 skipped, 1 deselected. `git diff --check` passed.

Remaining before completion: commit branch, run the required review axes, open PR, wait for exact-head GitHub CI, merge through PR, then verify canonical deploy revision/health/channel telemetry.

Update after review: closed the remaining Mini App recovery P2 by removing only the refused signed fields from in-memory `Telegram.WebView.initParams` and `Telegram.WebApp.initParams`, leaving platform/start params and fresh credentials intact. Added regression coverage for stale SDK initParams being cleared so fresh `WebApp.initData` can win.

Update after review: closed the trend preview P2 introduced by the visible-copy normalizer. Mini App prompt list/detail now use only cached lightweight preview URLs during the HTTP request; cache misses return the original preview immediately and schedule bounded/deduplicated background preprocessing. `trend_preview_service` now uses a semaphore, per-output locks, unique temp files, and task deduplication. The normalizer was updated so Docker-time source rewriting keeps the non-blocking helper.

Final verification evidence before PR: full Mini App Jest passed 19 suites / 79 tests. Mini App lint and production build passed; lint still reports the same 5 pre-existing React hook warnings. Focused backend regressions for MAX/Telegram referral and non-blocking trend preview passed 8 tests. Ruff passed on the changed Python delta. Final CI-like backend check in a temporary worktree with `apply_visible_copy_fixes.py` and `apply_happyfox_product_copy.py` passed: 373 passed, 1 skipped, 1 deselected. `git diff --check` passed. Spec review reported no blockers after the P2 fixes; Standards re-review is pending final acknowledgement.
Standards re-review reported no blockers for the two previous P2 findings. Note: trend preview task dedupe/locking is process-local; multi-process deployments would need shared coordination if that path is scaled horizontally.
