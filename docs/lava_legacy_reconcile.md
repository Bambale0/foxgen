# Восстановление старых платежей Lava

Скрипт `scripts/reconcile_lava_legacy_payments.py` исправляет старые транзакции,
в которых локальный `payment_id` содержит `invoice_id`, тогда как webhook Lava
присылает `contractId`.

Перед режимом `--apply` сделайте резервную копию production-базы. Скрипт
использует compare-and-set обновления, а начисление выполняет через
`complete_payment_atomic`.

## Проверить тесты

```bash
pytest tests/test_lava_legacy_reconcile.py -q
```

## Безопасный просмотр

```bash
python scripts/reconcile_lava_legacy_payments.py --limit 500
```

Команда обращается к Lava API и печатает JSON-строки, но не меняет базу.

## Исправить только идентификаторы

```bash
python scripts/reconcile_lava_legacy_payments.py --apply --limit 500
```

Для найденных транзакций `payment_id` заменяется на `contractId`. После этого
повторно отправленный webhook сможет найти транзакцию.

## Исправить и начислить уже оплаченные платежи

```bash
python scripts/reconcile_lava_legacy_payments.py \
  --apply \
  --complete-paid \
  --limit 500
```

Начисление выполняется через `complete_payment_atomic`, поэтому повторный запуск
не начисляет баланс дважды. Локальная транзакция со статусом `failed`
возвращается в `pending` только когда Lava API подтверждает статус оплаты.

## Проверка одной транзакции

```bash
python scripts/reconcile_lava_legacy_payments.py \
  --order-id '123456_1720000000000_start'
```

После проверки этой записи:

```bash
python scripts/reconcile_lava_legacy_payments.py \
  --order-id '123456_1720000000000_start' \
  --apply \
  --complete-paid
```

## Фильтрация локальных статусов

По умолчанию сканируются `pending` и `failed`. Статусы можно задать явно:

```bash
python scripts/reconcile_lava_legacy_payments.py \
  --status pending \
  --status failed \
  --limit 1000
```

Для запуска требуется рабочая переменная окружения `LAVA_API_KEY` и доступ к
той же базе данных, которую использует production-бот.
