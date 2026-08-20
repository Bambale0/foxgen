from pathlib import Path

from scripts.canonicalize_happyfox_runtime import canonicalize


def test_runtime_canonicalizer_uses_happyfox_public_origin(tmp_path: Path) -> None:
    runtime = tmp_path / ".env.happyfox.runtime"
    runtime.write_text(
        "WEBHOOK_HOST='https://alena.chillcreative.ru'\n"
        "MINI_APP_URL='https://old.example/mini-app/'\n"
        "PRODUCT_ID='happyfox'\n",
        encoding="utf-8",
    )

    result = canonicalize(runtime)
    content = runtime.read_text(encoding="utf-8")

    assert result == "https://alena.chillcreative.ru/mini-app/"
    assert "MINI_APP_URL='https://alena.chillcreative.ru/mini-app/'" in content
    assert "old.example" not in content


def test_production_image_bundles_happyfox_static_export() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:22-alpine AS miniapp-builder" in dockerfile
    assert "NEXT_PUBLIC_PRODUCT_ID=happyfox" in dockerfile
    assert "COPY --from=miniapp-builder" in dockerfile
    assert "/app/frontend/miniapp-v0/out" in dockerfile
    assert "revision.txt" in dockerfile


def test_production_miniapp_wrapper_verifies_bundled_release() -> None:
    wrapper = Path("scripts/deploy_happyfox_miniapp.sh").read_text(encoding="utf-8")
    assert "deploy_miniapp_local.sh" not in wrapper
    assert "revision.txt?revision=" in wrapper
    assert "bundled release verified" in wrapper


def test_happyfox_login_gate_uses_active_brand() -> None:
    gate = Path("frontend/miniapp-v0/components/telegram-open-gate.tsx").read_text(
        encoding="utf-8"
    )
    assert "Открыть {BRAND_NAME} в Telegram" in gate
    assert "Открыть NEUROMIX" not in gate
