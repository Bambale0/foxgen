# Copilot Instructions

This project follows the agent-based development workflow defined in `.agents/README.md`.

## Quick Rules

1. Read `AGENTS.md` for global repository instructions.
2. Read `.github/instructions/` for language-specific guidelines.
3. Before any change, inspect existing code, docs, and tests in the affected area.
4. Do not invent APIs, env vars, or DB columns — verify against existing code.
5. Keep changes minimal and isolated to the task.
6. Never commit secrets, tokens, or .env files.
7. Output: summary, files changed, tests run, risks.

## Language-Specific Instructions

- **Python backend**: `.github/instructions/python-backend.instructions.md`
- **Frontend**: `.github/instructions/frontend.instructions.md`
- **Tests**: `.github/instructions/tests.instructions.md`