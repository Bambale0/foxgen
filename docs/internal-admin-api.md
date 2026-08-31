# HappyFox internal API

The old `/internal/admin/*` Tanya Admin contract documented here is not present in the current HappyFox runtime and must not be used as an operational API.

Current internal API is registered by `bot/internal_api.py` under:

```text
/internal/v1
```

Current read-only routes:

```text
GET /internal/v1/health
GET /internal/v1/stats
```

## Authentication

Internal routes use timestamped HMAC headers:

```text
X-Internal-Timestamp
X-Internal-Signature
```

The signature contract is implemented in `bot/internal_api.py`; callers must use the exact current implementation/client contract rather than copying historical examples from old admin docs.

Requests outside the allowed time skew or with invalid signature are rejected.

## Health

`/internal/v1/health` reports HappyFox backend status/version and checks database connectivity.

The service identity is:

```text
happyfox-backend
```

## Stats

`/internal/v1/stats` returns aggregated read-only HappyFox statistics from the current database layer.

## Security

- `INTERNAL_API_SECRET` stays outside Git;
- do not expose internal routes as a public unauthenticated admin API;
- do not share the HMAC secret with Meta/Instagram webhook configuration;
- Meta webhook HMAC and internal API HMAC are separate trust boundaries.

## Historical admin documents

Files named `internal-admin-*` were imported from an older external Tanya Admin design. Unless current runtime code explicitly implements an endpoint, treat those files as historical/reference-only.

Any future HappyFox admin control-plane work should be implemented in `foxgen` (or an explicitly named external admin repository) with a new tested contract and updated docs, not by assuming the old `/internal/admin/*` endpoints still exist.
