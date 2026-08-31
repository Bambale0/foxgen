# HappyFox troubleshooting

Use current `main`, deployment evidence and canonical docs. Historical NEUROMIX/Tanya commands are not valid production instructions for HappyFox.

## 1. “Code is merged but production behaves old”

Check in order:

1. exact merge/main SHA;
2. main CI for that SHA;
3. `Deploy HappyFox production` target SHA/conclusion;
4. public health/static revision.

A merged PR or green PR CI alone does not prove production was updated.

## 2. Public health fails

Check:

- deployment target matches expected SHA;
- container/runtime health;
- Nginx/upstream/TLS;
- PostgreSQL connectivity;
- Redis availability;
- recent deployment logs.

Do not immediately modify Nginx or server checkout before confirming which layer is failing.

## 3. Mini App returns 401/403 in curl

Telegram Mini App APIs validate Telegram authentication data. A manual request without valid `initData` can correctly fail authentication while the backend is healthy.

Distinguish expected auth rejection from timeout/5xx/network failure.

## 4. Instagram webhook route is missing/404

First check:

```dotenv
INSTAGRAM_ENABLED
```

When `0`, Instagram route/worker registration is intentionally skipped. This is not a routing bug.

If live is expected, verify production runtime actually has `INSTAGRAM_ENABLED=1` and the Meta variables set.

## 5. Meta GET webhook verification fails

Check:

- public HTTPS path matches `INSTAGRAM_WEBHOOK_PATH`;
- Meta callback URL points to the correct HappyFox origin;
- `hub.verify_token` equals the configured `INSTAGRAM_VERIFY_TOKEN`;
- proxy forwards query parameters;
- the correct production version is deployed.

Never log/share the verify token value.

## 6. Meta POST webhook signature fails

The runtime verifies `X-Hub-Signature-256` using HMAC-SHA256 over the **raw request body** and `INSTAGRAM_APP_SECRET`.

Check:

- correct Meta app secret is deployed;
- reverse proxy does not alter/decompress/re-encode body unexpectedly;
- signature header reaches aiohttp;
- test signs the exact raw bytes sent.

Do not weaken signature validation or parse/re-serialize JSON before HMAC comparison.

## 7. Instagram event processed twice

Check Redis/idempotency state and stable event ID normalization.

Never solve duplicates by globally ignoring repeated user text; the same prompt can be legitimate. Deduplicate Meta delivery events using event identity/idempotency.

Financial/generation side effects must also be durable/idempotent independently.

## 8. Instagram replies in wrong language

Language is persisted per Instagram identity.

User can explicitly send:

```text
English
Русский
```

If wrong behavior remains:

- verify identity ID/account ID;
- inspect `instagram_channel_languages` safely;
- confirm new copy goes through `instagram_i18n.py`;
- confirm selection parser recognized `Photo/Фото` or `Video/Видео`.

Attachment-first flow should be bilingual until language is known.

## 9. First photo is not free

Expected rule: only first **successful Instagram photo** is free.

Check:

- promotion exists for the Instagram identity;
- status/reservation is not stale or consumed;
- user did not already receive a successful free result;
- relinking to a different Telegram account must not reset entitlement.

If a provider failed terminally, the promotion should be released/preserved.

## 10. Free photo was consumed after provider failure

Trace promotion reservation key and generation job.

Expected:

```text
reserve -> provider terminal fail -> release
```

Consumption belongs after successful media delivery/finalization path, not provider submit.

Do not manually recreate a second promotion row without understanding the unique identity constraint.

## 11. Video accepts a reference before payment

This is a product regression.

Expected:

```text
Video -> video:awaiting_topup -> top-up/Continue -> sufficient balance -> ask reference
```

A media message in `video:awaiting_topup` must not bypass the paywall. Check `instagram_creator_generation` / video state handler and corresponding regression test.

## 12. Continue/Продолжить does not resume video

Check:

1. Instagram identity is linked to a HappyFox user;
2. shared balance is sufficient for current Seedance price;
3. draft state is video top-up/resume state;
4. RU/EN command normalizer recognizes input;
5. pricing resolves from shared HappyFox video pricing.

If balance is insufficient, remaining in paywall is expected.

## 13. Instagram payment chooser shows CryptoBot or Stars

Instagram-specific handoff should expose only:

```text
YooKassa
Lava Top
```

Check `bot/handlers/instagram_account_link.py`.

Do **not** fix this by removing CryptoBot/Stars from the global Telegram payment system. Telegram keeps its configured providers independently.

## 14. Instagram YooKassa unavailable

Check YooKassa service enablement/credentials and available packages. Instagram reuses existing production YooKassa handlers rather than a second checkout implementation.

Verify webhook/transaction behavior with the normal payment diagnostics.

## 15. Lava Top package/method unavailable

Check:

- Lava service enabled;
- HappyFox `LAVA_OFFER_ID_*` for the selected package;
- RUB currency/offer resolution;
- card/SBP callbacks route to existing Lava production handlers.

Never fall back to imported Tanya offer IDs.

## 16. Telegram CryptoBot disappeared after Instagram change

That is a regression. Instagram restriction must not remove CryptoBot from Telegram.

Check whether shared/global payment keyboard/provider configuration was modified instead of only Instagram account-link handoff.

## 17. Paid generation charged twice

P0/P1 financial issue.

Trace:

```text
Instagram event ID
job ID
transaction/charge
provider_task_id
retry attempts
```

Expected: durable job prepared before charge, then one charge and one provider submit. Retry with a persisted provider task ID must poll the same task.

Do not manually refund/credit until duplicate transaction state is understood.

## 18. Provider generation runs twice after restart

Check `provider_task_id` persistence. If it exists, worker should resume polling that provider task instead of calling createTask again.

A job with `result_url` should retry delivery without regeneration.

## 19. Result delivered twice

Check `result_url` and `delivered_at_epoch` checkpoint. Local finalization retries after a saved delivery checkpoint should not intentionally re-send.

Note: there is an unavoidable distributed-systems ambiguity if Meta accepts a send and the process crashes before the local delivery checkpoint commits. Do not promise absolute exactly-once remote delivery.

## 20. Paid provider failure did not refund

Trace job billing mode/cost/transaction and terminal provider status.

Expected terminal paid failure -> refund once. Transient/pending provider state should normally remain queued/retry without premature refund if the same external task may still succeed.

## 21. Instagram comments do not start generation

Expected behavior is acquisition, not direct generation:

```text
comment keyword -> private invite -> Direct -> Photo/Video chooser
```

Meta private reply has platform restrictions; it is not an unlimited cold-DM channel.

## 22. Instagram live needs emergency disable

If Telegram/Mini App are healthy:

```dotenv
INSTAGRAM_ENABLED=0
```

Redeploy/restart the verified version. This is preferred over rolling back unrelated application changes.

Preserve identity/promotion/job data for investigation.

## 23. Safe diagnostics

Never paste full `.env`, access tokens, app secrets, payment secrets, Telegram bot token, signed request headers or unredacted user data.

Capture:

```text
exact SHA
deploy run
channel
sanitized event/job/transaction ID
state/status
expected vs actual
minimal sanitized logs
```
