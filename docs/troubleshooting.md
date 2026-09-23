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

## 4. Telegram bot is silent after deploy

Check both directions separately. A healthy `/health` route does not prove Telegram connectivity.

1. `getWebhookInfo` must show `https://api.happy-fox.online/webhook`, zero pending updates and no recent delivery error.
2. When `TELEGRAM_WEBHOOK_IP_ADDRESS` is configured, Telegram must report that same fixed ingress IP.
3. The relay must present a valid certificate for `api.happy-fox.online` and proxy to the dedicated backend.
4. Outbound Bot API calls from the dedicated host/container must succeed; check `happyfox-telegram-egress.service`.
5. Confirm the native system menu is `web_app` and points to `https://app.happy-fox.online/mini-app/`; quick commands must remain registered separately.

If incoming webhook delivery works but responses time out, diagnose outbound Telegram connectivity. If Bot API calls work but `pending_update_count` grows, diagnose ingress/TLS/relay. Do not start a second bot worker on the relay host.

### 4.1 Tunnel is active but every Bot API call times out

Symptom: incoming webhook delivery works, the bot receives updates, no reply arrives, and the log shows `TelegramNetworkError: HTTP Client says - Request timeout error` with ~60 s durations. `systemctl status happyfox-telegram-egress.service` may still report `active (running)`, because the SSH listener can stay healthy while the host firewall drops traffic to the tunnel port.

Cause: the HappyFox host firewall INPUT policy is `DROP`. The DNAT'ed egress reaches `172.18.0.1:<tunnel port>` instead of `api.telegram.org:443`, so the tunnel port needs its own `filter/INPUT` ACCEPT for the container subnets. Without it the container-side SYN is dropped and the client only sees a timeout.

Diagnose:

```bash
iptables -S INPUT | head -3
/usr/local/sbin/happyfox-telegram-egress-nat status
docker exec foxgen-happyfox-bot python -m scripts.check_telegram_egress
```

`status` reports `stage=status outcome=incomplete missing=<n>` when a rule is absent. Restore the canonical rule set instead of editing production source:

```bash
/usr/local/sbin/happyfox-telegram-egress-nat up
/usr/local/sbin/happyfox-telegram-egress-nat status
```

`happyfox-telegram-egress.service` re-applies the whole rule set on every start, so a partial rule set is a deploy/unit defect, not a one-off manual fix.

## 5. Instagram webhook route is missing/404

First check:

```dotenv
INSTAGRAM_ENABLED
```

When `0`, Instagram route/worker registration is intentionally skipped. This is not a routing bug.

If live is expected, verify production runtime actually has `INSTAGRAM_ENABLED=1` and the Meta variables set.

## 6. Meta GET webhook verification fails

Check:

- public HTTPS path matches `INSTAGRAM_WEBHOOK_PATH`;
- Meta callback URL points to the correct HappyFox origin;
- `hub.verify_token` equals the configured `INSTAGRAM_VERIFY_TOKEN`;
- proxy forwards query parameters;
- the correct production version is deployed.

Never log/share the verify token value.

## 7. Meta POST webhook signature fails

The runtime verifies `X-Hub-Signature-256` using HMAC-SHA256 over the **raw request body** and `INSTAGRAM_APP_SECRET`.

Check:

- correct Meta app secret is deployed;
- reverse proxy does not alter/decompress/re-encode body unexpectedly;
- signature header reaches aiohttp;
- test signs the exact raw bytes sent.

Do not weaken signature validation or parse/re-serialize JSON before HMAC comparison.

## 8. Instagram event processed twice

Check Redis/idempotency state and stable event ID normalization.

Never solve duplicates by globally ignoring repeated user text; the same prompt can be legitimate. Deduplicate Meta delivery events using event identity/idempotency.

Financial/generation side effects must also be durable/idempotent independently.

## 9. Instagram replies in wrong language

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

## 10. First photo is not free

Expected rule: only first **successful Instagram photo** is free.

Check:

- promotion exists for the Instagram identity;
- status/reservation is not stale or consumed;
- user did not already receive a successful free result;
- relinking to a different Telegram account must not reset entitlement.

If a provider failed terminally, the promotion should be released/preserved.

## 11. Free photo was consumed after provider failure

Trace promotion reservation key and generation job.

Expected:

```text
reserve -> provider terminal fail -> release
```

Consumption belongs after successful media delivery/finalization path, not provider submit.

Do not manually recreate a second promotion row without understanding the unique identity constraint.

## 12. Video accepts a reference before payment

This is a product regression.

Expected:

```text
Video -> video:awaiting_topup -> top-up/Continue -> sufficient balance -> ask reference
```

A media message in `video:awaiting_topup` must not bypass the paywall. Check `instagram_creator_generation` / video state handler and corresponding regression test.

## 13. Continue/Продолжить does not resume video

Check:

1. Instagram identity is linked to a HappyFox user;
2. shared balance is sufficient for current Seedance price;
3. draft state is video top-up/resume state;
4. RU/EN command normalizer recognizes input;
5. pricing resolves from shared HappyFox video pricing.

If balance is insufficient, remaining in paywall is expected.

## 14. Instagram payment chooser shows CryptoBot or Stars

Instagram-specific handoff should expose only:

```text
YooKassa
Lava Top
```

Check `bot/handlers/instagram_account_link.py`.

Do **not** fix this by removing CryptoBot/Stars from the global Telegram payment system. Telegram keeps its configured providers independently.

## 15. Instagram YooKassa unavailable

Check YooKassa service enablement/credentials and available packages. Instagram reuses existing production YooKassa handlers rather than a second checkout implementation.

Verify webhook/transaction behavior with the normal payment diagnostics.

## 16. Lava Top package/method unavailable

Check:

- Lava service enabled;
- HappyFox `LAVA_OFFER_ID_*` for the selected package;
- RUB currency/offer resolution;
- card/SBP callbacks route to existing Lava production handlers.

Never fall back to imported Tanya offer IDs.

## 17. Telegram CryptoBot disappeared after Instagram change

That is a regression. Instagram restriction must not remove CryptoBot from Telegram.

Check whether shared/global payment keyboard/provider configuration was modified instead of only Instagram account-link handoff.

## 18. Paid generation charged twice

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

## 19. Provider generation runs twice after restart

Check `provider_task_id` persistence. If it exists, worker should resume polling that provider task instead of calling createTask again.

A job with `result_url` should retry delivery without regeneration.

## 20. Result delivered twice

Check `result_url` and `delivered_at_epoch` checkpoint. Local finalization retries after a saved delivery checkpoint should not intentionally re-send.

Note: there is an unavoidable distributed-systems ambiguity if Meta accepts a send and the process crashes before the local delivery checkpoint commits. Do not promise absolute exactly-once remote delivery.

## 21. Paid provider failure did not refund

Trace job billing mode/cost/transaction and terminal provider status.

Expected terminal paid failure -> refund once. Transient/pending provider state should normally remain queued/retry without premature refund if the same external task may still succeed.

## 22. Instagram comments do not start generation

Expected behavior is acquisition, not direct generation:

```text
comment keyword -> private invite -> Direct -> Photo/Video chooser
```

Meta private reply has platform restrictions; it is not an unlimited cold-DM channel.

## 23. Instagram live needs emergency disable

If Telegram/Mini App are healthy:

```dotenv
INSTAGRAM_ENABLED=0
```

Redeploy/restart the verified version. This is preferred over rolling back unrelated application changes.

Preserve identity/promotion/job data for investigation.

## 24. Safe diagnostics

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


## 25. Prompt sent as formatted text gets no reply (rich_message)

Telegram clients can deliver formatted content (for example, text pasted from a
web page) as `Message.rich_message` without `text`, `caption` or `entities`.
Prompt handlers are `F.text` based, so an unnormalized rich message matches no
handler: the bot stays silent, no generation task is created, and telemetry
shows `route=message:rich_message handler=-`.

The normalization middleware (`bot/services/telegram_rich_message.py`)
extracts plain text from the rich blocks and writes it into `Message.text`
before routing. Verify after a restart:

1. Send a formatted prompt; telemetry must show
   `telegram_rich_message_normalized update_id=...` and the prompt handler must
   fire (`Added new generation task`).
2. A rich message that carries no text (media-only) logs
   `telegram_rich_message_without_text`; that is expected, not a delivery bug.
3. If neither log line appears for a rich message, check that
   `RichMessageNormalizerMiddleware` is registered as an update-level outer
   middleware after `TelegramUpdateTelemetryMiddleware` in `bot/main.py`.
4. Extraction failures must never drop the update silently: they log
   `telegram_rich_message_normalization_failed` and the update is left
   untouched rather than crashing the handler chain.


## 26. Bot is silent although health, webhook and the egress tunnel look healthy

Incident 2026-09-23: replies stopped while `/health` was 200, `getWebhookInfo`
reported the correct URL, zero pending updates and no delivery error, and
`happyfox-telegram-egress.service` was active. Telemetry showed
`telegram_bot_api method=... outcome=error error_type=TelegramNetworkError`
("Request timeout error") for `sendDocument`, `answerCallbackQuery` and
`editMessageText`.

Root cause: the host INPUT chain policy is `DROP`. Outbound Bot API calls leave
the container to the Docker gateway and are DNAT'ed to the SSH tunnel port
(`HAPPYFOX_TELEGRAM_EGRESS_PORT`, default 18443) on the host itself. The DNAT
happens in `PREROUTING`, but the packet still passes the `INPUT` filter chain,
where no rule accepted the tunnel port for the container subnet. Effect: SYN to
the tunnel port was dropped, the TCP connect hung until the Bot API timeout, and
the tunnel process itself kept listening and looked healthy.

Diagnose (read-only):

```bash
iptables -S INPUT | head            # INPUT policy must be DROP in production
iptables -t nat -S PREROUTING | grep 18443
iptables -t nat -S OUTPUT | grep 18443
/usr/local/sbin/happyfox-telegram-egress-nat status   # exit 0 only when complete
docker exec foxgen-happyfox-bot \
  python -m scripts.check_telegram_egress             # bounded getMe, fails loudly
```

Converge:

```bash
/usr/local/sbin/happyfox-telegram-egress-nat up
```

Do not work around this by starting a second bot worker on the relay, changing
`TELEGRAM_WEBHOOK_IP_ADDRESS`, or removing Telegram from `allowed_updates`.

Guardrails shipped with this fix:

- `scripts/happyfox_telegram_egress_nat.sh` is the single owner of the rule set:
  `INPUT` ACCEPT for every container subnet, `PREROUTING` DNAT for
  `149.154.160.0/20:443`, and `OUTPUT` REDIRECT for host-local calls. Values are
  overridable (`HAPPYFOX_TELEGRAM_EGRESS_*`), so nothing needs a source edit;
- `happyfox-telegram-egress.service` runs the script as `ExecStartPre`, so every
  start, restart and reboot re-applies the rule set;
- `happyfox-telegram-egress-guard.timer` re-applies it every five minutes, which
  recovers automatically when an unrelated host firewall change drops it again;
- the production deploy writes `/etc/default/happyfox-telegram-egress` from the
  live `foxgen_backend` network, restarts the tunnel, then requires
  `happyfox-telegram-egress-nat status` and
  `python -m scripts.check_telegram_egress` to succeed, so a silent-outage
  revision fails the deploy instead of looking green.

If the bot is still silent after `status` reports `rules=complete`, the failure is
elsewhere: re-check ingress (`getWebhookInfo`), container telemetry
(`telegram_update`, `telegram_bot_api`), and the handler route before touching
the firewall again.
