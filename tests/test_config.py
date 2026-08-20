"""Unit tests for bot/config.py"""

from pathlib import Path

from bot import env
from bot.config import Config


def test_project_env_loading_can_be_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(env.SKIP_PROJECT_ENV_VAR, "1")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("production env loader must not run during tests")

    monkeypatch.setattr(env, "load_dotenv", fail_if_called)
    monkeypatch.setattr(env, "dotenv_values", fail_if_called)

    env.load_project_env(tmp_path)


class TestConfig:
    def test_admin_ids(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = "123,456"
        assert cfg.admin_ids == [123, 456]

    def test_admin_ids_invalid(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = "invalid"
        assert cfg.admin_ids == []

    def test_admin_ids_empty(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = ""
        assert cfg.admin_ids == []

    def test_is_admin_true(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = "123456"
        assert cfg.is_admin(123456) is True

    def test_is_admin_false(self):
        cfg = Config()
        cfg.ADMIN_IDS_STR = "123456"
        assert cfg.is_admin(789012) is False

    def test_webhook_url(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://test.com"
        cfg.WEBHOOK_PATH = "/webhook"
        assert cfg.webhook_url == "https://test.com/webhook"

    def test_webhook_url_trailing_slash(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://test.com/"
        cfg.WEBHOOK_PATH = "/webhook"
        assert cfg.webhook_url == "https://test.com/webhook"

    def test_webhook_path_no_leading_slash(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://test.com"
        cfg.WEBHOOK_PATH = "webhook"
        assert cfg.webhook_url == "https://test.com/webhook"

    def test_webhook_bind_host_default_is_localhost(self):
        cfg = Config()
        assert cfg.WEBHOOK_BIND_HOST == "127.0.0.1"

    def test_redis_prefix_default_is_happyfox_specific(self, monkeypatch):
        monkeypatch.delenv("REDIS_PREFIX", raising=False)
        cfg = Config()
        assert cfg.REDIS_PREFIX == "foxgen_happyfox"

    def test_payment_provider_freekassa(self):
        cfg = Config()
        cfg.PAYMENT_PROVIDER = "freekassa"
        assert cfg.payment_provider == "freekassa"

    def test_payment_provider_fallback(self):
        cfg = Config()
        cfg.PAYMENT_PROVIDER = "invalid"
        cfg.LAVA_API_KEY = ""
        assert cfg.payment_provider == "cryptobot"

    def test_payment_provider_fallback_prefers_lava(self):
        cfg = Config()
        cfg.PAYMENT_PROVIDER = "invalid"
        cfg.LAVA_API_KEY = "lava-key"
        assert cfg.payment_provider == "lava"

    def test_has_freekassa_true(self):
        cfg = Config()
        cfg.FREEKASSA_MERCHANT_ID = "shop123"
        cfg.FREEKASSA_SECRET_WORD = "secret1"
        cfg.FREEKASSA_SECRET_WORD_2 = "secret2"
        assert cfg.has_freekassa is True

    def test_has_freekassa_false(self):
        cfg = Config()
        cfg.FREEKASSA_MERCHANT_ID = "shop123"
        cfg.FREEKASSA_SECRET_WORD = "secret1"
        cfg.FREEKASSA_SECRET_WORD_2 = ""
        assert cfg.has_freekassa is False

    def test_freekassa_notification_url(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://payments.example"
        cfg.FREEKASSA_WEBHOOK_PATH = "freekassa/webhook"
        assert (
            cfg.freekassa_notification_url
            == "https://payments.example/freekassa/webhook"
        )

    def test_legacy_yookassa_alias_points_to_freekassa(self):
        cfg = Config()
        cfg.WEBHOOK_HOST = "https://payments.example"
        cfg.FREEKASSA_WEBHOOK_PATH = "/freekassa/webhook"
        cfg.FREEKASSA_RETURN_URL = "https://payments.example/mini-app/"
        assert cfg.yookassa_notification_url == cfg.freekassa_notification_url
        assert cfg.YOOKASSA_RETURN_URL == cfg.FREEKASSA_RETURN_URL

    def test_static_base_url_default_is_local(self):
        cfg = Config()
        cfg.STATIC_BASE_URL = ""
        cfg.WEBHOOK_HOST = ""
        cfg.WEBHOOK_PORT = 8443
        assert cfg.static_base_url == "http://127.0.0.1:8443"

    def test_static_base_url_webhook(self):
        cfg = Config()
        cfg.STATIC_BASE_URL = ""
        cfg.WEBHOOK_HOST = "https://custom.com"
        assert cfg.static_base_url == "https://custom.com"

    def test_regular_banana_models_are_forced_to_kie(self):
        from bot.config import config
        from bot.services import nano_banana_2_service, nano_banana_pro_service

        assert config.NANOBANANA2_FALLBACK_API_KEY == ""
        assert config.NANOBANANA2_FALLBACK_BASE_URL == ""
        assert config.NANO_BANANA_PRO_FALLBACK_API_KEY == ""
        assert config.NANO_BANANA_PRO_FALLBACK_BASE_URL == ""

        assert nano_banana_2_service.primary_provider.base_url == "https://api.kie.ai"
        assert nano_banana_2_service.fallback_provider is None
        assert nano_banana_pro_service.primary_provider.base_url == "https://api.kie.ai"
        assert nano_banana_pro_service.fallback_provider is None
