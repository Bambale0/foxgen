# Historical NEUROMIX runner note

This file is retained only to prevent old links from becoming ambiguous.

NEUROMIX runner/service instructions are **not** valid HappyFox production instructions.

For HappyFox use:

- `runbook.md` — current operations;
- `docker_backend.md` — current container identity;
- `production-deployment.md` — exact-SHA release/rollback;
- `development-deployment.md` — current branch/CI process.

Current production source is `Bambale0/foxgen:main`, with Compose project `foxgen-happyfox` and container `foxgen-happyfox-bot`.

Do not run commands targeting old `banano-kling.service`, Tanya paths or NEUROMIX databases from this repository.
