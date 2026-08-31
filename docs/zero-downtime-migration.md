# HappyFox migration/availability note

The old NEUROMIX/Tanya host-to-host zero-downtime procedure is not a current HappyFox production runbook.

For HappyFox, prefer the repository exact-SHA deployment workflow with isolated PostgreSQL/Redis and explicit health/revision smoke. Any infrastructure migration that changes hosts, domains, database or Redis requires its own reviewed migration plan based on the current runtime.

Rules:

- source remains `foxgen/main`;
- do not reuse NEUROMIX/Tanya database or Redis as a shortcut;
- snapshot/backup HappyFox data before migration;
- validate schema compatibility;
- keep Telegram/Instagram webhook DNS/TLS cutover explicit;
- Instagram can be temporarily disabled with `INSTAGRAM_ENABLED=0` during risky infrastructure cutover;
- verify Telegram Mini App and, if enabled, Instagram signed webhook/Direct flow after cutover.

Use `happyfox-production-cutover.md`, `production-deployment.md`, `environment.md` and a task-specific migration plan for current operations.
