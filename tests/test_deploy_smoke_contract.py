from pathlib import Path


def test_deploy_retries_happy_fox_smokes_after_nginx_reload() -> None:
    script = Path("scripts/deploy-production.sh").read_text(encoding="utf-8")
    assert "verify_public_miniapp()" in script
    assert script.count("deadline=$((SECONDS + 30))") >= 2
    assert "attempt_timeout=$((remaining < 5 ? remaining : 5))" in script
    assert "for attempt in $(seq 1 15)" not in script
    assert "public Happy Fox Mini App $MINIAPP_RELEASE did not become ready within 30s" in script
    assert "Telegram Happy Fox menu did not converge to $MINIAPP_URL within 30s" in script
    assert "assert_service_image" in script
    assert "verify_live_bot_webapp_code" in script
    assert "curl --fail" in script


def test_deploy_verifies_exact_miniapp_release_and_catalog_assets() -> None:
    script = Path("scripts/deploy-production.sh").read_text(encoding="utf-8")

    assert "miniapp_release()" in script
    assert "append_miniapp_release()" in script
    assert "foxgen-miniapp-shell" in script
    assert '/mini-app/product-home.js?v=${expected_release}' in script
    assert '/mini-app/product-home.css?v=${expected_release}' in script
    assert 'expected = os.environ["MINIAPP_URL"]' in script
    assert "if actual != expected:" in script
