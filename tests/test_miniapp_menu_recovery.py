import shutil
import subprocess
from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "foxgen" / "miniapp_static"
INDEX = STATIC / "index.html"
RECOVERY = STATIC / "menu-recovery.js"


def test_menu_recovery_is_part_of_the_versioned_shell() -> None:
    html = INDEX.read_text(encoding="utf-8")

    recovery = f"/mini-app/menu-recovery.js?v={MINIAPP_RELEASE}"
    enhancements = f"/mini-app/enhancement-loader.js?v={MINIAPP_RELEASE}"
    assert recovery in html
    assert enhancements in html
    assert html.index(recovery) < html.index(enhancements)


def test_menu_recovery_uses_server_owned_model_availability() -> None:
    source = RECOVERY.read_text(encoding="utf-8")

    assert "window.__FOXGEN_BOOTSTRAP__" in source
    assert "enabled_for_submission !== false" in source
    assert "elevenlabs-turbo-2-5" in source
    assert "suno-v5" in source
    assert "kling-3-motion-control" in source
    assert "data-tts-product-head" in source
    assert "data-suno-product-head" in source
    assert "data-model=\"' + slug + '\"" in source


def test_menu_recovery_does_not_bypass_motion_owner_flow() -> None:
    source = RECOVERY.read_text(encoding="utf-8")

    assert "root.querySelector('[data-motion-open]')" in source
    assert "promoteLauncher('motion')" in source
    assert "ensureGenericProduct(\n        'kling-3-motion-control'" not in source


def test_menu_recovery_keeps_legacy_parser_surface_small() -> None:
    source = RECOVERY.read_text(encoding="utf-8")

    assert "?." not in source
    assert "??" not in source
    assert "=>" not in source

    node = shutil.which("node")
    if node is None:
        return
    result = subprocess.run(
        [node, "--check", str(RECOVERY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
