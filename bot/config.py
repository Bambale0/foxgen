import logging
import os
from dataclasses import dataclass, field

from bot.env import load_project_env

logger = logging.getLogger(__name__)

load_project_env()


@dataclass
class Config:
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # T-Bank (legacy)
    TBANK_TERMINAL_KEY: str = os.getenv("TBANK_TERMINAL_KEY", "")
    TBANK_SECRET_KEY: str = os.getenv("TBANK_SECRET_KEY", "")
    TBANK_API_URL: str = os.getenv("TBANK_API_URL", "https://securepay.tinkoff.ru/v2/")
    TBANK_SUCCESS_URL: str = os.getenv("TBANK_SUCCESS_URL", "")

    # FreeKassa
    FREEKASSA_MERCHANT_ID: str = os.getenv("FREEKASSA_MERCHANT_ID", "")
    FREEKASSA_SECRET_WORD: str = os.getenv("FREEKASSA_SECRET_WORD", "")
    FREEKASSA_SECRET_WORD_2: str = os.getenv("FREEKASSA_SECRET_WORD_2", "")
    FREEKASSA_API_KEY: str = os.getenv("FREEKASSA_API_KEY", "")
    FREEKASSA_CURRENCY: str = os.getenv("FREEKASSA_CURRENCY", "RUB").upper()
    FREEKASSA_RETURN_URL: str = os.getenv("FREEKASSA_RETURN_URL", "")
    FREEKASSA_FAILURE_URL: str = os.getenv("FREEKASSA_FAILURE_URL", "")
    FREEKASSA_WEBHOOK_PATH: str = os.getenv(
        "FREEKASSA_WEBHOOK_PATH", "/freekassa/webhook"
    )
    PAYMENT_PROVIDER: str = os.getenv("PAYMENT_PROVIDER", "lava").lower()

    # Telegram Stars
    TELEGRAM_STARS_ENABLED: bool = os.getenv("TELEGRAM_STARS_ENABLED", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    TELEGRAM_STARS_PER_RUB: float = float(os.getenv("TELEGRAM_STARS_PER_RUB", "1"))
    TELEGRAM_STARS_FLAT_FEE: int = int(os.getenv("TELEGRAM_STARS_FLAT_FEE", "0"))

    # CryptoBot / Crypto Pay
    CRYPTOBOT_API_TOKEN: str = os.getenv("CRYPTOBOT_API_TOKEN", "")
    CRYPTOBOT_USE_TESTNET: bool = os.getenv("CRYPTOBOT_USE_TESTNET", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    CRYPTOBOT_WEBHOOK_PATH: str = os.getenv(
        "CRYPTOBOT_WEBHOOK_PATH", "/cryptobot/webhook"
    )
    CRYPTOBOT_PENDING_TTL_DAYS: int = int(
        os.getenv("CRYPTOBOT_PENDING_TTL_DAYS", "7")
    )

    # Lava.top payments
    LAVA_API_KEY: str = os.getenv("LAVA_API_KEY", "")
    LAVA_API_BASE_URL: str = os.getenv("LAVA_API_BASE_URL", "https://gate.lava.top")
    LAVA_WEBHOOK_PATH: str = os.getenv("LAVA_WEBHOOK_PATH", "/lava/webhook")
    LAVA_DEFAULT_EMAIL: str = os.getenv("LAVA_DEFAULT_EMAIL", "buyer@example.com")
    LAVA_OFFER_ID_MINI: str = os.getenv("LAVA_OFFER_ID_MINI", "")
    LAVA_OFFER_ID_START: str = os.getenv("LAVA_OFFER_ID_START", "")
    LAVA_OFFER_ID_OPTIMAL: str = os.getenv("LAVA_OFFER_ID_OPTIMAL", "")
    LAVA_OFFER_ID_PRO: str = os.getenv("LAVA_OFFER_ID_PRO", "")
    LAVA_OFFER_ID_STUDIO: str = os.getenv("LAVA_OFFER_ID_STUDIO", "")
    LAVA_OFFER_ID_BUSINESS: str = os.getenv("LAVA_OFFER_ID_BUSINESS", "")
    LAVA_WEBHOOK_SECRET: str = os.getenv("LAVA_WEBHOOK_SECRET", "")
    LAVA_PENDING_TTL_HOURS: int = int(os.getenv("LAVA_PENDING_TTL_HOURS", "24"))

    # AI Services API Keys
    NANOBANANA_API_KEY: str = os.getenv("NANOBANANA_API_KEY", "")
    FREEPIK_API_KEY: str = os.getenv("FREEPIK_API_KEY", "")
    NOVITA_API_KEY: str = os.getenv("NOVITA_API_KEY", "")
    REPLICATE_API_TOKEN: str = os.getenv("REPLICATE_API_TOKEN", "")
    REPLICATE_WEBHOOK_SECRET: str = os.getenv("REPLICATE_WEBHOOK_SECRET", "")
    KIE_AI_API_KEY: str = os.getenv("KIE_AI_API_KEY", "")
    KIE_AI_WEBHOOK_PATH: str = os.getenv("KIE_AI_WEBHOOK_PATH", "/webhook/kie_ai")
    KIE_AI_WEBHOOK_SECRET: str = os.getenv("KIE_AI_WEBHOOK_SECRET", "")
    HEALTH_CHECK_SECRET: str = os.getenv("HEALTH_CHECK_SECRET", "")
    INTERNAL_API_SECRET: str = os.getenv("INTERNAL_API_SECRET", "")
    KIE_WEBHOOK_HMAC_KEY: str = os.getenv("KIE_WEBHOOK_HMAC_KEY", "")
    KIE_MARKET_WEBHOOK_PATH: str = os.getenv("KIE_MARKET_WEBHOOK_PATH", "/webhooks/kie")

    # Nano Banana 2 fallback provider - Gemini-compatible (optional)
    NANOBANANA2_FALLBACK_API_KEY: str = os.getenv("NANOBANANA2_FALLBACK_API_KEY", "")
    NANOBANANA2_FALLBACK_BASE_URL: str = os.getenv(
        "NANOBANANA2_FALLBACK_BASE_URL", ""
    )
    NANOBANANA2_APIYI_MODEL: str = os.getenv("NANOBANANA2_APIYI_MODEL", "")

    # Nano Banana Pro fallback provider - Gemini-compatible (optional)
    NANO_BANANA_PRO_FALLBACK_API_KEY: str = os.getenv(
        "NANO_BANANA_PRO_FALLBACK_API_KEY", ""
    )
    NANO_BANANA_PRO_FALLBACK_BASE_URL: str = os.getenv(
        "NANO_BANANA_PRO_FALLBACK_BASE_URL", ""
    )

    # Legacy API Keys (optional fallbacks)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    PHOTO_PROMPT_MODEL: str = os.getenv("PHOTO_PROMPT_MODEL", "gpt-5-5")

    # APIYI Vision — analysis photo in prompt (like VK bot)
    APIYI_VISION_MODEL: str = os.getenv("APIYI_VISION_MODEL", "gpt-5.5")
    APIYI_VISION_FALLBACK_MODELS: list[str] = field(default_factory=list)
    APIYI_BASE_URL: str = os.getenv(
        "APIYI_BASE_URL", "https://api.apiyi.com/v1"
    ).rstrip("/")

    PHOTO_PROMPT_MAX_AUDIO_BYTES: int = int(
        os.getenv("PHOTO_PROMPT_MAX_AUDIO_BYTES", str(10 * 1024 * 1024))
    )
    VIDEO_PROMPT_MAX_VIDEO_BYTES: int = int(
        os.getenv("VIDEO_PROMPT_MAX_VIDEO_BYTES", str(30 * 1024 * 1024))
    )
    VIDEO_PROMPT_MAX_DURATION_SECONDS: int = int(
        os.getenv("VIDEO_PROMPT_MAX_DURATION_SECONDS", "60")
    )
    KLING_API_KEY: str = os.getenv("KLING_API_KEY", "")
    PIAPI_API_KEY: str = os.getenv("PIAPI_API_KEY", "") or os.getenv(
        "KLING_API_KEY", ""
    )

    # NSFW Content Control
    ALLOW_NSFW: bool = os.getenv("ALLOW_NSFW", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # API Endpoints
    NANOBANANA_BASE_URL: str = "https://api.nanobanana.com/v1"
    FREEPIK_BASE_URL: str = "https://api.freepik.com/v1"
    KLING_BASE_URL: str = "https://api.freepik.com/v1"  # Legacy alias
    PIAPI_BASE_URL: str = "https://api.piapi.ai"
    NOVITA_BASE_URL: str = "https://api.novita.ai"
    KIE_BASE_URL: str = "https://api.kie.ai"

    # Webhooks
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8443"))
    WEBHOOK_BIND_HOST: str = os.getenv("WEBHOOK_BIND_HOST", "127.0.0.1")
    STATIC_BASE_URL: str = os.getenv("STATIC_BASE_URL", "")
    PERSIST_PROVIDER_RESULTS: bool = os.getenv("PERSIST_PROVIDER_RESULTS", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    MINI_APP_PATH: str = os.getenv("MINI_APP_PATH", "/mini-app")
    MINI_APP_URL: str = os.getenv("MINI_APP_URL", "")

    # Database / Redis
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///bot.db")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    REDIS_PREFIX: str = os.getenv("REDIS_PREFIX", "banano_kling")

    # Cloudflare R2 Storage (S3-compatible)
    R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
    R2_API_TOKEN: str = os.getenv("R2_API_TOKEN", "")
    R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    R2_ENDPOINT: str = os.getenv("R2_ENDPOINT", "")
    R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "")

    # Partner programme
    PARTNER_OFFER_URL: str = os.getenv("PARTNER_OFFER_URL", "")
    PARTNER_RULES_URL: str = os.getenv("PARTNER_RULES_URL", "")
    PARTNER_MIN_WITHDRAWAL_RUB: int = int(
        os.getenv("PARTNER_MIN_WITHDRAWAL_RUB", "1000")
    )

    PRESETS_PATH: str = "data/presets.json"
    PRICE_PATH: str = "data/price.json"
    ADMIN_IDS_STR: str = os.getenv("ADMIN_IDS", "")

    @property
    def admin_ids(self) -> list[int]:
        if not self.ADMIN_IDS_STR:
            return []
        try:
            return [
                int(item.strip())
                for item in self.ADMIN_IDS_STR.split(",")
                if item.strip()
            ]
        except ValueError:
            logger.warning("Invalid ADMIN_IDS format: %s", self.ADMIN_IDS_STR)
            return []

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_ids

    @property
    def redis_url(self) -> str:
        return (self.REDIS_URL or "redis://127.0.0.1:6379/0").strip()

    @property
    def webhook_url(self) -> str:
        host = (self.WEBHOOK_HOST or "").rstrip("/")
        path = self.WEBHOOK_PATH or "/webhook"
        if not path.startswith("/"):
            path = "/" + path
        return f"{host}{path}"

    @property
    def tbank_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/tbank/webhook"

    @property
    def freekassa_notification_url(self) -> str:
        path = self.FREEKASSA_WEBHOOK_PATH or "/freekassa/webhook"
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.WEBHOOK_HOST.rstrip('/')}{path}"

    @property
    def YOOKASSA_RETURN_URL(self) -> str:  # transitional API name
        return self.FREEKASSA_RETURN_URL

    @property
    def yookassa_notification_url(self) -> str:
        return self.freekassa_notification_url

    @property
    def payment_provider(self) -> str:
        if self.PAYMENT_PROVIDER in {
            "cryptobot",
            "lava",
            "freekassa",
            "tbank",
            "telegram_stars",
        }:
            return self.PAYMENT_PROVIDER
        return "lava" if self.LAVA_API_KEY else "cryptobot"

    @property
    def cryptobot_notification_url(self) -> str:
        path = self.CRYPTOBOT_WEBHOOK_PATH
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.WEBHOOK_HOST.rstrip('/')}{path}"

    @property
    def lava_notification_url(self) -> str:
        path = self.LAVA_WEBHOOK_PATH
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.WEBHOOK_HOST.rstrip('/')}{path}"

    def lava_offer_id_for_package(self, package_id: str) -> str:
        mapping = {
            "mini": self.LAVA_OFFER_ID_MINI,
            "start": self.LAVA_OFFER_ID_START,
            "optimal": self.LAVA_OFFER_ID_OPTIMAL,
            "pro": self.LAVA_OFFER_ID_PRO,
            "studio": self.LAVA_OFFER_ID_STUDIO,
            "business": self.LAVA_OFFER_ID_BUSINESS,
        }
        return mapping.get(package_id, "")

    @property
    def has_freekassa(self) -> bool:
        return bool(
            self.FREEKASSA_MERCHANT_ID
            and self.FREEKASSA_SECRET_WORD
            and self.FREEKASSA_SECRET_WORD_2
        )

    @property
    def has_yookassa(self) -> bool:
        """Deprecated compatibility flag; reports FreeKassa availability."""
        return self.has_freekassa

    @property
    def kling_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/kling"

    @property
    def replicate_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/replicate"

    @property
    def z_image_turbo_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/z-image-turbo"

    @property
    def kie_notification_url(self) -> str:
        path = self.KIE_AI_WEBHOOK_PATH
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.WEBHOOK_HOST.rstrip('/')}{path}"
        if self.KIE_AI_WEBHOOK_SECRET:
            import urllib.parse

            url += f"?secret={urllib.parse.quote(self.KIE_AI_WEBHOOK_SECRET)}"
        return url

    @property
    def kie_market_notification_url(self) -> str:
        path = self.KIE_MARKET_WEBHOOK_PATH
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.WEBHOOK_HOST.rstrip('/')}{path}"

    @property
    def wanx_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/wanx"

    def _old_kling_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/kling"

    @property
    def static_base_url(self) -> str:
        if (self.STATIC_BASE_URL or "").strip():
            return self.STATIC_BASE_URL.strip().rstrip("/")
        if (self.WEBHOOK_HOST or "").strip():
            return self.WEBHOOK_HOST.strip().rstrip("/")
        return "https://dev.chillcreative.ru"

    @property
    def mini_app_url(self) -> str:
        if self.MINI_APP_URL:
            return self.MINI_APP_URL
        base = (self.WEBHOOK_HOST or self.static_base_url).rstrip("/")
        path = self.MINI_APP_PATH or "/mini-app"
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base}{path.rstrip('/')}/"


config = Config()
