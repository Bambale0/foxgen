from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_motion_control_uses_dedicated_owner_scoped_api() -> None:
    script = (MINIAPP / "motion-control.js").read_text(encoding="utf-8")

    assert "const MODEL = 'kling-3-motion-control'" in script
    assert "'/v1/miniapp/auth'" in script
    assert "fetch(`/v1/miniapp${path}`" in script
    assert "`/motion/kling/inputs/${kind}`" in script
    assert "api('/motion/kling'" in script
    assert "Idempotency-Key" in script

    for forbidden in (
        "FOXGEN_KIE_API_KEY",
        "FOXGEN_INTERNAL_API_TOKEN",
        "X-FoxGen-User-Id",
        "https://api.kie.ai",
    ):
        assert forbidden not in script


def test_motion_control_hides_private_storage_fields_from_user_form() -> None:
    script = (MINIAPP / "motion-control.js").read_text(encoding="utf-8")

    assert "removeRawModelRow" in script
    assert 'name="motion-image"' in script
    assert 'name="motion-video"' in script
    assert 'name="motion-prompt"' in script
    assert 'name="image_storage_key"' not in script
    assert 'name="video_storage_key"' not in script
    assert "Фото персонажа" in script
    assert "Видео движения" in script


def test_motion_control_validates_provider_limits_before_upload() -> None:
    script = (MINIAPP / "motion-control.js").read_text(encoding="utf-8")

    assert "10 * 1024 * 1024" in script
    assert "100 * 1024 * 1024" in script
    assert "const MIN_DURATION = 3" in script
    assert "const MAX_DURATION = 30" in script
    assert "const MIN_RATIO = 2 / 5" in script
    assert "const MAX_RATIO = 5 / 2" in script
    assert "validateImage(file)" in script
    assert "validateVideo(file)" in script
    assert "videoMetadata(file)" in script


def test_motion_control_price_and_balance_are_server_driven() -> None:
    script = (MINIAPP / "motion-control.js").read_text(encoding="utf-8")

    assert "data?.prices" in script
    assert "item?.model_slug === MODEL" in script
    assert "data?.balance?.available_units" in script
    assert "Цена Motion Control ещё не опубликована" in script
    assert "Недостаточно CREDIT" in script
    assert "data-motion-wallet" in script


def test_motion_control_success_is_one_shot_and_links_to_works() -> None:
    script = (MINIAPP / "motion-control.js").read_text(encoding="utf-8")

    assert "if (busy || submitted) return" in script
    assert "submitted = true" in script
    assert "submit.textContent = 'В очереди'" in script
    assert "data-motion-works" in script
    assert "[data-nav=\"works\"]" in script
