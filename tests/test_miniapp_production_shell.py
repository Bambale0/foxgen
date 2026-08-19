from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "foxgen" / "miniapp_static"
INDEX = STATIC / "index.html"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_production_shell_declares_single_current_runtime_and_all_user_modules() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in html
    for asset in (
        "boot-guard.js",
        "runtime-loader.js",
        "enhancement-loader.js",
        "parity-app.js",
        "product-home.js",
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
    ):
        assert f"/mini-app/{asset}?v={MINIAPP_RELEASE}" in html

    for stylesheet in (
        "motion-control.css",
        "product-home.css",
    ):
        assert f"/mini-app/{stylesheet}?v={MINIAPP_RELEASE}" in html

    for asset in (
        "boot-guard.js",
        "runtime-loader.js",
        "enhancement-loader.js",
    ):
        tag = f'<script src="/mini-app/{asset}?v={MINIAPP_RELEASE}"></script>'
        assert tag in html

    parity_src = f"/mini-app/parity-app.js?v={MINIAPP_RELEASE}"
    product_home_src = f"/mini-app/product-home.js?v={MINIAPP_RELEASE}"
    assert f'data-parity-src="{parity_src}"' in html
    assert f'data-product-home-src="{product_home_src}"' in html
    assert "data-legacy-src" not in html
    assert "/mini-app/app.js" not in html
    assert 'data-critical-module="catalog"' not in html
    assert 'data-foxgen-catalog="booting"' in html
    assert "visibility: hidden" in html

    parity_defer = f'<script defer src="{parity_src}"></script>'
    assert parity_defer not in html
    assert '<script type="module" src="/mini-app/parity-app.js' not in html
    assert html.index("data-product-home-src") < html.index("complete-menu.js")


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


def test_runtime_loader_makes_current_catalog_mandatory() -> None:
    loader = (STATIC / "runtime-loader.js").read_text(encoding="utf-8")
    enhancements = (STATIC / "enhancement-loader.js").read_text(encoding="utf-8")

    assert "String.prototype.replaceAll" in loader
    assert "window.structuredClone" in loader
    assert "new Function" in loader
    assert "transpileLogicalAssignments" in loader
    assert "fetch(source, { cache: 'no-store' })" in loader
    assert "compiled.indexOf('??=')" in loader
    assert "compiled.indexOf('&&=')" in loader
    assert "data-product-home-src" in loader
    assert "data-legacy-src" not in loader
    assert "legacy=1" not in loader
    assert "__FOXGEN_RUNTIME_KIND__ = 'parity'" in loader
    assert "__FOXGEN_BOOT_FATAL__" in loader
    assert "__FOXGEN_CATALOG_RUNTIME_LOADED__" in loader
    assert "слишком старая" in loader

    assert "mountPendingAccountSurface" in loader
    assert 'data-bootstrap-pending="1"' in loader
    assert "Подключаем Telegram-аккаунт" in loader
    assert "foxgen:catalog-runtime-loaded" in loader
    assert "Подключаем аккаунт…" not in loader

    assert "foxgen:bootstrap" in enhancements
    assert "foxgen:catalog-runtime-loaded" in enhancements
    assert "data-critical-module" not in enhancements
    assert "data-foxgen-catalog" in enhancements
    assert "isCurrentSurfaceReady" in enhancements
    assert "waitForCurrentSurface" in enhancements
    assert "CURRENT_SURFACE_TIMEOUT_MS = 12000" in enhancements
    assert "COMMUNITY / LIVE" in enhancements
    assert "main.getAttribute('data-product-catalog') === '1'" in enhancements
    assert "bootstrapReady" in enhancements
    assert "maybeLoadOptionalModules" in enhancements
    assert "showCriticalFailure" in enhancements
    assert "__FOXGEN_BOOT_FATAL__" in enhancements
    assert "loadOptionalModules(optionalNodes)" in enhancements


def test_current_catalog_can_appear_before_account_bootstrap_finishes() -> None:
    loader = (STATIC / "runtime-loader.js").read_text(encoding="utf-8")
    enhancements = (STATIC / "enhancement-loader.js").read_text(encoding="utf-8")

    mount_index = loader.index("mountPendingAccountSurface();")
    catalog_load_index = loader.index("loadCurrentSource(catalogSource")
    event_index = loader.index("publishCatalogRuntimeReady();")
    assert mount_index < catalog_load_index < event_index

    assert "window.addEventListener('foxgen:catalog-runtime-loaded', loadEnhancements);" in enhancements
    assert "surfaceReady = true" in enhancements
    assert "document.documentElement.setAttribute('data-foxgen-catalog', 'ready')" in enhancements
    assert "if (optionalLoaded || !surfaceReady || !bootstrapReady || !optionalNodes) return;" in enhancements


def test_production_deploy_is_not_silently_disabled_after_green_main_ci() -> None:
    workflow = DEPLOY.read_text(encoding="utf-8")

    assert "AUTODEPLOY_ENABLED" not in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
