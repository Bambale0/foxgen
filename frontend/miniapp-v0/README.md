# NEUROMIX Mini App Frontend

`frontend/miniapp-v0` — production frontend Telegram Mini App NEUROMIX.

Frontend не является отдельным backend. Он собирается в статический export и использует API из `bot/miniapp.py`.

## 1. Production URL

```text
https://cdn.chillcreative.ru/mini-app/
```

Production build обслуживается Nginx на `91.200.84.187`. API запросы под `/mini-app/api/*` проксируются по HTTPS на `https://tanyapi.chillcreative.ru`.

## 2. Стек

- Next.js 16;
- React 19;
- TypeScript;
- Tailwind CSS 4;
- Framer Motion;
- Radix UI primitives;
- Jest + Testing Library;
- static export;
- no Node.js production runtime.

## 3. Основная структура

```text
frontend/miniapp-v0/
├── app/
│   ├── layout.tsx
│   ├── page.tsx
│   └── globals.css
├── components/
│   ├── mini-app-shell.tsx
│   ├── mini-app-loader.tsx
│   ├── telegram-open-gate.tsx
│   ├── hero-header.tsx
│   ├── tab-content.tsx
│   ├── tab-nav.tsx
│   └── tabs/
├── lib/
│   ├── api.ts
│   ├── app-context.tsx
│   ├── brand.ts
│   ├── types.ts
│   ├── start-params.ts
│   └── mock-data.ts
├── public/
├── scripts/
├── next.config.mjs
├── package.json
└── out/                       # generated static export
```

## 4. Branding

Пользовательский бренд:

```text
NEUROMIX
```

Единый источник:

```text
lib/brand.ts
```

Не хардкодить `Banano Studio`, `Banana Studio` и другие старые названия в компонентах.

Названия моделей `Nano Banana`, `Kling`, `Veo`, `Grok` и другие являются model/provider names и не переименовываются.

Подробности: `../../docs/branding.md`.

## 5. Runtime states

### Initial loading

`AppProvider` начинает с locked state и `isLoading=true`.

`MiniAppShell` должен сначала проверять loading state и показывать `MiniAppLoader`. Это предотвращает ложное появление Telegram gate, пока WebView ещё передаёт `initData`.

### Live mode

После успешного bootstrap:

- пользователь и баланс обновляются;
- модели берутся с backend;
- история задач обновляется;
- tabs становятся доступны;
- task detail синхронизируется с backend.

### Locked/browser mode

Если Telegram `initData` не получены после завершения проверки, отображается `TelegramOpenGate`. В обычном браузере он может использовать Telegram Login Widget.

## 6. Telegram integration

`app/layout.tsx` подключает Telegram Web App script и early-ready bridge.

При client mount shell вызывает:

- `Telegram.WebApp.ready()`;
- `Telegram.WebApp.expand()`.

Не удалять early-ready механизм без проверки Telegram Android, iOS и Desktop.

## 7. API contracts

Источник истины: `bot/miniapp.py`.

Основные routes:

```text
POST /mini-app/api/bootstrap
POST /mini-app/api/upload
POST /mini-app/api/generate-image
POST /mini-app/api/generate-video
POST /mini-app/api/generate-motion
POST /mini-app/api/task-detail
POST /mini-app/api/create-payment
POST /mini-app/api/ai-assistant
```

Также используются feed, prompt, profile, publication, browser-auth и public v1 routes.

Frontend не должен:

- придумывать user balance;
- подменять failed bootstrap mock-данными;
- показывать чужой task detail;
- считать provider URL вечным;
- считать `401` без Telegram auth backend outage.

## 8. Local development

```bash
cd frontend/miniapp-v0
npm ci
npm run dev
```

Dev mode Next.js не равен production static export. Перед merge обязательно проверить production build.

Для локального API потребуется корректная proxy/base configuration либо доступ к backend route. Не использовать production tokens в local frontend env.

## 9. Quality gate

```bash
cd frontend/miniapp-v0

npm ci
npm run lint
npm test
npm run build

test -f out/index.html
```

### Scripts

```text
npm run dev     -> next dev
npm run build   -> static export + Telegram head patch
npm run start   -> next start, не основной production mode
npm run lint    -> eslint
npm test        -> jest
```

## 10. Build configuration

`next.config.mjs` использует:

```text
NEXT_EXPORT=1
NEXT_PUBLIC_MINIAPP_BASE_PATH=/mini-app
```

При export:

- `output: export`;
- `basePath: /mini-app`;
- `assetPrefix: /mini-app`;
- `trailingSlash: true`;
- Next Image работает без image optimizer runtime.

Build output:

```text
out/
```

## 11. Static deployment

Рекомендуемая команда из backend/operator host:

```bash
cd /root/tanya/banano_kling
sudo bash cdn.sh --remote-deploy tanyafrontend
```

После завершения:

```bash
sudo bash cdn.sh --remote-status tanyafrontend
```

Подробности: `../../docs/miniapp-frontend-deployment.md`.

## 12. Cache compatibility

HTML должен иметь `no-store/no-cache`. Hashed chunks — immutable.

При обычном deploy не использовать удаление старых assets. Telegram WebView может продолжать использовать старый HTML после выкладки нового release.

Если старые chunks удалены, пользователь может получить white screen или бесконечный loader.

## 13. Media

Публичные сохранённые media должны использовать:

```text
https://media.chillcreative.ru/uploads/...
```

Feed grid должна предпочитать WebP thumbnail, если backend его предоставляет.

Frontend не должен загружать тяжёлый original для каждой карточки сетки без необходимости.

Временные provider URLs могут проходить через backend media gateway, если они ещё не сохранены локально.

## 14. Loader UX

`MiniAppLoader` должен:

- отображать NEUROMIX;
- быть полноэкранным;
- иметь доступный status;
- отображаться до конца auth/bootstrap;
- не показывать misleading error;
- не зависеть от загрузки тяжёлых tabs.

## 15. Dynamic tabs

Тяжёлые tabs загружаются через dynamic import. Для них обязателен skeleton fallback.

Главная Studio tab должна быть доступна без пустого промежутка между header и navigation.

## 16. Task synchronization

Frontend обновляет task state через bootstrap/task detail polling и focus/visibility sync согласно реализации `lib/app-context.tsx`.

При готовом backend result необходимо обновлять согласованно:

- `recentTasks`;
- `selectedTask`;
- `taskDetail`.

Иначе список и открытая карточка расходятся.

## 17. Deep links

`lib/start-params.ts` разбирает start params для:

- referral;
- profile;
- feed item;
- remix;
- prompt;
- task detail.

Любое изменение формата deep link должно быть согласовано с backend link builder и Telegram bot buttons.

## 18. Browser auth

Компонент `telegram-open-gate.tsx`:

- получает bot username из runtime config/API;
- создаёт Telegram Login Widget;
- отправляет Telegram auth payload backend;
- получает init data/session representation;
- перезагружает приложение.

Callback name может содержать legacy technical identifier. Это не пользовательский бренд и меняется только с проверкой backward compatibility.

## 19. Tests

Запуск:

```bash
npm test
```

При изменении auth/loading state добавить тесты минимум на:

- loader до bootstrap;
- gate после auth timeout;
- live state после bootstrap;
- browser auth error;
- brand presence;
- route/deep-link handling.

## 20. Диагностика production

### Title

```bash
curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

### Assets

```bash
curl -fsS https://cdn.chillcreative.ru/mini-app/ \
  | grep -oE '/mini-app/_next/static/[^" ]+\.(js|css)' \
  | sort -u
```

### API proxy

```bash
curl -i -X POST \
  https://cdn.chillcreative.ru/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Auth error ожидаем, proxy error — нет.

## 21. Definition of done для frontend change

- [ ] user-facing brand — NEUROMIX;
- [ ] lint проходит;
- [ ] tests проходят;
- [ ] production build создаёт `out/index.html`;
- [ ] current assets существуют;
- [ ] loading/auth states не конфликтуют;
- [ ] Telegram Android/iOS/Desktop smoke выполнен для критичных изменений;
- [ ] API payload соответствует backend;
- [ ] old chunks не удалены normal deploy;
- [ ] documentation обновлена.
