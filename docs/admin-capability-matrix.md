# FoxGen admin capability matrix

This matrix is the implementation gate for EPIC #9. The NEUROMIX migration brief supplied for this work is the capability contract. The referenced local NEUROMIX audit files are not present in the connected `Bambale0/banano_kling` GitHub branch, so capabilities are transferred from the supplied brief rather than by copying source files.

## Architecture invariants

- All admin authorization is server-side and uses one `AdminPolicy`.
- All writes go through shared admin services; Telegram, HTTP and web adapters are thin.
- Every write command is stored in an append-only command ledger with request/response snapshots.
- Idempotent actions reserve a key before side effects and replay the stored response.
- Destructive/expensive actions require an explicit confirmation token.
- Internal HTTP requests are network allowlisted and HMAC-SHA256 signed over exact raw body bytes.
- Support replies and notification campaigns are durable outbox work, never request-lifecycle-only side effects.
- Secrets are redacted recursively before audit/operation payloads are returned or logged.
- Tariffs and CMS documents are versioned; published versions are immutable.
- Regular users must fail closed through every transport, including forged callbacks and web requests.

## Capability matrix

| Capability | Source contract | Target module | Transport | R/W | Audit | Idempotent | Worker |
|---|---|---|---|---|---|---|---|
| Admin role/scopes | migration brief `admin_policy` | `foxgen.admin.policy` | all | R | yes | n/a | no |
| Admin command ledger | migration brief `admin_command_ledger` | `foxgen.infra.admin_models`, `foxgen.admin.repository` | all | W | self | yes | no |
| Summary/stats | Telegram `/admin`, internal API | `foxgen.admin.services.AdminQueryService` | Telegram/HTTP/Web | R | read audit | n/a | no |
| User lookup | Telegram `/admin`, internal API | `AdminQueryService` | Telegram/HTTP/Web | R | read audit | n/a | no |
| Block/unblock user | internal admin API | `AdminUserService` | Telegram/HTTP/Web | W | yes | yes | no |
| Balance adjustment | Telegram `/admin`, internal API | `AdminUserService` + billing ledger | Telegram/HTTP/Web | W | yes | yes | no |
| Generation inspection | internal admin API | `AdminQueryService` | HTTP/Web | R | read audit | n/a | no |
| Operation timeline | internal admin API | `AdminOperationService` | HTTP/Web | R | read audit | n/a | no |
| Operation replay | internal admin API | `AdminOperationService` | HTTP/Web | W | yes | yes | generation outbox |
| Operation refund | internal admin API | `AdminOperationService` | HTTP/Web | W | yes | yes | no |
| Payment list/detail | internal admin API | `AdminPaymentService` | HTTP/Web | R | read audit | n/a | no |
| Payment recheck | internal admin API | `AdminPaymentService` | HTTP/Web | W | yes | yes | admin outbox |
| Payment reprocess | internal admin API | `AdminPaymentService` | HTTP/Web | W | yes | yes | admin outbox |
| Finance dashboard | Telegram/internal API | `AdminQueryService` | Telegram/HTTP/Web | R | read audit | n/a | no |
| CSV/XLS-style export | Telegram `/admin` | `AdminExportService` | Telegram/HTTP | R | yes | n/a | no |
| Tariff current/version history | internal API | `AdminTariffService` | Telegram/HTTP/Web | R | read audit | n/a | no |
| Publish tariff/versioned pricing | pricing editor/internal API | `AdminTariffService` | Telegram/HTTP/Web | W | yes | yes | no |
| Package/image/video/partner/prompt costs | pricing editor | versioned tariff payload | Telegram/HTTP/Web | R/W | yes | publish key | no |
| Partner analytics | Telegram `/admin` | `AdminPartnerService` | Telegram/HTTP/Web | R | read audit | n/a | no |
| Partner withdrawal queue/actions | Telegram `/admin` | `AdminPartnerService` | Telegram/HTTP/Web | R/W | yes | yes for actions | no |
| Promo create/lookup/activate/deactivate | Telegram `/admin` | `AdminPromoService` | Telegram/HTTP/Web | R/W | yes | yes writes | no |
| Prompt moderation list/detail | Telegram `/admin` | `AdminPromptService` | Telegram/HTTP/Web | R | read audit | n/a | no |
| Prompt approve/reject/deactivate | Telegram `/admin` | `AdminPromptService` | Telegram/HTTP/Web | W | yes | yes | no |
| Subscription-required toggle | Telegram `/admin` | `AdminRuntimeService` | Telegram/HTTP/Web | W | yes | yes | no |
| Model availability toggle | EPIC #9 | `AdminRuntimeService` + submission guard | HTTP/Web/Telegram | W | yes | yes | no |
| Runtime config/preset reload | Telegram `/admin` | `AdminRuntimeService` | Telegram/HTTP | W | yes | yes | no |
| Support ticket list/detail | internal API | `AdminSupportService` | Telegram/HTTP/Web | R | read audit | n/a | no |
| Ticket assign/update | internal API | `AdminSupportService` | HTTP/Web | W | yes | yes | no |
| Ticket reply | internal API | `AdminSupportService` | HTTP/Web | W | yes | yes | support outbox |
| CMS document/version read | internal API | `AdminCmsService` | HTTP/Web | R | read audit | n/a | no |
| CMS save/publish | internal API | `AdminCmsService` | HTTP/Web | W | yes | yes publish | no |
| Broadcast preview | Telegram/internal API | `AdminNotificationService` | Telegram/HTTP/Web | R | yes | n/a | no |
| Campaign create/test/start/cancel | Telegram/internal API | `AdminNotificationService` | Telegram/HTTP/Web | W | yes | yes | notification worker |
| Delivery statuses/retries | migration brief `admin_workers` | `AdminWorker` | worker/Web | R/W | yes | dedupe key | yes |
| AI admin read-only diagnostics | Telegram `/admin` | `AdminAiService` | Telegram | R | yes | n/a | no |
| Feed moderation blur/remove | admin-only web affordance | `AdminModerationService` | HTTP/Web | W | yes | yes | no |
| Trends create/remove | admin-only web affordance | `AdminModerationService` | HTTP/Web | W | yes | yes | no |
| Privileged generation preview | admin-only web affordance | `AdminPreviewService` | HTTP/Web | R | yes | n/a | no |
| Audit browsing | security requirement | `AdminQueryService` | HTTP/Web | R | self | n/a | no |

## Required domain entities

- `AdminUser`
- `AdminCommand`
- `AdminAuditEvent`
- `TariffVersion`
- `PaymentEvent`
- `OperationEvent`
- `SupportTicket`
- `SupportMessage`
- `SupportOutbox`
- `CmsDocument`
- `CmsDocumentVersion`
- `NotificationCampaign`
- `NotificationDelivery`
- `PartnerProfile`
- `PartnerWithdrawal`
- `PromoCode`
- `PromptLibraryItem`
- `RuntimeFlag`
- `ModelAvailability`
- `TrendItem`
- `FeedModerationAction`

## State transitions

### Admin command

`reserved -> succeeded | failed`

A succeeded command is immutable and replays the stored response for the same `(admin_user_id, action, idempotency_key)`. Reuse with a different request hash is a conflict.

### Payment admin action

`observed -> recheck_requested -> checked`

`observed|checked -> reprocess_requested -> processed|failed`

A payment credited once stores `credited_ledger_key`; reprocessing can never create a second credit for the same payment.

### Support ticket

`open -> pending -> resolved -> closed`, with reopen to `open` by an authorized admin. Ticket replies create `SupportOutbox(status=pending)` and a `SupportMessage(status=queued)` before commit.

### Support outbox

`pending -> processing -> sent | retry_wait -> processing | dead_letter`

### CMS

A document owns immutable numbered versions. `draft -> published`; publishing a version never mutates prior published content.

### Notification campaign

`draft -> ready -> running -> completed`

`draft|ready|running -> cancelled`

Starting a campaign materializes each recipient into `NotificationDelivery` once under a unique `(campaign_id, recipient_id)` constraint.

### Notification delivery

`pending -> processing -> sent | retry_wait -> processing | failed`

### Partner withdrawal

`pending -> approved -> paid` or `pending|approved -> rejected`.

### Prompt moderation

`pending -> approved | rejected`; `approved -> inactive`.

## Delivery slices

1. Domain models, migration, policy, security, command ledger and shared services.
2. Signed internal admin API and runtime model-availability guard.
3. Telegram `/admin` thin UI/FSM and signed client.
4. Internal admin web operator surface.
5. Durable support/notification/payment admin workers.
6. Unit, integration, Telegram/FSM and web security tests plus runbook.
