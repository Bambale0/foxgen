# HappyFox Mini App channel hosts

HappyFox keeps one shared Mini App codebase and backend, but Telegram and MAX must use separate public launch hosts.

## Canonical hosts

- Telegram Mini App: `https://app.happy-fox.online/mini-app/`
- MAX Mini App: `https://max.happy-fox.online/mini-app/`
- Shared backend/API/webhooks: `https://api.happy-fox.online`
- Public landing: `https://happy-fox.online/`

The split is intentionally at the browser-launch boundary only. Generation, billing, models, storage, provider routing, identity services, and the backend remain shared where the product architecture already defines a shared core.

## Why the hosts are split

Telegram and MAX inject different signed launch data and different JavaScript bridges:

- Telegram: `/mini-app/telegram-web-app.js` → `window.Telegram.WebApp`
- MAX: `https://st.max.ru/js/max-web-app.js` → `window.WebApp`

A channel-specific published variant must load only its own bridge. This prevents one messenger bridge from influencing the other messenger's launch detection or authentication path.

The repository still builds one generic static export. `scripts/render_happyfox_miniapp_channel.py` produces deployment variants:

- `shared` — both bridges; transition-only mode before the MAX subdomain is activated;
- `telegram` — Telegram SDK only;
- `max` — MAX Bridge only.

## Transition safety

The production split is server-activated. Until `/etc/foxgen-happyfox/max-miniapp.env` exists, `scripts/activate_happyfox_channel_miniapps.sh` keeps shared launch mode active and restores the shared MAX redirect if a previous split is being rolled back.

This is deliberate: merging the preparation must not break the currently registered MAX Mini App URL before DNS and TLS for `max.happy-fox.online` exist.

## One-time activation after DNS exists

1. Create an A/AAAA record for `max.happy-fox.online` pointing to the HappyFox production edge.
2. On the HappyFox host, run:

   ```bash
   CERTBOT_EMAIL=<operations-email> bash scripts/provision_happyfox_max_miniapp_host.sh
   ```

   The script refuses to continue until the domain resolves, creates the dedicated web root, obtains/uses the Let's Encrypt certificate, installs an isolated nginx vhost and writes `/etc/foxgen-happyfox/max-miniapp.env`.

3. Activate the exact deployed main SHA:

   ```bash
   bash scripts/activate_happyfox_channel_miniapps.sh "$(git rev-parse HEAD)"
   ```

4. In MAX for Partners, set the bot's Mini App URL to:

   `https://max.happy-fox.online/mini-app/`

5. Verify the native MAX launch button (`open_app`) and direct deep link:

   `https://max.ru/<botName>?startapp`

The canonical `Deploy HappyFox production` workflow runs the same reconciliation step after every verified deployment. Once the server activation config exists, future deploys return to the split state automatically; without the config, the same step keeps shared launch mode active.

## Release invariants

After activation:

- `app.happy-fox.online` HTML must contain `/mini-app/telegram-web-app.js` and must not contain `https://st.max.ru/js/max-web-app.js`.
- `max.happy-fox.online` HTML must contain `https://st.max.ru/js/max-web-app.js` and must not contain `/mini-app/telegram-web-app.js`.
- both hosts must publish the exact same verified repository revision;
- both `/mini-app/api/` paths proxy to the same HappyFox backend;
- invalid bootstrap requests must fail closed at the backend, not with nginx 404/405;
- `GET https://api.happy-fox.online/max/webhook` must redirect to the dedicated MAX Mini App URL after activation;
- Telegram inline `web_app=WebAppInfo(...)` launches continue to target `app.happy-fox.online`;
- MAX `open_app` buttons continue to target the registered MAX Mini App attached to the bot.

## Rollback

Do not delete DNS/certificates as a first rollback step. To return temporarily to the shared host:

1. remove or move `/etc/foxgen-happyfox/max-miniapp.env` out of the activation path;
2. set the MAX partner Mini App URL back to `https://app.happy-fox.online/mini-app/`;
3. run the canonical HappyFox production deployment for the verified main SHA.

The reconciliation step restores the shared MAX redirect and the canonical deploy restores the generic shared bundle to `app.happy-fox.online`. Keep the dedicated MAX vhost available until the rollback has been verified.
