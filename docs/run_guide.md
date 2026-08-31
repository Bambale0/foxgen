# HappyFox run guide

This short guide points to current operational sources.

## Development

```bash
python -m pip install -r requirements.txt
python scripts/apply_visible_copy_fixes.py
python scripts/apply_happyfox_product_copy.py
python -m compileall -q bot scripts
pytest tests/ --ignore=tests/live -m 'not live_smoke'
```

Mini App:

```bash
cd frontend/miniapp-v0
npm ci
npm run lint
npm run build
```

## Production

Do not run historical `banano-kling.service` or Tanya checkout commands for HappyFox.

Production release path is GitHub-driven:

```text
PR -> main -> CI -> merge -> main CI -> exact-SHA HappyFox deploy
```

Current runtime identity:

```text
foxgen-happyfox
foxgen-happyfox-bot
happyfox database
foxgen_happyfox Redis prefix
```

Use `runbook.md` for operations and `production-deployment.md` for release/rollback.

## Instagram

Instagram is part of the same backend runtime and is disabled unless:

```dotenv
INSTAGRAM_ENABLED=1
```

Use `instagram-channel.md` for Meta webhook setup, Photo/Video flow, RU/EN, YooKassa/Lava and live smoke.
