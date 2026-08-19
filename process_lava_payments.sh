chmod +x process_lava_payments.sh

echo "=== Запуск проверки Lava платежей ==="
echo "Время: $(date)"
echo ""

# Активируем виртуальное окружение если нужно
cd /root/tanya/banano_kling

# Запускаем Python скрипт проверки
python3 check_lava_payments.py

# Проверяем, есть ли обновления статусов
echo ""
echo "=== Проверка обновленных платежей ==="
echo "Список последних 5 обработанных транзакций:"

SQL="SELECT order_id, provider, status, amount_rub, credits, updated_at 
FROM transactions 
WHERE provider = 'lava' AND status IN ('completed', 'failed')
ORDER BY updated_at DESC LIMIT 5"

# Используем .env для подключения к PostgreSQL
source .env 2>/dev/null || true

# Выполняем SQL запрос через psql
if [ -n "$POSTGRES_USER" ] && [ -n "$POSTGRES_PASSWORD" ] && [ -n "$POSTGRES_DB" ] && [ -n "$POSTGRES_HOST" ]; then
    export PGPASSWORD="$POSTGRES_PASSWORD"
    psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$SQL"
elif [ -f "bot.db" ]; then
    # Используем SQLite как fallback
    sqlite3 bot.db "$SQL"
else
    echo "Не удалось подключиться к БД"
fi

echo ""
echo "=== Завершено ==="