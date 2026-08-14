# Reference memory internal API examples

These endpoints are backend-only. Replace placeholders with the trusted internal bearer and the authenticated Telegram user ID.

```bash
curl -H 'Authorization: Bearer <internal-token>' \
     -H 'X-FoxGen-User-Id: 42' \
     'http://api:8080/v1/reference-memory?offset=0&limit=20'
```

```bash
curl -X POST \
     -H 'Authorization: Bearer <internal-token>' \
     -H 'X-FoxGen-User-Id: 42' \
     -H 'Content-Type: application/json' \
     -d '{"reference_ids":["<uuid>"]}' \
     http://api:8080/v1/reference-memory/resolve
```

Do not expose the bearer token or this internal identity header to browser code.
