from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_recoverable_draft_module_is_loaded_and_time_bounded() -> None:
    promo = (MINIAPP / "promo-redeem.js").read_text(encoding="utf-8")
    script = (MINIAPP / "user-draft-recovery.js").read_text(encoding="utf-8")

    assert "import './user-draft-recovery.js';" in promo
    assert "happy-fox:studio-draft:v1" in script
    assert "12 * 60 * 60 * 1000" in script
    assert "window.localStorage" in script


def test_draft_persists_schema_fields_and_media_mode_but_not_media_urls() -> None:
    script = (MINIAPP / "user-draft-recovery.js").read_text(encoding="utf-8")

    assert "collectFields()" in script
    assert "currentMediaMode()" in script
    assert "media_restore_required" in script
    assert "studio.querySelector('.draft-media-item')" in script
    assert "storage_key" not in script
    assert "preview_url" not in script


def test_restore_replays_controls_through_existing_studio_events() -> None:
    script = (MINIAPP / "user-draft-recovery.js").read_text(encoding="utf-8")

    assert "dispatchEvent(new Event('input', { bubbles: true }))" in script
    assert "dispatchEvent(new Event('change', { bubbles: true }))" in script
    assert "data-media-mode" in script
    assert "Файлы и референсы нужно прикрепить заново" in script


def test_draft_is_cleared_only_after_successful_transition_or_explicit_reset() -> None:
    script = (MINIAPP / "user-draft-recovery.js").read_text(encoding="utf-8")

    assert "submissionPending = true" in script
    assert "root?.querySelector('.generation-media')" in script
    assert "data-reset-draft" in script
    assert "clearDraft()" in script


def test_draft_recovery_does_not_cross_privileged_browser_boundary() -> None:
    script = (MINIAPP / "user-draft-recovery.js").read_text(encoding="utf-8")

    for forbidden in (
        "FOXGEN_INTERNAL_API_TOKEN",
        "FOXGEN_KIE_API_KEY",
        "X-Admin-Signature",
        "/internal/admin/",
    ):
        assert forbidden not in script
