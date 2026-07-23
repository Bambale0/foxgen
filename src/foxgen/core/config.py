from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FOXGEN_",
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

    @property
    def kie_callback_url(self) -> str | None:
        if self.kie_callback_base_url is None:
            return None
        return f"{str(self.kie_callback_base_url).rstrip('/')}/webhooks/kie"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
