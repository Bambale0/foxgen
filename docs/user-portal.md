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

The ordinary browser never receives admin approval/rejection actions. Review remains in the privileged admin contour.

## UI contract

The portal follows the Happy Fox graphite/orange design. Grunge remains decorative; forms, financial rows and support messages use clean high-contrast surfaces. Telegram BackButton navigation and the existing Mini App JWT refresh path remain shared with the rest of Happy Fox.
