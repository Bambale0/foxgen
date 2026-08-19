# Roadmap NEUROMIX

Актуальность: `2026-08-01`, ветка `tanyapi`.

Roadmap фиксирует ближайшие направления стабилизации. Это не список обещанных дат и не замена issue tracker.

## 1. Текущее состояние

### Product

Реализованы:

- Telegram bot с webhook runtime;
- Telegram Mini App;
- image/video/motion generation;
- работа с референсами;
- prompt-by-photo и video analysis flows;
- feed, trends, profiles, remix/repeat/share;
- balance, packages, promo codes, referrals и partner mechanics;
- browser auth fallback;
- task history и синхронизация результатов.

### Frontend

- Next.js static export;
- production frontend на `cdn.chillcreative.ru`;
- remote deployment через `cdn.sh` и профиль `tanyafrontend`;
- отдельный initial loader;
- Telegram auth gate после завершённой проверки;
- единый пользовательский бренд NEUROMIX;
- cache-overlap strategy для Telegram WebView.

### Backend

- production API на `tanyapi.chillcreative.ru`;
- `banano-kling.service`;
- Mini App API и provider/payment webhooks;
- local health;
- database compatibility layer;
- Redis FSM/cache с fallback;
- internal APIs и operational loops.

### Media

- существующее storage `static/uploads`;
- direct Nginx delivery;
- bind mount в `/var/www/media.chillcreative.ru/uploads`;
- `media.chillcreative.ru` через Cloudflare Free;
- Cache Rule только для публичной ленты;
- WebP previews;
- IPv4/IPv6/HTTP2/HTTP3/cache diagnostics.

### Documentation

Создан единый production documentation set:

- architecture;
- full deployment;
- frontend deployment;
- media runbook;
- environment reference;
- operations runbook;
- troubleshooting;
- branding;
- local development guide.

## 2. Приоритет P0: подтвердить инфраструктуру на production

- выполнить полный media deploy script на backend host;
- подтвердить certificate renewal;
- проверить Cloudflare Cache Rule на реальном feed file;
- проверить `CF-Cache-Status` и `Age`;
- проверить поведение через проблемные VPN;
- завершить successful remote frontend deploy на актуальном commit;
- выполнить Telegram smoke Android/iOS/Desktop;
- подтвердить, что loader не сменяется ложным auth gate;
- подтвердить все user-facing заголовки NEUROMIX.

## 3. Приоритет P1: frontend deploy reliability

### Dependency install

- добавить timeout/heartbeat вокруг `npm ci`;
- сохранять verbose npm log как release artifact/log;
- различать network stall, install scripts и OOM;
- не считать deprecated warnings failure;
- предусмотреть reuse безопасного npm cache;
- документировать supported Node/npm versions автоматически.

### Release process

- один release ID/commit в logs и health;
- atomic switch текущего frontend release;
- гарантированное хранение минимум двух наборов hashed chunks;
- отдельная безопасная rotation old assets;
- автоматический rollback при failed smoke;
- remote deploy lock от параллельных запусков.

## 4. Приоритет P1: media reliability

- проверить, что public filenames immutable;
- исключить годовой cache для приватных refs;
- добавить storage capacity alerts;
- добавить cleanup policy для временных media;
- контролировать thumbnail generation failures;
- добавить метрики original/preview size ratio;
- добавить мониторинг Cloudflare cache hit ratio;
- определить условия повторного включения HTTP/3 после VPN-теста.

## 5. Приоритет P1: observability

- machine-readable health с version/commit;
- frontend health с deployed commit и build timestamp;
- structured backend logs;
- correlation ID для frontend proxy -> backend -> provider;
- отдельные counters для auth errors, provider errors и proxy failures;
- alert на рост `NRestarts` systemd service;
- alert на disk usage uploads;
- payment reconcile lag;
- orphan webhook/task counters.

## 6. Приоритет P1: auth и Mini App startup

- regression tests loader/gate/live state;
- browser auth expiry/replay tests;
- Telegram `initData` timeout telemetry;
- понятная retry-кнопка при transient bootstrap failure;
- отличать invalid auth от backend unavailable;
- не раскрывать signature details в UI;
- проверить clock skew handling.

## 7. Приоритет P2: backend structure

- постепенно уменьшать `bot/main.py` и `bot/miniapp.py`;
- выделить route registration modules;
- выделить publication/media/auth services;
- унифицировать Telegram и Mini App generation orchestration;
- сохранить compatibility model IDs, callback IDs и deep links;
- покрывать extraction regression tests до refactor.

## 8. Приоритет P2: storage clarity

- окончательно закрепить primary production database path;
- синхронизировать schema, migration scripts и docs;
- проверить backup restore, а не только создание backup;
- документировать retention;
- исключить использование legacy DB dump как runtime source;
- добавить migration smoke в staging.

## 9. Приоритет P2: payments

- подтвердить фактически активные providers;
- отделить legacy modules от production configuration;
- idempotency tests для каждого active provider;
- reconciliation dashboard/summary;
- безопасный manual repair flow;
- audit trail ручных начислений;
- алерты на pending возрастом выше threshold.

## 10. Приоритет P2: branding cleanup

- user-facing audit bot + Mini App + payment pages;
- убрать старые Banana/Banano labels из пользовательского слоя;
- не менять model names Nano Banana;
- планировать technical identifier migration отдельно;
- добавить automated brand grep в CI;
- проверить icons/OpenGraph/Telegram menu metadata.

## 11. Приоритет P3: developer experience

- единая команда quality gate backend + frontend;
- pre-commit checks;
- documented staging environment;
- test fixtures для Mini App auth;
- локальный mock provider;
- dependency update policy;
- CI build static export;
- автоматическая проверка docs links и shell syntax.

## 12. Что не делать без отдельного migration plan

- не переименовывать массово callback IDs;
- не менять model IDs ради косметики;
- не переименовывать systemd/Redis/database identifiers без compatibility strategy;
- не удалять старые frontend chunks сразу после release;
- не перемещать `static/uploads` без data migration;
- не открывать backend port в интернет ради обхода Nginx;
- не применять Cache Everything ко всем uploads;
- не делать большой rewrite domain layer без regression coverage.

## 13. Definition of stable production

Система считается стабилизированной для текущего этапа, когда:

- backend health стабилен и restart count не растёт;
- frontend deploy воспроизводим и имеет rollback;
- media загружается в проблемных сетях;
- Cloudflare cache работает только для публичного контента;
- Telegram startup не показывает ложный gate;
- user-facing бренд везде NEUROMIX;
- generation/payment critical flows покрыты tests;
- backup restore проверен;
- оператор может диагностировать типовую проблему по документации без устных инструкций.

## 14. Правила обновления roadmap

Пересматривать документ при изменении:

- production topology;
- frontend deployment strategy;
- media storage/cache policy;
- active payment providers;
- database primary path;
- Mini App auth/startup model;
- пользовательского бренда;
- critical provider families;
- major operational incident.
