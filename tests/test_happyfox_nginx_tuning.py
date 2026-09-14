from scripts.tune_happyfox_nginx import tune_certbot_options, tune_site


def _site() -> str:
    return """server {
    server_name api.happy-fox.online;
    location / {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
    listen 443 ssl;
    ssl_protocols TLSv1.2;
}
server {
    server_name app.happy-fox.online;
    root /var/www/happyfox-app;
    location /mini-app/api/ {
        proxy_pass http://127.0.0.1:1888;
        proxy_http_version 1.1;
    }
    location /mini-app/ { try_files $uri $uri/ /mini-app/index.html; }
    listen [::]:443 ssl;
}
server {
    server_name happy-fox.online;
    root /var/www/happyfox-landing;
    index index.html;
    location = / { try_files /mini-app/landing/index.html =404; }
    location /mini-app/ { try_files $uri $uri/ =404; }
    listen 443 ssl ipv6only=on;
}
"""


def test_tune_happyfox_site_enables_h2_keepalive_and_static_cache() -> None:
    tuned = tune_site(_site())

    assert "upstream happyfox_backend {" in tuned
    assert "server 127.0.0.1:1888;" in tuned
    assert "keepalive 64;" in tuned
    assert tuned.count("proxy_pass http://happyfox_backend;") == 4
    assert tuned.count('proxy_set_header Connection "";') == 4
    assert tuned.count("proxy_socket_keepalive on;") == 4
    assert tuned.count("proxy_buffering off;") == 4
    assert tuned.count("proxy_request_buffering off;") == 4
    assert "listen 443 ssl http2;" in tuned
    assert "listen [::]:443 ssl http2;" in tuned
    assert "listen 443 ssl http2 ipv6only=on;" in tuned
    assert "ssl_protocols" not in tuned
    assert "location ^~ /mini-app/_next/static/" in tuned
    assert 'Cache-Control "public, max-age=31536000, immutable"' in tuned
    assert "location = /max/webhook {" in tuned
    assert "return 302 https://app.happy-fox.online/mini-app/" in tuned
    assert tuned.count("location /mini-app/api/ {") == 2
    assert tuned.count("location /mini-app/ { try_files $uri $uri/ /mini-app/index.html; }") == 2
    assert tuned.count("location = /mini-app/ {") == 2
    assert tuned.count("error_page 418 =200 /mini-app/index.html;") == 2
    assert tuned.count("if ($request_method = OPTIONS) { return 204; }") == 2
    assert tuned.count("if ($request_method = POST) { return 418; }") == 2


def test_tune_happyfox_site_is_idempotent() -> None:
    once = tune_site(_site())
    twice = tune_site(once)
    assert twice == once


def test_tune_certbot_options_keeps_only_tls12() -> None:
    source = """ssl_session_cache shared:le_nginx_SSL:10m;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
"""
    tuned = tune_certbot_options(source)
    assert "ssl_protocols TLSv1.2;" in tuned
    assert "TLSv1.3" not in tuned
