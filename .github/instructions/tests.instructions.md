---
applyTo: "**/*{test,spec}*.{py,ts,tsx,js,jsx}"
---

# Test Instructions

- Prefer behavior-focused tests over implementation snapshots.
- Mock network, payment, Telegram, cloud, and filesystem side effects.
- Include negative and edge cases, not only happy paths.
- Test idempotency for webhooks, payments, and background jobs.
- Keep tests deterministic and independent of execution order.
