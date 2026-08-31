# HappyFox trace map index

Canonical current traces:

- [../tracemap_generation.md](../tracemap_generation.md) — Telegram + Instagram generation, Seedream/Seedance durable lifecycle, retries/refunds.
- [../tracemap_payments.md](../tracemap_payments.md) — shared ledger, Telegram providers, Instagram YooKassa/Lava handoff, account-link/resume.
- [../tracemap_feed_referral.md](../tracemap_feed_referral.md) — feed/prompt/referral paths; verify current code before operational use if it contains legacy naming.
- [../tracemap_credits_check.md](../tracemap_credits_check.md) — shared balance checks; verify against current pricing/billing helpers.
- [../FSM_USER_FLOWS.md](../FSM_USER_FLOWS.md) — canonical Telegram + Instagram state transitions.
- [instagram-channel.md](instagram-channel.md) — canonical Instagram transport/product/live activation trace.

Historical full-map snapshots such as `tracemap_complete_RU.md` were imported with the production core and can contain old NEUROMIX/Tanya names or topology. Use them only for provenance/code discovery, not as production runbooks.

Trace convention:

```text
Source
 -> transport/handler
 -> normalization/auth
 -> identity/state
 -> validation/pricing
 -> DB/durable job
 -> provider/payment side effect
 -> webhook/poll/retry
 -> final ledger/history/delivery side effect
```

When a trace disagrees with runtime, priority is current code -> tests -> CI/workflows -> canonical docs.
