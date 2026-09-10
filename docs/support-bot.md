# HappyFox AI Support Bot

HappyFox has a dedicated Telegram support contour that is isolated from the main generation bot.

## Architecture

- Entry point: `python -m bot.support_bot_runtime`.
- Telegram token: `SUPPORT_BOT_TOKEN` (never the main `BOT_TOKEN`).
- Runtime: separate Docker Compose service `support_bot`.
- Compose profile: `support`; the service does not start during ordinary backend deploys until the profile is explicitly enabled.
- AI provider: Kie.ai Responses API, `POST /codex/v1/responses`.
- Model: `gpt-5-5` by default (`SUPPORT_AI_MODEL`).
- Kie credential: `SUPPORT_KIE_API_KEY`, with `KIE_AI_API_KEY` as an optional server-side fallback.
- Conversation history: Redis, scoped under the HappyFox prefix, 24-hour TTL by default, with an in-process fallback if Redis is unavailable.
- Human escalation: existing `support_tickets` / internal admin support UI.
- Operator replies for tickets with source `telegram_support_bot` are delivered by the support bot token, while ordinary `telegram` tickets stay on the main bot token.

The support process uses long polling deliberately. This keeps the transport fully separate without adding another public reverse-proxy route or changing the main HappyFox webhook runtime.

## User flow

1. `/start` resets context and opens AI support.
2. Text questions are answered by GPT-5.5.
3. Screenshots are sent to GPT-5.5 as image input together with the user's text.
4. `/new` clears the AI conversation.
5. `/operator` immediately creates a human support ticket.
6. GPT-5.5 may request escalation for account/payment/refund/server issues. The internal marker is removed before sending the answer to the user, and a human ticket is created automatically.
7. Documents/video/audio bypass AI and are attached to a human ticket.
8. If Kie is unavailable after retries, the user's question is automatically escalated instead of being lost.

## Production configuration

Create `/opt/happyfox/repo/.env.happyfox.support` from `.env.happyfox.support.example` and set at minimum:

```dotenv
SUPPORT_BOT_TOKEN=<telegram support bot token>
SUPPORT_KIE_API_KEY=<optional dedicated Kie key>
```

Do not store either value in Git.

Start the isolated contour:

```bash
docker compose -f compose.backend.yml --profile support up -d support_bot
```

The regular main bot remains unchanged.

## Safety boundary

GPT-5.5 can explain and troubleshoot but cannot mutate balances, payments, accounts, generations, refunds or admin settings. Such requests are escalated to the existing human support workflow. The system prompt also forbids asking for passwords, 2FA codes, bank credentials or API keys.
