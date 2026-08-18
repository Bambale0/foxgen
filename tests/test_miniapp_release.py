from foxgen.miniapp_release import MINIAPP_RELEASE, versioned_miniapp_url


def test_release_marker_matches_current_shell_generation() -> None:
    assert MINIAPP_RELEASE == "parity-v5"


def test_versioned_miniapp_url_busts_top_level_webview_cache() -> None:
    assert (
        versioned_miniapp_url("https://fox.example.com/mini-app/")
        == "https://fox.example.com/mini-app/?v=parity-v5"
    )


def test_versioned_miniapp_url_preserves_existing_query() -> None:
    assert (
        versioned_miniapp_url("https://fox.example.com/mini-app/?start=motion")
        == "https://fox.example.com/mini-app/?start=motion&v=parity-v5"
    )
