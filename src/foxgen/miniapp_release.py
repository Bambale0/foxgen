from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MINIAPP_RELEASE = "parity-v5"


def versioned_miniapp_url(url: str) -> str:
    """Return the public Mini App URL with a release cache-buster."""

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["v"] = MINIAPP_RELEASE
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )
