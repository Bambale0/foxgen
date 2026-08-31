# Historical internal admin notifications contract

The notification control-plane endpoints previously described here belonged to an older external admin design. They are not a current HappyFox production contract unless present in current runtime code/tests.

Use `internal-admin-api.md` for the current `/internal/v1` read-only API. For user notifications, broadcasts and Telegram/Instagram delivery, inspect current HappyFox channel handlers/services.

Do not assume an old Tanya Admin endpoint is safe to call or expose publicly. Any future notification admin write API requires explicit authorization, rate/audience safeguards, audit trail, dry-run/confirmation behavior and regression coverage before being documented as active.
