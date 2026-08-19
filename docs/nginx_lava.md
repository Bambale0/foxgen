# Настройка nginx для приёма вебхуков LAVA на домене tanyapi.chillcreative.ru

Файлы, созданные в репозитории:
- [nginx/lava.conf](nginx/lava.conf)

Шаги для развёртывания на сервере:

1. Скопируйте конфиг в `/etc/nginx/sites-available/` и создайте симлинк в `/etc/nginx/sites-enabled/`:

```bash
sudo cp nginx/lava.conf /etc/nginx/sites-available/lava.conf
sudo ln -s /etc/nginx/sites-available/lava.conf /etc/nginx/sites-enabled/lava.conf
```

2. Получите TLS-сертификат (рекомендую certbot):

```bash
# Установите certbot и плагин для nginx, затем выполните
sudo certbot --nginx -d tanyapi.chillcreative.ru
```

3. Проверка и перезагрузка nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

4. Убедитесь, что ваш backend слушает на `127.0.0.1:8443` (или поправьте upstream в nginx/lava.conf).

5. Проверьте доступность webhook вручную:

```bash
curl -v -X POST https://tanyapi.chillcreative.ru/lava/webhook -d '{"test":"ok"}' -H 'Content-Type: application/json'
```

6. Проверьте логи nginx и бекенда при отладке:

```bash
sudo journalctl -u nginx -f
# и логи вашего приложения (в зависимости от настроек)
```

Дополнительные рекомендации:
- Если сайт находится за Cloudflare, добавьте его диапазоны IP в `/etc/nginx/cloudflare.conf` и раскомментируйте include.
- Если LAVA присылает большие payloads, можно увеличить `client_max_body_size` в конфиге.
- Если backend слушает на другом порту/хосте — измените `upstream lava_backend` в `nginx/lava.conf`.
