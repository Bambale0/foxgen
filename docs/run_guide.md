# Локальный запуск и проверка NEUROMIX

## 1. Назначение

Документ описывает безопасный local/dev workflow для ветки `tanyapi` без использования production secrets и production data.

Pytest изолирован от production `.env`: `tests/conftest.py` должен блокировать загрузку project env и очищать application settings до импорта config. Тесты не должны обращаться к production providers, Redis, database или webhook endpoints без явного live-test режима.

## 2. Требования

- Python версии, совместимой с проектом;
- `venv`;
- pip;
- Node.js 22 или версия, ожидаемая frontend installer;
- npm;
- Git;
- локальная SQLite либо отдельная dev PostgreSQL;
- отдельный dev Redis при проверке FSM persistence;
- отдельный Telegram bot token для полноценного webhook/manual smoke.

## 3. Checkout

```bash
git clone https://github.com/Bambale0/banano_kling.git
cd banano_kling

git fetch origin tanyapi
git switch tanyapi
git status --short
```

Не вести разработку production-задачи из `main`, если целевой runtime — `tanyapi`.

## 4. Backend environment

```bash
python -m venv venv
. venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Создать dev `.env` с отдельными значениями. Минимальный пример:

```dotenv
BOT_TOKEN=DEV_BOT_TOKEN
WEBHOOK_HOST=http://127.0.0.1:8443
WEBHOOK_PATH=/webhook
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=8443
MINI_APP_PATH=/mini-app
MINI_APP_URL=http://localhost:3000/mini-app/
STATIC_BASE_URL=http://127.0.0.1:8443
DATABASE_URL=sqlite:///dev-bot.db
REDIS_URL=redis://127.0.0.1:6379/15
REDIS_PREFIX=neuromix_dev
```

Не копировать production `.env` целиком.

## 5. Syntax и import gate

```bash
. venv/bin/activate
python -m py_compile $(find bot tests scripts -name '*.py')
```

Для точечной проверки:

```bash
python -m py_compile bot/main.py bot/miniapp.py bot/config.py
```

## 6. Tests

Полный suite:

```bash
python -m pytest
```

Verbose:

```bash
python -m pytest -vv
```

Точечный файл:

```bash
python -m pytest tests/test_browser_auth.py -vv
```

Live/provider tests запускать только при явном понимании стоимости, побочных эффектов и используемых credentials.

## 7. Backend local run

```bash
. venv/bin/activate
python -m bot.main
```

Health:

```bash
curl -fsS http://127.0.0.1:${WEBHOOK_PORT:-8443}/health
```

Если установлен `HEALTH_CHECK_SECRET`, использовать отдельный dev secret и соответствующий Authorization header.

## 8. Redis

Проверка:

```bash
redis-cli -u redis://127.0.0.1:6379/15 ping
```

Ожидается:

```text
PONG
```

Использовать отдельный DB index/prefix, чтобы dev не затронул production keys.

## 9. Database

### SQLite dev

```dotenv
DATABASE_URL=sqlite:///dev-bot.db
```

Не использовать production `bot.db` для тестовых миграций.

### PostgreSQL dev

Создать отдельную database/user. Перед migration/read-write tests сделать dump. Использовать `docs/postgres-migration.md` и project verification scripts.

## 10. Frontend install

```bash
cd frontend/miniapp-v0
npm ci
```

Если lockfile изменён осознанно:

```bash
npm install
```

После изменения dependencies обязательно проверить diff `package-lock.json`.

## 11. Frontend development

```bash
cd frontend/miniapp-v0
npm run dev
```

Dev server не воспроизводит полностью production static export/basePath/cache behavior.

Для Telegram WebView может потребоваться HTTPS tunnel и настройка dev bot Mini App URL. Не использовать production bot для экспериментального tunnel без необходимости.

## 12. Frontend quality gate

```bash
cd frontend/miniapp-v0
npm run lint
npm test
npm run build
test -f out/index.html
```

Build использует static export с `/mini-app` base path.

## 13. Проверка бренда

```bash
grep -RniE 'Banano AI Studio|Banana Studio|Banano Studio|Banano Kling' \
  frontend/miniapp-v0/app \
  frontend/miniapp-v0/components \
  frontend/miniapp-v0/lib \
  || true
```

Не считать model names `Nano Banana` нарушением бренда.

## 14. Локальная проверка static export

Можно временно обслужить `out` простым static server:

```bash
cd frontend/miniapp-v0/out
python -m http.server 8080
```

При этом base path `/mini-app` может требовать соответствующей структуры/маршрутизации. Более точная проверка — project frontend installer в isolated environment.

## 15. API contract testing

Без Telegram initData bootstrap должен возвращать auth error:

```bash
curl -i -X POST \
  http://127.0.0.1:${WEBHOOK_PORT:-8443}/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Ожидаем `400/401/403`, а не `500`.

Для authenticated tests использовать test fixtures или dev bot initData. Не хранить реальный initData в репозитории.

## 16. Telegram manual smoke

На dev bot:

- `/start`;
- главное меню;
- переход в photo flow;
- переход в video flow;
- reference upload;
- balance display;
- Mini App open;
- loader -> live state;
- history;
- test task;
- publication flow.

Не запускать платную provider generation без явного намерения.

## 17. Media local behavior

Backend development может отдавать uploads самостоятельно. Production media topology с Cloudflare/Nginx не обязана воспроизводиться локально.

При изменении URL builder проверить:

- `STATIC_BASE_URL` пустой;
- `STATIC_BASE_URL` с localhost;
- production-like `https://media.example.test`;
- отсутствие двойного `/uploads/uploads`;
- корректное URL encoding.

## 18. Browser auth tests

Проверить:

- config route возвращает bot username;
- валидная Telegram Login signature принимается;
- просроченный auth date отклоняется;
- неверный hash отклоняется;
- frontend loader не заменяется gate до завершения initial check;
- error state не раскрывает секреты.

## 19. Before commit checklist

```bash
git status --short
git diff --check
python -m pytest
python -m py_compile $(find bot tests scripts -name '*.py')

cd frontend/miniapp-v0
npm run lint
npm test
npm run build
```

Документация должна быть обновлена, если меняются:

- env variables;
- production topology;
- deploy commands;
- API route/payload;
- branding;
- loader/auth behavior;
- media/cache policy.

## 20. Что нельзя делать в local/dev

- использовать production database для tests;
- запускать destructive migration без backup;
- использовать production Cloudflare token;
- коммитить `.env`;
- публиковать BOT_TOKEN;
- открывать dev server без auth в интернет;
- считать dev `next dev` доказательством working static export;
- заменять backend contract mock-данными вместо исправления несовместимости.

## 21. Production references

- Production URL: `https://cdn.chillcreative.ru/mini-app/`;
- Backend: `https://tanyapi.chillcreative.ru`;
- Media: `https://media.chillcreative.ru`.

Production deploy выполнять только по:

- [production-deployment.md](production-deployment.md);
- [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md);
- [runbook.md](runbook.md).
