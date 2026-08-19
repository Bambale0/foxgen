# HappyFox production-core migration

FoxGen was re-based as a source snapshot from the proven production core:

- source repository: `Bambale0/banano_kling`
- source branch: `tanyapi`
- exact source SHA: `36f92a0504f849c0c591652a880410e33a1c89aa`
- imported into: `Bambale0/foxgen`
- migration date: 2026-08-20

The original FoxGen code before this migration is preserved at:
`legacy/foxgen-pre-tanyapi-20260820`.

GitHub workflows are intentionally not copied from NEUROMIX. FoxGen keeps
an isolated CI/deploy surface and receives HappyFox-specific workflows in
follow-up commits. Product-specific branding, credentials, domains,
database, Redis and media namespace are also layered separately.
