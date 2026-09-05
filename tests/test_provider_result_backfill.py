import json

from scripts import backfill_provider_results as backfill


def test_decode_result_urls_accepts_json_lists_and_single_legacy_value() -> None:
    assert backfill._decode_result_urls('["https://a.example/x.png", "https://b.example/y.png"]') == [
        "https://a.example/x.png",
        "https://b.example/y.png",
    ]
    assert backfill._decode_result_urls("https://a.example/x.png") == [
        "https://a.example/x.png"
    ]
    assert backfill._decode_result_urls(None) == []


def test_encode_result_urls_is_stable_json() -> None:
    encoded = backfill._encode_result_urls(
        ["https://media.example/a.png", "https://media.example/b.png"]
    )

    assert json.loads(encoded or "[]") == [
        "https://media.example/a.png",
        "https://media.example/b.png",
    ]


def test_local_happyfox_upload_is_not_a_backfill_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        backfill.config,
        "STATIC_BASE_URL",
        "https://media.happyfox.example",
    )

    assert not backfill._looks_external(
        "https://media.happyfox.example/static/uploads/result.png"
    )
    assert backfill._looks_external("https://tempfile.aiquickdraw.com/result.png")
