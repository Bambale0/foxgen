# Zero-downtime migration runbook

> Этот документ относится к переносу всего backend runtime и данных. Текущая production-схема переносит только static frontend на отдельный host; для неё используйте [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md). Адрес и blocker ниже сохранены как контекст незавершённой backend-миграции и не являются адресом текущего frontend host.

Target host: `root@144.76.188.75 -p 22`

Target path: `/root/tanya/banano_kling`

Current blocker: from this host, `144.76.188.75` responds to ping but TCP/22 times out. Open SSH for source IP `89.125.51.145`, confirm the SSH port, or provide the correct endpoint before running the remote steps.

## What moves

- Project files, `.git`, `.env`, `.env.postgres`, scripts, docs, logs, backups.
- SQLite runtime DB: `bot.db`, `bot.db-wal`, `bot.db-shm`.
- User/provider media: `static/uploads/` (about 12 GB locally).
- Codex user config/auth/plugins/skills, excluding heavy local logs and sessions.

The local `venv/` is intentionally not copied. It is rebuilt on the new server from `requirements.txt`.

## First pass while old production is running

```bash
read -r -s SSHPASS
export SSHPASS
REMOTE_HOST=144.76.188.75 REMOTE_PORT=22 REMOTE_DIR=/root/tanya/banano_kling IDENTITY_FILE=/root/.ssh/banano_migration_ed25519 MODE=initial ./scripts/sync_to_new_server.sh
REMOTE_HOST=144.76.188.75 REMOTE_PORT=22 IDENTITY_FILE=/root/.ssh/banano_migration_ed25519 MODE=codex ./scripts/sync_to_new_server.sh
unset SSHPASS
```

Then provision the new host without starting the bot:

```bash
ssh -p 22 root@144.76.188.75 'cd /root/tanya/banano_kling && SERVER_NAME=_ ./scripts/bootstrap_new_server.sh'
```

This installs system packages, Redis, nginx, Python dependencies, systemd unit, and Codex config. The bot service is prepared but disabled by default.

## Verify staging

```bash
ssh -p 22 root@144.76.188.75 'nginx -t'
ssh -p 22 root@144.76.188.75 'systemctl status redis-server --no-pager'
ssh -p 22 root@144.76.188.75 'cd /root/tanya/banano_kling && venv/bin/python -m pytest tests/test_config.py tests/test_database.py'
ssh -p 22 root@144.76.188.75 'codex --version && codex mcp list'
```

Do not leave the new bot running before cutover.

## Final cutover

1. Lower DNS TTL ahead of time if DNS is still under your control.
2. Stop the old bot or otherwise pause writes.
3. Run final sync:

```bash
REMOTE_HOST=144.76.188.75 REMOTE_PORT=22 REMOTE_DIR=/root/tanya/banano_kling IDENTITY_FILE=/root/.ssh/banano_migration_ed25519 MODE=final ./scripts/sync_to_new_server.sh
```

4. On the new server, run a quick DB check:

```bash
ssh -p 22 root@144.76.188.75 'cd /root/tanya/banano_kling && sqlite3 bot.db "PRAGMA quick_check;"'
```

5. Start the new service:

```bash
ssh -p 22 root@144.76.188.75 'systemctl enable --now banano-kling && systemctl status banano-kling --no-pager'
```

6. Point DNS to the new IP. When the domain resolves to the new host, issue/move certificates and switch nginx to HTTPS.
7. Confirm:

```bash
curl -i http://144.76.188.75/health
ssh -p 22 root@144.76.188.75 'journalctl -u banano-kling -n 200 --no-pager'
```

## HTTPS after domain move

Until the domain and certificate are moved, nginx intentionally serves HTTP only and proxies to aiohttp. After DNS points to the new server:

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d tanyapi.chillcreative.ru
nginx -t && systemctl reload nginx
```

Then verify external webhook routes over HTTPS:

```bash
curl -i https://tanyapi.chillcreative.ru/health
```
