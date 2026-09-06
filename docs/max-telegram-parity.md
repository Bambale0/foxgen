# MAX ↔ Telegram UX parity matrix

This document is a release checklist. Telegram Bot is the visible UX source of truth; MAX keeps native identity, storage and billing boundaries.

| Telegram surface | MAX surface | Required parity |
| --- | --- | --- |
| Main menu | `max:home` | same visible rows/order/actions |
| Create photo | `max:create_image` | model → refs → settings → prompt → confirm |
| Create video | `max:create_video` | model → type → media → settings → prompt → confirm |
| Motion Control | `max:motion_control` | same scenario/options/outcome |
| Prompt by description/photo | `max:photo_prompt` | native MAX media → shared analyzer → MAX debit/refund |
| Prompt by video | `max:video_prompt` | native MAX video → shared analyzer → MAX debit/refund |
| AI assistant | `max:assistant` | same purpose and navigation, MAX-owned context |
| Prompt library | `max:prompts` | native browsing and prompt detail |
| Feed | `max:feed` | public feed browsing and equivalent actions |
| Balance | `max:balance` | same terminology/navigation; separate MAX ledger |
| Support | `max:support` | same destination/outcome |
| Partners | `max:partners` | same product outcome; MAX-native referral IDs |
| More | `max:more` | Help / Support / Top up / Home |

## Creator invariants

Photo:

```text
model → reference collection/skip → ratio/quality/count → prompt → confirm → durable jobs
```

Video:

```text
model → source type → required media → duration/ratio/model settings → prompt → confirm → durable job
```

Specialized model wizards may keep additional settings only when Telegram exposes the same provider capability. They still enter from the same model-first navigation.

## Transport exceptions

MAX callback payloads and attachment envelopes necessarily differ from Telegram callback_data and Telegram file IDs. These transport differences are not UX differences.

Payment providers may differ when a provider is platform-specific, but balance/top-up navigation and failure recovery must preserve the same user outcome.

## Release assertion

Do not mark MAX parity complete while any visible Telegram main action maps to a placeholder, “coming soon” screen or an older MAX-only information architecture.
