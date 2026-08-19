---
applyTo: "**/*.py"
---

# Python Backend Instructions

- Use Python 3.11+ style unless the project specifies another version.
- Prefer `async` only where the framework and call chain are already async.
- Add type hints to public functions and complex internal functions.
- Use dataclasses or Pydantic models for structured payloads.
- Validate external API responses before using nested fields.
- Keep business logic out of route/handler functions when possible.
- Use explicit logging around integrations, background tasks, payments, webhooks, and retries.
- Tests should cover success path, validation failure, external API failure, and idempotency where relevant.
