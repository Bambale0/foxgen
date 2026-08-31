# HappyFox PostgreSQL migration note

Production HappyFox uses PostgreSQL. SQLite remains useful only for isolated tests/local fixtures where supported.

Current operational rules:

- `DATABASE_URL` in production must point to the dedicated HappyFox PostgreSQL database;
- production preflight should reject SQLite;
- new channel tables (identity/link/promotion/language/Instagram jobs) must support PostgreSQL startup/migration paths;
- do not import or point HappyFox at a NEUROMIX/Tanya production database;
- before schema/data repair, take a compatible HappyFox backup and verify rollback strategy.

Canonical sources:

- `environment.md`
- `architecture.md`
- `production-deployment.md`
- runtime schema/database modules and tests.

For changes to Instagram schema, regression-test both the SQLite test path and PostgreSQL-specific DDL/connection behavior used by production.
