# HappyFox branding and user-facing copy

## Product brand

User-facing product name is **HappyFox**.

Do not present the product as NEUROMIX, Tanya, Banano Kling or FoxGen legacy in new user-facing copy.

Historical/internal compatibility identifiers such as `banana_*`, `banano_*`, old database enums or callback values may remain where changing them would require a dedicated migration. Technical compatibility names are not user branding.

## Channel surfaces

### Telegram

Telegram Bot + Mini App is the full HappyFox application surface. Navigation, balance, history, feed, partner/support/admin copy should use HappyFox terminology and the user-facing currency **🐾**.

### Instagram

Instagram is a compact creator/acquisition channel. Copy should be conversational, short and task-oriented rather than reproducing the Telegram menu structure.

Core first question:

```text
Фото / Photo
Видео / Video
```

User does not need to know provider implementation details beyond model names that are useful product choices/status information.

## Model names

External model/product names are not rebranded:

```text
Seedream 5 Pro
Seedance 2.5
Kling
Veo
Grok
Nano Banana
other provider/model names in Telegram catalog
```

Instagram fixed models:

- Photo -> Seedream 5 Pro;
- Video -> Seedance 2.5.

## RU/EN Instagram copy

Instagram supports Russian and English automatically.

Rules:

- use `bot/instagram_i18n.py` for Instagram creator/billing/error text;
- meaningful Russian text establishes Russian;
- meaningful English text establishes English;
- attachment-first entry is bilingual until language is known;
- `English` and `Русский` explicitly switch language;
- do not add one-off hard-coded Russian responses to Instagram handlers.

Tone should remain equivalent across languages: creator-friendly, clear about price/payment and free entitlement, no technical API jargon.

## Payment terminology

Instagram:

```text
YooKassa
Lava Top
```

Telegram may additionally show CryptoBot, Stars or other configured providers. Do not write global copy claiming HappyFox has only two payment methods when the restriction is Instagram-specific.

## Free/paid claims

Allowed Instagram claim:

```text
First successful photo generation is free.
```

Do not claim:

```text
first generation is free
first video is free
all first actions are free
```

Video is always paid.

After the free photo, direct the user to top up and continue; do not imply an entitlement was consumed when the provider failed before successful delivery.

## Technical errors

User-facing errors should describe what to do next, not expose:

- HTTP status internals;
- provider payloads;
- database/table names;
- tokens/signatures;
- stack traces;
- raw provider messages containing implementation details.

Logs may contain sanitized technical context, never secrets.

## Documentation copy

Canonical operational docs should use HappyFox/main/current production identity. Historical documents may preserve old product names only when explicitly marked as historical/reference snapshots.
