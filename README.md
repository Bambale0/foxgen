# HappyFox

**HappyFox** — Telegram-бот и Telegram Mini App для генерации изображений, видео и AI-контента с балансом, платежами, референсами, историей, лентой, партнёрской программой и административным контуром.

Репозиторий `Bambale0/foxgen` — самостоятельный продукт. Внутри сохранены некоторые технические идентификаторы `banano_*`/`banana_*`: это совместимые provider/database/runtime identifiers, а не пользовательский бренд.

## Production core

20 августа 2026 HappyFox был переведён на проверенное production-ядро `Bambale0/banano_kling`, ветка `tanyapi`, exact SHA:

```text
36f92a0504f849c0c591652a880410e33a1c89aa
```

Источник и точка миграции зафиксированы в [`MIGRATION_SOURCE.md`](MIGRATION_SOURCE.md). Предыдущая реализация FoxGen сохранена в ветке:

```text
legacy/foxgen-pre-tanyapi-20260820
```

`banano_kling/tanyapi` после миграции не является runtime-зависимостью HappyFox: код живёт и развивается в `foxgen`.

## Возможности

### Telegram / Mini App

- Telegram WebApp `initData` с серверной HMAC-проверкой;
- Next.js + React Mini App;
- production static export;
- главные пользовательские разделы, генерация, история и realtime/status sync;
- загрузка файлов и сохранённые референсы;
- лента, профили, remix/repeat/share;
- браузерный fallback-вход;
- адаптация под Telegram WebView.

### Генерации

Ядро содержит production adapters/capabilities для image/video сценариев, включая семейства Nano Banana, GPT Image, Seedream, Seedance, Kling, Grok, Veo, Wan и другие модели, доступность которых определяется runtime-конфигурацией и `data/price.json`.

Поддерживаются:

- text → image;
- image/reference → image;
- text → video;
- image/reference → video;
- video edit / video reference flows;
- Motion Control;
- first/last frame и multimodal scenarios для поддерживающих моделей;
- provider callbacks, polling, retries и сохранение результатов.

### Billing / product

- внутренний баланс и ledger;
- Telegram Stars;
- CryptoBot;
- T-Bank;
- дополнительные payment adapters, оставшиеся совместимыми с production core;
- промокоды;
- referral/partner flows;
- административные операции.

## Стек

```text
Python 3.12
aiogram 3 + aiohttp
PostgreSQL
Redis
Next.js 16 + React 19 + TypeScript
Docker / Docker Compose
Playwright browser E2E
GitHub Actions
```

SQLite compatibility остаётся в коде для тестов/миграций, но HappyFox production deploy требует PostgreSQL.

## Структура

```text
bot/                       backend, Telegram handlers, Mini App API
bot/services/              AI/payment/storage/reliability adapters
frontend/miniapp-v0/       Next.js Mini App
data/                      prices/runtime presets
scripts/                   deploy, backup, repair, migration utilities
tests/                     backend regression/integration tests
deploy/                    HappyFox environment templates
.github/workflows/ci.yml   release CI gate
```

## Локальная проверка

Backend:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-mock ruff

PRODUCT_ID=happyfox \
BOT_TOKEN='123456:TEST_TOKEN_FOR_CI_ONLY' \
pytest tests/ --ignore=tests/live -m 'not live_smoke'
```

Mini App:

```bash
cd frontend/miniapp-v0
npm ci
npm audit --omit=dev --audit-level=high
npm run lint
NEXT_PUBLIC_PRODUCT_ID=happyfox npm run build
npx playwright install --with-deps chromium
rm -rf .e2e-server
mkdir -p .e2e-server/mini-app
cp -R out/. .e2e-server/mini-app/
NEXT_PUBLIC_PRODUCT_ID=happyfox node e2e/critical-flows.mjs
```

## CI release gate

Каждый PR и `main` проходят:

1. dependency install/check;
2. HappyFox product-copy normalization;
3. Python compile;
4. Ruff для нового HappyFox Python delta;
5. полный safe regression suite production core;
6. Mini App dependency audit + lint;
7. production Next static export;
8. HappyFox brand/export assertions;
9. Chromium critical browser journeys;
10. production Docker image build + runtime smoke.

Historical lint debt импортированного production core не считается новым кодом, но весь backend всё равно проходит regression tests.

## Production environment

Шаблон:

```text
deploy/happyfox.env.example
```

Обязательные принципы:

- отдельный Telegram bot token;
- отдельный PostgreSQL database/user;
- отдельный Redis URL/DB и `REDIS_PREFIX=foxgen_happyfox`;
- отдельные Mini App/API/media URLs;
- отдельные payment webhooks/credentials;
- никакого fallback на Tanya/NEUROMIX hosts или data stores.

Безопасный ручной entrypoint:

```bash
sudo bash scripts/deploy_happyfox.sh deploy
```

Он fail-closed проверяет HappyFox URLs, PostgreSQL и Redis isolation перед вызовом проверенного Docker deploy engine.

## Branding

Frontend source of truth:

```text
frontend/miniapp-v0/lib/product.ts
frontend/miniapp-v0/lib/brand.ts
frontend/miniapp-v0/public/happyfox-logo.webp
```

Backend source of truth:

```text
bot/product.py
```

Пользовательский бренд — **HappyFox**. Названия AI-моделей (`Nano Banana`, `Kling`, `Seedance`, `Grok`, `Veo` и т. п.) не переименовываются.

## Source of truth

При конфликте документации и реализации приоритет такой:

1. `.github/workflows/ci.yml`;
2. `bot/main.py`;
3. `bot/miniapp.py`;
4. `bot/config.py`;
5. `frontend/miniapp-v0/lib/api.ts` и `lib/app-context.tsx`;
6. `data/price.json` / `bot/services/preset_manager.py`;
7. `tests/`;
8. документация.

## Security

Не коммитить `.env`, Telegram tokens, provider/payment keys, SSH/private keys и Cloudflare credentials. Production secrets живут только в server-side environment/GitHub Environment. Перед релизом не допускается использование общей БД, Redis namespace, media root или payment webhook с другим продуктом.
