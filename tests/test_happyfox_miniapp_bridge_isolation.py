from __future__ import annotations

from pathlib import Path

from scripts.render_happyfox_miniapp_channel import render_html, render_tree


HTML = """<!doctype html>
<html>
<head>
<script src="/mini-app/telegram-web-app.js"></script>
<script src="https://st.max.ru/js/max-web-app.js"></script>
<script src="/mini-app/_next/static/app.js"></script>
</head>
<body>HappyFox</body>
</html>
"""


def test_telegram_variant_keeps_only_telegram_bridge() -> None:
    rendered = render_html(HTML, "telegram")

    assert '/mini-app/telegram-web-app.js' in rendered
    assert 'https://st.max.ru/js/max-web-app.js' not in rendered
    assert 'happyfox-miniapp-channel" content="telegram' in rendered


def test_max_variant_keeps_only_max_bridge() -> None:
    rendered = render_html(HTML, "max")

    assert 'https://st.max.ru/js/max-web-app.js' in rendered
    assert '/mini-app/telegram-web-app.js' not in rendered
    assert 'happyfox-miniapp-channel" content="max' in rendered


def test_shared_variant_preserves_both_bridges() -> None:
    rendered = render_html(HTML, "shared")

    assert '/mini-app/telegram-web-app.js' in rendered
    assert 'https://st.max.ru/js/max-web-app.js' in rendered
    assert 'happyfox-miniapp-channel" content="shared' in rendered


def test_renderer_is_repeatable(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text(HTML, encoding="utf-8")

    assert render_tree(tmp_path, "telegram") == 1
    assert render_tree(tmp_path, "telegram") == 1
    assert 'https://st.max.ru/js/max-web-app.js' not in index.read_text(encoding="utf-8")


def test_production_deploy_isolates_bridges_only_after_max_origin_split() -> None:
    deploy = Path("scripts/deploy_happyfox_dedicated.sh").read_text(encoding="utf-8")

    shared = 'if [[ "$MAX_APP_ORIGIN" == "$APP_ORIGIN" ]]; then'
    assert shared in deploy
    assert "render_happyfox_miniapp_channel.py /var/www/happyfox-app/mini-app shared" in deploy
    assert "render_happyfox_miniapp_channel.py /var/www/happyfox-max/mini-app shared" in deploy
    assert "render_happyfox_miniapp_channel.py /var/www/happyfox-app/mini-app telegram" in deploy
    assert "render_happyfox_miniapp_channel.py /var/www/happyfox-max/mini-app max" in deploy
    assert "! grep -Fq 'https://st.max.ru/js/max-web-app.js' \"$telegram_index\"" in deploy
    assert "! grep -Fq '/mini-app/telegram-web-app.js' \"$max_index\"" in deploy
