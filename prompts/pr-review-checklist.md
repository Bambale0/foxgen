# PR Review Checklist for AI-Agent Changes

## Correctness
- Does the diff actually satisfy the issue?
- Are edge cases handled?
- Are public contracts preserved or clearly documented?

## Tests
- Are new behaviors covered?
- Are failures and external API errors covered?
- Are tests deterministic?

## Security
- No secrets committed.
- Auth and permissions checked.
- Inputs validated.
- Webhooks/payments verified and idempotent.
- No unsafe command execution or untrusted setup scripts.

## Maintainability
- Small scope.
- Existing patterns preserved.
- Names are clear.
- No unnecessary framework/dependency additions.

## Release
- Migration required?
- Env vars/secrets required?
- Rollback clear?
- Monitoring/logging sufficient?
