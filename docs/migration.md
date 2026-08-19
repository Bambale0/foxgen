# Migration and Repair Guide

Этот документ описывает не внешние provider migrations, а внутренние data/runtime scripts, которые лежат в `scripts/`.

## 1. Когда нужен этот файл

- перенос SQLite -> PostgreSQL
- проверка runtime DB backend
- backfill feed/referral data
- redelivery / repair после инцидента

## 2. Основные scripts

### DB / runtime

- `scripts/backup_db.sh`
- `scripts/check_postgres_runtime.py`
- `scripts/migrate_sqlite_to_postgres.py`
- `scripts/verify_postgres_migration.py`

### Feed / referral repair

- `scripts/persist_existing_feed.py`
- `scripts/restore_feed_from_kie.py`
- `scripts/backfill_feed_author_photos.py`
- `scripts/backfill_referral_events_from_logs.py`
- `scripts/repair_referral_cycles.py`
- `scripts/repair_referral_sync.py`

### Delivery / payment / watcher

- `scripts/redeliver_tasks.py`
- `scripts/poll_yookassa_pending.py`
- `scripts/watcher.py`

## 3. Правила запуска

- сначала читать код скрипта
- запускать только с понятным `DATABASE_URL`
- перед изменяющими операциями делать backup
- не выполнять repair scripts на проде без понимания rollback path

## 4. Практический порядок при DB migration

1. Сделать backup
2. Проверить текущий backend через `check_postgres_runtime.py`
3. Выполнить migration script
4. Выполнить verification script
5. Перезапустить runtime
6. Проверить `/health` и smoke flows

## 5. Что не документирует этот файл

- provider payload contracts
- Mini App frontend build
- production nginx/systemd specifics

Для этого смотри:

- [runbook.md](runbook.md)
- [postgres-migration.md](postgres-migration.md)
- [architecture.md](architecture.md)
