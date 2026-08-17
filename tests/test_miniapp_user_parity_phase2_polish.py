from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_profile_payment_rows_converge_to_one_real_stars_action() -> None:
    script = (MINIAPP / "user-parity-phase2.js").read_text(encoding="utf-8")

    assert "normalizeProfilePayments" in script
    assert "Платежи" in script
    assert "Пополнить баланс" in script
    assert "button.dataset.starsTopup = '1'" in script
    assert "button.remove()" in script


def test_admission_notice_reuses_existing_sibling_instead_of_duplicating() -> None:
    script = (MINIAPP / "user-parity-phase2.js").read_text(encoding="utf-8")

    assert "let notice = card.nextElementSibling" in script
    assert "data-parity-admission-notice" in script


def test_dedicated_tts_and_suno_price_warnings_are_not_duplicated() -> None:
    script = (MINIAPP / "user-parity-phase2.js").read_text(encoding="utf-8")

    assert "[data-tts-price-warning],[data-suno-price-warning]" in script
    assert "previous.remove()" in script
