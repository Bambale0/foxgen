from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "foxgen" / "miniapp_static"
INDEX = STATIC / "index.html"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_production_shell_declares_one_core_runtime_and_all_backend_modules() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in html
    for asset in (
        "boot-guard.js",
        "runtime-loader.js",
        "enhancement-loader.js",
        "parity-app.js",
        "complete-menu.js",
        "user-parity-hardening.js",
        "user-parity-phase2.js",
        "user-draft-recovery.js",
        "tts-parity.js",
        "suno-parity.js",
        "suno-extend.js",
        "suno-upload-cover.js",
        "suno-upload-extend.js",
        "motion-control.js",
        "promo-redeem.js",
        "backend-parity-ui.js",
    ):
        assert f"/mini-app/{asset}?v={MINIAPP_RELEASE}" in html

    for stylesheet in (
        "app.css",
        "studio.css",
        "parity.css",
        "complete-menu.css",
        "motion-control.css",
        "promo-redeem.css",
        "backend-parity.css",
    ):
        assert f"/mini-app/{stylesheet}?v={MINIAPP_RELEASE}" in html

    parity_src = f"/mini-app/parity-app.js?v={MINIAPP_RELEASE}"
    assert f'data-parity-src="{parity_src}"' in html
    assert "data-product-home-src" not in html
    assert "product-home.js" not in html
    assert "product-home.css" not in html
    assert "/mini-app/app.js" not in html
    assert "visibility: hidden" not in html
    assert 'data-foxgen-catalog="booting"' not in html
    assert not (STATIC / "product-home.js").exists()
    assert not (STATIC / "product-home.css").exists()


def test_production_boot_guard_fails_closed_without_stale_runtime_redirect() -> None:
    guard = (STATIC / "boot-guard.js").read_text(encoding="utf-8")

    assert "BOOT_TIMEOUT_MS = 15000" in guard
    assert "Happy Fox не запустился" in guard
    assert "data-boot-retry" in guard
    assert "unhandledrejection" in guard
    assert "__FOXGEN_BOOT_FAIL__" in guard
    assert "__FOXGEN_BOOT_FATAL__" in guard
    assert "legacy=1" not in guard
    assert "совместимый режим" not in guard
    assert "location.replace" not in guard
    assert ".replaceAll(" not in guard
    assert "?." not in guard
    assert "??" not in guard


def test_runtime_loader_requires_only_the_real_parity_core() -> None:
    loader = (STATIC / "runtime-loader.js").read_text(encoding="utf-8")

    assert "String.prototype.replaceAll" in loader
    assert "window.structuredClone" in loader
    assert "new Function" in loader
    assert "transpileLogicalAssignments" in loader
    assert "fetch(source, { cache: 'no-store' })" in loader
    assert "compiled.indexOf('??=')" in loader
    assert "compiled.indexOf('&&=')" in loader
    assert "data-parity-src" in loader
    assert "data-product-home-src" not in loader
    assert "mountPendingAccountSurface" not in loader
    assert "catalog-runtime-loaded" not in loader
    assert "data-legacy-src" not in loader
    assert "legacy=1" not in loader
    assert "__FOXGEN_RUNTIME_KIND__ = 'parity'" in loader
    assert "__FOXGEN_CORE_LOADED__" in loader
    assert "foxgen:core-loaded" in loader
    assert "__FOXGEN_BOOT_FATAL__" in loader


def test_enhancements_cannot_hide_or_block_the_core_application() -> None:
    enhancements = (STATIC / "enhancement-loader.js").read_text(encoding="utf-8")

    assert "foxgen:bootstrap" in enhancements
    assert "loadSequentially" in enhancements
    assert "optional enhancement failed to load" in enhancements
    assert "data-foxgen-enhancements" in enhancements
    assert "surfaceReady" not in enhancements
    assert "CURRENT_SURFACE_TIMEOUT_MS" not in enhancements
    assert "data-foxgen-catalog" not in enhancements
    assert "showCriticalFailure" not in enhancements
    assert "__FOXGEN_BOOT_FATAL__" not in enhancements


def test_backend_parity_ui_exposes_all_primary_user_domains() -> None:
    ui = (STATIC / "backend-parity-ui.js").read_text(encoding="utf-8")
    css = (STATIC / "backend-parity.css").read_text(encoding="utf-8")

    for label in ("Главная", "Модели", "Создать", "Работы", "Баланс", "Профиль"):
        assert label in ui
    for domain in (
        "Сообщество",
        "Референсы",
        "Тарифы",
        "Партнёры",
        "Поддержка",
        "Все модели",
    ):
        assert domain in ui
    for slug in (
        "suno-v5-extend",
        "suno-v5-upload-cover",
        "suno-v5-upload-extend",
        "kling-3-motion-control",
    ):
        assert slug in ui
    assert "/me/publications?limit=50" in ui
    assert "method: 'DELETE'" in ui
    assert "/publications/${encodeURIComponent(scope)}" in ui
    assert "repeat(6" in css
    assert ".complete-tool.is-planned" in css


def test_production_deploy_is_not_silently_disabled_after_green_main_ci() -> None:
    workflow = DEPLOY.read_text(encoding="utf-8")

    assert "AUTODEPLOY_ENABLED" not in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
