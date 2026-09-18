import asyncio

from bot import miniapp


def _video_trend_prompt(preview_url="https://cdn.example.invalid/source.mp4"):
    return {
        "tags": ["trend"],
        "generation_settings": {"kind": "video"},
        "preview_url": preview_url,
    }


def test_miniapp_trend_preview_cache_miss_schedules_background_work(monkeypatch) -> None:
    scheduled = []

    monkeypatch.setattr(miniapp, "get_cached_lightweight_trend_preview_url", lambda _url: None)
    monkeypatch.setattr(
        miniapp,
        "schedule_lightweight_trend_preview",
        lambda url: scheduled.append(url) or True,
    )

    prompt = _video_trend_prompt()
    result = asyncio.run(miniapp._apply_lightweight_trend_preview(prompt))

    assert result is prompt
    assert scheduled == ["https://cdn.example.invalid/source.mp4"]


def test_miniapp_trend_preview_uses_cached_url(monkeypatch) -> None:
    monkeypatch.setattr(
        miniapp,
        "get_cached_lightweight_trend_preview_url",
        lambda _url: "https://static.example.invalid/uploads/trend-previews/cached.mp4",
    )
    monkeypatch.setattr(miniapp, "schedule_lightweight_trend_preview", lambda _url: False)

    prompt = _video_trend_prompt()
    result = asyncio.run(miniapp._apply_lightweight_trend_preview(prompt))

    assert result is not prompt
    assert result["preview_url"] == "https://static.example.invalid/uploads/trend-previews/cached.mp4"
    assert result["original_preview_url"] == "https://cdn.example.invalid/source.mp4"
