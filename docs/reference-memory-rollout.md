# Reference memory rollout

Recommended production rollout order:

1. deploy code with task submission still in its existing state;
2. run Alembic upgrade to `20260815_0009`;
3. verify `reference_assets` with `scripts/check_schema.py`;
4. verify the private S3 bucket permits API writes/reads and worker deletes under `references/`;
5. smoke-save one reference, reopen the library, reuse it in a non-billable validation path if available, then delete it and confirm the deletion outbox completes;
6. verify the existing short `inputs/` lifecycle rule does not match `references/`;
7. only then treat reference memory as production-ready for normal generation traffic.

Rollback of application code must not drop the table or delete `references/` objects. Database downgrade is intended for controlled migration verification before production data exists, not as a routine production rollback mechanism.
