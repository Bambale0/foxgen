from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MINIAPP_RELEASE = "parity-v12"
MINIAPP_RELEASE_QUERY_KEY = "release"


def versioned_miniapp_url(url: str) -> str:
    """Return the public Mini App URL with an explicit release cache-buster."""

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[MINIAPP_RELEASE_QUERY_KEY] = MINIAPP_RELEASE
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )
