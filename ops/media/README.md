# HappyFox media operations

HappyFox stores/delivers generated and uploaded media through the product's own isolated media/storage configuration.

## Rules

- do not use NEUROMIX/Tanya media paths/domains as HappyFox production defaults;
- `static/uploads` may remain a runtime storage root, but public exposure is controlled by the current deployment/Nginx configuration;
- `STATIC_BASE_URL` defines the public media base where application code needs an externally reachable URL;
- provider/Instagram publishing media must be reachable via public HTTPS;
- private/reference uploads must not receive blanket long-lived public caching;
- public immutable feed assets can use aggressive cache only when filenames/URLs are content-stable.

## Current product boundary

Production data/media belong to HappyFox. Never bind-mount or restore another product's upload directory into the HappyFox runtime as a shortcut.

Host-specific origin IP, mount path, Nginx site and CDN settings are deployment configuration and should not be hardcoded in this runbook.

## Delivery architecture

Typical pattern:

```text
HappyFox backend writes media
 -> persistent HappyFox upload/storage root
 -> Nginx/static origin
 -> optional CDN/proxy for public immutable content
 -> Telegram / Instagram / browser
```

Python should not proxy large static file bodies when Nginx/static delivery is available.

## Cache classes

### Public immutable results/feed previews

Can use long-lived cache when the URL never changes content.

### User references/private/temporary uploads

Use conservative/no-store policy unless the privacy model explicitly permits public caching.

Never apply `Cache Everything` to all `/uploads/*` without classifying data.

## Instagram requirements

Instagram DM result delivery can send external media URLs. Publishing container APIs also require Meta to fetch media via public HTTPS.

If generation returns inline bytes, the Instagram generation layer may persist a result under HappyFox uploads and construct a URL from the configured public host/base. Verify that URL is reachable from outside the private network.

## Diagnostics

Check:

```text
file exists in HappyFox storage
public URL resolves over HTTPS
correct Content-Type
range/static delivery when relevant
no redirect/auth loop for provider-fetched media
cache policy matches asset privacy
```

For a public media URL:

```bash
curl -sSI 'https://<happyfox-media-origin>/uploads/<path>'
```

Do not expose real signed/private URLs in issue reports.

## Capacity/cleanup

Monitor disk/object-storage usage and define retention for:

- temporary uploads;
- generated results;
- provider cache/downloads;
- public feed previews;
- Instagram inline-result fallbacks.

Cleanup must not delete media still referenced by generation history, active provider jobs or public posts.

## Canonical configuration

- `.env.happyfox.example`
- `docs/environment.md`
- `docs/production-deployment.md`
- current Nginx/deploy scripts if used by the production environment.

Historical Cloudflare/Tanya-specific instructions from the imported repository are not current HappyFox production instructions.
