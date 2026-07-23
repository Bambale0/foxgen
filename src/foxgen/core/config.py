from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FOXGEN_",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8080, ge=1, le=65535)

    telegram_bot_token: SecretStr | None = None
    database_url: str = "postgresql+asyncpg://foxgen:foxgen@localhost:5432/foxgen"
    redis_url: str = "redis://localhost:6379/0"

    kie_api_key: SecretStr | None = None
    kie_base_url: AnyHttpUrl = AnyHttpUrl("https://api.kie.ai")
    kie_callback_base_url: AnyHttpUrl | None = None
    kie_webhook_hmac_key: SecretStr | None = None
    webhook_max_age_seconds: int = Field(default=300, ge=30, le=3600)

    # Paid task creation is disabled unless both the switch and an internal token are set.
    task_submission_enabled: bool = False
    internal_api_token: SecretStr | None = None
    submission_user_rate_limit_per_minute: int = Field(default=10, ge=1, le=10_000)
    submission_global_rate_limit_per_minute: int = Field(default=100, ge=1, le=100_000)
    submission_user_concurrency_limit: int = Field(default=2, ge=1, le=100)
    submission_global_concurrency_limit: int = Field(default=20, ge=1, le=10_000)

    worker_loop_interval_seconds: float = Field(default=1.0, ge=0.1, le=60)
    worker_outbox_batch_size: int = Field(default=10, ge=1, le=500)
    worker_outbox_lease_seconds: int = Field(default=120, ge=30, le=3600)
    worker_outbox_max_attempts: int = Field(default=8, ge=1, le=100)
    provider_poll_interval_seconds: int = Field(default=20, ge=5, le=3600)
    stale_submitting_seconds: int = Field(default=600, ge=60, le=86_400)

    media_download_timeout_seconds: float = Field(default=60.0, ge=5, le=600)
    media_max_bytes: int = Field(default=536_870_912, ge=1_048_576, le=2_147_483_648)
    media_presigned_url_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)

    s3_endpoint_url: AnyHttpUrl | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "foxgen-media"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_force_path_style: bool = True

    @property
    def kie_callback_url(self) -> str | None:
        if self.kie_callback_base_url is None:
            return None
        return f"{str(self.kie_callback_base_url).rstrip('/')}/webhooks/kie"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
