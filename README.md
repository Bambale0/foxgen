# NEUROMIX

`NEUROMIX` — Telegram-бот и Telegram Mini App для генерации изображений и видео, работы с референсами, публикации контента, платежей, партнёрской программы и внутренних административных инструментов.

> Репозиторий исторически называется `banano_kling`, а в коде встречаются технические идентификаторы `banano-*`, `banana_*` и названия моделей семейства Nano Banana. Это внутренние и provider-идентификаторы. Пользовательский бренд продукта — **NEUROMIX**.

## Ветки и выпуск

Проект использует отдельные DEV- и production-контуры:

```text
feature/* -> PR в dev -> строгий CI -> автодеплой DEV-бота и DEV Mini App
          -> ручной Telegram smoke -> PR dev -> tanyapi
          -> автодеплой production-бота и production Mini App
```

| Ветка | Назначение | Deploy |
| --- | --- | --- |
| `feature/*`, `fix/*`, `agent/*` | изолированная разработка | только CI в PR |
| `dev` | тестовый Telegram-бот и тестовая Mini App | автоматический DEV deploy после зелёного CI |
| `tanyapi` | production source of truth | автоматический production deploy |
| `main` | default/историческая ветка репозитория | не участвует в release flow NEUROMIX |

DEV использует отдельные bot token, webhook, Mini App URL, checkout, Docker project/container, базу, Redis namespace, media и тестовые payment credentials. Полная подготовка описана в [docs/development-deployment.md](docs/development-deployment.md).

## Production-схема

Production всегда соответствует ветке `tanyapi`.

| Компонент | Адрес | Сервер | Назначение |
| --- | --- | --- | --- |
| Telegram Mini App | `https://cdn.chillcreative.ru/mini-app/` | `91.200.84.187` | Статический Next.js export и reverse proxy к API |
| Backend API | `https://tanyapi.chillcreative.ru` | `144.76.188.75` | Telegram webhook, Mini App API, webhooks провайдеров и платежей |
| Media origin/CDN | `https://media.chillcreative.ru/uploads/...` | `144.76.188.75` через Cloudflare | Nginx-раздача существующей папки `static/uploads` |
| Backend checkout | — | `144.76.188.75` | `/root/tanya/banano_kling`, строго ветка `tanyapi` |
| Backend service | — | `144.76.188.75` | `banano-kling.service` |

Поток production-запросов:

```text
Telegram WebView
    ├── HTML / CSS / JS ──> cdn.chillcreative.ru ──> Nginx static export
    ├── /mini-app/api/* ──> cdn.chillcreative.ru ──HTTPS─> tanyapi.chillcreative.ru
    └── /uploads/feed/* ──> media.chillcreative.ru ──Cloudflare─> Nginx ──> static/uploads
```

Публичный backend проходит через HTTPS-домен. Открывать внешний доступ к `aiohttp :1888` для frontend-сервера не требуется.

## Основные возможности

### Telegram-бот

- webhook runtime на `aiogram 3` + `aiohttp`;
- FSM-сценарии генерации фото, видео и motion control;
- отправка фото/видео/референса в любой момент поддерживаемого сценария;
- история задач и повтор генерации;
- публикация в общую ленту и профиль либо только в профиль;
- платежи, баланс, промокоды, партнёрские начисления;
- административные и диагностические маршруты.

### Mini App

- единый бренд **NEUROMIX** в заголовках, metadata, загрузчике и основных экранах;
- отдельный полноэкранный загрузчик во время получения Telegram `initData` и bootstrap;
- браузерный вход через Telegram Login Widget как fallback вне WebView;
- создание фото, видео и motion generation;
- загрузка пользовательских файлов и сохранённых референсов;
- лента, тренды, профили, remix/repeat/share;
- синхронизация статуса задач с backend;
- статическая production-сборка без Node.js runtime на frontend-сервере.

### Media delivery

- production-файлы продолжают храниться в `/root/tanya/banano_kling/static/uploads`;
- Nginx получает к ним доступ через постоянный bind mount;
- публичная лента и WebP-превью кешируются Cloudflare;
- приватные и временные uploads не получают годовой публичный кеш;
- DEV использует отдельный checkout/media root и не должен писать в production `static/uploads`.

## Стек

- Python 3;
- `aiogram 3`, `aiohttp`;
- SQLite/PostgreSQL compatibility layer;
- Redis для FSM/cache с fallback;
- Next.js 16, React 19, Tailwind CSS 4;
- Nginx, Docker Compose, systemd, Certbot;
- Cloudflare Free для production media proxy/cache;
- provider integrations для генерации изображений и видео;
- GitHub Actions для DEV и production CI/CD.

## Структура репозитория

```text
.
├── .github/workflows/            # DEV/production CI и deploy
├── bot/                          # Backend, Telegram handlers, Mini App API
├── data/                         # Цены и runtime data
├── docs/                         # Основная документация
├── frontend/miniapp-v0/          # Next.js Mini App frontend
├── ops/media/                    # Nginx/media-конфигурация и инструкция
├── scripts/                      # Deploy, migration, diagnostics, repair
├── static/uploads/               # Media текущего checkout/окружения
├── tests/                        # Regression и integration tests
├── cdn.sh                        # Менеджер frontend-host и удалённого deploy
└── requirements.txt
```

## Рабочий процесс разработчика

### 1. Создание изменения

Создавать ветку от актуального `dev`:

```bash
git fetch --prune origin
git switch dev
git pull --ff-only origin dev
git switch -c feature/my-change
```

### 2. Проверка в DEV

- открыть PR `feature/my-change -> dev`;
- дождаться `CI — Tanya development`;
- после review выполнить merge в `dev`;
- дождаться automatic DEV backend/frontend deploy;
- полностью закрыть DEV Mini App и открыть её через DEV-бота;
- пройти smoke сценария изменения.

### 3. Выпуск в production

После подтверждения DEV:

- открыть release PR `dev -> tanyapi`;
- не добавлять в него непроверенные изменения;
- дождаться production CI;
- выполнить merge в `tanyapi`;
- дождаться production backend/frontend autodeploy;
- пройти короткий production smoke.

Не выполнять обычный production deploy вручную и не использовать `main` как release branch.

## Локальные проверки

### Backend

```bash
. venv/bin/activate
python -m pytest tests/ --ignore=tests/live -m 'not live_smoke'
python -m py_compile $(find bot tests scripts -name '*.py')
```

### Frontend

Актуальный frontend gate основан на production build и Browser E2E. Старый Jest smoke-файл не является release gate, пока не будет переписан под текущие API и компоненты.

```bash
cd frontend/miniapp-v0
npm ci
npm audit --audit-level=high
npm run lint
npm run build
npx playwright install --with-deps chromium
rm -rf .e2e-server
mkdir -p .e2e-server/mini-app
cp -R out/. .e2e-server/mini-app/
node e2e/critical-flows.mjs
```

Проверка static export:

```bash
test -s out/index.html
test -d out/_next/static
grep -q '_next/static' out/index.html
```

## Ручные production-команды

Команды ниже предназначены для диагностики, первоначальной настройки или аварийного восстановления. Обычный выпуск выполняется GitHub Actions после merge `dev -> tanyapi`.

### Backend status

```bash
cd /root/tanya/banano_kling
git switch tanyapi
git status --short
sudo bash scripts/deploy_backend_docker.sh status
curl -fsS http://127.0.0.1:1888/health
```

### Frontend status

```bash
cd /root/tanya/banano_kling
sudo bash cdn.sh --remote-status tanyafrontend
```

### Media origin

```bash
cd /root/tanya/banano_kling

LETSENCRYPT_EMAIL='admin@example.com' \
ORIGIN_IPV4='144.76.188.75' \
sudo -E bash scripts/deploy_media_origin.sh
```

## Источники истины

При расхождении документации и реализации использовать следующий приоритет:

1. `.github/workflows/ci-development.yml`, `deploy-development.yml`, `deploy-frontend-development.yml` — DEV CI/CD;
2. `.github/workflows/deploy-production.yml`, `deploy-frontend-production.yml` — production CI/CD;
3. `bot/main.py` — runtime wiring и HTTP server;
4. `bot/miniapp.py` — Mini App API и auth contracts;
5. `bot/config.py` — env surface;
6. `frontend/miniapp-v0/lib/api.ts` и `lib/app-context.tsx` — frontend runtime contract;
7. `data/price.json` и `bot/services/preset_manager.py` — модели и цены;
8. `tests/` — ожидаемое поведение;
9. документация.

## Документация

- [docs/development-deployment.md](docs/development-deployment.md) — DEV-бот, отдельные credentials, autodeploy и promotion `dev -> tanyapi`;
- [docs/README.md](docs/README.md) — карта документации;
- [docs/production_auto_deploy.md](docs/production_auto_deploy.md) — production autodeploy строго из `tanyapi`;
- [docs/architecture.md](docs/architecture.md) — архитектура и потоки данных;
- [docs/production-deployment.md](docs/production-deployment.md) — полный production deploy от DNS до smoke tests;
- [docs/miniapp-frontend-deployment.md](docs/miniapp-frontend-deployment.md) — frontend/CDN и `cdn.sh`;
- [ops/media/README.md](ops/media/README.md) — media-домен, Nginx, SSL и Cloudflare;
- [docs/environment.md](docs/environment.md) — переменные окружения;
- [docs/runbook.md](docs/runbook.md) — ежедневная эксплуатация;
- [docs/troubleshooting.md](docs/troubleshooting.md) — диагностика и аварийные сценарии;
- [docs/branding.md](docs/branding.md) — правила бренда NEUROMIX;
- [frontend/miniapp-v0/README.md](frontend/miniapp-v0/README.md) — frontend development и build.

## Безопасность

- не коммитить `.env`, Telegram bot tokens, provider/payment keys, private keys и Cloudflare credentials;
- не использовать production `BOT_TOKEN` в DEV runtime;
- не использовать одну database, Redis prefix, upload root или payment webhook для DEV и production;
- DEV workflows не должны fallback на `PROD_*` secrets;
- environment `development` ограничить веткой `dev`, environment `production` — веткой `tanyapi`;
- не передавать секреты в аргументах команд, если они попадут в shell history;
- хранить Cloudflare token в root-only файле;
- не публиковать backend runtime port наружу без необходимости;
- перед ручными аварийными действиями создавать backup и проверять `nginx -t`;
- HTML не кешировать надолго, hashed assets кешировать как immutable;
- не использовать `rsync --delete` при обычном frontend deploy из-за кеша Telegram WebView.
