# Historical internal admin CMS/support contract

This file came from an older Tanya Admin control-plane design. Treat the documented `/internal/admin/*` CMS/support endpoints as historical unless current HappyFox runtime code and tests explicitly implement them.

Current HappyFox internal read-only API is documented in `internal-admin-api.md` and implemented in `bot/internal_api.py`.

For current support/content behavior, inspect the active HappyFox handlers/services and Mini App APIs. Do not deploy or build an external admin client against endpoints described only in this historical document.

Any future CMS/support admin API should be introduced as a new tested HappyFox contract with HMAC/network authorization, idempotent writes where applicable, audit trail and updated documentation in the same PR.
