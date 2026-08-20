from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    port = int(os.getenv("WEBHOOK_PORT", "1888"))
    secret = os.getenv("HEALTH_CHECK_SECRET", "").strip()
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    request = Request(f"http://127.0.0.1:{port}/health", headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            if response.status != 200:
                print(f"healthcheck: unexpected HTTP {response.status}", file=sys.stderr)
                return 1
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        print(f"healthcheck: {error}", file=sys.stderr)
        return 1

    if payload.get("status") != "ok":
        print(f"healthcheck: unexpected payload {payload!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
