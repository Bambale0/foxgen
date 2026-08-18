from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "foxgen" / "miniapp_static" / "index.html"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_production_shell_loads_all_user_parity_modules() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in html
    for module in (
        "boot-guard.js",
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
        "product-home.js",
    ):
        assert f"/mini-app/{module}?v={MINIAPP_RELEASE}" in html

    for stylesheet in (
        "motion-control.css",
        "product-home.css",
    ):
        assert f"/mini-app/{stylesheet}?v={MINIAPP_RELEASE}" in html

    assert f'<script defer src="/mini-app/parity-app.js?v={MINIAPP_RELEASE}"></script>' in html
    assert f'<script src="/mini-app/boot-guard.js?v={MINIAPP_RELEASE}"></script>' in html
    assert '<script type="module" src="/mini-app/parity-app.js' not in html
    assert '<script type="module" src="/mini-app/app.js' not in html


def test_production_boot_guard_has_bounded_failure_state() -> None:
    guard = (ROOT / "src" / "foxgen" / "miniapp_static" / "boot-guard.js").read_text(
        encoding="utf-8"
    )

    assert "BOOT_TIMEOUT_MS = 15000" in guard
    assert "Happy Fox не запустился" in guard
    assert "data-boot-retry" in guard
    assert "unhandledrejection" in guard


def test_production_deploy_is_not_silently_disabled_after_green_main_ci() -> None:
    workflow = DEPLOY.read_text(encoding="utf-8")

    assert "AUTODEPLOY_ENABLED" not in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
