from foxgen.miniapp_release import (
    MINIAPP_RELEASE,
    MINIAPP_RELEASE_QUERY_KEY,
    versioned_miniapp_url,
)


def test_versioned_miniapp_url_busts_top_level_webview_cache() -> None:
    assert (
        versioned_miniapp_url("https://fox.example.com/mini-app/")
        == f"https://fox.example.com/mini-app/?{MINIAPP_RELEASE_QUERY_KEY}={MINIAPP_RELEASE}"
    )


def test_versioned_miniapp_url_preserves_existing_query() -> None:
    assert (
        versioned_miniapp_url("https://fox.example.com/mini-app/?start=motion")
        == (
            "https://fox.example.com/mini-app/?start=motion"
            f"&{MINIAPP_RELEASE_QUERY_KEY}={MINIAPP_RELEASE}"
        )
    )
