# DEV-окружение и выпуск в production

Этот документ задаёт обязательную двухконтурную схему разработки NEUROMIX.

## 1. Ветки и окружения

| Ветка | Окружение | Назначение | Автодеплой |
| --- | --- | --- | --- |
| `feature/*`, `fix/*`, `agent/*` | нет постоянного runtime | разработка и pull request | только CI |
| `dev` | development | отдельный DEV-бот и DEV Mini App | после каждого успешного push/merge в `dev` |
| `tanyapi` | production | основной production-бот и production Mini App | после каждого успешного push/merge в `tanyapi` |
| `main` | не используется в release flow | историческая/default ветка репозитория | запрещён для deploy NEUROMIX |

Главный маршрут изменения:

```text
feature branch
    -> pull request в dev
    -> strict development CI
    -> merge в dev
    -> automatic DEV backend/frontend deploy
    -> ручной Telegram smoke на DEV-боте
    -> pull request dev -> tanyapi
    -> production CI
    -> merge в tanyapi
    -> automatic production backend/frontend deploy
```

Нельзя отправлять обычные функциональные изменения сразу в `tanyapi`, минуя DEV-бота. Исключение — подтверждённый аварийный hotfix, который после production должен быть немедленно синхронизирован обратно в `dev`.

## 2. Что должно быть отдельным

DEV — это не второй процесс с production-токеном. Обязательна изоляция:

- отдельный Telegram-бот, созданный через `@BotFather`;
- отдельный `BOT_TOKEN`;
- отдельный public webhook URL;
- отдельный Mini App URL;
- отдельный backend checkout;
- отдельный Docker Compose project;
- отдельное имя контейнера;
- отдельный runtime port;
- отдельная база данных;
- отдельный Redis prefix, а лучше отдельный Redis DB;
- отдельное media/upload пространство;
- отдельные payment webhook URL и sandbox/test credentials;
- отдельные GitHub Actions environment secrets.

Production продолжает использовать ветку `tanyapi` и свои текущие production credentials.

## 3. Telegram DEV-бот

Создать отдельного бота через `@BotFather` и сохранить его токен только в DEV `.env` и GitHub environment `development`, если token требуется workflow.

Рекомендуемые различия во внешнем виде:

- имя содержит `DEV`;
- username отличается от production;
- описание явно говорит, что бот тестовый;
- DEV Mini App использует отдельный HTTPS URL;
- тестовый бот не добавляется в production-каналы и не используется клиентами.

Токен production-бота нельзя копировать в DEV `.env`. Backend проверяет Telegram Mini App `initData` через bot token, поэтому DEV Mini App должна открываться DEV-ботом и проверяться DEV-токеном.

## 4. GitHub environments

В репозитории создать два GitHub Actions environment:

```text
development
production
```

Environment `development` разрешить только ветке `dev`.

Environment `production` разрешить только ветке `tanyapi`.

Production может оставаться полностью автоматическим после merge в `tanyapi`. Environment нужен прежде всего для изоляции secrets и истории deployments. При необходимости позже можно включить required reviewer.

### Development secrets

Добавить в environment `development`:

| Secret | Назначение |
| --- | --- |
| `DEV_SSH_HOST` | SSH host DEV backend |
| `DEV_SSH_USER` | SSH user, обычно `root` или отдельный deploy user |
| `DEV_SSH_PORT` | SSH port, необязательно при `22` |
| `DEV_SSH_PRIVATE_KEY` | отдельный ключ GitHub Actions для DEV backend |
| `DEV_SSH_KNOWN_HOSTS` | закреплённый host key DEV backend |
| `DEV_FRONTEND_SSH_HOST` | SSH host DEV frontend |
| `DEV_FRONTEND_SSH_USER` | SSH user DEV frontend |
| `DEV_FRONTEND_SSH_PORT` | SSH port DEV frontend |
| `DEV_FRONTEND_SSH_PRIVATE_KEY` | отдельный deploy key DEV frontend |
| `DEV_FRONTEND_SSH_KNOWN_HOSTS` | закреплённый host key DEV frontend |

Если backend и frontend находятся на одном сервере, SSH secrets могут содержать одинаковые значения, но хранить их всё равно следует в environment `development`.

### Development variables

Добавить в environment `development`:

| Variable | Пример назначения |
| --- | --- |
| `DEV_PROJECT_PATH` | отдельный checkout backend, например `/root/tanya/banano_kling-dev` |
| `DEV_COMPOSE_PROJECT_NAME` | `banano-kling-dev` |
| `DEV_CONTAINER_NAME` | `banano-kling-dev-bot` |
| `DEV_SYSTEMD_SERVICE` | optional legacy fallback service, например `banano-kling-dev` |
| `DEV_API_BASE_URL` | HTTPS origin DEV backend |
| `DEV_FRONTEND_DOMAIN` | domain без `https://`, на котором размещена DEV Mini App |
| `DEV_FRONTEND_PROJECT_PATH` | отдельный checkout frontend source |
| `DEV_FRONTEND_PROFILE` | optional полный путь к frontend profile |

Реальные домены, IP и пути не коммитить вместо environment values.

## 5. Подготовка DEV backend checkout

На DEV backend host:

```bash
install -d -m 0755 /root/tanya
git clone https://github.com/Bambale0/banano_kling.git /root/tanya/banano_kling-dev
cd /root/tanya/banano_kling-dev
git switch dev
git pull --ff-only origin dev
```

Если репозиторий private, настроить отдельный read-only deploy key. Не копировать production checkout и его `.env` целиком.

Создать DEV `.env` с правами `600`.

Минимальная логика значений:

```dotenv
BOT_TOKEN=DEV_BOT_TOKEN_FROM_BOTFATHER

WEBHOOK_HOST=https://DEV_BACKEND_DOMAIN
WEBHOOK_PATH=/webhook
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=UNIQUE_DEV_PORT

MINI_APP_PATH=/mini-app
MINI_APP_URL=https://DEV_FRONTEND_DOMAIN/mini-app/
STATIC_BASE_URL=https://DEV_MEDIA_ORIGIN

DATABASE_URL=SEPARATE_DEV_DATABASE
REDIS_URL=redis://127.0.0.1:6379/SEPARATE_DB_INDEX
REDIS_PREFIX=neuromix-dev

ADMIN_IDS=TESTER_TELEGRAM_IDS
```

Дополнительно:

- provider keys использовать отдельные или ограниченные по бюджету;
- production payment credentials не включать;
- использовать sandbox/test credentials, если provider их поддерживает;
- отключить реальные рассылки;
- required channel subscription направить на DEV-канал либо отключить;
- убедиться, что DEV webhook providers не меняют production transactions/tasks.

## 6. Docker isolation

`compose.backend.yml` поддерживает переменные:

```text
COMPOSE_PROJECT_NAME
CONTAINER_NAME
BANANO_IMAGE
```

Development deploy задаёт отдельные значения. Production defaults остаются:

```text
COMPOSE_PROJECT_NAME=banano-kling
CONTAINER_NAME=banano-kling-bot
```

DEV defaults:

```text
COMPOSE_PROJECT_NAME=banano-kling-dev
CONTAINER_NAME=banano-kling-dev-bot
```

Отдельный checkout обеспечивает отдельные каталоги:

```text
data/
static/uploads/
logs/
backups/
outputs/
```

Нельзя запускать DEV и production из одного project directory.

## 7. DEV backend autodeploy

Workflow:

```text
.github/workflows/deploy-development.yml
```

Trigger:

```text
push в dev
```

Порядок:

1. ждёт matching run `CI — Tanya development` для точного SHA;
2. требует conclusion `success`;
3. получает только secrets environment `development`;
4. подключается по SSH с pinned host key;
5. проверяет чистый checkout;
6. выполняет `fetch/switch/reset` до точного SHA ветки `dev`;
7. запускает Docker deploy с отдельными Compose/container names;
8. проверяет container health;
9. проверяет OCI revision label на точное совпадение SHA.

При незаполненных environment values deploy падает явно и не пытается использовать production secrets.

## 8. DEV frontend profile

На frontend host создать отдельный profile, например:

```text
/etc/banano-miniapp/profiles/DEV_FRONTEND_DOMAIN.env
```

Основа:

```dotenv
FRONTEND_DOMAIN=DEV_FRONTEND_DOMAIN
BACKEND_ORIGIN=https://DEV_BACKEND_DOMAIN
CERTBOT_EMAIL=ADMIN_EMAIL

REPO_URL=https://github.com/Bambale0/banano_kling.git
REPO_BRANCH=dev
SOURCE_DIR=/opt/banano-kling-dev-src
RUN_NPM_AUDIT=1
FORCE_RESET_SOURCE=0
NODE_MAJOR=24

WEB_ROOT=/var/www/DEV_FRONTEND_DOMAIN
MINIAPP_ROOT=/var/www/DEV_FRONTEND_DOMAIN/mini-app
BACKUP_ROOT=/var/backups/banano-miniapp/DEV_FRONTEND_DOMAIN
KEEP_BACKUPS=7

BACKEND_HOST_HEADER=DEV_BACKEND_DOMAIN
BACKEND_TLS_NAME=DEV_BACKEND_DOMAIN
BACKEND_HEALTH_PATH=/health
CLIENT_MAX_BODY_SIZE=60M
PROXY_TIMEOUT_SECONDS=600
ENABLE_UFW=1
SKIP_TLS=0
SKIP_DNS_CHECK=0
```

`REPO_BRANCH` обязан быть `dev`. Production profile продолжает использовать `tanyapi`.

## 9. DEV frontend autodeploy

Workflow:

```text
.github/workflows/deploy-frontend-development.yml
```

Он запускается на push в `dev`, когда изменены frontend или frontend deploy scripts.

Порядок:

1. ждёт строгий development CI;
2. локально выполняет frontend lint, tests и static build;
3. собирает frontend с `DEV_API_BASE_URL`;
4. подключается к DEV frontend host;
5. переключает отдельный checkout на точный SHA ветки `dev`;
6. выполняет deploy через отдельный DEV profile;
7. сравнивает tested и deployed `index.html`;
8. проверяет frontend health и HTTP 200 Mini App.

## 10. Проверка DEV после deploy

После каждого значимого изменения полностью закрыть DEV Mini App и открыть её через DEV-бота заново.

Минимальный smoke:

- DEV-бот отвечает на `/start`;
- webhook принадлежит DEV-боту;
- Mini App открывается с DEV URL;
- Telegram `initData` проходит bootstrap;
- отображается DEV-пользователь и DEV-баланс;
- production-баланс и история отсутствуют;
- загрузка JPG/PNG/WEBP/HEIC работает;
- создаётся тестовая image task;
- создаётся test video task, если provider включён;
- pending меняется на completed/failed;
- refund при failed не дублируется;
- профиль, feed, comments и remix работают в DEV data scope;
- test payment не начисляет production-пользователю;
- media URL ведёт в DEV storage;
- production-бот продолжает работать без изменений.

## 11. Выпуск DEV в production

После успешного smoke:

1. убедиться, что `dev` CI и deploy зелёные;
2. убедиться, что tested SHA совпадает с head ветки `dev`;
3. создать pull request `dev -> tanyapi`;
4. не добавлять новые функциональные изменения в release PR;
5. дождаться production CI;
6. выполнить merge в `tanyapi`;
7. дождаться backend и frontend production autodeploy;
8. выполнить короткий production smoke;
9. не переносить DEV `.env`, DEV database или DEV media в production.

Production source of truth:

```text
tanyapi
```

`main` не участвует в выпуске и не должен быть target для release PR.

## 12. Hotfix

Если production требует срочного исправления:

```text
hotfix branch from tanyapi
    -> PR в tanyapi
    -> production deploy
    -> PR/sync tanyapi -> dev
```

Нельзя оставить hotfix только в `tanyapi`, иначе следующий release `dev -> tanyapi` может вернуть старое поведение или создать конфликт.

## 13. Rollback DEV

DEV rollback не должен затрагивать production.

Варианты:

- revert проблемного commit в `dev`;
- повторный deploy последнего подтверждённого DEV SHA;
- остановка только DEV container;
- восстановление только DEV database backup;
- rollback только DEV frontend root/profile.

Никогда не использовать production container name, production checkout или production database в DEV rollback-командах.

## 14. Definition of done для DEV-контура

DEV-контур считается готовым, когда:

- создан отдельный Telegram-бот;
- создан отдельный HTTPS backend URL;
- создан отдельный HTTPS Mini App URL;
- DEV `.env` содержит отдельный token и data stores;
- GitHub environment `development` заполнен;
- branch `dev` ограничена development deploy;
- push в `dev` проходит strict CI;
- backend exact SHA автоматически появляется на DEV-боте;
- frontend exact SHA автоматически появляется в DEV Mini App;
- production workflow по-прежнему реагирует только на `tanyapi`;
- release PR создаётся только `dev -> tanyapi`.
