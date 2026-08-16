from pathlib import Path


MINIAPP = Path(__file__).resolve().parents[1] / "src" / "foxgen" / "miniapp_static"


def test_suno_extend_module_is_loaded_from_happy_fox_shell() -> None:
    html = (MINIAPP / "index.html").read_text(encoding="utf-8")
    script = (MINIAPP / "suno-extend.js").read_text(encoding="utf-8")

    assert "/mini-app/suno-extend.js" in html
    assert "Продолжить свой трек" in script
    assert "/music/suno/sources" in script
    assert "/music/suno/extend" in script


def test_suno_extend_uses_owner_sources_not_manual_ids() -> None:
    script = (MINIAPP / "suno-extend.js").read_text(encoding="utf-8")

    assert "data-suno-extend-source" in script
    assert "source_generation_id: selected.generation_id" in script
    assert "audio_id: selected.audio_id" in script
    assert "data-suno-extend-at" in script
    assert "Точка продолжения должна быть раньше конца исходного трека" in script
    assert 'data-model="suno-v5-extend"' in script
    assert ".remove()" in script


def test_suno_extend_browser_never_calls_kie_or_supplies_price() -> None:
    script = (MINIAPP / "suno-extend.js").read_text(encoding="utf-8").lower()

    assert "api.kie.ai" not in script
    assert "/api/v1/generate/extend" not in script
    assert "kie_api_key" not in script
    assert "authorization: bearer" not in script
    assert "amount_units:" not in script
    assert "idempotency-key" in script


def test_suno_extend_price_and_balance_are_backend_owned() -> None:
    script = (MINIAPP / "suno-extend.js").read_text(encoding="utf-8")

    assert "bootstrap?.models" in script
    assert "bootstrap?.balance?.available_units" in script
    assert "Цена Suno V5 Extend не опубликована" in script
    assert "Недостаточно средств" in script
    assert "disabled" in script
