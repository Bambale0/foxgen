from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "foxgen" / "miniapp_static"
INDEX = STATIC / "index.html"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_production_shell_declares_core_fallback_and_all_user_parity_modules() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in html
    for asset in (
        "boot-guard.js",
        "runtime-loader.js",
        "enhancement-loader.js",
        "parity-app.js",
        "app.js",
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
        "product-home.js",
    ):
        assert f"/mini-app/{asset}?v={MINIAPP_RELEASE}" in html

    for stylesheet in (
        "motion-control.css",
        "product-home.css",
    ):
        assert f"/mini-app/{stylesheet}?v={MINIAPP_RELEASE}" in html

    core_scripts = (
        "boot-guard.js",
        "runtime-loader.js",
        "enhancement-loader.js",
    )
    for asset in core_scripts:
        tag = f'<script src="/mini-app/{asset}?v={MINIAPP_RELEASE}"></script>'
        assert tag in html

    parity_src = f"/mini-app/parity-app.js?v={MINIAPP_RELEASE}"
    legacy_src = f"/mini-app/app.js?v={MINIAPP_RELEASE}"
    assert f'data-parity-src="{parity_src}"' in html
    assert f'data-legacy-src="{legacy_src}"' in html

    parity_defer = f'<script defer src="{parity_src}"></script>'
    assert parity_defer not in html
    assert '<script type="module" src="/mini-app/parity-app.js' not in html
    assert '<script type="module" src="/mini-app/app.js' not in html

    product_home_url = f"/mini-app/product-home.js?v={MINIAPP_RELEASE}"
    critical_attr = 'data-critical-module="catalog"'
    critical = f'<span data-module-src="{product_home_url}" {critical_attr}></span>'
    assert critical in html
    assert html.index(critical) < html.index("complete-menu.js")


def test_production_boot_guard_has_bounded_legacy_safe_failure_state() -> None:
    guard = (STATIC / "boot-guard.js").read_text(encoding="utf-8")

    assert "BOOT_TIMEOUT_MS = 15000" in guard
    assert "Happy Fox не запустился" in guard
    assert "data-boot-retry" in guard
    assert "unhandledrejection" in guard
    assert "__FOXGEN_BOOT_FAIL__" in guard
    assert "legacy=1" in guard
    assert "Переключаем совместимый режим" in guard
    assert ".replaceAll(" not in guard
    assert "?." not in guard
    assert "??" not in guard


def test_runtime_loader_keeps_catalog_available_in_compat_mode() -> None:
    loader = (STATIC / "runtime-loader.js").read_text(encoding="utf-8")
    enhancements = (STATIC / "enhancement-loader.js").read_text(encoding="utf-8")

    assert "String.prototype.replaceAll" in loader
    assert "window.structuredClone" in loader
    assert "new Function" in loader
    assert "??=" in loader
    assert "&&=" in loader
    assert "data-legacy-src" in loader
    assert "__FOXGEN_RUNTIME_KIND__" in loader

    assert "foxgen:bootstrap" in enhancements
    assert "__FOXGEN_RUNTIME_KIND__ === 'legacy'" not in enhancements
    assert "data-critical-module" in enhancements
    assert "data-foxgen-catalog" in enhancements
    assert "showCriticalFailure" in enhancements
    assert "loadOptionalModules" in enhancements


def test_production_deploy_is_not_silently_disabled_after_green_main_ci() -> None:
    workflow = DEPLOY.read_text(encoding="utf-8")

    assert "AUTODEPLOY_ENABLED" not in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
