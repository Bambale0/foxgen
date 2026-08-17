from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "foxgen" / "miniapp_static" / "index.html"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_production_shell_loads_all_user_parity_modules() -> None:
    html = INDEX.read_text(encoding="utf-8")

    assert 'name="foxgen-miniapp-shell" content="parity-v3"' in html
    for module in (
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
    ):
        assert f"/mini-app/{module}?v=parity-v3" in html

    assert "/mini-app/motion-control.css?v=parity-v3" in html
    assert '<script type="module" src="/mini-app/app.js' not in html


def test_production_deploy_is_not_silently_disabled_after_green_main_ci() -> None:
    workflow = DEPLOY.read_text(encoding="utf-8")

    assert "AUTODEPLOY_ENABLED" not in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
