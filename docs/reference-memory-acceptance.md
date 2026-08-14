# Reference memory acceptance checklist

A release containing reference memory is complete only when all checks below pass.

- Save one Telegram photo from `📚 Память реф`; reopen `/menu`, start a new generation and verify the photo is still present.
- Save the same bytes twice; verify only one active library item is counted and no second durable S3 object is required.
- Select multiple saved images for Nano Banana and Seedream; verify the selection count obeys each model's current capability.
- Use saved images as first frame and as ordered first+last frames for supported video flows.
- Mix temporary image/video/audio inputs with saved image references in a multimodal video flow; verify total and per-kind limits still apply.
- Delete a saved reference; verify it disappears from the library immediately, the worker removes the S3 object, and a stale Redis draft containing its UUID fails closed during final resolve.
- Fill the configured item quota and byte quota; verify a concurrent extra save is rejected without creating an active row or billable generation.
- Confirm `/start` and `/menu` delete current temporary inputs but never delete durable `references/` objects.
- Confirm every preview/provider URL is time-limited and the bucket remains private.
- Run Alembic upgrade, downgrade and re-upgrade plus `scripts/check_schema.py`.
- Run Ruff, changed-file formatting, strict mypy, unit/contract tests, real PostgreSQL/Redis lifecycle tests, secret scan, Trivy and production image smoke.
