from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_user_parity_hardening_is_loaded_from_existing_bundle() -> None:
    promo = (MINIAPP / "promo-redeem.js").read_text(encoding="utf-8")
    script = (MINIAPP / "user-parity-hardening.js").read_text(encoding="utf-8")

    assert "import './user-parity-hardening.js';" in promo
    assert "hf-user-parity-hardening" in script


def test_generation_detail_surfaces_every_stored_result_with_real_media_controls() -> None:
    script = (MINIAPP / "user-parity-hardening.js").read_text(encoding="utf-8")

    assert "generation.media.filter" in script
    assert "items.map((item, index) => renderResultMedia" in script
    assert '<audio src="${url}" controls preload="metadata"></audio>' in script
    assert '<video src="${url}" controls playsinline preload="metadata"></video>' in script
    assert "data-parity-result-action" in script
    assert "data-open-result" in script


def test_generation_publication_action_supports_server_side_unpublish() -> None:
    script = (MINIAPP / "user-parity-hardening.js").read_text(encoding="utf-8")

    assert "/me/publications?limit=50" in script
    assert "/publications/${encodeURIComponent(scope)}" in script
    assert "{ method: 'DELETE' }" in script
    assert "data-parity-unpublish" in script
    assert "Убрать из ленты" in script
    assert "Убрать из профиля" in script


def test_profile_exposes_real_stars_topup_instead_of_stale_payment_placeholder() -> None:
    script = (MINIAPP / "user-parity-hardening.js").read_text(encoding="utf-8")

    assert "Пополнить баланс" in script
    assert "Telegram Stars" in script
    assert "topup.dataset.starsTopup = '1'" in script
    assert "Пополнение работает через нативный Telegram Stars checkout" in script


def test_publication_detail_renders_all_media_and_audio_playback() -> None:
    script = (MINIAPP / "user-parity-hardening.js").read_text(encoding="utf-8")

    assert "publication.media.filter" in script
    assert "parity-publication-results" in script
    assert '<audio src="${url}" controls preload="metadata"></audio>' in script


def test_hardening_keeps_browser_inside_owner_scoped_miniapp_boundary() -> None:
    script = (MINIAPP / "user-parity-hardening.js").read_text(encoding="utf-8")

    assert "/v1/miniapp/auth" in script
    assert "/v1/miniapp${path}" in script
    assert "Authorization" in script
    assert "init_data: tg.initData" in script

    forbidden = {
        "FOXGEN_INTERNAL_API_TOKEN",
        "FOXGEN_KIE_API_KEY",
        "X-Admin-Signature",
        "/internal/admin/",
    }
    for value in forbidden:
        assert value not in script
