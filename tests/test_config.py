from foxgen.core.config import Settings


def test_empty_optional_environment_values_are_ignored(monkeypatch) -> None:
    monkeypatch.setenv("FOXGEN_KIE_CALLBACK_BASE_URL", "")
    monkeypatch.setenv("FOXGEN_KIE_WEBHOOK_HMAC_KEY", "")

    settings = Settings(_env_file=None, env="test")

    assert settings.kie_callback_base_url is None
    assert settings.kie_webhook_hmac_key is None
