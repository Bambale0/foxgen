# Документация NEUROMIX

Этот каталог содержит документацию DEV- и production-контуров репозитория `Bambale0/banano_kling`.

## Ветки и release flow

```text
feature/* -> PR в dev -> автодеплой DEV-бота -> ручной smoke
          -> PR dev -> tanyapi -> автодеплой production
```

- `dev` — источник DEV-бота и DEV Mini App;
- `tanyapi` — единственный источник production-бота и production Mini App;
- `main` не участвует в deploy NEUROMIX.

Главный документ по новому процессу: [development-deployment.md](development-deployment.md).

## Как пользоваться документацией

Для разработки и выпуска:

1. [development-deployment.md](development-deployment.md) — отдельный DEV-бот, secrets, серверы, autodeploy и promotion `dev -> tanyapi`;
2. [../README.md](../README.md) — что это за система и где находится production;
3. [production_auto_deploy.md](production_auto_deploy.md) — production autodeploy строго из `tanyapi`;
4. [production-deployment.md](production-deployment.md) — первичное production-развёртывание и полный deploy;
5. [runbook.md](runbook.md) — ежедневные команды оператора;
6. [troubleshooting.md](troubleshooting.md) — диагностика ошибок;
7. [architecture.md](architecture.md) — устройство системы и потоки данных.

Для изменения frontend:

1. [../frontend/miniapp-v0/README.md](../frontend/miniapp-v0/README.md);
2. [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md);
3. [development-deployment.md](development-deployment.md) для отдельного DEV profile/domain;
4. [branding.md](branding.md).

Для media-домена:

1. [../ops/media/README.md](../ops/media/README.md);
2. `scripts/deploy_media_origin.sh`;
3. `scripts/check_media_delivery.sh`.

## Основные документы

| Документ | Для кого | Что содержит |
| --- | --- | --- |
| [development-deployment.md](development-deployment.md) | разработчик, DevOps, владелец | DEV-бот, ветка `dev`, environment secrets, автодеплой и выпуск в `tanyapi` |
| [architecture.md](architecture.md) | разработчик, интегратор | компоненты, topology, auth, storage, API и media flows |
| [production_auto_deploy.md](production_auto_deploy.md) | разработчик, DevOps | promotion `dev -> tanyapi` и production autodeploy |
| [production-deployment.md](production-deployment.md) | DevOps, владелец проекта | DNS, backend, frontend, media, SSL, Cloudflare, smoke tests и rollback |
| [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md) | frontend/DevOps | `cdn.sh`, remote profile, build, release, cache overlap и npm troubleshooting |
| [environment.md](environment.md) | разработчик, DevOps | env-переменные, обязательность, значения и правила хранения секретов |
| [runbook.md](runbook.md) | оператор | restart, status, logs, health, backup и routine checks |
| [troubleshooting.md](troubleshooting.md) | оператор, разработчик | симптомы, причины, команды диагностики и безопасные действия |
| [branding.md](branding.md) | frontend, контент, QA | пользовательский бренд NEUROMIX и допустимые технические имена |
| [roadmap.md](roadmap.md) | продукт, разработчик | задачи и приоритеты, если документ актуализирован под текущий код |
| [tracemap.md](tracemap.md) | разработчик | индекс пользовательских и технических потоков |
| [migration.md](migration.md) | DevOps, backend | backfill, repair и data migration scripts |
| [postgres-migration.md](postgres-migration.md) | backend, DevOps | перенос и проверка PostgreSQL runtime |
| [zero-downtime-migration.md](zero-downtime-migration.md) | DevOps | перенос backend runtime без длительной остановки |

## Production topology

```text
cdn.chillcreative.ru (91.200.84.187)
  ├── /mini-app/             -> статический Next.js export
  └── /mini-app/api/*        -> HTTPS proxy на tanyapi.chillcreative.ru

tanyapi.chillcreative.ru (144.76.188.75)
  ├── Telegram webhook production-бота
  ├── Mini App API
  ├── provider/payment webhooks
  └── aiohttp runtime за локальным Nginx

media.chillcreative.ru (Cloudflare -> 144.76.188.75)
  └── /uploads/*             -> Nginx -> bind mount -> static/uploads
```

Production topology относится только к ветке `tanyapi`. DEV domains, paths и credentials задаются GitHub environment `development` и DEV server `.env`; они не должны использовать production bot token, database или media root.

## Владение документами

### Операционные документы

Должны обновляться при изменении:

- DEV/production branch policy;
- production-доменов или IP;
- DEV-доменов или deploy paths;
- systemd service;
- путей проекта;
- Nginx topology;
- Cloudflare rules;
- deploy scripts;
- env-переменных;
- frontend build process.

К этой группе относятся:

- `README.md`;
- `docs/development-deployment.md`;
- `docs/architecture.md`;
- `docs/production_auto_deploy.md`;
- `docs/production-deployment.md`;
- `docs/miniapp-frontend-deployment.md`;
- `docs/environment.md`;
- `docs/runbook.md`;
- `docs/troubleshooting.md`;
- `ops/media/README.md`;
- `frontend/miniapp-v0/README.md`.

### Provider reference docs

Файлы про отдельные внешние API могут быть снимками документации провайдера и не всегда отражают текущую реализацию. Например:

- `kling_api*.md`;
- `kie_ai_integration.md`;
- `veo_api.md`;
- `motion_control_api.md`;
- `tbank_api.md`;
- `crypto_api.md`.

Если reference-документ конфликтует с runtime, приоритет имеют:

1. `bot/services/*`;
2. `bot/main.py` и `bot/miniapp.py`;
3. `bot/config.py`;
4. `tests/*`;
5. фактический ответ провайдера в безопасно очищенных логах.

## Legacy-материалы

В репозитории могут оставаться:

- старые домены;
- старые IP;
- backup-файлы;
- historical tracemap;
- старое название Banano/Banana;
- старые схемы прямого доступа к backend port;
- старые упоминания deploy из `main`.

Они не должны использоваться для production-действий без сверки с `development-deployment.md`, `production_auto_deploy.md` и текущими workflows.

## Правила обновления документации

При изменении инфраструктуры в одном pull request или серии связанных коммитов обновить:

- branch/release flow;
- topology в `README.md` и `architecture.md`;
- команды deploy в соответствующем runbook;
- env-reference, если добавлена или изменена переменная;
- troubleshooting, если появился новый класс ошибки;
- rollback-процедуру;
- фактический результат проверки в описании изменения, но не временные логи и секреты.

## Минимальный documentation review перед релизом

- feature PR направлен в `dev`;
- DEV exact SHA автоматически задеплоен;
- DEV Telegram smoke пройден;
- release PR направлен `dev -> tanyapi`;
- production workflow слушает только `tanyapi`;
- `main` не указан как production branch;
- DEV и production bot tokens различаются;
- DEV и production databases/storage различаются;
- все пользовательские заголовки используют NEUROMIX;
- production frontend указан как `cdn.chillcreative.ru`;
- production backend указан как `tanyapi.chillcreative.ru`;
- production media указан как `media.chillcreative.ru`;
- нет рекомендаций открывать `:1888` в интернет;
- нет реальных токенов, паролей и содержимого `.env`;
- deploy и rollback команды проверены на синтаксические ошибки;
- различаются ожидаемый `401` без Telegram `initData` и настоящий отказ backend.
