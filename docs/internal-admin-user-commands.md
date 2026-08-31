# Historical internal admin user-command contract

The `/internal/admin/*` user command/control API previously documented here belongs to an older Tanya Admin design and is not a current HappyFox production contract unless current runtime code/tests implement it.

Current HappyFox user state is channel-neutral at the domain level and may be referenced by Telegram and Instagram identities. Any future administrative user mutation must therefore avoid assuming every user is identified only by a Telegram ID.

Use current runtime/database code for authoritative user operations and `internal-admin-api.md` for the currently documented read-only internal API.

Future admin user commands require explicit server-side authorization, audit trail, idempotency/confirmation for destructive actions, and channel-aware identity handling before rollout.
