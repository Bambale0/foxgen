# User promo redemption

FoxGen supports administrator-managed promo codes that grant one-time `CREDIT` bonuses to authenticated users. Promo redemption is a financial operation: the browser never supplies the reward amount and no balance row is mutated outside the shared PostgreSQL/ledger boundary.

## Admin definition

Promo definitions already live in `promo_codes` and are managed through the signed internal admin control plane. A promo has:

- normalized uppercase `code`;
- `active` flag;
- positive `reward_units` required for user redemption;
- optional `max_uses`;
- materialized `uses` counter;
- metadata and creating admin identity.

Admin creation/update is not a user redemption. The reward is granted only when an authenticated user successfully redeems the code.

## User APIs

Trusted Telegram/user-service transport:

```text
POST /v1/user-portal/promos/redeem
```

Authentication:

- internal bearer token;
- owner binding through `X-FoxGen-User-Id`;
- optional `X-FoxGen-Username` projection.

Happy Fox transport:

```text
POST /v1/miniapp/promos/redeem
```

Authentication is the normal Telegram `initData` -> Happy Fox JWT owner boundary. The request payload contains only:

```json
{"code": "FOX500"}
```

The response returns normalized code, granted CREDIT, current available balance and whether the call replayed an existing redemption.

## Atomic redemption

The service normalizes the code with `strip().upper()` and locks the `promo_codes` row before checking or consuming it. The transaction performs:

```text
BEGIN
  lock promo code
  check existing (promo_code, user_id) redemption
  validate active/reward/max_uses
  ensure user
  lock/ensure CREDIT wallet
  available_units += reward_units
  append immutable ledger entry
  create promo_redemptions row
  promo_codes.uses += 1
COMMIT
```

The immutable ledger key is:

```text
promo-credit:<NORMALIZED_CODE>:<user_id>
```

The redemption row and ledger key are independently unique. A duplicate request for the same user/code returns the existing redemption and current balance; it does not consume another use or append another credit.

## Concurrency and max uses

`max_uses` is protected by the same row lock that serializes redemption. For `max_uses=1`, two different users cannot both observe the same remaining use and receive the reward. Once the successful transaction increments `uses`, the next transaction fails before user wallet/redemption creation.

For one user sending concurrent duplicate requests, the first transaction creates the redemption and the second waits on the promo lock, then observes the durable redemption and replays it.

## Durable schema

Alembic revision `20260816_0014` adds `promo_redemptions`:

```text
id
promo_code -> promo_codes.code
user_id -> users.id
reward_units
ledger_key
redeemed_at
```

Constraints:

- unique `(promo_code, user_id)`;
- unique `ledger_key`;
- `reward_units > 0`;
- promo-definition deletion is restricted when redemption audit rows exist.

The promo definition therefore cannot be deleted out from under its redemption audit history. Ordinary disablement uses `active=false` instead.

## Failure behavior

- missing code: no wallet mutation;
- inactive code: no wallet mutation;
- zero/non-positive reward: no wallet mutation;
- exhausted `max_uses`: no wallet/redemption for the attempted user;
- duplicate user redemption: replay existing result, no new credit/use;
- ledger key exists without a matching redemption: fail closed with idempotency conflict rather than guessing.

A user who redeemed while the promo was valid can still replay that existing redemption later if the code becomes disabled or exhausted; replay does not create a new financial effect.

## Happy Fox UI

The wallet screen loads `promo-redeem.js`/`promo-redeem.css`. The control:

1. accepts a code only;
2. authenticates through Telegram `initData` and a short-lived Mini App JWT;
3. posts to `/v1/miniapp/promos/redeem`;
4. shows granted CREDIT/current balance or the replay message;
5. refreshes the wallet projection after success.

Outside Telegram, the UI fails closed instead of attempting an unauthenticated redemption.

## Testing and E2E

Required CI coverage includes:

- owner-scoped Mini App/trusted API tests;
- Happy Fox static UI contract;
- real PostgreSQL concurrent duplicate redemption;
- real PostgreSQL `max_uses` enforcement;
- exactly one redemption, one use and one immutable promo ledger entry;
- cross-layer E2E: signed admin promo creation -> Happy Fox JWT redeem -> trusted ledger read -> duplicate replay -> exhausted second-user rejection.

The E2E runs in the required infrastructure job with real FastAPI routing/security and real PostgreSQL state. No external provider call is needed for promo redemption.

## Current scope boundary

This feature implements explicit promo-code bonuses. Automatic purchase-triggered bonus campaigns (for example, bonus CREDIT based on a Stars package/payment without a user-entered code) are a separate policy slice and must not be inferred from `promo_codes`.