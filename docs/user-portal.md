# Happy Fox user portal

Happy Fox exposes ordinary user-facing tariff, support and partner capabilities through the Telegram-derived Mini App JWT. These routes do not expose the signed admin control plane or operator credentials.

## Tariffs

`GET /v1/miniapp/tariff` returns only the current published tariff version. The browser renders the server payload and never invents package prices or commercial terms.

## Support

Owner-scoped routes let the authenticated Telegram user list, create and read support tickets, reply to an open ticket and close it. Ticket/message history is durable and another user receives no access to the ticket.

Mini App surface:

- support home and ticket list;
- create ticket form;
- ticket conversation;
- reply;
- close with explicit confirmation;
- empty/loading/error states.

## Partners

The partner page exposes the authenticated user's partner profile, referral count, earned/pending/available units and withdrawal history. A user can join the partner program and create a withdrawal request against their own available partner balance.

Withdrawal creation requires an `Idempotency-Key`. The key is persisted with a canonical request hash, so an ambiguous retry replays the same withdrawal while reuse with different amount/destination fails closed. The Happy Fox form keeps one key until the request succeeds.

The ordinary browser never receives admin approval/rejection actions. Review remains in the privileged admin contour.

## Safety boundaries

Trusted user-portal reads/writes authenticate user context independently of `FOXGEN_TASK_SUBMISSION_ENABLED`; disabling paid provider submission must not disable tariff/support/partner access. Browser Mini App routes continue to use the Telegram-derived JWT.

Partner withdrawal idempotency is a PostgreSQL uniqueness boundary, not a frontend-only debounce. Admin/operator approval remains a separate privileged action.

## UI contract

The portal follows the Happy Fox graphite/orange design. Grunge remains decorative; forms, financial rows and support messages use clean high-contrast surfaces. Telegram BackButton navigation and the existing Mini App JWT refresh path remain shared with the rest of Happy Fox.
