from __future__ import annotations

import argparse
import re
from pathlib import Path

TELEGRAM_SCRIPT_RE = re.compile(
    r'<script\b[^>]*\bsrc=["\']/mini-app/telegram-web-app\.js["\'][^>]*>\s*</script>',
    re.IGNORECASE,
)
MAX_SCRIPT_RE = re.compile(
    r'<script\b[^>]*\bsrc=["\']https://st\.max\.ru/js/max-web-app\.js["\'][^>]*>\s*</script>',
    re.IGNORECASE,
)
CHANNEL_MARKER_RE = re.compile(
    r'<meta\s+name=["\']happyfox-miniapp-channel["\']\s+content=["\'][^"\']+["\']\s*/?>',
    re.IGNORECASE,
)
HEAD_RE = re.compile(r"<head(?:\s[^>]*)?>", re.IGNORECASE)
VALID_CHANNELS = frozenset({"shared", "telegram", "max"})


def render_html(html: str, channel: str) -> str:
    channel = channel.strip().lower()
    if channel not in VALID_CHANNELS:
        raise ValueError(f"unsupported Mini App channel: {channel}")

    rendered = CHANNEL_MARKER_RE.sub("", html)
    if channel == "telegram":
        rendered = MAX_SCRIPT_RE.sub("", rendered)
    elif channel == "max":
        rendered = TELEGRAM_SCRIPT_RE.sub("", rendered)

    marker = f'<meta name="happyfox-miniapp-channel" content="{channel}" />'
    head = HEAD_RE.search(rendered)
    if head is None:
        raise ValueError("Mini App HTML does not contain <head>")
    rendered = rendered[: head.end()] + marker + rendered[head.end() :]

    bridge_counts = (
        len(TELEGRAM_SCRIPT_RE.findall(rendered)),
        len(MAX_SCRIPT_RE.findall(rendered)),
    )
    expected = {
        "shared": (1, 1),
        "telegram": (1, 0),
        "max": (0, 1),
    }[channel]
    if bridge_counts != expected:
        raise ValueError(
            "Mini App bridge contract mismatch: "
            f"channel={channel} actual={bridge_counts} expected={expected}"
        )
    return rendered


def render_tree(root: Path, channel: str) -> int:
    if not root.is_dir():
        raise ValueError(f"Mini App root does not exist: {root}")

    processed = 0
    for path in sorted(root.rglob("*.html")):
        original = path.read_text(encoding="utf-8")
        rendered = render_html(original, channel)
        if rendered != original:
            path.write_text(rendered, encoding="utf-8")
        processed += 1

    if processed == 0:
        raise ValueError(f"no HTML files were found under {root}")
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render one HappyFox Mini App static export for a messenger channel"
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("channel", choices=sorted(VALID_CHANNELS))
    args = parser.parse_args()
    processed = render_tree(args.root, args.channel)
    print(f"rendered channel={args.channel} html_files={processed} root={args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
