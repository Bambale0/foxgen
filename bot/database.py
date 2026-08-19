import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, List, Optional
from urllib.parse import urlparse

from bot import db as db_backend

logger = logging.getLogger(__name__)
_LOGGED_REFERRAL_CYCLES: set[tuple[int, int, int]] = set()

DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
MASTER_PARTNER_TELEGRAM_ID = int(os.getenv("MASTER_PARTNER_TELEGRAM_ID", "339795159"))
SAVED_REFERENCES_MAX_PER_KIND = int(os.getenv("SAVED_REFERENCES_MAX_PER_KIND", "3"))
REFERRAL_ANTIFRAUD_MAX_PER_HOUR = int(os.getenv("REFERRAL_ANTIFRAUD_MAX_PER_HOUR", "30"))
REFERRAL_ANTIFRAUD_MAX_PER_DAY = int(os.getenv("REFERRAL_ANTIFRAUD_MAX_PER_DAY", "120"))
REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS = int(
    os.getenv("REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS", "10")
)
REFERRAL_ANTIFRAUD_BURST_MAX = int(
    os.getenv("REFERRAL_ANTIFRAUD_BURST_MAX", "6")
)
REFERRAL_ANTIFRAUD_BLOCK_CODES = {
    code.strip().upper()
    for code in os.getenv("REFERRAL_ANTIFRAUD_BLOCK_CODES", "").split(",")
    if code.strip()
}
REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS = {
    int(value.strip())
    for value in os.getenv("REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS", "").split(",")
    if value.strip().isdigit()
}
MAX_ACTIVE_PROMPTS_PER_USER = 5
TOP_PROMPTS_LIMIT = 10
FEED_PUBLIC_IMAGE_MAX_ITEMS = 999999
FEED_PUBLIC_VIDEO_MAX_ITEMS = 999999
FEED_PUBLIC_RECENT_GRACE_HOURS = 168
FEED_PUBLIC_CLEANUP_INTERVAL_SECONDS = 999999999
FEED_EPHEMERAL_RESULT_TTL_HOURS = int(os.getenv("FEED_EPHEMERAL_RESULT_TTL_HOURS", "72"))
FEED_EPHEMERAL_RESULT_HOSTS = {
    host.strip().lower().lstrip(".")
    for host in os.getenv("FEED_EPHEMERAL_RESULT_HOSTS", "tempfile.aiquickdraw.com").split(",")
    if host.strip()
}
FEED_PUBLIC_TYPES = {"image", "video"}
_last_public_feed_cleanup_at = 0.0
_last_public_feed_cleanup_db_path: str | None = None
_public_feed_cleanup_lock: asyncio.Lock | None = None


def _get_public_feed_cleanup_lock() -> asyncio.Lock:
    global _public_feed_cleanup_lock
    if _public_feed_cleanup_lock is None:
        _public_feed_cleanup_lock = asyncio.Lock()
    return _public_feed_cleanup_lock


def _public_feed_cleanup_due() -> bool:
    if _last_public_feed_cleanup_db_path != DATABASE_PATH:
        return True
    return (time.monotonic() - _last_public_feed_cleanup_at) >= FEED_PUBLIC_CLEANUP_INTERVAL_SECONDS


def _mark_public_feed_cleanup_done() -> None:
    global _last_public_feed_cleanup_at, _last_public_feed_cleanup_db_path
    _last_public_feed_cleanup_at = time.monotonic()
    _last_public_feed_cleanup_db_path = DATABASE_PATH

PROMPT_CATEGORIES = {"art", "business", "marketing", "photo", "video", "other"}
PROMPT_STATUSES = {"pending", "approved", "rejected", "deactivated"}

# Партнёрская программа — единственный источник констант
PARTNER_LEVEL1_PERCENT: int = 30   # % с покупок рефералов 1-го уровня
PARTNER_LEVEL2_PERCENT: int = 7    # % с покупок рефералов 2-го уровня
PARTNER_NEW_USER_BONUS: int = 5    # бананы новому пользователю при регистрации
PARTNER_INVITER_BONUS: int = 3     # бананы пригласившему за каждую регистрацию
PROMPT_REPEAT_REWARD_RUB: float = float(os.getenv("PROMPT_REPEAT_REWARD_RUB", "10"))
PROMO_BONUS_BY_CREDITS: dict[int, int] = {
    25: 5,
    50: 10,
    100: 15,
    200: 20,
    500: 50,
}


class Credits(float):
    """Float subclass that displays without trailing .0"""

    def __str__(self):
        if self == int(self):
            return str(int(self))
        return f"{self:.1f}"

    def __format__(self, spec):
        if not spec:
            return self.__str__()
        return float.__format__(self, spec)


@dataclass
class User:
    id: int
    telegram_id: int
    credits: float
    created_at: datetime
    updated_at: datetime
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    referral_code: Optional[str] = None
    referred_by: Optional[int] = None
    referral_earned: int = 0
    has_paid: bool = False
    partner_agreed_at: Optional[datetime] = None
    partner_total_revenue_rub: float = 0.0
    partner_balance_rub: float = 0.0
    partner_withdrawn_rub: float = 0.0
    prompt_repeat_balance_rub: float = 0.0
    prompt_repeat_total_rub: float = 0.0
    partner_tier: str = "basic"
    channel_url: Optional[str] = None
    photo_url: Optional[str] = None


@dataclass
class Transaction:
    id: int
    order_id: str
    user_id: int
    payment_id: str
    provider: str
    credits: int
    amount_rub: float
    status: str
    created_at: datetime
    promo_code_id: Optional[int] = None
    promo_code: Optional[str] = None
    promo_bonus_credits: int = 0


@dataclass
class PromoCode:
    id: int
    code: str
    partner_name: Optional[str]
    partner_telegram_id: Optional[int]
    partner_user_id: Optional[int]
    is_active: bool
    usage_count: int
    total_bonus_credits: int
    total_amount_rub: float
    created_by_telegram_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime] = None


@dataclass
class SavedReference:
    id: int
    user_id: int
    kind: str
    file_url: str
    file_hash: str
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


@dataclass
class UserPrompt:
    id: int
    author_id: int
    title: str
    description: str
    category: str
    prompt_text: str
    preview_url: Optional[str] = None
    model: Optional[str] = None
    tags: Optional[list[str]] = None
    generation_settings: dict[str, Any] | None = None
    likes: int = 0
    uses_count: int = 0
    is_public: bool = True
    status: str = "pending"
    reject_reason: Optional[str] = None
    ai_moderation_decision: Optional[str] = None
    ai_moderation_risk: Optional[str] = None
    ai_moderation_reason: Optional[str] = None
    ai_moderation_recommendation: Optional[str] = None
    ai_moderation_raw: Optional[str] = None
    ai_moderated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


def _parse_json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_json_dict(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_optional_value(
    row: db_backend.Row,
    key: str,
    default: Any = None,
) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def normalize_promo_code(value: str | None) -> str:
    code = re.sub(r"\s+", "", str(value or "").strip().upper())
    return re.sub(r"[^0-9A-ZА-ЯЁ_-]+", "", code)[:32]


def get_promo_bonus_for_credits(credits: float | int | str) -> int:
    try:
        amount = int(round(float(credits)))
    except (TypeError, ValueError):
        return 0
    return int(PROMO_BONUS_BY_CREDITS.get(amount, 0))


def _row_to_promo_code(row: db_backend.Row | None) -> Optional[PromoCode]:
    if not row:
        return None
    return PromoCode(
        id=int(row["id"]),
        code=row["code"],
        partner_name=row["partner_name"],
        partner_telegram_id=(
            int(row["partner_telegram_id"]) if row["partner_telegram_id"] else None
        ),
        partner_user_id=int(row["partner_user_id"]) if row["partner_user_id"] else None,
        is_active=bool(row["is_active"]),
        usage_count=int(row["usage_count"] or 0),
        total_bonus_credits=int(row["total_bonus_credits"] or 0),
        total_amount_rub=float(row["total_amount_rub"] or 0),
        created_by_telegram_id=(
            int(row["created_by_telegram_id"])
            if row["created_by_telegram_id"]
            else None
        ),
        created_at=_parse_datetime(row["created_at"]) or datetime.utcnow(),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _row_to_user_prompt(row: db_backend.Row | None) -> Optional[UserPrompt]:
    if not row:
        return None

    ai_moderated_at = None
    if row["ai_moderated_at"]:
        try:
            ai_moderated_at = datetime.fromisoformat(row["ai_moderated_at"])
        except (TypeError, ValueError):
            ai_moderated_at = None

    created_at = None
    if row["created_at"]:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            created_at = None

    return UserPrompt(
        id=row["id"],
        author_id=row["author_id"],
        title=row["title"],
        description=row["description"] or "",
        category=row["category"] or "other",
        prompt_text=row["prompt_text"],
        preview_url=row["preview_url"],
        model=row["model"],
        tags=[str(tag) for tag in _parse_json_list(row["tags"])],
        generation_settings=_parse_json_dict(
            _row_optional_value(row, "generation_settings")
        ),
        likes=int(row["likes"] or 0),
        uses_count=int(row["uses_count"] or 0),
        is_public=bool(row["is_public"]),
        status=row["status"] or "pending",
        reject_reason=row["reject_reason"],
        ai_moderation_decision=row["ai_moderation_decision"],
        ai_moderation_risk=row["ai_moderation_risk"],
        ai_moderation_reason=row["ai_moderation_reason"],
        ai_moderation_recommendation=row["ai_moderation_recommendation"],
        ai_moderation_raw=row["ai_moderation_raw"],
        ai_moderated_at=ai_moderated_at,
        created_at=created_at,
    )


def _prompt_to_dict(prompt: UserPrompt | None) -> Optional[dict[str, Any]]:
    if prompt is None:
        return None
    return {
        "id": prompt.id,
        "author_id": prompt.author_id,
        "title": prompt.title,
        "description": prompt.description,
        "category": prompt.category,
        "prompt_text": prompt.prompt_text,
        "preview_url": prompt.preview_url,
        "model": prompt.model,
        "tags": prompt.tags or [],
        "generation_settings": prompt.generation_settings or {},
        "likes": prompt.likes,
        "uses_count": prompt.uses_count,
        "is_public": prompt.is_public,
        "status": prompt.status,
        "reject_reason": prompt.reject_reason,
        "ai_moderation_decision": prompt.ai_moderation_decision,
        "ai_moderation_risk": prompt.ai_moderation_risk,
        "ai_moderation_reason": prompt.ai_moderation_reason,
        "ai_moderation_recommendation": prompt.ai_moderation_recommendation,
        "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
    }


def _prompt_admin_dict(row: db_backend.Row | None) -> Optional[dict[str, Any]]:
    prompt = _prompt_to_dict(_row_to_user_prompt(row))
    if not prompt or row is None:
        return prompt

    prompt.update(
        {
            "author_telegram_id": (
                int(row["author_telegram_id"])
                if "author_telegram_id" in row.keys() and row["author_telegram_id"]
                else None
            ),
            "author_username": (
                row["author_username"] if "author_username" in row.keys() else None
            ),
            "author_first_name": (
                row["author_first_name"] if "author_first_name" in row.keys() else None
            ),
            "author_last_name": (
                row["author_last_name"] if "author_last_name" in row.keys() else None
            ),
            "author_referral_code": (
                row["author_referral_code"]
                if "author_referral_code" in row.keys()
                else None
            ),
        }
    )
    return prompt


def normalize_prompt_tags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        value = re.sub(r"[^a-z0-9а-яё_-]+", "-", str(tag).strip().lower()).strip("-_")
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value[:32])
        if len(normalized) >= 12:
            break
    return normalized


def infer_tags(prompt_text: str) -> list[str]:
    text = f" {str(prompt_text or '').lower()} "
    rules = {
        "cinematic": ("cinematic", "movie", "film", "lens", "camera", "кино"),
        "realism": ("photo", "realistic", "photorealistic", "realism", "реалист"),
        "portrait": ("portrait", "face", "person", "character", "портрет", "лицо"),
        "product": ("product", "packshot", "ecommerce", "brand", "товар", "упаков"),
        "fashion": ("fashion", "clothes", "dress", "editorial", "мода", "одежд"),
        "marketing": ("ad ", "advert", "banner", "campaign", "реклама", "баннер"),
        "cyberpunk": ("cyberpunk", "neon", "futuristic", "киберпанк", "неон"),
        "anime": ("anime", "manga", "аниме", "манга"),
        "music": ("music", "album", "cover art", "музык", "обложк"),
        "business": ("business", "office", "startup", "presentation", "бизнес"),
    }
    tags = [
        tag
        for tag, keywords in rules.items()
        if any(keyword in text for keyword in keywords)
    ]
    return normalize_prompt_tags(tags or ["best"])


def infer_category(prompt_text: str, tags: list[str] | None = None) -> str:
    text = str(prompt_text or "").lower()
    tag_set = set(tags or [])
    if "trend-video" in tag_set or "video" in tag_set:
        return "video"
    if {"product", "marketing"} & tag_set or any(
        word in text for word in ("advert", "banner", "реклама", "бренд", "campaign")
    ):
        return "marketing"
    if "business" in tag_set or any(
        word in text for word in ("business", "office", "startup", "presentation", "бизнес")
    ):
        return "business"
    if {"realism", "portrait", "fashion"} & tag_set or any(
        word in text for word in ("photo", "portrait", "camera", "фото", "портрет")
    ):
        return "photo"
    if any(word in text for word in ("art", "illustration", "anime", "арт", "иллюстрац")):
        return "art"
    return "other"


def derive_title(prompt_text: str) -> str:
    text = " ".join(str(prompt_text or "").split())
    if not text:
        return "Новый промпт"
    title = re.split(r"[.!?\n]", text, maxsplit=1)[0].strip()
    return (title[:57] + "...") if len(title) > 60 else title


def derive_description(prompt_text: str) -> str:
    text = " ".join(str(prompt_text or "").split())
    if not text:
        return "Готовая идея для генерации."
    return (text[:197] + "...") if len(text) > 200 else text


async def _ensure_prompt_feed_schema(db: db_backend.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'other',
            prompt_text TEXT NOT NULL,
            preview_url TEXT,
            model TEXT,
            tags TEXT DEFAULT '[]',
            generation_settings TEXT DEFAULT '{}',
            likes INTEGER DEFAULT 0,
            uses_count INTEGER DEFAULT 0,
            is_public BOOLEAN DEFAULT 1,
            status TEXT DEFAULT 'pending',
            reject_reason TEXT,
            ai_moderation_decision TEXT,
            ai_moderation_risk TEXT,
            ai_moderation_reason TEXT,
            ai_moderation_recommendation TEXT,
            ai_moderation_raw TEXT,
            ai_moderated_at TIMESTAMP,
            source_generation_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (author_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    try:
        await db.execute("ALTER TABLE user_prompts ADD COLUMN source_generation_id INTEGER")
    except db_backend.OperationalError:
        pass
    try:
        await db.execute(
            "ALTER TABLE user_prompts ADD COLUMN generation_settings TEXT DEFAULT '{}'"
        )
    except db_backend.OperationalError:
        pass
    await db.execute("""
        CREATE TABLE IF NOT EXISTS prompt_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            prompt_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (prompt_id) REFERENCES user_prompts (id) ON DELETE CASCADE,
            UNIQUE(user_id, prompt_id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS feed_generation_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            generation_task_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (generation_task_id) REFERENCES generation_tasks (id) ON DELETE CASCADE,
            UNIQUE(user_id, generation_task_id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS feed_remix_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_generation_task_id INTEGER NOT NULL,
            remix_generation_task_id INTEGER NOT NULL,
            source_author_id INTEGER NOT NULL,
            remix_author_id INTEGER NOT NULL,
            credits_spent REAL DEFAULT 0,
            royalty_credits REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_generation_task_id, remix_generation_task_id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS prompt_repeat_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL,
            repeater_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            repeat_task_id TEXT,
            credits_spent REAL DEFAULT 0,
            amount_rub REAL NOT NULL DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (author_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (repeater_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    for _column_name, statement in [
        ("result_urls", "ALTER TABLE generation_tasks ADD COLUMN result_urls TEXT"),
        ("is_public_feed", "ALTER TABLE generation_tasks ADD COLUMN is_public_feed BOOLEAN DEFAULT 0"),
        ("is_profile_visible", "ALTER TABLE generation_tasks ADD COLUMN is_profile_visible BOOLEAN DEFAULT 0"),
        ("is_adult_content", "ALTER TABLE generation_tasks ADD COLUMN is_adult_content BOOLEAN DEFAULT 0"),
        ("is_prompt_library", "ALTER TABLE generation_tasks ADD COLUMN is_prompt_library BOOLEAN DEFAULT 0"),
        ("source_feed_gen_id", "ALTER TABLE generation_tasks ADD COLUMN source_feed_gen_id INTEGER"),
        ("parent_generation_id", "ALTER TABLE generation_tasks ADD COLUMN parent_generation_id INTEGER"),
        ("action_type", "ALTER TABLE generation_tasks ADD COLUMN action_type TEXT"),
        ("likes_count", "ALTER TABLE generation_tasks ADD COLUMN likes_count INTEGER DEFAULT 0"),
        ("shares_count", "ALTER TABLE generation_tasks ADD COLUMN shares_count INTEGER DEFAULT 0"),
        ("feed_prompt_visible", "ALTER TABLE generation_tasks ADD COLUMN feed_prompt_visible BOOLEAN DEFAULT 0"),
        ("feed_references_visible", "ALTER TABLE generation_tasks ADD COLUMN feed_references_visible BOOLEAN DEFAULT 0"),
        ("feed_blurred", "ALTER TABLE generation_tasks ADD COLUMN feed_blurred BOOLEAN DEFAULT 0"),
        ("feed_published_at", "ALTER TABLE generation_tasks ADD COLUMN feed_published_at TIMESTAMP"),
    ]:
        try:
            await db.execute(statement)
        except db_backend.OperationalError:
            pass

    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_user_created ON generation_tasks(user_id, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed ON generation_tasks(is_public_feed, status, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed_safe ON generation_tasks(is_public_feed, is_adult_content, status, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_profile ON generation_tasks(user_id, is_profile_visible, status, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed_published ON generation_tasks(is_public_feed, status, feed_published_at DESC, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_source_feed ON generation_tasks(source_feed_gen_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_parent_status ON generation_tasks(parent_generation_id, status)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_prompts_status ON user_prompts(status, is_public, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_prompts_author_status ON user_prompts(author_id, status)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_prompts_source_generation ON user_prompts(source_generation_id)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_prompt_repeat_events_author ON prompt_repeat_events(author_id, created_at DESC)"
    )


async def _ensure_saved_references_schema(db: db_backend.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS saved_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            file_url TEXT NOT NULL,
            file_hash TEXT,
            original_filename TEXT,
            content_type TEXT,
            source TEXT DEFAULT 'telegram',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    cursor = await db.execute("PRAGMA table_info(saved_references)")
    columns = {row[1] for row in await cursor.fetchall()}

    column_migrations = [
        ("file_hash", "ALTER TABLE saved_references ADD COLUMN file_hash TEXT"),
        ("original_filename", "ALTER TABLE saved_references ADD COLUMN original_filename TEXT"),
        ("content_type", "ALTER TABLE saved_references ADD COLUMN content_type TEXT"),
        ("source", "ALTER TABLE saved_references ADD COLUMN source TEXT DEFAULT 'telegram'"),
        ("updated_at", "ALTER TABLE saved_references ADD COLUMN updated_at TIMESTAMP"),
        ("last_used_at", "ALTER TABLE saved_references ADD COLUMN last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]
    for column_name, statement in column_migrations:
        if column_name not in columns:
            try:
                await db.execute(statement)
            except db_backend.OperationalError:
                pass

    await db.execute(
        "UPDATE saved_references SET file_hash = COALESCE(file_hash, file_url) WHERE file_hash IS NULL OR TRIM(file_hash) = ''"
    )
    await db.execute(
        "UPDATE saved_references SET source = COALESCE(NULLIF(source, ''), 'telegram')"
    )
    await db.execute(
        "UPDATE saved_references SET last_used_at = COALESCE(last_used_at, created_at, CURRENT_TIMESTAMP) WHERE last_used_at IS NULL"
    )
    await db.execute(
        "UPDATE saved_references SET updated_at = COALESCE(updated_at, last_used_at, created_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_saved_references_user_kind_last_used ON saved_references(user_id, kind, last_used_at DESC, created_at DESC)"
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_references_user_kind_hash ON saved_references(user_id, kind, file_hash)"
    )


@dataclass
class GenerationTask:
    id: int
    user_id: int
    task_id: str
    type: str
    preset_id: str
    model: Optional[str] = None
    duration: Optional[int] = None
    aspect_ratio: Optional[str] = None
    prompt: Optional[str] = None
    cost: Optional[int] = None
    status: str = "pending"
    telegram_id: Optional[int] = None
    result_url: Optional[str] = None
    result_urls: Optional[List[str]] = None
    request_data: Optional[str] = None
    is_public_feed: bool = False
    is_prompt_library: bool = False
    source_feed_gen_id: Optional[int] = None
    parent_generation_id: Optional[int] = None
    action_type: Optional[str] = None
    likes_count: int = 0
    shares_count: int = 0
    feed_prompt_visible: bool = False
    feed_references_visible: bool = False
    feed_blurred: bool = False
    created_at: Optional[datetime] = None


async def init_db():
    """Инициализация базы данных"""
    async with db_backend.connect() as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                credits REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Referral system migrations for existing databases
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        except db_backend.OperationalError:
            pass
        for statement in (
            "ALTER TABLE users ADD COLUMN username TEXT",
            "ALTER TABLE users ADD COLUMN first_name TEXT",
            "ALTER TABLE users ADD COLUMN last_name TEXT",
            "ALTER TABLE users ADD COLUMN channel_url TEXT",
        ):
            try:
                await db.execute(statement)
            except db_backend.OperationalError:
                pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN referral_earned INTEGER DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN has_paid BOOLEAN DEFAULT 0")
        except db_backend.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN partner_agreed_at TIMESTAMP")
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN partner_total_revenue_rub REAL DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN partner_balance_rub REAL DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN partner_withdrawn_rub REAL DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN prompt_repeat_balance_rub REAL DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN prompt_repeat_total_rub REAL DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN partner_tier TEXT DEFAULT 'basic'"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN photo_url TEXT"
            )
        except db_backend.OperationalError:
            pass
        for statement in (
            "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN banned_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN banned_by_telegram_id INTEGER",
        ):
            try:
                await db.execute(statement)
            except db_backend.OperationalError:
                pass

        if db_backend.is_postgres():
            cursor = await db.execute(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'users'
                  AND column_name = 'credits'
                """
            )
            row = await cursor.fetchone()
            if row and str(row[0]).lower() in {"smallint", "integer", "bigint"}:
                await db.execute(
                    "ALTER TABLE users ALTER COLUMN credits "
                    "TYPE NUMERIC(12, 4) USING credits::numeric"
                )

        # Таблица транзакций
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                payment_id TEXT,
                provider TEXT DEFAULT 'cryptobot',
                credits INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                promo_code_id INTEGER,
                promo_code TEXT,
                promo_bonus_credits INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        for statement in (
            "ALTER TABLE transactions ADD COLUMN promo_code_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN promo_code TEXT",
            "ALTER TABLE transactions ADD COLUMN promo_bonus_credits INTEGER DEFAULT 0",
        ):
            try:
                await db.execute(statement)
            except db_backend.OperationalError:
                pass

        # Unique index на payment_id: защита от двойного начисления при повторных вебхуках
        # SQLite допускает NULL в уникальных индексах (NULL != NULL)
        try:
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_payment_provider "
                "ON transactions(payment_id, provider) WHERE payment_id IS NOT NULL"
            )
        except db_backend.OperationalError:
            try:
                # Fallback для SQLite без partial indexes
                await db.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_payment_provider "
                    "ON transactions(payment_id, provider)"
                )
            except db_backend.OperationalError:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                partner_name TEXT,
                partner_telegram_id INTEGER,
                partner_user_id INTEGER,
                is_active BOOLEAN DEFAULT 1,
                usage_count INTEGER DEFAULT 0,
                total_bonus_credits INTEGER DEFAULT 0,
                total_amount_rub REAL DEFAULT 0,
                created_by_telegram_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (partner_user_id) REFERENCES users (id)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_promo_codes_code
            ON promo_codes(code)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_code_id INTEGER NOT NULL,
                transaction_id INTEGER UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                bonus_credits INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promo_code_id) REFERENCES promo_codes (id),
                FOREIGN KEY (transaction_id) REFERENCES transactions (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_promo_redemptions_promo
            ON promo_redemptions(promo_code_id, created_at)
        """)

        # Таблица задач генерации
        await db.execute("""
            CREATE TABLE IF NOT EXISTS generation_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                telegram_id INTEGER,
                task_id TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                preset_id TEXT NOT NULL,
                model TEXT,
                duration INTEGER,
                aspect_ratio TEXT,
                prompt TEXT,
                cost INTEGER,
                request_data TEXT,
                status TEXT DEFAULT 'pending',
                result_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Migration: add columns if not exists
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN telegram_id INTEGER"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE generation_tasks ADD COLUMN model TEXT")
        except db_backend.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE generation_tasks ADD COLUMN duration INTEGER")
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN aspect_ratio TEXT"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE generation_tasks ADD COLUMN prompt TEXT")
        except db_backend.OperationalError:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE generation_tasks ADD COLUMN cost INTEGER")
        except db_backend.OperationalError:
            pass  # Column already exists
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN request_data TEXT"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE generation_tasks ADD COLUMN updated_at TIMESTAMP"
            )
            await db.execute(
                "UPDATE generation_tasks SET updated_at = COALESCE(completed_at, created_at, CURRENT_TIMESTAMP) WHERE updated_at IS NULL"
            )
        except db_backend.OperationalError:
            pass

        # Миграция: добавляем provider в transactions
        try:
            await db.execute(
                "ALTER TABLE transactions ADD COLUMN provider TEXT DEFAULT 'cryptobot'"
            )
        except db_backend.OperationalError:
            pass

        # Таблица истории генераций
        await db.execute("""
            CREATE TABLE IF NOT EXISTS generation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                preset_id TEXT NOT NULL,
                prompt TEXT,
                cost INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Таблица настроек пользователя
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                preferred_model TEXT DEFAULT 'flash',
                preferred_video_model TEXT DEFAULT 'v3_std',
                preferred_i2v_model TEXT DEFAULT 'v3_std',
                image_service TEXT DEFAULT 'nanobanana',
                referral_purchase_notifications_enabled BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_by_telegram_id INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Referral system tables and migrations
        # Add columns to users if not exist
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN referred_by INTEGER REFERENCES users(id)"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN referral_earned INTEGER DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN has_paid BOOLEAN DEFAULT FALSE"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN prompt_repeat_balance_rub REAL DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN prompt_repeat_total_rub REAL DEFAULT 0"
            )
        except db_backend.OperationalError:
            pass

        try:
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)"
            )
        except db_backend.OperationalError:
            pass

        # Referrals table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                bonus_credits INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users(id),
                FOREIGN KEY (referred_id) REFERENCES users(id),
                UNIQUE(referrer_id, referred_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS feed_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generation_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (generation_id) REFERENCES generation_tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feed_comments_generation_created ON feed_comments(generation_id, created_at DESC)"
        )

        # Backfill missing referral codes for existing users later in get_or_create_user

        # Миграция: добавляем колонку image_service если её нет
        try:
            await db.execute(
                "ALTER TABLE user_settings ADD COLUMN image_service TEXT DEFAULT 'nanobanana'"
            )
        except db_backend.OperationalError:
            pass  # Колонка уже существует
        try:
            await db.execute(
                "ALTER TABLE user_settings ADD COLUMN referral_purchase_notifications_enabled BOOLEAN DEFAULT 1"
            )
        except db_backend.OperationalError:
            pass  # Колонка уже существует

        await db.execute("""
            CREATE TABLE IF NOT EXISTS partner_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_rub REAL NOT NULL,
                method TEXT NOT NULL,
                requisites TEXT,
                status TEXT DEFAULT 'requested',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Таблица batch_jobs
        await db.execute("""
            CREATE TABLE IF NOT EXISTS batch_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                total_cost INTEGER NOT NULL,
                results_count INTEGER DEFAULT 0,
                duration REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        await _ensure_saved_references_schema(db)
        await _ensure_prompt_feed_schema(db)

        await db.commit()
        logger.info("Database initialized successfully")

        # Таблица уведомлений для мини‑аппа
        await db.execute("""
            CREATE TABLE IF NOT EXISTS miniapp_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """)
        await db.commit()

        # Referral service tables (referral_events, partner_commissions)
        from bot.services.referral_service import init_referral_tables_if_needed
        await init_referral_tables_if_needed()


async def get_or_create_user(
    telegram_id: int,
    referral_code: str | None = None,
) -> User:
    """Получает или создаёт пользователя (thread-safe).
    
    Если передан referral_code и пользователь создаётся впервые,
    привязка к рефереру происходит атомарно в одной транзакции.
    Если пользователь уже существует, но referred_by IS NULL и нет оплат,
    также пытается привязать (через process_referral).
    """
    code = (referral_code or "").strip().upper()
    referrer_id: int | None = None

    # Ищем реферрера заранее, чтобы не делать лишних запросов в транзакции
    if code:
        async with db_backend.connect(DATABASE_PATH) as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT id FROM users WHERE referral_code = ? AND telegram_id != ?",
                (code, telegram_id),
            )
            ref_row = await cursor.fetchone()
            if ref_row:
                referrer_id = ref_row["id"]

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        # Ищем пользователя
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        referred_by = None  # инициализация перед обеими ветками

        if row:
            referred_by = row["referred_by"] if "referred_by" in row.keys() else None
            referral_earned = (
                row["referral_earned"] if "referral_earned" in row.keys() else 0
            )
            has_paid = bool(row["has_paid"]) if "has_paid" in row.keys() else False

            # Привязка реферала для существующего пользователя делается
            # через единый process_referral_click в вызывающем коде (common.py).
            # Здесь НЕ дублируем антифрод-логику — она уже есть в referral_service.
            referral_code = (
                row["referral_code"] if "referral_code" in row.keys() else None
            )
            # referred_by уже обновлён выше (referrer_id), если привязка сработала
            referral_earned = (
                row["referral_earned"] if "referral_earned" in row.keys() else 0
            )
            has_paid = bool(row["has_paid"]) if "has_paid" in row.keys() else False
            partner_agreed_at = (
                datetime.fromisoformat(row["partner_agreed_at"])
                if row["partner_agreed_at"] and "partner_agreed_at" in row.keys()
                else None
            )
            return User(
                id=row["id"],
                telegram_id=row["telegram_id"],
                credits=Credits(row["credits"] or 0),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                username=row["username"] if "username" in row.keys() else None,
                first_name=row["first_name"] if "first_name" in row.keys() else None,
                last_name=row["last_name"] if "last_name" in row.keys() else None,
                referral_code=referral_code,
                referred_by=referred_by,
                referral_earned=referral_earned or 0,
                has_paid=has_paid,
                partner_agreed_at=partner_agreed_at,
                partner_total_revenue_rub=(
                    float(row["partner_total_revenue_rub"] or 0)
                    if "partner_total_revenue_rub" in row.keys()
                    else 0.0
                ),
                partner_balance_rub=(
                    float(row["partner_balance_rub"] or 0)
                    if "partner_balance_rub" in row.keys()
                    else 0.0
                ),
                partner_withdrawn_rub=(
                    float(row["partner_withdrawn_rub"] or 0)
                    if "partner_withdrawn_rub" in row.keys()
                    else 0.0
                ),
                prompt_repeat_balance_rub=(
                    float(row["prompt_repeat_balance_rub"] or 0)
                    if "prompt_repeat_balance_rub" in row.keys()
                    else 0.0
                ),
                prompt_repeat_total_rub=(
                    float(row["prompt_repeat_total_rub"] or 0)
                    if "prompt_repeat_total_rub" in row.keys()
                    else 0.0
                ),
                partner_tier=(
                    row["partner_tier"]
                    if "partner_tier" in row.keys() and row["partner_tier"]
                    else "basic"
                ),
                channel_url=(
                    row["channel_url"]
                    if "channel_url" in row.keys() and row["channel_url"]
                    else None
                ),
                photo_url=(
                    row["photo_url"]
                    if "photo_url" in row.keys() and row["photo_url"]
                    else None
                ),
            )

        # Создаём нового пользователя с бонусными кредитами
        # Используем INSERT OR IGNORE для защиты от race condition
        try:
            new_referral_code = await generate_referral_code(db)
            # АНТИФРОД: перед созданием с referrer_id проверяем все лимиты
            safe_referrer_id = referrer_id  # может быть обнулён ниже
            if safe_referrer_id:
                if code in REFERRAL_ANTIFRAUD_BLOCK_CODES or safe_referrer_id in REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS:
                    logger.warning(
                        "Referral blocked by antifraud blocklist (new user): telegram_id=%s code=%s referrer_id=%s",
                        telegram_id, code, safe_referrer_id,
                    )
                    safe_referrer_id = None
                else:
                    hourly_cursor = await db.execute(
                        "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', '-1 hour')",
                        (safe_referrer_id,),
                    )
                    hourly_count = int((await hourly_cursor.fetchone())["cnt"])
                    if hourly_count >= REFERRAL_ANTIFRAUD_MAX_PER_HOUR:
                        logger.warning(
                            "Referral blocked by antifraud hourly limit (new user): telegram_id=%s referrer_id=%s hourly=%s limit=%s",
                            telegram_id, safe_referrer_id, hourly_count, REFERRAL_ANTIFRAUD_MAX_PER_HOUR,
                        )
                        safe_referrer_id = None
                    else:
                        daily_cursor = await db.execute(
                            "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', '-1 day')",
                            (safe_referrer_id,),
                        )
                        daily_count = int((await daily_cursor.fetchone())["cnt"])
                        if daily_count >= REFERRAL_ANTIFRAUD_MAX_PER_DAY:
                            logger.warning(
                                "Referral blocked by antifraud daily limit (new user): telegram_id=%s referrer_id=%s daily=%s limit=%s",
                                telegram_id, safe_referrer_id, daily_count, REFERRAL_ANTIFRAUD_MAX_PER_DAY,
                            )
                            safe_referrer_id = None

            # ВСЕГДА создаём пользователя с referred_by=NULL.
            # Привязка реферала делается ОТДЕЛЬНО через единый process_referral_click
            # (из bot/services/referral_service.py) после получения user_id.
            # Это закрывает антифрод-дыру: раньше проверки обходились при INSERT.
            await db.execute(
                "INSERT INTO users (telegram_id, credits, referral_code, referred_by) VALUES (?, ?, ?, NULL)",
                (telegram_id, PARTNER_NEW_USER_BONUS, new_referral_code),
            )
            await db.commit()
            logger.info(
                "Created new user: telegram_id=%s (referral will be attached separately)",
                telegram_id,
            )
        except db_backend.IntegrityError:
            # Пользователь уже создан другим параллельным запросом
            logger.debug(f"User {telegram_id} already exists (race condition handled)")

        # Получаем пользователя (созданного нами или другим запросом)
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        if not row:
            logger.error(f"Failed to fetch newly created user {telegram_id}")
            raise ValueError(f"User {telegram_id} not found after creation")

        referral_code = row["referral_code"] if "referral_code" in row.keys() else None
        referred_by = row["referred_by"] if "referred_by" in row.keys() else None
        referral_earned = (
            row["referral_earned"] if "referral_earned" in row.keys() else 0
        )
        has_paid = bool(row["has_paid"]) if "has_paid" in row.keys() else False
        partner_agreed_at = (
            datetime.fromisoformat(row["partner_agreed_at"])
            if row["partner_agreed_at"] and "partner_agreed_at" in row.keys()
            else None
        )
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            credits=Credits(row["credits"] or 0),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            username=row["username"] if "username" in row.keys() else None,
            first_name=row["first_name"] if "first_name" in row.keys() else None,
            last_name=row["last_name"] if "last_name" in row.keys() else None,
            referral_code=referral_code,
            referred_by=referred_by,
            referral_earned=referral_earned or 0,
            has_paid=has_paid,
            partner_agreed_at=partner_agreed_at,
            partner_total_revenue_rub=(
                float(row["partner_total_revenue_rub"] or 0)
                if "partner_total_revenue_rub" in row.keys()
                else 0.0
            ),
            partner_balance_rub=(
                float(row["partner_balance_rub"] or 0)
                if "partner_balance_rub" in row.keys()
                else 0.0
            ),
            partner_withdrawn_rub=(
                float(row["partner_withdrawn_rub"] or 0)
                if "partner_withdrawn_rub" in row.keys()
                else 0.0
            ),
            prompt_repeat_balance_rub=(
                float(row["prompt_repeat_balance_rub"] or 0)
                if "prompt_repeat_balance_rub" in row.keys()
                else 0.0
            ),
            prompt_repeat_total_rub=(
                float(row["prompt_repeat_total_rub"] or 0)
                if "prompt_repeat_total_rub" in row.keys()
                else 0.0
            ),
            partner_tier=(
                row["partner_tier"]
                if "partner_tier" in row.keys() and row["partner_tier"]
                else "basic"
            ),
            channel_url=(
                row["channel_url"]
                if "channel_url" in row.keys() and row["channel_url"]
                else None
            ),
        )


async def get_master_partner_user() -> User:
    """Возвращает центрального партнёра, которому начисляются все реферальные бонусы."""
    master = await get_or_create_user(MASTER_PARTNER_TELEGRAM_ID)
    return master


async def update_user_profile(
    telegram_id: int,
    *,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    photo_url: Optional[str] = None,
) -> bool:
    """Stores lightweight Telegram profile fields for public author labels."""
    clean_username = (username or "").lstrip("@") or None
    clean_first_name = (first_name or "").strip() or None
    clean_last_name = (last_name or "").strip() or None
    clean_photo_url = (photo_url or "").strip() or None

    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT username, first_name, last_name, photo_url
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        )
        current = await cursor.fetchone()
        if current and (
            current["username"],
            current["first_name"],
            current["last_name"],
            current["photo_url"] if "photo_url" in current.keys() else None,
        ) == (clean_username, clean_first_name, clean_last_name, clean_photo_url):
            return True

        cursor = await db.execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?,
                last_name = ?,
                photo_url = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
            """,
            (clean_username, clean_first_name, clean_last_name, clean_photo_url, telegram_id),
        )
        await db.commit()
        return cursor.rowcount > 0


def _normalize_channel_url(channel_url: str) -> str:
    raw = " ".join(str(channel_url or "").split()).strip()
    if not raw:
        return ""
    if len(raw) > 160:
        raise ValueError("Ссылка на канал слишком длинная")

    username_match = re.fullmatch(r"@?([A-Za-z0-9_]{5,32})", raw)
    if username_match:
        return f"https://t.me/{username_match.group(1)}"

    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        raw = f"https://{raw}"

    match = re.fullmatch(
        r"https?://(?:www\.)?(?:t\.me|telegram\.me)/([A-Za-z0-9_+/-]{1,96})/?",
        raw,
    )
    if not match:
        raise ValueError("Укажите Telegram-канал: @channel или https://t.me/channel")

    path = match.group(1).strip("/")
    return f"https://t.me/{path}"


async def save_user_channel_url(telegram_id: int, channel_url: str) -> str:
    """Stores the author's public Telegram channel link."""
    normalized = _normalize_channel_url(channel_url)
    async with db_backend.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET channel_url = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
            """,
            (normalized or None, telegram_id),
        )
        await db.commit()
    return normalized


async def generate_referral_code(db: Optional[db_backend.Connection] = None) -> str:
    """Генерирует уникальный реферальный код."""
    import secrets
    import string

    alphabet = string.ascii_uppercase + string.digits
    conn = db
    owns_connection = conn is None

    if owns_connection:
        conn = await db_backend.connect(DATABASE_PATH)

    assert conn is not None
    conn.row_factory = db_backend.Row

    try:
        for _ in range(20):
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            cursor = await conn.execute(
                "SELECT 1 FROM users WHERE referral_code = ? LIMIT 1", (code,)
            )
            if not await cursor.fetchone():
                return code
        raise RuntimeError("Failed to generate unique referral code")
    finally:
        if owns_connection:
            await conn.close()


async def get_user_by_referral_code(referral_code: str) -> Optional[User]:
    """Получает пользователя по реферальному коду."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE referral_code = ?",
            (referral_code.strip().upper(),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            credits=row["credits"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            username=row["username"] if "username" in row.keys() else None,
            first_name=row["first_name"] if "first_name" in row.keys() else None,
            last_name=row["last_name"] if "last_name" in row.keys() else None,
            referral_code=(
                row["referral_code"] if "referral_code" in row.keys() else None
            ),
            referred_by=row["referred_by"] if "referred_by" in row.keys() else None,
            referral_earned=(
                row["referral_earned"] if "referral_earned" in row.keys() else 0
            ),
            has_paid=bool(row["has_paid"]) if "has_paid" in row.keys() else False,
            partner_agreed_at=(
                datetime.fromisoformat(row["partner_agreed_at"])
                if row["partner_agreed_at"] and "partner_agreed_at" in row.keys()
                else None
            ),
            partner_total_revenue_rub=(
                float(row["partner_total_revenue_rub"] or 0)
                if "partner_total_revenue_rub" in row.keys()
                else 0.0
            ),
            partner_balance_rub=(
                float(row["partner_balance_rub"] or 0)
                if "partner_balance_rub" in row.keys()
                else 0.0
            ),
            partner_withdrawn_rub=(
                float(row["partner_withdrawn_rub"] or 0)
                if "partner_withdrawn_rub" in row.keys()
                else 0.0
            ),
            prompt_repeat_balance_rub=(
                float(row["prompt_repeat_balance_rub"] or 0)
                if "prompt_repeat_balance_rub" in row.keys()
                else 0.0
            ),
            prompt_repeat_total_rub=(
                float(row["prompt_repeat_total_rub"] or 0)
                if "prompt_repeat_total_rub" in row.keys()
                else 0.0
            ),
            partner_tier=(
                row["partner_tier"]
                if "partner_tier" in row.keys() and row["partner_tier"]
                else "basic"
            ),
            channel_url=(
                row["channel_url"]
                if "channel_url" in row.keys() and row["channel_url"]
                else None
            ),
        )


async def update_user_referral_code(telegram_id: int, referral_code: str) -> bool:
    """Сохраняет реферальный код пользователя."""
    async with db_backend.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET referral_code = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (referral_code, telegram_id),
        )
        await db.commit()
        _BOT_SETTING_CACHE.pop(setting_key, None)
        return True


async def _referral_chain_contains(
    db: db_backend.Connection,
    *,
    start_user_id: int,
    target_user_id: int,
) -> bool:
    """Returns True if target is already in start_user_id's referral ancestry."""
    current_id = start_user_id
    seen: set[int] = set()

    for _ in range(100):
        if current_id == target_user_id:
            return True
        if current_id in seen:
            cycle_key = (int(start_user_id), int(target_user_id), int(current_id))
            if cycle_key not in _LOGGED_REFERRAL_CYCLES:
                _LOGGED_REFERRAL_CYCLES.add(cycle_key)
                logger.warning(
                    "Referral ancestry cycle detected: start_user_id=%s target_user_id=%s repeated_user_id=%s",
                    start_user_id,
                    target_user_id,
                    current_id,
                )
            else:
                logger.debug(
                    "Referral ancestry cycle already reported: start_user_id=%s target_user_id=%s repeated_user_id=%s",
                    start_user_id,
                    target_user_id,
                    current_id,
                )
            return False
        seen.add(current_id)

        cursor = await db.execute(
            "SELECT referred_by FROM users WHERE id = ?",
            (current_id,),
        )
        row = await cursor.fetchone()
        if not row or not row["referred_by"]:
            return False
        current_id = int(row["referred_by"])

    return True


async def set_user_referrer(telegram_id: int, referrer_telegram_id: int) -> bool:
    """Привязывает пользователя к рефереру один раз."""
    try:
        from bot.config import config

        if config.is_admin(int(telegram_id)):
            logger.info(
                "Referral skipped: admin user cannot be manually referred telegram_id=%s referrer_telegram_id=%s",
                telegram_id,
                referrer_telegram_id,
            )
            return False
    except Exception:
        logger.exception("Failed to check admin manual referral guard telegram_id=%s", telegram_id)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        user_cursor = await db.execute(
            "SELECT id, referred_by FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        user_row = await user_cursor.fetchone()
        ref_cursor = await db.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (referrer_telegram_id,)
        )
        ref_row = await ref_cursor.fetchone()

        if not user_row or not ref_row:
            return False
        if user_row["referred_by"]:
            return False
        if user_row["id"] == ref_row["id"]:
            return False
        if await _referral_chain_contains(
            db,
            start_user_id=ref_row["id"],
            target_user_id=user_row["id"],
        ):
            return False

        update_cursor = await db.execute(
            """
            UPDATE users
            SET referred_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
              AND referred_by IS NULL
              AND id != ?
            """,
            (ref_row["id"], telegram_id, ref_row["id"]),
        )
        if update_cursor.rowcount != 1:
            await db.rollback()
            return False
        insert_cursor = await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, 0)",
            (ref_row["id"], user_row["id"]),
        )
        if insert_cursor.rowcount != 1:
            await db.rollback()
            return False
        await db.commit()
        return True


async def process_referral(
    referred_telegram_id: int,
    referral_code: str,
    signup_bonus: int = 0,
    inviter_bonus: int = PARTNER_INVITER_BONUS,
) -> bool:
    """Закрепляет пользователя за партнёром: пригласившему +3🍌 (новичок уже получил 5 при регистрации)."""
    referral_code = (referral_code or "").strip().upper()
    if not referral_code:
        logger.info(
            "Referral skipped: empty code for referred_telegram_id=%s",
            referred_telegram_id,
        )
        return False
    try:
        from bot.config import config

        if config.is_admin(int(referred_telegram_id)):
            logger.info(
                "Referral skipped: admin user cannot be referred referred_telegram_id=%s code=%s",
                referred_telegram_id,
                referral_code,
            )
            return False
    except Exception:
        logger.exception(
            "Failed to check admin referral guard referred_telegram_id=%s",
            referred_telegram_id,
        )

    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row

        referrer_cursor = await db.execute(
            "SELECT id, COALESCE(is_banned, 0) AS is_banned FROM users WHERE referral_code = ?",
            (referral_code,),
        )
        referrer = await referrer_cursor.fetchone()
        if not referrer:
            logger.info(
                "Referral skipped: code not found referred_telegram_id=%s code=%s",
                referred_telegram_id,
                referral_code,
            )
            return False
        if referrer["is_banned"]:
            logger.warning(
                "Referral blocked: referrer already banned referred_telegram_id=%s code=%s referrer_id=%s",
                referred_telegram_id,
                referral_code,
                referrer["id"],
            )
            return False

        referred_cursor = await db.execute(
            """
            SELECT
                u.id,
                u.referred_by,
                COALESCE(u.has_paid, 0) AS has_paid,
                EXISTS(
                    SELECT 1
                    FROM transactions t
                    WHERE t.user_id = u.id
                      AND t.status = 'completed'
                    LIMIT 1
                ) AS has_completed_payment
            FROM users u
            WHERE u.telegram_id = ?
            """,
            (referred_telegram_id,),
        )
        referred = await referred_cursor.fetchone()
        if not referred:
            logger.info(
                "Referral skipped: referred user not found referred_telegram_id=%s code=%s referrer_id=%s",
                referred_telegram_id,
                referral_code,
                referrer["id"],
            )
            return False
        if referred["referred_by"]:
            logger.info(
                "Referral skipped: already referred referred_telegram_id=%s code=%s referrer_id=%s existing_referrer_id=%s",
                referred_telegram_id,
                referral_code,
                referrer["id"],
                referred["referred_by"],
            )
            return False
        if referred["id"] == referrer["id"]:
            logger.info(
                "Referral skipped: self referral referred_telegram_id=%s code=%s user_id=%s",
                referred_telegram_id,
                referral_code,
                referred["id"],
            )
            return False
        if referred["has_paid"] or referred["has_completed_payment"]:
            logger.info(
                "Referral skipped: user already paid referred_telegram_id=%s code=%s referrer_id=%s has_paid=%s has_completed_payment=%s",
                referred_telegram_id,
                referral_code,
                referrer["id"],
                referred["has_paid"],
                referred["has_completed_payment"],
            )
            return False
        if referral_code in REFERRAL_ANTIFRAUD_BLOCK_CODES or referrer["id"] in REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS:
            logger.warning(
                "Referral blocked by antifraud blocklist: referred_telegram_id=%s code=%s referrer_id=%s referred_id=%s",
                referred_telegram_id,
                referral_code,
                referrer["id"],
                referred["id"],
            )
            return False
        hourly_cursor = await db.execute(
            "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', '-1 hour')",
            (referrer["id"],),
        )
        hourly_count = int((await hourly_cursor.fetchone())["cnt"])
        if hourly_count >= REFERRAL_ANTIFRAUD_MAX_PER_HOUR:
            logger.warning(
                "Referral blocked by antifraud hourly limit: referred_telegram_id=%s code=%s referrer_id=%s referred_id=%s hourly_count=%s limit=%s",
                referred_telegram_id,
                referral_code,
                referrer["id"],
                referred["id"],
                hourly_count,
                REFERRAL_ANTIFRAUD_MAX_PER_HOUR,
            )
            return False
        daily_cursor = await db.execute(
            "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', '-1 day')",
            (referrer["id"],),
        )
        daily_count = int((await daily_cursor.fetchone())["cnt"])
        if daily_count >= REFERRAL_ANTIFRAUD_MAX_PER_DAY:
            logger.warning(
                "Referral blocked by antifraud daily limit: referred_telegram_id=%s code=%s referrer_id=%s referred_id=%s daily_count=%s limit=%s",
                referred_telegram_id,
                referral_code,
                referrer["id"],
                referred["id"],
                daily_count,
                REFERRAL_ANTIFRAUD_MAX_PER_DAY,
            )
            return False
        if (
            REFERRAL_ANTIFRAUD_BURST_MAX > 0
            and REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS > 0
        ):
            burst_cursor = await db.execute(
                "SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = ? AND created_at >= datetime('now', ?)",
                (
                    referrer["id"],
                    f"-{REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS} seconds",
                ),
            )
            burst_count = int((await burst_cursor.fetchone())["cnt"])
            if burst_count >= REFERRAL_ANTIFRAUD_BURST_MAX - 1:
                await db.execute(
                    """
                    UPDATE users
                    SET is_banned = 1,
                        banned_at = CURRENT_TIMESTAMP,
                        banned_by_telegram_id = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (referrer["id"],),
                )
                await db.commit()
                logger.warning(
                    "Referral autoban triggered by burst: referred_telegram_id=%s code=%s referrer_id=%s referred_id=%s burst_count=%s window_seconds=%s threshold=%s",
                    referred_telegram_id,
                    referral_code,
                    referrer["id"],
                    referred["id"],
                    burst_count + 1,
                    REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS,
                    REFERRAL_ANTIFRAUD_BURST_MAX,
                )
                return False
        if await _referral_chain_contains(
            db,
            start_user_id=referrer["id"],
            target_user_id=referred["id"],
        ):
            logger.info(
                "Referral skipped: chain cycle referred_telegram_id=%s code=%s referrer_id=%s referred_id=%s",
                referred_telegram_id,
                referral_code,
                referrer["id"],
                referred["id"],
            )
            return False

        update_cursor = await db.execute(
            """
            UPDATE users
            SET referred_by = ?, credits = credits + ?, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
              AND referred_by IS NULL
              AND id != ?
              AND COALESCE(has_paid, 0) = 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM transactions t
                  WHERE t.user_id = users.id
                    AND t.status = 'completed'
                  LIMIT 1
              )
            """,
            (referrer["id"], signup_bonus, referred_telegram_id, referrer["id"]),
        )
        if update_cursor.rowcount != 1:
            await db.rollback()
            logger.info(
                "Referral skipped: update rowcount=%s referred_telegram_id=%s code=%s referrer_id=%s referred_id=%s",
                update_cursor.rowcount,
                referred_telegram_id,
                referral_code,
                referrer["id"],
                referred["id"],
            )
            return False
        insert_cursor = await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, ?)",
            (referrer["id"], referred["id"], signup_bonus),
        )
        if insert_cursor.rowcount != 1:
            await db.rollback()
            logger.info(
                "Referral skipped: insert rowcount=%s referred_telegram_id=%s code=%s referrer_id=%s referred_id=%s",
                insert_cursor.rowcount,
                referred_telegram_id,
                referral_code,
                referrer["id"],
                referred["id"],
            )
            return False
        await db.execute(
            "UPDATE users SET credits = credits + ?, referral_earned = referral_earned + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (inviter_bonus, inviter_bonus, referrer["id"]),
        )
        await db.commit()
        logger.info(
            "Referral processed: referred_telegram_id=%s code=%s referrer_id=%s referred_id=%s signup_bonus=%s inviter_bonus=%s",
            referred_telegram_id,
            referral_code,
            referrer["id"],
            referred["id"],
            signup_bonus,
            inviter_bonus,
        )
        return True


async def mark_user_paid(telegram_id: int) -> bool:
    """Помечает пользователя как оплатившего хотя бы один раз."""
    async with db_backend.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET has_paid = 1, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (telegram_id,),
        )
        await db.commit()
        return True


async def complete_payment_atomic(
    order_id: str,
) -> dict:
    """Атомарно завершает платёж в одной транзакции.

    Возвращает данные, необходимые для post-commit уведомлений.
    Порядок: pending -> processing -> add_credits -> referral commission ->
             partner_commissions ledger -> promo redemption -> completed.
    """
    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            # 1. SELECT transaction FOR UPDATE (имитация через проверку статуса)
            txn_cursor = await db.execute(
                "SELECT * FROM transactions WHERE order_id = ?",
                (order_id,),
            )
            txn_row = await txn_cursor.fetchone()
            if not txn_row:
                await db.rollback()
                return {"ok": False, "reason": "not_found"}

            if txn_row["status"] == "completed":
                await db.rollback()
                return {
                    "ok": True,
                    "already_completed": True,
                    "transaction": Transaction(
                        id=txn_row["id"],
                        order_id=txn_row["order_id"],
                        user_id=txn_row["user_id"],
                        payment_id=txn_row["payment_id"],
                        provider=txn_row["provider"] if "provider" in txn_row.keys() else "cryptobot",
                        credits=txn_row["credits"],
                        amount_rub=txn_row["amount_rub"],
                        status=txn_row["status"],
                        created_at=datetime.fromisoformat(txn_row["created_at"]),
                    ),
                    "telegram_id": None,
                    "referral_bonus": {},
                    "promo_bonus": {},
                }

            if txn_row["status"] not in ("pending", "processing"):
                await db.rollback()
                return {"ok": False, "reason": f"invalid_status:{txn_row['status']}"}

            # 2. pending -> processing (защита от двойного начисления)
            update_result = await db.execute(
                "UPDATE transactions SET status = 'processing' WHERE order_id = ? AND status = 'pending'",
                (order_id,),
            )
            if update_result.rowcount != 1:
                # Уже был переведён кем-то в processing/completed
                if txn_row["status"] == "processing":
                    # Другой процесс уже обрабатывает — выходим
                    await db.rollback()
                    return {"ok": False, "reason": "already_processing"}

            transaction = Transaction(
                id=txn_row["id"],
                order_id=txn_row["order_id"],
                user_id=txn_row["user_id"],
                payment_id=txn_row["payment_id"],
                provider=txn_row["provider"] if "provider" in txn_row.keys() else "cryptobot",
                credits=txn_row["credits"],
                amount_rub=txn_row["amount_rub"],
                status="processing",
                created_at=datetime.fromisoformat(txn_row["created_at"]),
                promo_code_id=txn_row["promo_code_id"] if "promo_code_id" in txn_row.keys() else None,
                promo_code=txn_row["promo_code"] if "promo_code" in txn_row.keys() else None,
                promo_bonus_credits=int(txn_row["promo_bonus_credits"] or 0) if "promo_bonus_credits" in txn_row.keys() else 0,
            )

            # Получаем telegram_id
            user_cursor = await db.execute(
                "SELECT telegram_id, referred_by, has_paid FROM users WHERE id = ?",
                (txn_row["user_id"],),
            )
            user_row = await user_cursor.fetchone()
            if not user_row:
                await db.rollback()
                return {"ok": False, "reason": "user_not_found"}

            telegram_id = int(user_row["telegram_id"])
            referred_by = user_row["referred_by"] if "referred_by" in user_row.keys() else None
            user_already_paid = bool(user_row["has_paid"]) if "has_paid" in user_row.keys() else False

            # 3. add_credits
            await db.execute(
                "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (transaction.credits, telegram_id),
            )

            # 4. referral commission + partner_commissions ledger
            referral_bonus: dict[str, Any] = {"mode": "none", "value": 0, "percent": 0}
            if referred_by:
                base_value = float(transaction.amount_rub)
                ref1_id = int(referred_by)

                ref1_cursor = await db.execute(
                    "SELECT telegram_id, partner_total_revenue_rub, partner_tier, referred_by FROM users WHERE id = ?",
                    (ref1_id,),
                )
                ref1_row = await ref1_cursor.fetchone()
                ref1_revenue = float(ref1_row["partner_total_revenue_rub"] or 0) if ref1_row else 0.0
                ref1_tier = get_partner_tier_by_total(ref1_revenue)
                ref1_percent = get_partner_percent_by_tier(ref1_tier)
                level1_bonus = round(base_value * ref1_percent / 100.0, 2)

                # Начисление ref1
                await db.execute(
                    "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, "
                    "partner_balance_rub = partner_balance_rub + ?, "
                    "partner_tier = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (base_value, level1_bonus, ref1_tier, ref1_id),
                )

                # Ledger: partner_commissions для level 1
                try:
                    await db.execute(
                        """
                        INSERT INTO partner_commissions (transaction_id, order_id, referrer_id, referred_id, level, base_amount_rub, percent, amount_rub, tier)
                        VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                        ON CONFLICT(transaction_id, referrer_id, level) DO NOTHING
                        """,
                        (txn_row["id"], order_id, ref1_id, txn_row["user_id"], base_value, float(ref1_percent), level1_bonus, ref1_tier),
                    )
                except db_backend.OperationalError:
                    logger.warning(
                        "partner_commissions table not ready (level 1): txn=%s ref1=%s",
                        txn_row["id"], ref1_id,
                    )

                ref2_bonus = 0.0
                ref2_row = None
                ref2_telegram_id = None
                ref1_is_admin = False
                if ref1_row and ref1_row["telegram_id"]:
                    try:
                        from bot.config import config

                        ref1_is_admin = config.is_admin(int(ref1_row["telegram_id"]))
                    except Exception:
                        logger.exception(
                            "Failed to check admin L2 guard for ref1_id=%s",
                            ref1_id,
                        )
                if ref1_row and ref1_row["referred_by"] and not ref1_is_admin:
                    ref2_id = int(ref1_row["referred_by"])
                    level2_bonus = round(base_value * PARTNER_LEVEL2_PERCENT / 100.0, 2)
                    ref2_cursor = await db.execute(
                        "SELECT telegram_id, partner_total_revenue_rub, partner_tier FROM users WHERE id = ?",
                        (ref2_id,),
                    )
                    ref2_row = await ref2_cursor.fetchone()
                    ref2_revenue = float(ref2_row["partner_total_revenue_rub"] or 0) if ref2_row else 0.0
                    ref2_tier = get_partner_tier_by_total(ref2_revenue)
                    ref2_telegram_id = int(ref2_row["telegram_id"]) if ref2_row and ref2_row["telegram_id"] else None

                    await db.execute(
                        "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, "
                        "partner_balance_rub = partner_balance_rub + ?, "
                        "partner_tier = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (base_value, level2_bonus, ref2_tier, ref2_id),
                    )

                    # Ledger: partner_commissions для level 2
                    try:
                        await db.execute(
                            """
                            INSERT INTO partner_commissions (transaction_id, order_id, referrer_id, referred_id, level, base_amount_rub, percent, amount_rub)
                            VALUES (?, ?, ?, ?, 2, ?, ?, ?)
                            ON CONFLICT(transaction_id, referrer_id, level) DO NOTHING
                            """,
                            (txn_row["id"], order_id, ref2_id, txn_row["user_id"], base_value, float(PARTNER_LEVEL2_PERCENT), level2_bonus),
                        )
                    except db_backend.OperationalError:
                        pass

                    ref2_bonus = level2_bonus

                referral_bonus = {
                    "mode": "partner",
                    "value": level1_bonus,
                    "percent": ref1_percent,
                    "referrer_tier": ref1_tier,
                    "referrer_user_id": ref1_id,
                    "referrer_telegram_id": int(ref1_row["telegram_id"]) if ref1_row and ref1_row["telegram_id"] else None,
                    "level2_value": ref2_bonus,
                    "level2_percent": PARTNER_LEVEL2_PERCENT,
                    "level2_referrer_user_id": ref2_id if ref2_bonus > 0 else None,
                    "level2_referrer_telegram_id": ref2_telegram_id,
                }

            # 5. promo redemption
            promo_bonus: dict[str, Any] = {}
            promo_code_id = int(txn_row["promo_code_id"] or 0) if "promo_code_id" in txn_row.keys() and txn_row["promo_code_id"] else 0
            bonus_credits = int(txn_row["promo_bonus_credits"] or 0) if "promo_bonus_credits" in txn_row.keys() else 0
            if promo_code_id and bonus_credits > 0:
                promo_cursor = await db.execute(
                    "INSERT OR IGNORE INTO promo_redemptions (promo_code_id, transaction_id, user_id, amount_rub, bonus_credits) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (promo_code_id, txn_row["id"], txn_row["user_id"], float(txn_row["amount_rub"]), bonus_credits),
                )
                if promo_cursor.rowcount > 0:
                    await db.execute(
                        "UPDATE promo_codes SET usage_count = usage_count + 1, "
                        "total_bonus_credits = total_bonus_credits + ?, "
                        "total_amount_rub = total_amount_rub + ?, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (bonus_credits, float(txn_row["amount_rub"]), promo_code_id),
                    )
                promo_bonus = {
                    "code": (txn_row["promo_code"] or "") if "promo_code" in txn_row.keys() else "",
                    "bonus_credits": bonus_credits,
                    "inserted": promo_cursor.rowcount > 0,
                }

            # 6. mark has_paid
            if not user_already_paid:
                await db.execute(
                    "UPDATE users SET has_paid = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (txn_row["user_id"],),
                )

            # 7. processing -> completed
            await db.execute(
                "UPDATE transactions SET status = 'completed' WHERE order_id = ? AND status = 'processing'",
                (order_id,),
            )

            await db.commit()

            transaction.status = "completed"
            return {
                "ok": True,
                "already_completed": False,
                "transaction": transaction,
                "telegram_id": telegram_id,
                "referral_bonus": referral_bonus,
                "promo_bonus": promo_bonus,
            }
        except Exception:
            await db.rollback()
            raise


async def credit_referral_commission(
    telegram_id: int,
    transaction_credits: int,
    transaction_amount_rub: Optional[float] = None,
    bonus_percent: int = PARTNER_LEVEL1_PERCENT,
    level2_percent: int = PARTNER_LEVEL2_PERCENT,
) -> dict:
    """Начисляет партнёру 1 уровня и 2 уровня с каждой оплаты.

    По актуальным условиям 1 уровень всегда получает фиксированные 30%,
    а 2 уровень — фиксированные 7% без tier-based надбавок.
    """
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT id, referred_by, has_paid FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        user = await cursor.fetchone()
        if not user:
            return {"mode": "none", "value": 0, "percent": 0}
        if not user["referred_by"]:
            if not user["has_paid"]:
                await db.execute(
                    "UPDATE users SET has_paid = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (user["id"],),
                )
                await db.commit()
            return {"mode": "none", "value": 0, "percent": 0}

        base_value = float(
            transaction_amount_rub
            if transaction_amount_rub is not None
            else transaction_credits
        )

        ref1_id = user["referred_by"]
        ref1_cursor = await db.execute(
            "SELECT telegram_id, partner_total_revenue_rub, partner_tier, referred_by FROM users WHERE id = ?",
            (ref1_id,),
        )
        ref1_row = await ref1_cursor.fetchone()
        ref1_tier = get_partner_tier_by_total(0.0)
        ref1_percent = bonus_percent
        level1_bonus = round(base_value * ref1_percent / 100.0, 2)

        await db.execute(
            "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, "
            "partner_balance_rub = partner_balance_rub + ?, "
            "partner_tier = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (base_value, level1_bonus, ref1_tier, ref1_id),
        )

        level2_bonus = 0.0
        ref2_row = None
        ref1_is_admin = False
        if ref1_row and ref1_row["telegram_id"]:
            try:
                from bot.config import config

                ref1_is_admin = config.is_admin(int(ref1_row["telegram_id"]))
            except Exception:
                logger.exception(
                    "Failed to check admin L2 guard for ref1_id=%s",
                    ref1_id,
                )
        if ref1_row and ref1_row["referred_by"] and not ref1_is_admin:
            ref2_id = ref1_row["referred_by"]
            ref2_cursor = await db.execute(
                "SELECT telegram_id, partner_total_revenue_rub, partner_tier FROM users WHERE id = ?",
                (ref2_id,),
            )
            ref2_row = await ref2_cursor.fetchone()
            level2_bonus = round(base_value * level2_percent / 100.0, 2)
            ref2_tier = get_partner_tier_by_total(0.0)
            await db.execute(
                "UPDATE users SET partner_total_revenue_rub = partner_total_revenue_rub + ?, "
                "partner_balance_rub = partner_balance_rub + ?, "
                "partner_tier = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (base_value, level2_bonus, ref2_tier, ref2_id),
            )

        if not user["has_paid"]:
            await db.execute(
                "UPDATE users SET has_paid = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user["id"],),
            )
        await db.commit()
        return {
            "mode": "partner",
            "value": level1_bonus,
            "percent": ref1_percent,
            "referrer_tier": ref1_tier,
            "referrer_user_id": ref1_id,
            "referrer_telegram_id": (
                int(ref1_row["telegram_id"]) if ref1_row and ref1_row["telegram_id"] else None
            ),
            "level2_value": level2_bonus,
            "level2_percent": level2_percent,
            "level2_referrer_user_id": ref2_id if level2_bonus > 0 else None,
            "level2_referrer_telegram_id": (
                int(ref2_row["telegram_id"])
                if level2_bonus > 0 and ref2_row and ref2_row["telegram_id"]
                else None
            ),
        }


# Обратная совместимость — старое имя функции
async def credit_first_payment_referral_bonus(
    telegram_id: int,
    transaction_credits: int,
    transaction_amount_rub: Optional[float] = None,
    bonus_percent: int = PARTNER_LEVEL1_PERCENT,
) -> dict:
    return await credit_referral_commission(
        telegram_id, transaction_credits, transaction_amount_rub, bonus_percent
    )


def get_partner_tier_by_total(total_revenue_rub: float) -> str:
    """Возвращает единый tier партнёрки.

    Исторические tier-статусы в БД могут оставаться, но больше не влияют
    ни на отображение, ни на расчёт комиссии.
    """
    _ = total_revenue_rub
    return "basic"


def get_partner_percent_by_tier(tier: str) -> int:
    _ = tier
    return PARTNER_LEVEL1_PERCENT


async def accept_partner_agreement(telegram_id: int) -> bool:
    """Подтверждает участие в партнёрской программе."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        # Read current referral-related fields to ensure we don't accidentally overwrite them
        cursor = await db.execute(
            "SELECT referral_code, referred_by, referral_earned, partner_agreed_at, partner_tier FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        before = await cursor.fetchone()

        await db.execute(
            "UPDATE users SET partner_agreed_at = CURRENT_TIMESTAMP, partner_tier = 'basic', updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (telegram_id,),
        )
        await db.commit()

        # Read back and log unexpected changes
        cursor = await db.execute(
            "SELECT referral_code, referred_by, referral_earned, partner_agreed_at, partner_tier FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        after = await cursor.fetchone()

        try:
            # If any referral fields changed unexpectedly, log a warning for diagnostics
            if before and after:
                for field in ("referral_code", "referred_by", "referral_earned"):
                    if before[field] != after[field]:
                        logger.warning(
                            "accept_partner_agreement changed %s for %s: %s -> %s",
                            field,
                            telegram_id,
                            before[field],
                            after[field],
                        )
        except Exception:
            logger.exception(
                "Error while validating referral fields after accept_partner_agreement"
            )

        return True


async def get_partner_overview(telegram_id: int) -> dict:
    """Возвращает данные партнёрского кабинета."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        target_user = await get_or_create_user(telegram_id)
        target_user_id = target_user.id

        ref_cursor = await db.execute(
            "SELECT COUNT(*) as count FROM users WHERE referred_by = ?",
            (target_user_id,),
        )
        referrals_row = await ref_cursor.fetchone()

        pay_cursor = await db.execute(
            """
            SELECT COUNT(*) as count,
                   COALESCE(SUM(CASE WHEN date(t.created_at) >= date('now', '-30 day') THEN t.amount_rub ELSE 0 END), 0) as monthly_revenue,
                   COALESCE(SUM(CASE WHEN date(t.created_at) = date('now') THEN t.amount_rub ELSE 0 END), 0) as today_revenue,
                   COALESCE(SUM(CASE WHEN date(t.created_at) = date('now') THEN 1 ELSE 0 END), 0) as today_payments,
                   COALESCE(SUM(CASE WHEN date(t.created_at) >= date('now', '-7 day') THEN 1 ELSE 0 END), 0) as active_7d
            FROM referrals r
            JOIN users u ON u.id = r.referred_id
            JOIN transactions t ON t.user_id = u.id
            WHERE r.referrer_id = ?
              AND u.referred_by = r.referrer_id
              AND t.status = 'completed'
              AND datetime(t.created_at) >= datetime(r.created_at)
            """,
            (target_user_id,),
        )
        pay_row = await pay_cursor.fetchone()

        level2_cursor = await db.execute(
            """
            SELECT COUNT(*) as count
            FROM users u2
            JOIN users u1 ON u2.referred_by = u1.id
            WHERE u1.referred_by = ?
            """,
            (target_user_id,),
        )
        level2_row = await level2_cursor.fetchone()

        # Единственный источник истины для выведенных сумм — колонка partner_withdrawn_rub
        pending_cur = await db.execute(
            "SELECT COALESCE(SUM(amount_rub), 0) AS pending FROM partner_withdrawals "
            "WHERE user_id = ? AND status = 'requested'",
            (target_user_id,),
        )
        pending_row = await pending_cur.fetchone()
        pending_rub = float(pending_row["pending"] or 0)
        raw_balance = float(target_user.partner_balance_rub or 0)
        available_balance = round(max(0.0, raw_balance - pending_rub), 2)
        prompt_repeat_balance = round(
            min(
                max(0.0, float(target_user.prompt_repeat_balance_rub or 0)),
                available_balance,
            ),
            2,
        )

        tier = get_partner_tier_by_total(target_user.partner_total_revenue_rub or 0)
        percent = get_partner_percent_by_tier(tier)

        return {
            "is_partner": bool(target_user.partner_agreed_at),
            "partner_agreed_at": (
                target_user.partner_agreed_at.isoformat()
                if target_user.partner_agreed_at
                else None
            ),
            "referrals_count": referrals_row["count"] or 0,
            "level1_count": referrals_row["count"] or 0,
            "level2_count": level2_row["count"] or 0,
            "total_revenue_rub": round(target_user.partner_total_revenue_rub or 0, 2),
            "balance_rub": available_balance,
            "total_balance_rub": round(raw_balance, 2),
            "prompt_repeat_balance_rub": prompt_repeat_balance,
            "prompt_repeat_total_rub": round(
                target_user.prompt_repeat_total_rub or 0, 2
            ),
            "pending_rub": round(pending_rub, 2),
            "withdrawn_rub": round(target_user.partner_withdrawn_rub or 0, 2),
            "tier": tier,
            "percent": percent,
            "active_7d": pay_row["active_7d"] or 0,
            "total_payments": pay_row["count"] or 0,
            "monthly_revenue": round(pay_row["monthly_revenue"] or 0, 2),
            "today_payments": pay_row["today_payments"] or 0,
            "today_revenue": round(pay_row["today_revenue"] or 0, 2),
            "channel_url": target_user.channel_url or "",
        }


async def get_admin_partner_stats(limit: int = 10) -> dict:
    """Возвращает сводку по партнёрской программе для админки."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_partners,
                COALESCE(SUM(partner_balance_rub), 0) AS total_balance_rub,
                COALESCE(SUM(partner_total_revenue_rub), 0) AS total_partner_revenue_rub
            FROM users
            WHERE partner_agreed_at IS NOT NULL
               OR partner_balance_rub > 0
               OR partner_total_revenue_rub > 0
               OR EXISTS (
                   SELECT 1
                   FROM users referrals
                   WHERE referrals.referred_by = users.id
               )
            """
        )
        summary_row = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT COUNT(*) AS count
            FROM users
            WHERE partner_agreed_at IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM users referrals
                  WHERE referrals.referred_by = users.id
              )
            """
        )
        active_row = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(amount_rub), 0) AS total
            FROM partner_withdrawals
            WHERE status = 'completed'
            """
        )
        withdrawn_row = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(
                    CASE
                        WHEN datetime(created_at) >= datetime('now', '-1 day') THEN 1
                        ELSE 0
                    END
                ), 0) AS last_24h
            FROM referral_events
            WHERE reason = 'burst_autoban'
            """
        )
        burst_row = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                u.telegram_id,
                u.referral_code,
                u.partner_balance_rub,
                u.partner_total_revenue_rub,
                COALESCE(w.total_withdrawn, 0) AS withdrawn_rub,
                (
                    SELECT COUNT(*)
                    FROM users ref1
                    WHERE ref1.referred_by = u.id
                ) AS level1_count,
                (
                    SELECT COUNT(*)
                    FROM users ref2
                    JOIN users ref1 ON ref2.referred_by = ref1.id
                    WHERE ref1.referred_by = u.id
                ) AS level2_count
            FROM users u
            LEFT JOIN (
                SELECT user_id, SUM(amount_rub) AS total_withdrawn
                FROM partner_withdrawals
                WHERE status = 'completed'
                GROUP BY user_id
            ) w ON w.user_id = u.id
            WHERE u.partner_agreed_at IS NOT NULL
               OR u.partner_balance_rub > 0
               OR u.partner_total_revenue_rub > 0
               OR EXISTS (
                   SELECT 1
                   FROM users referrals
                   WHERE referrals.referred_by = u.id
               )
            ORDER BY
                u.partner_balance_rub DESC,
                u.partner_total_revenue_rub DESC,
                level1_count DESC,
                u.id ASC
            LIMIT ?
            """,
            (limit,),
        )
        partner_rows = await cursor.fetchall()

        return {
            "total_partners": summary_row["total_partners"] or 0,
            "active_partners": active_row["count"] or 0,
            "total_balance_rub": round(summary_row["total_balance_rub"] or 0, 2),
            "total_partner_revenue_rub": round(
                summary_row["total_partner_revenue_rub"] or 0, 2
            ),
            "total_withdrawn_rub": round(withdrawn_row["total"] or 0, 2),
            "burst_autobans_total": burst_row["total"] or 0,
            "burst_autobans_24h": burst_row["last_24h"] or 0,
            "top_partners": [
                {
                    "telegram_id": row["telegram_id"],
                    "referral_code": row["referral_code"] or "",
                    "balance_rub": round(row["partner_balance_rub"] or 0, 2),
                    "total_revenue_rub": round(
                        row["partner_total_revenue_rub"] or 0, 2
                    ),
                    "withdrawn_rub": round(row["withdrawn_rub"] or 0, 2),
                    "level1_count": row["level1_count"] or 0,
                    "level2_count": row["level2_count"] or 0,
                }
                for row in partner_rows
            ],
        }


async def get_admin_referral_burst_autobans(limit: int = 20) -> dict:
    """Возвращает список последних autoban-событий по burst-антифроду."""
    safe_limit = max(1, min(int(limit or 20), 100))
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        summary_cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(
                    CASE
                        WHEN datetime(created_at) >= datetime('now', '-1 day') THEN 1
                        ELSE 0
                    END
                ), 0) AS last_24h,
                MAX(created_at) AS latest_created_at
            FROM referral_events
            WHERE reason = 'burst_autoban'
            """
        )
        summary_row = await summary_cursor.fetchone()

        events_cursor = await db.execute(
            """
            SELECT
                re.id,
                re.created_at,
                re.clicked_referrer_id,
                re.clicked_code,
                re.visitor_telegram_id,
                re.source,
                re.start_param,
                u.telegram_id AS referrer_telegram_id,
                COALESCE(u.is_banned, 0) AS referrer_is_banned
            FROM referral_events re
            LEFT JOIN users u ON u.id = re.clicked_referrer_id
            WHERE re.reason = 'burst_autoban'
            ORDER BY re.created_at DESC, re.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        event_rows = await events_cursor.fetchall()

        return {
            "total": summary_row["total"] or 0,
            "last_24h": summary_row["last_24h"] or 0,
            "latest_created_at": summary_row["latest_created_at"],
            "items": [
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "referrer_user_id": row["clicked_referrer_id"],
                    "referrer_telegram_id": row["referrer_telegram_id"],
                    "referral_code": row["clicked_code"] or "",
                    "visitor_telegram_id": row["visitor_telegram_id"],
                    "source": row["source"] or "",
                    "start_param": row["start_param"] or "",
                    "referrer_is_banned": bool(row["referrer_is_banned"]),
                }
                for row in event_rows
            ],
        }


async def get_admin_partner_details(
    telegram_id: int, referrals_limit: int = 15
) -> Optional[dict]:
    """Возвращает детальную партнёрскую статистику по конкретному пользователю."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        user_row = await cursor.fetchone()
        if not user_row:
            return None

        user = User(
            id=user_row["id"],
            telegram_id=user_row["telegram_id"],
            credits=Credits(user_row["credits"] or 0),
            created_at=datetime.fromisoformat(user_row["created_at"]),
            updated_at=datetime.fromisoformat(user_row["updated_at"]),
            referral_code=user_row["referral_code"],
            referred_by=user_row["referred_by"],
            referral_earned=user_row["referral_earned"] or 0,
            has_paid=bool(user_row["has_paid"]),
            partner_agreed_at=(
                datetime.fromisoformat(user_row["partner_agreed_at"])
                if user_row["partner_agreed_at"]
                else None
            ),
            partner_total_revenue_rub=float(
                user_row["partner_total_revenue_rub"] or 0
            ),
            partner_balance_rub=float(user_row["partner_balance_rub"] or 0),
            partner_withdrawn_rub=float(user_row["partner_withdrawn_rub"] or 0),
            prompt_repeat_balance_rub=float(
                user_row["prompt_repeat_balance_rub"] or 0
            )
            if "prompt_repeat_balance_rub" in user_row.keys()
            else 0.0,
            prompt_repeat_total_rub=float(user_row["prompt_repeat_total_rub"] or 0)
            if "prompt_repeat_total_rub" in user_row.keys()
            else 0.0,
            partner_tier=user_row["partner_tier"] or "basic",
            channel_url=(
                user_row["channel_url"]
                if "channel_url" in user_row.keys() and user_row["channel_url"]
                else None
            ),
        )

        overview = await get_partner_overview(telegram_id)

        cursor = await db.execute(
            """
            SELECT
                u.telegram_id,
                u.credits,
                CASE
                    WHEN COALESCE(u.has_paid, 0) = 1
                      OR EXISTS (
                          SELECT 1
                          FROM transactions paid_t
                          WHERE paid_t.user_id = u.id
                            AND paid_t.status = 'completed'
                          LIMIT 1
                      )
                    THEN 1
                    ELSE 0
                END AS has_paid,
                u.created_at,
                r.created_at AS referral_created_at,
                COALESCE((
                    SELECT SUM(t.amount_rub)
                    FROM transactions t
                    WHERE t.user_id = u.id
                      AND t.status = 'completed'
                      AND datetime(t.created_at) >= datetime(r.created_at)
                ), 0) AS spent_rub,
                COALESCE((
                    SELECT COUNT(*)
                    FROM transactions t
                    WHERE t.user_id = u.id
                      AND t.status = 'completed'
                      AND datetime(t.created_at) >= datetime(r.created_at)
                ), 0) AS payments_count,
                (
                    SELECT COUNT(*)
                    FROM users subref
                    WHERE subref.referred_by = u.id
                ) AS subrefs_count
            FROM referrals r
            JOIN users u ON u.id = r.referred_id
            WHERE r.referrer_id = ?
              AND u.referred_by = r.referrer_id
            ORDER BY spent_rub DESC, u.created_at DESC
            LIMIT ?
            """,
            (user.id, referrals_limit),
        )
        referral_rows = await cursor.fetchall()

        return {
            "telegram_id": user.telegram_id,
            "credits": Credits(user.credits),
            "referral_code": user.referral_code or "",
            "is_partner": bool(user.partner_agreed_at),
            "partner_agreed_at": (
                user.partner_agreed_at.strftime("%d.%m.%Y %H:%M")
                if user.partner_agreed_at
                else None
            ),
            "partner_tier": get_partner_tier_by_total(
                user.partner_total_revenue_rub or 0
            ),
            "referral_earned": user.referral_earned or 0,
            "overview": overview,
            "referrals": [
                {
                    "telegram_id": row["telegram_id"],
                    "credits": Credits(row["credits"] or 0),
                    "has_paid": bool(row["has_paid"]),
                    "created_at": row["created_at"],
                    "referral_created_at": row["referral_created_at"],
                    "spent_rub": round(row["spent_rub"] or 0, 2),
                    "payments_count": row["payments_count"] or 0,
                    "subrefs_count": row["subrefs_count"] or 0,
                }
                for row in referral_rows
            ],
        }


async def get_admin_partner_payment_report(
    telegram_id: int,
    referrals_limit: int = 5000,
    payments_limit: int = 5000,
) -> Optional[dict]:
    """Возвращает XLS-детализацию оплат прямых рефералов партнёра."""
    safe_referrals_limit = max(1, min(int(referrals_limit or 5000), 20000))
    safe_payments_limit = max(1, min(int(payments_limit or 5000), 20000))

    details = await get_admin_partner_details(
        telegram_id,
        referrals_limit=safe_referrals_limit,
    )
    if not details:
        return None

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        summary_cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS payments_count,
                COALESCE(SUM(t.amount_rub), 0) AS paid_rub,
                COALESCE(SUM(t.credits), 0) AS paid_credits
            FROM users partner
            JOIN referrals r ON r.referrer_id = partner.id
            JOIN users referred ON referred.id = r.referred_id
            JOIN transactions t ON t.user_id = referred.id
            WHERE partner.telegram_id = ?
              AND referred.referred_by = r.referrer_id
              AND t.status = 'completed'
              AND datetime(t.created_at) >= datetime(r.created_at)
            """,
            (telegram_id,),
        )
        summary_row = await summary_cursor.fetchone()

        payments_cursor = await db.execute(
            """
            SELECT
                t.id AS transaction_id,
                t.created_at,
                t.order_id,
                t.payment_id,
                t.provider,
                t.credits,
                t.amount_rub,
                referred.id AS referred_user_id,
                referred.telegram_id AS referred_telegram_id,
                referred.referral_code AS referred_code,
                r.created_at AS referral_created_at
            FROM users partner
            JOIN referrals r ON r.referrer_id = partner.id
            JOIN users referred ON referred.id = r.referred_id
            JOIN transactions t ON t.user_id = referred.id
            WHERE partner.telegram_id = ?
              AND referred.referred_by = r.referrer_id
              AND t.status = 'completed'
              AND datetime(t.created_at) >= datetime(r.created_at)
            ORDER BY datetime(t.created_at) DESC, t.id DESC
            LIMIT ?
            """,
            (telegram_id, safe_payments_limit),
        )
        payment_rows = await payments_cursor.fetchall()

    return {
        **details,
        "limits": {
            "referrals": safe_referrals_limit,
            "payments": safe_payments_limit,
        },
        "payments_summary": {
            "payments_count": summary_row["payments_count"] or 0,
            "paid_rub": round(float(summary_row["paid_rub"] or 0), 2),
            "paid_credits": summary_row["paid_credits"] or 0,
        },
        "payments": [
            {
                "transaction_id": row["transaction_id"],
                "created_at": row["created_at"],
                "order_id": row["order_id"] or "",
                "payment_id": row["payment_id"] or "",
                "provider": row["provider"] or "",
                "credits": row["credits"] or 0,
                "amount_rub": round(float(row["amount_rub"] or 0), 2),
                "referred_user_id": row["referred_user_id"],
                "referred_telegram_id": row["referred_telegram_id"],
                "referred_code": row["referred_code"] or "",
                "referral_created_at": row["referral_created_at"],
            }
            for row in payment_rows
        ],
    }


def _sqlite_rows_to_dicts(rows: list[db_backend.Row]) -> list[dict]:
    return [{key: row[key] for key in row.keys()} for row in rows]


def _safe_report_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 100
    return max(1, min(value, 5000))


async def get_admin_finance_report(limit: int = 100) -> dict:
    """Детальный финансово-реферальный отчёт для админки."""
    safe_limit = _safe_report_limit(limit)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_topups,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN amount_rub ELSE 0 END), 0) AS completed_revenue_rub,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN credits ELSE 0 END), 0) AS completed_credits,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN promo_bonus_credits ELSE 0 END), 0) AS completed_promo_bonus_credits,
                COALESCE(SUM(CASE WHEN status = 'completed' AND promo_bonus_credits > 0 THEN 1 ELSE 0 END), 0) AS completed_promo_count,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_count,
                COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_count,
                COALESCE(SUM(CASE WHEN status NOT IN ('completed', 'pending') THEN 1 ELSE 0 END), 0) AS failed_count
            FROM transactions
            """
        )
        topups_summary = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                t.id,
                t.order_id,
                t.payment_id,
                t.provider,
                t.credits,
                t.amount_rub,
                t.promo_code,
                t.promo_bonus_credits,
                t.status,
                t.created_at,
                u.id AS user_db_id,
                u.telegram_id,
                u.credits AS user_balance,
                u.referral_code,
                ref.telegram_id AS referrer_telegram_id,
                ref.referral_code AS referrer_code,
                pc.partner_name AS promo_partner_name,
                pc.partner_telegram_id AS promo_partner_telegram_id
            FROM transactions t
            JOIN users u ON u.id = t.user_id
            LEFT JOIN users ref ON ref.id = u.referred_by
            LEFT JOIN promo_codes pc ON pc.id = t.promo_code_id
            ORDER BY datetime(t.created_at) DESC, t.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        topups = _sqlite_rows_to_dicts(await cursor.fetchall())

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_rows,
                COALESCE(SUM(cost), 0) AS total_cost
            FROM generation_tasks
            WHERE COALESCE(cost, 0) > 0
            """
        )
        task_deductions_summary = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_rows,
                COALESCE(SUM(cost), 0) AS total_cost
            FROM generation_history
            WHERE COALESCE(cost, 0) > 0
            """
        )
        history_deductions_summary = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_rows,
                COALESCE(SUM(total_cost), 0) AS total_cost
            FROM batch_jobs
            WHERE COALESCE(total_cost, 0) > 0
            """
        )
        batch_deductions_summary = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                'generation_task' AS source,
                gt.id,
                gt.task_id,
                gt.type,
                gt.preset_id,
                gt.model,
                gt.duration,
                gt.aspect_ratio,
                gt.prompt,
                gt.cost,
                gt.status,
                gt.result_url,
                gt.request_data,
                gt.created_at,
                gt.completed_at,
                gt.updated_at,
                u.id AS user_db_id,
                u.telegram_id,
                u.credits AS user_balance,
                ref.telegram_id AS referrer_telegram_id,
                ref.referral_code AS referrer_code
            FROM generation_tasks gt
            JOIN users u ON u.id = gt.user_id
            LEFT JOIN users ref ON ref.id = u.referred_by
            WHERE COALESCE(gt.cost, 0) > 0
            ORDER BY datetime(gt.created_at) DESC, gt.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        deductions = _sqlite_rows_to_dicts(await cursor.fetchall())

        cursor = await db.execute(
            """
            SELECT
                'generation_history' AS source,
                gh.id,
                NULL AS task_id,
                NULL AS type,
                gh.preset_id,
                NULL AS model,
                NULL AS duration,
                NULL AS aspect_ratio,
                gh.prompt,
                gh.cost,
                'completed' AS status,
                NULL AS result_url,
                NULL AS request_data,
                gh.created_at,
                NULL AS completed_at,
                NULL AS updated_at,
                u.id AS user_db_id,
                u.telegram_id,
                u.credits AS user_balance,
                ref.telegram_id AS referrer_telegram_id,
                ref.referral_code AS referrer_code
            FROM generation_history gh
            JOIN users u ON u.id = gh.user_id
            LEFT JOIN users ref ON ref.id = u.referred_by
            WHERE COALESCE(gh.cost, 0) > 0
            ORDER BY datetime(gh.created_at) DESC, gh.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        deductions.extend(_sqlite_rows_to_dicts(await cursor.fetchall()))

        cursor = await db.execute(
            """
            SELECT
                'batch_job' AS source,
                bj.id,
                bj.job_id AS task_id,
                bj.mode AS type,
                NULL AS preset_id,
                NULL AS model,
                bj.duration AS duration,
                NULL AS aspect_ratio,
                NULL AS prompt,
                bj.total_cost AS cost,
                'completed' AS status,
                NULL AS result_url,
                NULL AS request_data,
                bj.created_at,
                NULL AS completed_at,
                NULL AS updated_at,
                u.id AS user_db_id,
                u.telegram_id,
                u.credits AS user_balance,
                ref.telegram_id AS referrer_telegram_id,
                ref.referral_code AS referrer_code,
                bj.results_count
            FROM batch_jobs bj
            JOIN users u ON u.id = bj.user_id
            LEFT JOIN users ref ON ref.id = u.referred_by
            WHERE COALESCE(bj.total_cost, 0) > 0
            ORDER BY datetime(bj.created_at) DESC, bj.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        deductions.extend(_sqlite_rows_to_dicts(await cursor.fetchall()))
        deductions.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        deductions = deductions[:safe_limit]

        cursor = await db.execute(
            """
            SELECT
                r.id,
                r.created_at AS referral_created_at,
                r.bonus_credits,
                ref.id AS referrer_user_id,
                ref.telegram_id AS referrer_telegram_id,
                ref.referral_code AS referrer_code,
                ref.partner_tier AS referrer_tier,
                ref.partner_balance_rub AS referrer_balance_rub,
                ref.partner_total_revenue_rub AS referrer_total_revenue_rub,
                u.id AS referred_user_id,
                u.telegram_id AS referred_telegram_id,
                u.referral_code AS referred_code,
                u.created_at AS referred_created_at,
                u.credits AS referred_balance,
                u.has_paid AS referred_has_paid,
                COALESCE(pay.payments_count, 0) AS payments_count,
                COALESCE(pay.paid_rub, 0) AS paid_rub,
                COALESCE(pay.paid_credits, 0) AS paid_credits,
                pay.last_payment_at,
                (
                    SELECT COUNT(*)
                    FROM users sub
                    WHERE sub.referred_by = u.id
                ) AS subrefs_count
            FROM referrals r
            JOIN users ref ON ref.id = r.referrer_id
            JOIN users u ON u.id = r.referred_id
            LEFT JOIN (
                SELECT
                    user_id,
                    COUNT(*) AS payments_count,
                    SUM(amount_rub) AS paid_rub,
                    SUM(credits) AS paid_credits,
                    MAX(created_at) AS last_payment_at
                FROM transactions
                WHERE status = 'completed'
                GROUP BY user_id
            ) pay ON pay.user_id = u.id
            ORDER BY datetime(r.created_at) DESC, r.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        referrals_l1 = _sqlite_rows_to_dicts(await cursor.fetchall())

        cursor = await db.execute(
            """
            SELECT
                root.id AS root_partner_user_id,
                root.telegram_id AS root_partner_telegram_id,
                root.referral_code AS root_partner_code,
                root.partner_tier AS root_partner_tier,
                l1.id AS line1_user_id,
                l1.telegram_id AS line1_telegram_id,
                l1.referral_code AS line1_code,
                l1.created_at AS line1_created_at,
                l2.id AS line2_user_id,
                l2.telegram_id AS line2_telegram_id,
                l2.referral_code AS line2_code,
                l2.created_at AS line2_created_at,
                l2.credits AS line2_balance,
                l2.has_paid AS line2_has_paid,
                r.created_at AS referral_created_at,
                r.bonus_credits,
                COALESCE(pay.payments_count, 0) AS payments_count,
                COALESCE(pay.paid_rub, 0) AS paid_rub,
                COALESCE(pay.paid_credits, 0) AS paid_credits,
                pay.last_payment_at
            FROM users l2
            JOIN users l1 ON l1.id = l2.referred_by
            JOIN users root ON root.id = l1.referred_by
            LEFT JOIN referrals r ON r.referrer_id = l1.id AND r.referred_id = l2.id
            LEFT JOIN (
                SELECT
                    user_id,
                    COUNT(*) AS payments_count,
                    SUM(amount_rub) AS paid_rub,
                    SUM(credits) AS paid_credits,
                    MAX(created_at) AS last_payment_at
                FROM transactions
                WHERE status = 'completed'
                GROUP BY user_id
            ) pay ON pay.user_id = l2.id
            ORDER BY datetime(l2.created_at) DESC, l2.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        referrals_l2 = _sqlite_rows_to_dicts(await cursor.fetchall())

        cursor = await db.execute(
            """
            SELECT COUNT(*) AS commission_rows_count
            FROM transactions t
            JOIN users payer ON payer.id = t.user_id
            JOIN users l1 ON l1.id = payer.referred_by
            WHERE t.status = 'completed'
            """
        )
        commission_summary = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                t.id AS transaction_id,
                t.order_id,
                t.provider,
                t.credits,
                t.amount_rub,
                t.created_at,
                payer.id AS payer_user_id,
                payer.telegram_id AS payer_telegram_id,
                payer.referral_code AS payer_code,
                l1.id AS level1_partner_user_id,
                l1.telegram_id AS level1_partner_telegram_id,
                l1.referral_code AS level1_partner_code,
                l1.partner_tier AS level1_partner_tier,
                l2.id AS level2_partner_user_id,
                l2.telegram_id AS level2_partner_telegram_id,
                l2.referral_code AS level2_partner_code,
                l2.partner_tier AS level2_partner_tier
            FROM transactions t
            JOIN users payer ON payer.id = t.user_id
            JOIN users l1 ON l1.id = payer.referred_by
            LEFT JOIN users l2 ON l2.id = l1.referred_by
            WHERE t.status = 'completed'
            ORDER BY datetime(t.created_at) DESC, t.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        commission_rows = _sqlite_rows_to_dicts(await cursor.fetchall())
        partner_commissions = []
        total_level1_commission_rub = 0.0
        total_level2_commission_rub = 0.0
        for row in commission_rows:
            amount_rub = float(row.get("amount_rub") or 0)
            level1_commission = round(amount_rub * PARTNER_LEVEL1_PERCENT / 100, 2)
            level2_commission = (
                round(amount_rub * PARTNER_LEVEL2_PERCENT / 100, 2)
                if row.get("level2_partner_telegram_id")
                else 0.0
            )
            row["level1_percent"] = PARTNER_LEVEL1_PERCENT
            row["level1_commission_rub"] = level1_commission
            row["level2_percent"] = (
                PARTNER_LEVEL2_PERCENT if row.get("level2_partner_telegram_id") else 0
            )
            row["level2_commission_rub"] = level2_commission
            partner_commissions.append(row)
            total_level1_commission_rub += level1_commission
            total_level2_commission_rub += level2_commission

        cursor = await db.execute(
            """
            SELECT
                pw.id,
                pw.amount_rub,
                pw.method,
                pw.requisites,
                pw.status,
                pw.created_at,
                pw.updated_at,
                u.id AS user_db_id,
                u.telegram_id,
                u.partner_balance_rub AS current_balance_rub,
                u.partner_withdrawn_rub AS withdrawn_rub,
                u.partner_total_revenue_rub AS total_revenue_rub
            FROM partner_withdrawals pw
            JOIN users u ON u.id = pw.user_id
            ORDER BY datetime(pw.created_at) DESC, pw.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        withdrawals = _sqlite_rows_to_dicts(await cursor.fetchall())

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS referrals_l1_count,
                COALESCE(SUM(CASE WHEN referred.has_paid = 1 THEN 1 ELSE 0 END), 0) AS paid_l1_count
            FROM referrals r
            JOIN users referred ON referred.id = r.referred_id
            """
        )
        referrals_l1_summary = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT COUNT(*) AS referrals_l2_count
            FROM users l2
            JOIN users l1 ON l1.id = l2.referred_by
            JOIN users root ON root.id = l1.referred_by
            """
        )
        referrals_l2_summary = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_withdrawals,
                COALESCE(SUM(CASE WHEN status = 'requested' THEN amount_rub ELSE 0 END), 0) AS requested_rub,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN amount_rub ELSE 0 END), 0) AS completed_rub,
                COALESCE(SUM(CASE WHEN status = 'cancelled' THEN amount_rub ELSE 0 END), 0) AS cancelled_rub
            FROM partner_withdrawals
            """
        )
        withdrawals_summary = await cursor.fetchone()

        deductions_total_count = (
            (task_deductions_summary["total_rows"] or 0)
            + (history_deductions_summary["total_rows"] or 0)
            + (batch_deductions_summary["total_rows"] or 0)
        )
        deductions_total_cost = (
            float(task_deductions_summary["total_cost"] or 0)
            + float(history_deductions_summary["total_cost"] or 0)
            + float(batch_deductions_summary["total_cost"] or 0)
        )

        return {
            "limit": safe_limit,
            "summary": {
                "topups_count": topups_summary["total_topups"] or 0,
                "completed_topups_count": topups_summary["completed_count"] or 0,
                "pending_topups_count": topups_summary["pending_count"] or 0,
                "failed_topups_count": topups_summary["failed_count"] or 0,
                "completed_revenue_rub": round(
                    float(topups_summary["completed_revenue_rub"] or 0), 2
                ),
                "completed_credits": topups_summary["completed_credits"] or 0,
                "completed_promo_bonus_credits": (
                    topups_summary["completed_promo_bonus_credits"] or 0
                ),
                "completed_promo_count": topups_summary["completed_promo_count"] or 0,
                "deductions_count": deductions_total_count,
                "deductions_cost": round(deductions_total_cost, 2),
                "referrals_l1_count": referrals_l1_summary["referrals_l1_count"] or 0,
                "paid_referrals_l1_count": referrals_l1_summary["paid_l1_count"] or 0,
                "referrals_l2_count": referrals_l2_summary["referrals_l2_count"] or 0,
                "commission_rows_count": commission_summary["commission_rows_count"] or 0,
                "level1_commission_sample_rub": round(
                    total_level1_commission_rub, 2
                ),
                "level2_commission_sample_rub": round(
                    total_level2_commission_rub, 2
                ),
                "withdrawals_count": withdrawals_summary["total_withdrawals"] or 0,
                "withdrawals_requested_rub": round(
                    float(withdrawals_summary["requested_rub"] or 0), 2
                ),
                "withdrawals_completed_rub": round(
                    float(withdrawals_summary["completed_rub"] or 0), 2
                ),
                "withdrawals_cancelled_rub": round(
                    float(withdrawals_summary["cancelled_rub"] or 0), 2
                ),
            },
            "topups": topups,
            "deductions": deductions,
            "referrals_l1": referrals_l1,
            "referrals_l2": referrals_l2,
            "partner_commissions": partner_commissions,
            "withdrawals": withdrawals,
            "notes": [
                "Партнёрские начисления восстановлены расчётно по завершённым платежам и текущим процентам программы.",
                "Списания собраны из generation_tasks, generation_history и batch_jobs.",
            ],
        }


async def get_partner_pending_withdrawals_sum(telegram_id: int) -> float:
    """Сумма ожидающих заявок на вывод по пользователю."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(pw.amount_rub), 0) AS total
            FROM partner_withdrawals pw
            JOIN users u ON u.id = pw.user_id
            WHERE u.telegram_id = ?
              AND pw.status = 'requested'
            """,
            (telegram_id,),
        )
        row = await cursor.fetchone()
        return round(float(row["total"] or 0), 2)


async def get_partner_available_withdrawal(telegram_id: int) -> float:
    """Доступная к заказу сумма с учётом уже ожидающих заявок."""
    user = await get_or_create_user(telegram_id)
    pending_sum = await get_partner_pending_withdrawals_sum(telegram_id)
    return round(max(0.0, float(user.partner_balance_rub or 0) - pending_sum), 2)


async def exchange_partner_balance_to_credits(
    telegram_id: int, requested_amount_rub: float, rub_per_credit: float
) -> dict:
    """Мгновенно обменивает часть партнёрского баланса на бананы."""
    requested_amount_rub = round(float(requested_amount_rub or 0), 2)
    rub_per_credit = float(rub_per_credit or 0)
    if requested_amount_rub <= 0:
        return {"ok": False, "reason": "invalid_amount"}
    if rub_per_credit <= 0:
        return {"ok": False, "reason": "invalid_rate"}

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await db.execute("BEGIN IMMEDIATE")

        user_cursor = await db.execute(
            "SELECT id, telegram_id, credits, partner_balance_rub, prompt_repeat_balance_rub, partner_agreed_at FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        user_row = await user_cursor.fetchone()
        if not user_row:
            await db.rollback()
            return {"ok": False, "reason": "user_not_found"}

        try:
            pending_cursor = await db.execute(
                """
                SELECT COALESCE(SUM(amount_rub), 0) AS pending_sum
                FROM partner_withdrawals
                WHERE user_id = ? AND status = 'requested'
                """,
                (user_row["id"],),
            )
            pending_row = await pending_cursor.fetchone()
            pending_sum = float(pending_row["pending_sum"] or 0) if pending_row else 0.0
        except db_backend.OperationalError:
            pending_sum = 0.0

        current_partner_balance = float(user_row["partner_balance_rub"] or 0)
        available_rub = round(max(0.0, current_partner_balance - pending_sum), 2)
        credits_to_add = int(requested_amount_rub / rub_per_credit)
        debit_amount_rub = round(credits_to_add * rub_per_credit, 2)

        if not user_row["partner_agreed_at"]:
            await db.rollback()
            return {"ok": False, "reason": "not_partner"}

        if credits_to_add < 1:
            await db.rollback()
            return {"ok": False, "reason": "too_small", "available_rub": available_rub}

        if debit_amount_rub > available_rub:
            await db.rollback()
            return {
                "ok": False,
                "reason": "insufficient_balance",
                "available_rub": available_rub,
                "requested_amount_rub": requested_amount_rub,
            }

        await db.execute(
            """
            UPDATE users
            SET credits = credits + ?,
                partner_balance_rub = partner_balance_rub - ?,
                prompt_repeat_balance_rub = MIN(
                    COALESCE(prompt_repeat_balance_rub, 0),
                    MAX(COALESCE(partner_balance_rub, 0) - ?, 0)
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
            """,
            (credits_to_add, debit_amount_rub, debit_amount_rub, telegram_id),
        )
        await db.commit()

    logger.info(
        "Partner balance exchanged to credits: user=%s rub=%s credits=%s rate=%s",
        telegram_id,
        debit_amount_rub,
        credits_to_add,
        rub_per_credit,
    )
    return {
        "ok": True,
        "credits_added": credits_to_add,
        "debited_rub": debit_amount_rub,
        "requested_amount_rub": requested_amount_rub,
        "available_rub_before": available_rub,
        "available_rub_after": round(max(0.0, available_rub - debit_amount_rub), 2),
        "rate_rub_per_credit": rub_per_credit,
    }


async def create_partner_withdrawal(
    telegram_id: int,
    amount_rub: float,
    method: str,
    requisites: str,
    min_amount_rub: Optional[float] = None,
) -> Optional[dict]:
    """Создаёт заявку на вывод без мгновенного списания баланса.

    Вся проверка баланса выполняется внутри одной транзакции (BEGIN IMMEDIATE),
    чтобы исключить race condition при двух параллельных запросах.
    """
    from bot.config import config as _cfg

    _min = float(getattr(_cfg, "PARTNER_MIN_WITHDRAWAL_RUB", 0)) if min_amount_rub is None else min_amount_rub

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        # Эксклюзивная блокировка на запись — сериализует конкурентные запросы
        await db.execute("BEGIN IMMEDIATE")
        try:
            user_cur = await db.execute(
                "SELECT id, partner_agreed_at, partner_balance_rub FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            user_row = await user_cur.fetchone()
            if not user_row or not user_row["partner_agreed_at"]:
                await db.rollback()
                return None

            user_id = user_row["id"]
            balance = float(user_row["partner_balance_rub"] or 0)

            pending_cur = await db.execute(
                "SELECT COALESCE(SUM(amount_rub), 0) AS total FROM partner_withdrawals "
                "WHERE user_id = ? AND status = 'requested'",
                (user_id,),
            )
            pending_row = await pending_cur.fetchone()
            pending = float(pending_row["total"] or 0)
            available = round(max(0.0, balance - pending), 2)

            if amount_rub > available:
                await db.rollback()
                return None
            if _min > 0 and amount_rub < _min:
                await db.rollback()
                return None

            cursor = await db.execute(
                "INSERT INTO partner_withdrawals (user_id, amount_rub, method, requisites, status) "
                "VALUES (?, ?, ?, ?, 'requested')",
                (user_id, amount_rub, method, requisites),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return {
            "id": cursor.lastrowid,
            "telegram_id": telegram_id,
            "amount_rub": round(amount_rub, 2),
            "method": method,
            "requisites": requisites,
            "current_balance_rub": round(balance, 2),
            "remaining_available_rub": round(max(0.0, available - amount_rub), 2),
        }


async def get_partner_withdrawal_request(withdrawal_id: int) -> Optional[dict]:
    """Возвращает заявку на вывод вместе с текущим балансом пользователя."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                pw.id,
                pw.user_id,
                u.telegram_id,
                u.partner_balance_rub,
                pw.amount_rub,
                pw.method,
                pw.requisites,
                pw.status,
                pw.created_at
            FROM partner_withdrawals pw
            JOIN users u ON u.id = pw.user_id
            WHERE pw.id = ?
            """,
            (withdrawal_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "telegram_id": row["telegram_id"],
            "amount_rub": round(float(row["amount_rub"] or 0), 2),
            "method": row["method"] or "",
            "requisites": row["requisites"] or "",
            "status": row["status"],
            "created_at": row["created_at"],
            "current_balance_rub": round(float(row["partner_balance_rub"] or 0), 2),
        }


async def get_pending_partner_withdrawals(limit: int = 20) -> list[dict]:
    """Возвращает список ожидающих заявок на вывод для админки."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                pw.id,
                u.telegram_id,
                pw.amount_rub,
                pw.method,
                pw.requisites,
                pw.created_at,
                u.partner_balance_rub
            FROM partner_withdrawals pw
            JOIN users u ON u.id = pw.user_id
            WHERE pw.status = 'requested'
            ORDER BY pw.created_at ASC, pw.id ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

        return [
            {
                "id": row["id"],
                "telegram_id": row["telegram_id"],
                "amount_rub": round(float(row["amount_rub"] or 0), 2),
                "method": row["method"] or "",
                "requisites": row["requisites"] or "",
                "created_at": row["created_at"],
                "current_balance_rub": round(float(row["partner_balance_rub"] or 0), 2),
            }
            for row in rows
        ]


async def approve_partner_withdrawal(withdrawal_id: int) -> Optional[dict]:
    """Подтверждает заявку и только в этот момент списывает сумму с баланса."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                pw.id,
                pw.user_id,
                u.telegram_id,
                u.partner_balance_rub,
                pw.amount_rub,
                pw.status,
                pw.requisites
            FROM partner_withdrawals pw
            JOIN users u ON u.id = pw.user_id
            WHERE pw.id = ?
            """,
            (withdrawal_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        if row["status"] != "requested":
            return {
                "ok": False,
                "reason": "already_processed",
                "status": row["status"],
                "telegram_id": row["telegram_id"],
            }

        current_balance = float(row["partner_balance_rub"] or 0)
        amount_rub = float(row["amount_rub"] or 0)
        if current_balance < amount_rub:
            return {
                "ok": False,
                "reason": "insufficient_balance",
                "status": row["status"],
                "telegram_id": row["telegram_id"],
                "current_balance_rub": round(current_balance, 2),
                "amount_rub": round(amount_rub, 2),
            }

        await db.execute(
            """
            UPDATE partner_withdrawals
            SET status = 'completed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (withdrawal_id,),
        )
        await db.execute(
            """
            UPDATE users
            SET partner_balance_rub = partner_balance_rub - ?,
                partner_withdrawn_rub = partner_withdrawn_rub + ?,
                prompt_repeat_balance_rub = MIN(
                    COALESCE(prompt_repeat_balance_rub, 0),
                    MAX(COALESCE(partner_balance_rub, 0) - ?, 0)
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (amount_rub, amount_rub, amount_rub, row["user_id"]),
        )
        await db.commit()

        return {
            "ok": True,
            "status": "completed",
            "telegram_id": row["telegram_id"],
            "amount_rub": round(amount_rub, 2),
            "current_balance_rub": round(current_balance, 2),
            "new_balance_rub": round(current_balance - amount_rub, 2),
            "requisites": row["requisites"] or "",
        }


async def cancel_partner_withdrawal(withdrawal_id: int) -> Optional[dict]:
    """Отменяет заявку без списания баланса."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                pw.id,
                u.telegram_id,
                pw.amount_rub,
                pw.status
            FROM partner_withdrawals pw
            JOIN users u ON u.id = pw.user_id
            WHERE pw.id = ?
            """,
            (withdrawal_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        if row["status"] != "requested":
            return {
                "ok": False,
                "reason": "already_processed",
                "status": row["status"],
                "telegram_id": row["telegram_id"],
            }

        await db.execute(
            """
            UPDATE partner_withdrawals
            SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (withdrawal_id,),
        )
        await db.commit()

        return {
            "ok": True,
            "status": "cancelled",
            "telegram_id": row["telegram_id"],
            "amount_rub": round(float(row["amount_rub"] or 0), 2),
        }


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _saved_reference_from_row(row: db_backend.Row) -> SavedReference:
    return SavedReference(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        file_url=row["file_url"],
        file_hash=row["file_hash"],
        original_filename=row["original_filename"],
        content_type=row["content_type"],
        source=row["source"],
        created_at=_parse_optional_datetime(row["created_at"]),
        updated_at=_parse_optional_datetime(row["updated_at"]),
        last_used_at=_parse_optional_datetime(row["last_used_at"]),
    )


def _saved_reference_to_payload(reference: SavedReference) -> dict:
    return {
        "id": reference.id,
        "user_id": reference.user_id,
        "kind": reference.kind,
        "file_url": reference.file_url,
        "file_hash": reference.file_hash,
        "original_filename": reference.original_filename,
        "content_type": reference.content_type,
        "source": reference.source,
        "created_at": reference.created_at.isoformat() if reference.created_at else None,
        "updated_at": reference.updated_at.isoformat() if reference.updated_at else None,
        "last_used_at": reference.last_used_at.isoformat() if reference.last_used_at else None,
    }


def _saved_reference_from_payload(payload: dict) -> SavedReference:
    return SavedReference(
        id=int(payload.get("id", 0)),
        user_id=int(payload.get("user_id", 0)),
        kind=str(payload.get("kind", "image")),
        file_url=str(payload.get("file_url", "")),
        file_hash=str(payload.get("file_hash", "")),
        original_filename=payload.get("original_filename"),
        content_type=payload.get("content_type"),
        source=payload.get("source"),
        created_at=_parse_optional_datetime(payload.get("created_at")),
        updated_at=_parse_optional_datetime(payload.get("updated_at")),
        last_used_at=_parse_optional_datetime(payload.get("last_used_at")),
    )


def _saved_reference_is_available(reference: SavedReference) -> bool:
    try:
        from bot.services.media_input_utils import (
            is_local_upload_source,
            resolve_local_upload_path,
        )

        if is_local_upload_source(reference.file_url):
            return bool(resolve_local_upload_path(reference.file_url))
    except Exception:
        logger.exception("Failed to validate saved reference file: %s", reference.file_url)
        return True
    return True


def _filter_available_saved_references(
    references: list[SavedReference],
    *,
    limit: int,
) -> list[SavedReference]:
    return [item for item in references if _saved_reference_is_available(item)][:limit]


async def _invalidate_saved_reference_cache(telegram_id: int) -> None:
    try:
        from bot.services.redis_service import redis_service

        keys = []
        for kind in ("all", "image", "video", "audio"):
            for limit in (12, 24, 50):
                keys.append(redis_service.build_key(f"saved_refs:{telegram_id}:{kind}:{limit}"))
        for key in keys:
            await redis_service.delete(key)
    except Exception:
        logger.exception("Failed to invalidate saved reference cache for telegram_id=%s", telegram_id)


async def _remove_saved_reference_file(file_url: str) -> None:
    try:
        from bot.services.media_input_utils import resolve_local_upload_path

        local_path = resolve_local_upload_path(file_url)
        if not local_path or not os.path.exists(local_path):
            return

        os.remove(local_path)

        uploads_root = os.path.abspath(os.path.join("static", "uploads"))
        current_dir = os.path.dirname(os.path.abspath(local_path))
        while current_dir.startswith(uploads_root) and current_dir != uploads_root:
            try:
                if os.listdir(current_dir):
                    break
                os.rmdir(current_dir)
                current_dir = os.path.dirname(current_dir)
            except OSError:
                break
    except FileNotFoundError:
        return
    except Exception:
        logger.exception("Failed to remove saved reference file: %s", file_url)


async def _remove_saved_reference_files(file_urls: list[str]) -> None:
    for file_url in dict.fromkeys(url for url in file_urls if url):
        await _remove_saved_reference_file(file_url)


async def _prune_saved_references_for_user_id(
    db: db_backend.Connection,
    *,
    user_id: int,
    kind: str,
    keep_latest: int = SAVED_REFERENCES_MAX_PER_KIND,
) -> tuple[int, list[str]]:
    safe_keep_latest = max(1, int(keep_latest or SAVED_REFERENCES_MAX_PER_KIND))
    db.row_factory = db_backend.Row
    cursor = await db.execute(
        """
        SELECT id, file_url
        FROM saved_references
        WHERE user_id = ? AND kind = ?
        ORDER BY COALESCE(last_used_at, created_at) DESC, id DESC
        LIMIT -1 OFFSET ?
        """,
        (user_id, kind, safe_keep_latest),
    )
    stale_rows = await cursor.fetchall()
    if not stale_rows:
        return 0, []

    delete_ids = [int(row["id"]) for row in stale_rows]
    deleted_urls = [str(row["file_url"]) for row in stale_rows if row["file_url"]]

    id_placeholders = ", ".join("?" for _ in delete_ids)
    url_placeholders = ", ".join("?" for _ in deleted_urls)
    removable_urls = deleted_urls

    if deleted_urls:
        cursor = await db.execute(
            f"SELECT DISTINCT file_url FROM saved_references WHERE file_url IN ({url_placeholders}) AND id NOT IN ({id_placeholders})",
            [*deleted_urls, *delete_ids],
        )
        still_used_urls = {str(row[0]) for row in await cursor.fetchall() if row[0]}
        removable_urls = [url for url in deleted_urls if url not in still_used_urls]

    await db.execute(
        f"DELETE FROM saved_references WHERE id IN ({id_placeholders})",
        delete_ids,
    )
    return len(delete_ids), removable_urls


async def prune_saved_references_for_user(
    telegram_id: int,
    *,
    kind: Optional[str] = None,
    keep_latest: int = SAVED_REFERENCES_MAX_PER_KIND,
) -> int:
    user = await get_or_create_user(telegram_id)
    target_kinds = [kind] if kind in {"image", "video", "audio"} else ["image", "video", "audio"]
    removed_count = 0
    removable_urls: list[str] = []

    async with db_backend.connect(DATABASE_PATH) as db:
        for target_kind in target_kinds:
            deleted_count, deletable_urls = await _prune_saved_references_for_user_id(
                db,
                user_id=user.id,
                kind=target_kind,
                keep_latest=keep_latest,
            )
            removed_count += deleted_count
            removable_urls.extend(deletable_urls)
        await db.commit()

    if removed_count:
        await _remove_saved_reference_files(removable_urls)
        await _invalidate_saved_reference_cache(telegram_id)
    return removed_count


async def cleanup_saved_references(
    keep_latest: int = SAVED_REFERENCES_MAX_PER_KIND,
    *,
    max_age_days: int = 14,
    min_keep_per_kind: int = 1,
) -> int:
    safe_keep_latest = max(1, int(keep_latest or SAVED_REFERENCES_MAX_PER_KIND))
    safe_min_keep = max(1, min(int(min_keep_per_kind or 1), safe_keep_latest))
    safe_max_age_days = max(0, int(max_age_days or 0))
    removed_count = 0
    removable_urls: list[str] = []
    telegram_ids: set[int] = set()

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT sr.user_id, u.telegram_id, sr.kind, COUNT(*) AS refs_count
            FROM saved_references sr
            JOIN users u ON u.id = sr.user_id
            GROUP BY sr.user_id, u.telegram_id, sr.kind
            HAVING COUNT(*) > ?
            """,
            (safe_keep_latest,),
        )
        groups = await cursor.fetchall()

        for group in groups:
            deleted_count, deletable_urls = await _prune_saved_references_for_user_id(
                db,
                user_id=int(group["user_id"]),
                kind=str(group["kind"]),
                keep_latest=safe_keep_latest,
            )
            removed_count += deleted_count
            removable_urls.extend(deletable_urls)
            if group["telegram_id"]:
                telegram_ids.add(int(group["telegram_id"]))

        if safe_max_age_days > 0:
            age_modifier = f"-{safe_max_age_days} days"
            old_rows_cursor = await db.execute(
                """
                WITH ranked AS (
                    SELECT sr.id, sr.file_url, u.telegram_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY sr.user_id, sr.kind
                               ORDER BY datetime(COALESCE(sr.last_used_at, sr.created_at)) DESC, sr.id DESC
                           ) AS rn
                    FROM saved_references sr
                    JOIN users u ON u.id = sr.user_id
                    WHERE datetime(COALESCE(sr.last_used_at, sr.created_at)) < datetime('now', ?)
                )
                SELECT id, file_url, telegram_id
                FROM ranked
                WHERE rn > ?
                """,
                (age_modifier, safe_min_keep),
            )
            old_rows = await old_rows_cursor.fetchall()
            if old_rows:
                await db.executemany(
                    "DELETE FROM saved_references WHERE id = ?",
                    [(int(row["id"]),) for row in old_rows],
                )
                removed_count += len(old_rows)
                removable_urls.extend(
                    str(row["file_url"] or "")
                    for row in old_rows
                    if row["file_url"]
                )
                telegram_ids.update(
                    int(row["telegram_id"])
                    for row in old_rows
                    if row["telegram_id"]
                )

        await db.commit()

    if removable_urls:
        logger.info(
            "Pruned %s saved reference rows; files are left for orphan cleanup",
            len(removable_urls),
        )

    for telegram_id in telegram_ids:
        await _invalidate_saved_reference_cache(telegram_id)

    return removed_count


async def cleanup_orphaned_reference_files(max_age_seconds: int = 24 * 3600) -> dict[str, int]:
    base_dir = os.path.join("static", "uploads", "refs")
    if not os.path.exists(base_dir):
        return {"removed_count": 0, "removed_bytes": 0}

    from bot.services.media_input_utils import resolve_local_upload_path

    referenced_paths: set[str] = set()
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT file_url FROM saved_references WHERE file_url IS NOT NULL AND TRIM(file_url) != ''"
        )
        rows = await cursor.fetchall()

    for row in rows:
        local_path = resolve_local_upload_path(str(row[0] or ""))
        if local_path:
            abs_path = os.path.abspath(local_path)
            referenced_paths.add(abs_path)
            base_path, _ext = os.path.splitext(abs_path)
            for sibling_ext in (".png", ".jpg", ".jpeg", ".webp"):
                sibling_path = base_path + sibling_ext
                if os.path.exists(sibling_path):
                    referenced_paths.add(os.path.abspath(sibling_path))

    now = time.time()
    removed_count = 0
    removed_bytes = 0

    for root, dirs, files in os.walk(base_dir, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.abspath(path) in referenced_paths:
                    continue
                if now - os.path.getmtime(path) <= max_age_seconds:
                    continue
                removed_bytes += os.path.getsize(path)
                os.remove(path)
                removed_count += 1
            except FileNotFoundError:
                continue
            except Exception:
                logger.exception("Failed to remove orphaned reference file: %s", path)

        for dirname in dirs:
            directory = os.path.join(root, dirname)
            try:
                if not os.listdir(directory):
                    os.rmdir(directory)
            except OSError:
                pass

    return {"removed_count": removed_count, "removed_bytes": removed_bytes}


async def cleanup_stale_local_generation_tasks(
    max_age_seconds: int = 60 * 60,
) -> dict[str, float | int]:
    """Fail old local image tasks that never received a provider task id."""
    from bot.config import config

    cutoff_modifier = f"-{max(60, int(max_age_seconds))} seconds"
    refunded_credits = 0.0
    failed_count = 0

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, user_id, telegram_id, task_id, COALESCE(cost, 0) AS cost
            FROM generation_tasks
            WHERE status = 'pending'
              AND type = 'image'
              AND task_id LIKE ?
              AND datetime(created_at) < datetime('now', ?)
            """,
            ('img_%', cutoff_modifier),
        )
        rows = await cursor.fetchall()

        for row in rows:
            result = await db.execute(
                """
                UPDATE generation_tasks
                SET status = 'failed',
                    result_url = NULL,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (int(row["id"]),),
            )
            if result.rowcount <= 0:
                continue

            failed_count += 1
            cost = float(row["cost"] or 0)
            telegram_id = int(row["telegram_id"] or 0)
            if cost > 0 and telegram_id and not config.is_admin(telegram_id):
                await db.execute(
                    "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (cost, int(row["user_id"])),
                )
                refunded_credits += cost

        await db.commit()

    if failed_count:
        logger.info(
            "Cleaned stale local generation tasks: failed=%s refunded_credits=%s",
            failed_count,
            refunded_credits,
        )
    return {"failed_count": failed_count, "refunded_credits": refunded_credits}


async def get_saved_reference_by_hash(telegram_id: int, kind: str, file_hash: str) -> Optional[SavedReference]:
    user = await get_or_create_user(telegram_id)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM saved_references
            WHERE user_id = ? AND kind = ? AND file_hash = ?
            LIMIT 1
            """,
            (user.id, kind, file_hash),
        )
        row = await cursor.fetchone()
        return _saved_reference_from_row(row) if row else None


async def get_saved_reference_by_id(telegram_id: int, reference_id: int) -> Optional[SavedReference]:
    user = await get_or_create_user(telegram_id)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT * FROM saved_references WHERE id = ? AND user_id = ? LIMIT 1",
            (reference_id, user.id),
        )
        row = await cursor.fetchone()
        return _saved_reference_from_row(row) if row else None


async def delete_saved_reference(telegram_id: int, reference_id: int) -> bool:
    user = await get_or_create_user(telegram_id)
    file_url: str | None = None

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT file_url FROM saved_references WHERE id = ? AND user_id = ? LIMIT 1",
            (reference_id, user.id),
        )
        row = await cursor.fetchone()
        if not row:
            return False

        file_url = row["file_url"]
        await db.execute(
            "DELETE FROM saved_references WHERE id = ? AND user_id = ?",
            (reference_id, user.id),
        )
        await db.commit()

        if file_url:
            cursor = await db.execute(
                "SELECT 1 FROM saved_references WHERE file_url = ? LIMIT 1",
                (file_url,),
            )
            still_used = await cursor.fetchone()
        else:
            still_used = True

    if file_url and not still_used:
        await _remove_saved_reference_file(file_url)
    await _invalidate_saved_reference_cache(telegram_id)
    return True


async def save_user_reference(
    telegram_id: int,
    *,
    kind: str,
    file_url: str,
    file_hash: str,
    original_filename: Optional[str] = None,
    content_type: Optional[str] = None,
    source: str = "telegram",
) -> SavedReference:
    user = await get_or_create_user(telegram_id)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await db.execute(
            """
            INSERT INTO saved_references (user_id, kind, file_url, file_hash, original_filename, content_type, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, kind, file_hash) DO UPDATE SET
                file_url = excluded.file_url,
                original_filename = COALESCE(excluded.original_filename, saved_references.original_filename),
                content_type = COALESCE(excluded.content_type, saved_references.content_type),
                source = COALESCE(excluded.source, saved_references.source),
                updated_at = CURRENT_TIMESTAMP,
                last_used_at = CURRENT_TIMESTAMP
            """,
            (user.id, kind, file_url, file_hash, original_filename, content_type, source),
        )
        await db.commit()
        await _prune_saved_references_for_user_id(
            db,
            user_id=user.id,
            kind=kind,
            keep_latest=SAVED_REFERENCES_MAX_PER_KIND,
        )
        await db.commit()
        cursor = await db.execute(
            """
            SELECT *
            FROM saved_references
            WHERE user_id = ? AND kind = ? AND file_hash = ?
            LIMIT 1
            """,
            (user.id, kind, file_hash),
        )
        row = await cursor.fetchone()
    await _invalidate_saved_reference_cache(telegram_id)
    return _saved_reference_from_row(row)


async def touch_saved_references(telegram_id: int, file_urls: list[str], kind: Optional[str] = None) -> None:
    urls = [str(url).strip() for url in (file_urls or []) if str(url).strip()]
    if not urls:
        return

    user = await get_or_create_user(telegram_id)
    placeholders = ", ".join("?" for _ in urls)
    params: list = [user.id, *urls]
    where_kind = ""
    if kind:
        where_kind = " AND kind = ?"
        params.append(kind)

    async with db_backend.connect(DATABASE_PATH) as db:
        await db.execute(
            f"UPDATE saved_references SET last_used_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND file_url IN ({placeholders}){where_kind}",
            params,
        )
        await db.commit()
    await _invalidate_saved_reference_cache(telegram_id)


async def list_saved_references(telegram_id: int, kind: Optional[str] = None, limit: int = 24) -> list[SavedReference]:
    safe_kind = kind if kind in {"image", "video", "audio"} else None
    safe_limit = max(1, min(int(limit or 24), 50))
    cache_kind = safe_kind or "all"
    cache_key_suffix = f"saved_refs:{telegram_id}:{cache_kind}:{safe_limit}"

    try:
        from bot.services.redis_service import redis_service

        cached = await redis_service.get(redis_service.build_key(cache_key_suffix))
        if cached:
            payload = json.loads(cached)
            if isinstance(payload, list):
                references = [
                    _saved_reference_from_payload(item)
                    for item in payload
                    if isinstance(item, dict)
                ]
                available = _filter_available_saved_references(references, limit=safe_limit)
                if len(available) == len(references):
                    return available
    except Exception:
        logger.exception("Failed to read saved references cache for telegram_id=%s", telegram_id)

    user = await get_or_create_user(telegram_id)
    query = "SELECT * FROM saved_references WHERE user_id = ?"
    params: list = [user.id]
    if safe_kind:
        query += " AND kind = ?"
        params.append(safe_kind)
    query += " ORDER BY COALESCE(last_used_at, created_at) DESC, id DESC LIMIT ?"
    params.append(safe_limit * 3)

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    references = _filter_available_saved_references(
        [_saved_reference_from_row(row) for row in rows],
        limit=safe_limit,
    )

    try:
        from bot.services.redis_service import redis_service

        await redis_service.set(
            redis_service.build_key(cache_key_suffix),
            json.dumps([_saved_reference_to_payload(item) for item in references], ensure_ascii=False),
            ttl_seconds=3600,
        )
    except Exception:
        logger.exception("Failed to write saved references cache for telegram_id=%s", telegram_id)

    return references


async def get_referral_stats(telegram_id: int) -> dict:
    """Возвращает статистику по рефералам пользователя."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        user = await get_or_create_user(telegram_id)

        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM referrals WHERE referrer_id = ?",
            (user.id,),
        )
        row = await cursor.fetchone()

        return {
            "referral_code": user.referral_code or "",
            "referrals_count": row["count"] or 0,
            # referral_earned хранит именно бонус пригласившему (+3🍌 за каждого)
            "referral_earned": user.referral_earned or 0,
        }


async def create_promo_code(
    code: str,
    *,
    partner_name: str | None = None,
    partner_telegram_id: int | None = None,
    created_by_telegram_id: int | None = None,
    is_active: bool = True,
) -> Optional[PromoCode]:
    """Создаёт многоразовый промокод для бонусов на пополнение."""
    normalized_code = normalize_promo_code(code)
    if len(normalized_code) < 2:
        raise ValueError("promo_code_too_short")

    clean_partner_name = str(partner_name or "").strip()[:80] or None
    partner_user_id = None

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        if partner_telegram_id:
            cursor = await db.execute(
                "SELECT id FROM users WHERE telegram_id = ? LIMIT 1",
                (int(partner_telegram_id),),
            )
            partner_row = await cursor.fetchone()
            if partner_row:
                partner_user_id = int(partner_row["id"])

        try:
            cursor = await db.execute(
                """
                INSERT INTO promo_codes (
                    code, partner_name, partner_telegram_id, partner_user_id,
                    is_active, created_by_telegram_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_code,
                    clean_partner_name,
                    int(partner_telegram_id) if partner_telegram_id else None,
                    partner_user_id,
                    1 if is_active else 0,
                    int(created_by_telegram_id) if created_by_telegram_id else None,
                ),
            )
            promo_id = cursor.lastrowid
            cursor = await db.execute(
                "SELECT * FROM promo_codes WHERE id = ?", (promo_id,)
            )
            row = await cursor.fetchone()
            await db.commit()
            return _row_to_promo_code(row)
        except db_backend.IntegrityError:
            await db.rollback()
            return None


async def get_promo_code_by_code(
    code: str, *, active_only: bool = True
) -> Optional[PromoCode]:
    normalized_code = normalize_promo_code(code)
    if not normalized_code:
        return None

    query = "SELECT * FROM promo_codes WHERE code = ?"
    params: tuple[Any, ...] = (normalized_code,)
    if active_only:
        query += " AND is_active = 1"
    query += " LIMIT 1"

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(query, params)
        return _row_to_promo_code(await cursor.fetchone())


async def get_promo_code_by_id(promo_code_id: int) -> Optional[PromoCode]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT * FROM promo_codes WHERE id = ? LIMIT 1", (int(promo_code_id),)
        )
        return _row_to_promo_code(await cursor.fetchone())


async def list_promo_codes(limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 20), 100))
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                pc.*,
                u.telegram_id AS linked_partner_telegram_id
            FROM promo_codes pc
            LEFT JOIN users u ON u.id = pc.partner_user_id
            ORDER BY pc.is_active DESC, pc.usage_count DESC, datetime(pc.created_at) DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        return _sqlite_rows_to_dicts(await cursor.fetchall())


async def get_admin_promo_stats(limit: int = 12) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 12), 50))
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_codes,
                COALESCE(SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END), 0) AS active_codes,
                COALESCE(SUM(usage_count), 0) AS usage_count,
                COALESCE(SUM(total_bonus_credits), 0) AS total_bonus_credits,
                COALESCE(SUM(total_amount_rub), 0) AS total_amount_rub
            FROM promo_codes
            """
        )
        summary = await cursor.fetchone()
        promocodes = await list_promo_codes(safe_limit)
        return {
            "total_codes": summary["total_codes"] or 0,
            "active_codes": summary["active_codes"] or 0,
            "usage_count": summary["usage_count"] or 0,
            "total_bonus_credits": summary["total_bonus_credits"] or 0,
            "total_amount_rub": round(float(summary["total_amount_rub"] or 0), 2),
            "promocodes": promocodes,
            "bonus_by_credits": dict(PROMO_BONUS_BY_CREDITS),
        }


async def get_promo_code_details(
    promo_code_id: int, redemptions_limit: int = 10
) -> Optional[dict[str, Any]]:
    safe_limit = max(1, min(int(redemptions_limit or 10), 50))
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                pc.*,
                u.telegram_id AS linked_partner_telegram_id
            FROM promo_codes pc
            LEFT JOIN users u ON u.id = pc.partner_user_id
            WHERE pc.id = ?
            LIMIT 1
            """,
            (int(promo_code_id),),
        )
        promo = await cursor.fetchone()
        if not promo:
            return None

        cursor = await db.execute(
            """
            SELECT
                pr.id,
                pr.amount_rub,
                pr.bonus_credits,
                pr.created_at,
                t.order_id,
                t.provider,
                u.telegram_id
            FROM promo_redemptions pr
            JOIN transactions t ON t.id = pr.transaction_id
            JOIN users u ON u.id = pr.user_id
            WHERE pr.promo_code_id = ?
            ORDER BY datetime(pr.created_at) DESC, pr.id DESC
            LIMIT ?
            """,
            (int(promo_code_id), safe_limit),
        )
        return {
            "promo": dict(promo),
            "redemptions": _sqlite_rows_to_dicts(await cursor.fetchall()),
            "bonus_by_credits": dict(PROMO_BONUS_BY_CREDITS),
        }


async def set_promo_code_active(promo_code_id: int, is_active: bool) -> Optional[PromoCode]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await db.execute(
            """
            UPDATE promo_codes
            SET is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if is_active else 0, int(promo_code_id)),
        )
        cursor = await db.execute(
            "SELECT * FROM promo_codes WHERE id = ? LIMIT 1", (int(promo_code_id),)
        )
        row = await cursor.fetchone()
        await db.commit()
        return _row_to_promo_code(row)


async def record_promo_redemption(transaction: Transaction) -> dict[str, Any]:
    """Фиксирует статистику промокода после успешного платежа."""
    promo_code_id = getattr(transaction, "promo_code_id", None)
    bonus_credits = int(getattr(transaction, "promo_bonus_credits", 0) or 0)
    if not promo_code_id or bonus_credits <= 0:
        return {}

    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO promo_redemptions (
                promo_code_id, transaction_id, user_id, amount_rub, bonus_credits
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(promo_code_id),
                int(transaction.id),
                int(transaction.user_id),
                float(transaction.amount_rub),
                bonus_credits,
            ),
        )
        inserted = cursor.rowcount > 0
        if inserted:
            await db.execute(
                """
                UPDATE promo_codes
                SET usage_count = usage_count + 1,
                    total_bonus_credits = total_bonus_credits + ?,
                    total_amount_rub = total_amount_rub + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (bonus_credits, float(transaction.amount_rub), int(promo_code_id)),
            )
        await db.commit()

    return {
        "code": getattr(transaction, "promo_code", None) or "",
        "bonus_credits": bonus_credits,
        "inserted": inserted,
    }


async def get_user_credits(telegram_id: int) -> Credits:
    """Получает баланс без потери дробной части кредита."""
    user = await get_or_create_user(telegram_id)
    return Credits(user.credits)


async def add_credits(telegram_id: int, amount: int) -> bool:
    """Добавляет кредиты пользователю"""
    if amount <= 0:
        logger.warning(f"add_credits: non-positive amount {amount} for user {telegram_id}")
        return False
    async with db_backend.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (amount, telegram_id),
        )
        await db.commit()
        logger.info(f"Added {amount} credits to user {telegram_id}")
        return True


async def deduct_credits(
    telegram_id: int, amount: int, check_balance: bool = True
) -> bool:
    """Списывает кредиты с проверкой баланса"""
    if amount <= 0:
        logger.warning(f"deduct_credits: non-positive amount {amount} for user {telegram_id}")
        return False
    from bot.config import config

    # Админы не платят
    if config.is_admin(telegram_id):
        logger.info(f"Admin {telegram_id} - free access (skipped {amount} credits)")
        return True

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await db.execute("BEGIN IMMEDIATE")

        if check_balance:
            cursor = await db.execute(
                "SELECT credits FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            row = await cursor.fetchone()

            if not row or row["credits"] < amount:
                await db.rollback()
                return False

            await db.execute(
                "UPDATE users SET credits = credits - ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ? AND credits >= ?",
                (amount, telegram_id, amount),
            )
        else:
            await db.execute(
                "UPDATE users SET credits = credits - ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (amount, telegram_id),
            )

        if db.total_changes == 0:
            await db.rollback()
            return False

        await db.commit()
        logger.info(f"Deducted {amount} credits from user {telegram_id}")
        return True


async def check_can_afford(telegram_id: int, amount: int) -> bool:
    """Проверяет, может ли пользователь позволить себе операцию"""
    from bot.config import config

    # Админы всегда могут
    if config.is_admin(telegram_id):
        return True

    user = await get_or_create_user(telegram_id)
    return user.credits >= amount


async def create_transaction(
    order_id: str,
    user_id: int,
    payment_id: str,
    provider: str,
    credits: int,
    amount_rub: float,
    status: str = "pending",
    promo_code_id: Optional[int] = None,
    promo_code: Optional[str] = None,
    promo_bonus_credits: int = 0,
) -> bool:
    """Создаёт транзакцию платежа"""
    async with db_backend.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO transactions 
                   (order_id, user_id, payment_id, provider, credits, amount_rub, status,
                    promo_code_id, promo_code, promo_bonus_credits) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    user_id,
                    payment_id,
                    provider,
                    credits,
                    amount_rub,
                    status,
                    promo_code_id,
                    normalize_promo_code(promo_code) if promo_code else None,
                    int(promo_bonus_credits or 0),
                ),
            )
            await db.commit()
            return True
        except db_backend.IntegrityError:
            logger.warning(f"Transaction already exists: {order_id}")
            return False


async def create_miniapp_notification(user_id: int, message: str) -> bool:
    """Создаёт уведомление, которое мини‑апп прочитает при следующем bootstrap."""
    async with db_backend.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO miniapp_notifications (user_id, message) VALUES (?, ?)",
                (user_id, message),
            )
            await db.commit()
            return True
        except Exception:
            logger.exception("Failed to create miniapp notification")
            return False


async def get_and_clear_miniapp_notifications(telegram_id: int) -> list:
    """Получает и удаляет все накопленные уведомления для пользователя (по telegram_id)."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        # Получаем внутренний user_id
        cursor = await db.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return []
        uid = row["id"]
        cursor = await db.execute(
            "SELECT id, message, created_at FROM miniapp_notifications WHERE user_id = ? ORDER BY created_at DESC",
            (uid,),
        )
        notes = await cursor.fetchall()
        messages = [n["message"] for n in notes]
        # Удаляем выбранные
        await db.execute("DELETE FROM miniapp_notifications WHERE user_id = ?", (uid,))
        await db.commit()
        return messages


async def get_transaction_by_order(order_id: str) -> Optional[Transaction]:
    """Получает транзакцию по order_id"""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        cursor = await db.execute(
            "SELECT * FROM transactions WHERE order_id = ?", (order_id,)
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return Transaction(
            id=row["id"],
            order_id=row["order_id"],
            provider=(
                row["provider"]
                if "provider" in row.keys() and row["provider"]
                else "cryptobot"
            ),
            user_id=row["user_id"],
            payment_id=row["payment_id"],
            credits=row["credits"],
            amount_rub=row["amount_rub"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            promo_code_id=(
                row["promo_code_id"]
                if "promo_code_id" in row.keys() and row["promo_code_id"]
                else None
            ),
            promo_code=(
                row["promo_code"]
                if "promo_code" in row.keys() and row["promo_code"]
                else None
            ),
            promo_bonus_credits=(
                int(row["promo_bonus_credits"] or 0)
                if "promo_bonus_credits" in row.keys()
                else 0
            ),
        )


async def update_transaction_status(order_id: str, status: str) -> bool:
    """Обновляет статус транзакции. Возвращает True, если строка была изменена."""
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "UPDATE transactions SET status = ? WHERE order_id = ? AND status != ?",
            (status, order_id, status),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_transaction_payment_id(order_id: str, payment_id: str) -> bool:
    """Сохраняет внешний идентификатор платежа у существующей транзакции."""
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE transactions
            SET payment_id = ?
            WHERE order_id = ?
              AND COALESCE(payment_id, '') != ?
            """,
            (payment_id, order_id, payment_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_telegram_id_by_user_id(user_id: int) -> Optional[int]:
    """Получает telegram_id по внутреннему user_id"""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT telegram_id FROM users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row["telegram_id"] if row else None


def _merge_task_id_aliases(request_data: Optional[dict | str], *task_ids: Any) -> Optional[dict | str]:
    if not isinstance(request_data, dict):
        return request_data
    payload = dict(request_data)
    raw_aliases = payload.get("task_id_aliases") or []
    if isinstance(raw_aliases, str):
        raw_aliases = [raw_aliases]
    aliases: list[str] = []
    for value in [*raw_aliases, *task_ids]:
        normalized = str(value or "").strip()
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    if aliases:
        payload["task_id_aliases"] = aliases
    return payload


async def add_generation_task(
    user_id: int,
    telegram_id: int,
    task_id: str,
    type: str,
    preset_id: str,
    model: Optional[str] = None,
    duration: Optional[int] = None,
    aspect_ratio: Optional[str] = None,
    prompt: Optional[str] = None,
    cost: Optional[int] = None,
    request_data: Optional[dict | str] = None,
    source_feed_gen_id: Optional[int] = None,
    parent_generation_id: Optional[int] = None,
    action_type: Optional[str] = None,
) -> bool:
    """Создаёт задачу генерации"""
    async with db_backend.connect(DATABASE_PATH) as db:
        normalized_request = _merge_task_id_aliases(request_data, task_id)
        serialized_request = (
            json.dumps(normalized_request, ensure_ascii=False)
            if isinstance(normalized_request, dict)
            else normalized_request
        )
        result = await db.execute(
            """INSERT OR IGNORE INTO generation_tasks 
               (user_id, telegram_id, task_id, type, preset_id, model, duration, aspect_ratio, prompt, cost, request_data, status,
                source_feed_gen_id, parent_generation_id, action_type) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                user_id,
                telegram_id,
                task_id,
                type,
                preset_id,
                model,
                duration,
                aspect_ratio,
                prompt,
                cost,
                serialized_request,
                source_feed_gen_id,
                parent_generation_id,
                action_type,
            ),
        )
        await db.commit()
        if result.rowcount > 0:
            logger.info(
                f"Added new generation task: {task_id} for telegram_id {telegram_id}"
            )
            return True
        else:
            logger.debug(f"Generation task already exists: {task_id}")
            return False


async def get_task_by_id(task_id: str) -> Optional[GenerationTask]:
    """Получает задачу по task_id, а для обратной совместимости — и по numeric id."""
    lookup_value = str(task_id or "").strip()
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        cursor = await db.execute(
            "SELECT * FROM generation_tasks WHERE task_id = ?", (lookup_value,)
        )
        row = await cursor.fetchone()

        if not row and lookup_value.isdigit():
            cursor = await db.execute(
                "SELECT * FROM generation_tasks WHERE id = ?", (int(lookup_value),)
            )
            row = await cursor.fetchone()

        if not row and lookup_value:
            cursor = await db.execute(
                """
                SELECT *
                FROM generation_tasks
                WHERE EXISTS (
                    SELECT 1
                    FROM json_each(
                        CASE
                            WHEN json_valid(generation_tasks.request_data)
                            THEN generation_tasks.request_data
                            ELSE '{}'
                        END,
                        '$.task_id_aliases'
                    )
                    WHERE CAST(value AS TEXT) = ?
                )
                ORDER BY id DESC
                LIMIT 1
                """,
                (lookup_value,),
            )
            row = await cursor.fetchone()

        if not row:
            return None

        return GenerationTask(
            id=row["id"],
            user_id=row["user_id"],
            task_id=row["task_id"],
            type=row["type"],
            preset_id=row["preset_id"],
            model=row["model"],
            duration=row["duration"],
            aspect_ratio=row["aspect_ratio"],
            prompt=row["prompt"],
            cost=row["cost"],
            status=row["status"],
            telegram_id=row["telegram_id"],
            result_url=row["result_url"],
            result_urls=[
                str(item)
                for item in _parse_json_list(row["result_urls"])
            ]
            if "result_urls" in row.keys()
            else None,
            request_data=row["request_data"] if "request_data" in row.keys() else None,
            is_public_feed=(
                bool(row["is_public_feed"]) if "is_public_feed" in row.keys() else False
            ),
            is_prompt_library=(
                bool(row["is_prompt_library"])
                if "is_prompt_library" in row.keys()
                else False
            ),
            source_feed_gen_id=(
                row["source_feed_gen_id"] if "source_feed_gen_id" in row.keys() else None
            ),
            parent_generation_id=(
                row["parent_generation_id"]
                if "parent_generation_id" in row.keys()
                else None
            ),
            action_type=row["action_type"] if "action_type" in row.keys() else None,
            likes_count=(
                int(row["likes_count"] or 0) if "likes_count" in row.keys() else 0
            ),
            shares_count=(
                int(row["shares_count"] or 0) if "shares_count" in row.keys() else 0
            ),
            feed_prompt_visible=(
                bool(row["feed_prompt_visible"])
                if "feed_prompt_visible" in row.keys()
                else False
            ),
            feed_references_visible=(
                bool(row["feed_references_visible"])
                if "feed_references_visible" in row.keys()
                else False
            ),
            feed_blurred=(
                bool(row["feed_blurred"])
                if "feed_blurred" in row.keys()
                else False
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


async def complete_video_task(task_id: str, result_url: str) -> bool:
    """Отмечает задачу как выполненную"""
    lookup_value = str(task_id or "").strip()
    async with db_backend.connect(DATABASE_PATH) as db:
        final_status = "completed" if result_url else "failed"
        cursor = await db.execute(
            """UPDATE generation_tasks 
               SET status = ?, result_url = ?, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE task_id = ?
                  OR EXISTS (
                      SELECT 1
                      FROM json_each(
                          CASE
                              WHEN json_valid(generation_tasks.request_data)
                              THEN generation_tasks.request_data
                              ELSE '{}'
                          END,
                          '$.task_id_aliases'
                      )
                      WHERE CAST(value AS TEXT) = ?
                  )""",
            (final_status, result_url, lookup_value, lookup_value),
        )
        await db.commit()
        updated = int(getattr(cursor, "rowcount", 0) or 0)
        if updated <= 0:
            logger.warning(
                "complete_video_task: no rows updated for task_id=%s final_status=%s",
                lookup_value,
                final_status,
            )
            return False
        logger.info(
            "complete_video_task: updated rows=%s task_id=%s final_status=%s",
            updated,
            lookup_value,
            final_status,
        )
        return True


async def create_prompt(
    *,
    author_id: int,
    prompt_text: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    preview_url: Optional[str] = None,
    model: Optional[str] = None,
    tags: Optional[list[str]] = None,
    generation_settings: dict[str, Any] | None = None,
    is_public: bool = True,
) -> Optional[dict[str, Any]]:
    prompt_text = str(prompt_text or "").strip()
    if not prompt_text:
        return None

    inferred_tags = normalize_prompt_tags(tags) or infer_tags(prompt_text)
    final_category = (category or infer_category(prompt_text, inferred_tags)).strip()
    if final_category not in PROMPT_CATEGORIES:
        final_category = "other"

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            INSERT INTO user_prompts (
                author_id, title, description, category, prompt_text, preview_url,
                model, tags, generation_settings, is_public, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                author_id,
                (title or derive_title(prompt_text)).strip()[:60],
                (description or derive_description(prompt_text)).strip()[:200],
                final_category,
                prompt_text,
                preview_url,
                model,
                json.dumps(inferred_tags, ensure_ascii=False),
                json.dumps(generation_settings or {}, ensure_ascii=False),
                1 if is_public else 0,
            ),
        )
        await db.commit()
        return await get_prompt_by_id(cursor.lastrowid)


async def get_prompt_by_id(prompt_id: int, *, approved_public_only: bool = False) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        sql = "SELECT * FROM user_prompts WHERE id = ?"
        params: list[Any] = [prompt_id]
        if approved_public_only:
            sql += " AND status = 'approved' AND is_public = 1"
        cursor = await db.execute(sql, params)
        row = await cursor.fetchone()
    return _prompt_to_dict(_row_to_user_prompt(row))


async def count_active_prompts_by_author(author_id: int) -> int:
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM user_prompts
            WHERE author_id = ? AND status IN ('pending', 'approved')
            """,
            (author_id,),
        )
        row = await cursor.fetchone()
        return int((row or [0])[0] or 0)


async def _fetch_prompt_list(
    where_sql: str,
    params: list[Any],
    *,
    order_sql: str,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 20), 1), 100)
    safe_offset = max(int(offset or 0), 0)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT * FROM user_prompts
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, safe_limit, safe_offset),
        )
        rows = await cursor.fetchall()
    return [
        item
        for item in (_prompt_to_dict(_row_to_user_prompt(row)) for row in rows)
        if item is not None
    ]


async def get_top_prompts(limit: int = TOP_PROMPTS_LIMIT) -> list[dict[str, Any]]:
    return await _fetch_prompt_list(
        "status = 'approved' AND is_public = 1",
        [],
        order_sql="uses_count DESC, created_at DESC",
        limit=limit,
    )


async def get_popular_prompts(limit: int = TOP_PROMPTS_LIMIT) -> list[dict[str, Any]]:
    return await _fetch_prompt_list(
        "status = 'approved' AND is_public = 1",
        [],
        order_sql="likes DESC, uses_count DESC, created_at DESC",
        limit=limit,
    )


async def get_prompts_by_tag(tag: str, limit: int = TOP_PROMPTS_LIMIT) -> list[dict[str, Any]]:
    normalized = normalize_prompt_tags([tag])
    if not normalized:
        return []
    return await _fetch_prompt_list(
        "status = 'approved' AND is_public = 1 AND tags LIKE ?",
        [f'%"{normalized[0]}"%'],
        order_sql="uses_count DESC, likes DESC, created_at DESC",
        limit=limit,
    )


async def get_approved_prompts(
    category: Optional[str] = None,
    offset: int = 0,
    limit: int = 40,
) -> list[dict[str, Any]]:
    where = "status = 'approved' AND is_public = 1"
    params: list[Any] = []
    if category and category in PROMPT_CATEGORIES:
        where += " AND category = ?"
        params.append(category)
    return await _fetch_prompt_list(
        where,
        params,
        order_sql="created_at DESC",
        limit=limit,
        offset=offset,
    )


async def count_approved_prompts(category: Optional[str] = None) -> int:
    where = "status = 'approved' AND is_public = 1"
    params: list[Any] = []
    if category and category in PROMPT_CATEGORIES:
        where += " AND category = ?"
        params.append(category)
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(f"SELECT COUNT(*) FROM user_prompts WHERE {where}", params)
        row = await cursor.fetchone()
        return int((row or [0])[0] or 0)


async def get_admin_prompt_stats() -> dict[str, int]:
    stats = {status: 0 for status in PROMPT_STATUSES}
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT COALESCE(status, 'pending') AS status, COUNT(*) AS count
            FROM user_prompts
            GROUP BY COALESCE(status, 'pending')
            """
        )
        rows = await cursor.fetchall()
        for status, count in rows:
            stats[str(status or "pending")] = int(count or 0)

        cursor = await db.execute(
            "SELECT COUNT(*) FROM user_prompts WHERE is_public = 1"
        )
        public_row = await cursor.fetchone()

    stats["total"] = sum(
        count for status, count in stats.items() if status != "total"
    )
    stats["public"] = int((public_row or [0])[0] or 0)
    return stats


async def get_admin_prompts(
    status: Optional[str] = "pending",
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 10), 1), 50)
    safe_offset = max(int(offset or 0), 0)
    params: list[Any] = []
    where = "1 = 1"
    if status and status != "all":
        if status not in PROMPT_STATUSES:
            return []
        where = "up.status = ?"
        params.append(status)

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT up.*,
                   u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code
            FROM user_prompts up
            LEFT JOIN users u ON u.id = up.author_id
            WHERE {where}
            ORDER BY up.created_at DESC, up.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, safe_limit, safe_offset),
        )
        rows = await cursor.fetchall()

    return [
        item
        for item in (_prompt_admin_dict(row) for row in rows)
        if item is not None
    ]


async def get_admin_prompt_details(prompt_id: int) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT up.*,
                   u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code
            FROM user_prompts up
            LEFT JOIN users u ON u.id = up.author_id
            WHERE up.id = ?
            LIMIT 1
            """,
            (prompt_id,),
        )
        row = await cursor.fetchone()
    return _prompt_admin_dict(row)


async def like_prompt(prompt_id: int, user_id: int) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT * FROM user_prompts WHERE id = ? AND status = 'approved' AND is_public = 1",
            (prompt_id,),
        )
        prompt = await cursor.fetchone()
        if not prompt:
            return None

        cursor = await db.execute(
            "INSERT OR IGNORE INTO prompt_likes (user_id, prompt_id) VALUES (?, ?)",
            (user_id, prompt_id),
        )
        if cursor.rowcount > 0:
            await db.execute(
                "UPDATE user_prompts SET likes = likes + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (prompt_id,),
            )
        await db.commit()

    return await get_prompt_by_id(prompt_id, approved_public_only=True)


async def _credit_prompt_repeat_reward_in_db(
    db: db_backend.Connection,
    *,
    author_id: int,
    repeater_id: int,
    source_type: str,
    source_id: int,
    repeat_task_id: Optional[str] = None,
    credits_spent: Optional[float] = None,
    amount_rub: float = PROMPT_REPEAT_REWARD_RUB,
) -> bool:
    if not author_id or not repeater_id or author_id == repeater_id:
        return False
    reward = round(float(amount_rub or 0), 2)
    if reward <= 0:
        return False

    await db.execute(
        """
        INSERT INTO prompt_repeat_events (
            author_id, repeater_id, source_type, source_id,
            repeat_task_id, credits_spent, amount_rub
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            author_id,
            repeater_id,
            source_type[:32],
            int(source_id),
            (repeat_task_id or None),
            float(credits_spent or 0),
            reward,
        ),
    )
    await db.execute(
        """
        UPDATE users
        SET partner_balance_rub = COALESCE(partner_balance_rub, 0) + ?,
            prompt_repeat_balance_rub = COALESCE(prompt_repeat_balance_rub, 0) + ?,
            prompt_repeat_total_rub = COALESCE(prompt_repeat_total_rub, 0) + ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (reward, reward, reward, author_id),
    )
    return True


async def credit_feed_prompt_repeat(
    source_generation_id: int | str,
    repeater_user_id: int,
    *,
    repeat_task_id: Optional[str] = None,
    credits_spent: Optional[float] = None,
) -> bool:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, user_id
            FROM generation_tasks
            WHERE id = ?
              AND type IN ('image', 'video')
              AND status = 'completed'
              AND is_public_feed = 1
            LIMIT 1
            """,
            (int(source_generation_id),),
        )
        source = await cursor.fetchone()
        if not source:
            return False
        credited = await _credit_prompt_repeat_reward_in_db(
            db,
            author_id=int(source["user_id"]),
            repeater_id=int(repeater_user_id),
            source_type="feed",
            source_id=int(source["id"]),
            repeat_task_id=repeat_task_id,
            credits_spent=credits_spent,
        )
        if credited:
            await db.commit()
        return credited


async def use_prompt(
    prompt_id: int,
    user_id: int,
    credits_spent: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT * FROM user_prompts WHERE id = ? AND status = 'approved' AND is_public = 1",
            (prompt_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        await db.execute(
            "UPDATE user_prompts SET uses_count = uses_count + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (prompt_id,),
        )
        if credits_spent is not None and float(credits_spent or 0) > 0:
            await _credit_prompt_repeat_reward_in_db(
                db,
                author_id=int(row["author_id"]),
                repeater_id=int(user_id),
                source_type="prompt",
                source_id=int(prompt_id),
                credits_spent=credits_spent,
            )
        await db.commit()
    return await get_prompt_by_id(prompt_id, approved_public_only=True)


async def approve_prompt(prompt_id: int) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT source_generation_id, author_id FROM user_prompts WHERE id = ? LIMIT 1",
            (prompt_id,),
        )
        row = await cursor.fetchone()
        await db.execute(
            """
            UPDATE user_prompts
            SET status = 'approved', reject_reason = NULL, is_public = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (prompt_id,),
        )
        if row and row["source_generation_id"]:
            await db.execute(
                """
                UPDATE generation_tasks
                SET is_prompt_library = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (row["source_generation_id"], row["author_id"]),
            )
        await db.commit()
    return await get_prompt_by_id(prompt_id)


async def reject_prompt(prompt_id: int, reject_reason: str = "") -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            "SELECT source_generation_id, author_id FROM user_prompts WHERE id = ? LIMIT 1",
            (prompt_id,),
        )
        row = await cursor.fetchone()
        await db.execute(
            """
            UPDATE user_prompts
            SET status = 'rejected', reject_reason = ?, is_public = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (reject_reason[:500], prompt_id),
        )
        if row and row["source_generation_id"]:
            await db.execute(
                """
                UPDATE generation_tasks
                SET is_prompt_library = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (row["source_generation_id"], row["author_id"]),
            )
        await db.commit()
    return await get_prompt_by_id(prompt_id)


async def deactivate_prompt(prompt_id: int, author_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    params: list[Any] = [prompt_id]
    where = "id = ?"
    if author_id is not None:
        where += " AND author_id = ?"
        params.append(author_id)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"SELECT source_generation_id, author_id FROM user_prompts WHERE {where} LIMIT 1",
            params,
        )
        row = await cursor.fetchone()
        await db.execute(
            f"""
            UPDATE user_prompts
            SET status = 'deactivated', is_public = 0, updated_at = CURRENT_TIMESTAMP
            WHERE {where}
            """,
            params,
        )
        if row and row["source_generation_id"]:
            await db.execute(
                """
                UPDATE generation_tasks
                SET is_prompt_library = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (row["source_generation_id"], row["author_id"]),
            )
        await db.commit()
    return await get_prompt_by_id(prompt_id)


async def get_author_prompts(author_id: int) -> list[dict[str, Any]]:
    return await _fetch_prompt_list(
        "author_id = ? AND status != 'deactivated'",
        [author_id],
        order_sql="created_at DESC",
        limit=100,
    )


async def get_author_total_uses(author_id: int) -> int:
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(uses_count), 0) FROM user_prompts WHERE author_id = ?",
            (author_id,),
        )
        row = await cursor.fetchone()
        return int((row or [0])[0] or 0)


async def set_ai_moderation_result(
    prompt_id: int,
    *,
    decision: str,
    risk: Optional[str] = None,
    reason: Optional[str] = None,
    recommendation: Optional[str] = None,
    raw: Optional[dict[str, Any] | str] = None,
) -> Optional[dict[str, Any]]:
    raw_value = json.dumps(raw, ensure_ascii=False) if isinstance(raw, dict) else raw
    async with db_backend.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE user_prompts
            SET ai_moderation_decision = ?,
                ai_moderation_risk = ?,
                ai_moderation_reason = ?,
                ai_moderation_recommendation = ?,
                ai_moderation_raw = ?,
                ai_moderated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                decision[:64],
                (risk or "")[:64] or None,
                (reason or "")[:1000] or None,
                (recommendation or "")[:1000] or None,
                raw_value,
                prompt_id,
            ),
        )
        await db.commit()
    return await get_prompt_by_id(prompt_id)


def _generation_attr(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
    key: str,
    default: Any = None,
) -> Any:
    if generation is None:
        return default
    if isinstance(generation, GenerationTask):
        return getattr(generation, key, default)
    try:
        if hasattr(generation, "keys") and key not in generation.keys():
            return default
        return generation[key]
    except Exception:
        return getattr(generation, key, default)


def generation_feed_prompt_visible(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(_generation_attr(generation, "feed_prompt_visible", False))


def generation_references_visible(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(_generation_attr(generation, "feed_references_visible", False))


def generation_feed_blurred(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(_generation_attr(generation, "feed_blurred", False))


def generation_profile_visible(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(
        _generation_attr(generation, "is_profile_visible", False)
        or _generation_attr(generation, "is_public_feed", False)
    )


def generation_adult_content(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(_generation_attr(generation, "is_adult_content", False))


def generation_publication_scope(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> str:
    if bool(_generation_attr(generation, "is_public_feed", False)) and not generation_adult_content(generation):
        return "feed"
    if generation_profile_visible(generation):
        return "profile"
    return "private"


def generation_prompt_hidden(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(_generation_attr(generation, "source_feed_gen_id")) or not generation_feed_prompt_visible(generation)


def _generation_identifier_clause(identifier: int | str) -> tuple[str, Any]:
    value = str(identifier).strip()
    if value.isdigit():
        return "id = ?", int(value)
    return "task_id = ?", value


async def _fetch_generation_row(
    db: db_backend.Connection,
    identifier: int | str,
    *,
    user_id: Optional[int] = None,
    public_only: bool = False,
) -> Optional[db_backend.Row]:
    clause, value = _generation_identifier_clause(identifier)
    where = [clause]
    params: list[Any] = [value]
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    if public_only:
        where.extend(
            [
                "type IN ('image', 'video')",
                "status = 'completed'",
                "result_url IS NOT NULL",
                "is_public_feed = 1",
                "COALESCE(is_adult_content, 0) = 0",
            ]
        )
    cursor = await db.execute(
        f"SELECT * FROM generation_tasks WHERE {' AND '.join(where)} LIMIT 1",
        params,
    )
    return await cursor.fetchone()


def _generation_result_urls(row: db_backend.Row) -> list[str]:
    urls = [
        str(item)
        for item in _parse_json_list(row["result_urls"] if "result_urls" in row.keys() else None)
        if str(item).strip()
    ]
    result_url = row["result_url"]
    if result_url and result_url not in urls:
        urls.insert(0, result_url)
    return urls


def _feed_row_timestamp(row: db_backend.Row) -> Optional[datetime]:
    for key in ("completed_at", "updated_at", "created_at"):
        if key in row.keys():
            parsed = _parse_datetime(row[key])
            if parsed:
                return parsed
    return None


def _feed_result_host(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").strip().lower().lstrip(".")
    except Exception:
        return ""


def _is_ephemeral_feed_result_url(url: str) -> bool:
    host = _feed_result_host(url)
    if not host:
        return False
    return any(host == ephemeral or host.endswith(f".{ephemeral}") for ephemeral in FEED_EPHEMERAL_RESULT_HOSTS)


def _is_feed_result_expired(row: db_backend.Row, url: str) -> bool:
    if FEED_EPHEMERAL_RESULT_TTL_HOURS <= 0 or not _is_ephemeral_feed_result_url(url):
        return False
    timestamp = _feed_row_timestamp(row)
    if not timestamp:
        return False
    now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.utcnow()
    return now - timestamp > timedelta(hours=FEED_EPHEMERAL_RESULT_TTL_HOURS)


def _is_feed_result_url_available(row: db_backend.Row, url: str) -> bool:
    candidate = str(url or "").strip()
    if not candidate.startswith(("http://", "https://")):
        return False

    try:
        from bot.services.media_input_utils import (
            is_local_upload_source,
            resolve_local_upload_path,
        )

        if is_local_upload_source(candidate):
            return bool(resolve_local_upload_path(candidate))
    except Exception:
        logger.exception("Failed to validate local feed result url: %s", candidate)
        return False

    return not _is_feed_result_expired(row, candidate)


def _feed_result_urls(row: db_backend.Row) -> list[str]:
    available: list[str] = []
    for url in _generation_result_urls(row):
        normalized = str(url or "").strip()
        if normalized and normalized not in available and _is_feed_result_url_available(row, normalized):
            available.append(normalized)
    return available


def _public_reference_urls(row: db_backend.Row, urls: Any) -> list[str]:
    available: list[str] = []
    for url in _parse_json_list(urls) if isinstance(urls, str) else list(urls or []):
        normalized = str(url or "").strip()
        if (
            normalized
            and normalized not in available
            and _is_feed_result_url_available(row, normalized)
        ):
            available.append(normalized)
    return available


def _feed_reference_images(row: db_backend.Row, request_data: dict[str, Any]) -> list[str]:
    source_refs = request_data.get("source_reference_images")
    if isinstance(source_refs, list):
        return _public_reference_urls(row, source_refs)
    return _public_reference_urls(row, request_data.get("reference_images", []))


def _feed_reference_videos(row: db_backend.Row, request_data: dict[str, Any]) -> list[str]:
    return _public_reference_urls(row, request_data.get("v_reference_videos", []))


def _feed_activity_time_for_sort(row: db_backend.Row) -> datetime:
    values: list[datetime] = []
    for key in ("created_at", "updated_at"):
        if key not in row.keys() or not row[key]:
            continue
        try:
            values.append(datetime.fromisoformat(str(row[key])))
        except (TypeError, ValueError):
            continue
    return max(values) if values else datetime.min


def _calculate_feed_score(row: db_backend.Row) -> float:
    remix_count = int(row["remix_count"] or 0) if "remix_count" in row.keys() else 0
    likes_count = int(row["likes_count"] or 0)
    shares_count = int(row["shares_count"] or 0)
    generation_count = 1 + remix_count
    score = likes_count + remix_count * 3 + shares_count * 5 + generation_count * 4
    activity_time = _feed_activity_time_for_sort(row)
    if activity_time != datetime.min:
        age_seconds = (datetime.utcnow() - activity_time).total_seconds()
        if age_seconds <= 2 * 3600:
            score *= 1.5
    return float(score)


def _feed_public_limit_for_type(generation_type: str) -> int:
    if generation_type == "video":
        return FEED_PUBLIC_VIDEO_MAX_ITEMS
    return FEED_PUBLIC_IMAGE_MAX_ITEMS


async def cleanup_public_feed_limits(*, force: bool = False) -> dict[str, int]:
    """No-op: feed limits disabled."""
    return {"image": 0, "video": 0}


def _author_display_name(row: db_backend.Row) -> str:
    username = ""
    if "author_username" in row.keys() and row["author_username"]:
        username = str(row["author_username"]).strip().lstrip("@")
    if username:
        return f"@{username}"

    name_parts = []
    for key in ("author_first_name", "author_last_name"):
        if key in row.keys() and row[key]:
            name_parts.append(str(row[key]).strip())
    display_name = " ".join(part for part in name_parts if part)
    if display_name:
        return display_name

    if "author_telegram_id" in row.keys() and row["author_telegram_id"]:
        return f"user_{row['author_telegram_id']}"
    return f"user_{row['user_id']}"


def _generation_row_to_card(
    row: db_backend.Row,
    *,
    viewer_user_id: Optional[int] = None,
    include_unavailable: bool = False,
) -> Optional[dict[str, Any]]:
    feed_urls = _feed_result_urls(row)
    media_unavailable = not feed_urls
    if media_unavailable and not include_unavailable:
        return None
    remix_count = int(row["remix_count"] or 0) if "remix_count" in row.keys() else 0
    comments_count = int(row["comments_count"] or 0) if "comments_count" in row.keys() else 0
    author = _author_display_name(row)
    request_data = _parse_json_dict(row["request_data"] if "request_data" in row.keys() else None)
    prompt_hidden = generation_prompt_hidden(row)
    viewer_is_owner = bool(viewer_user_id and row["user_id"] == viewer_user_id)
    references_visible = generation_references_visible(row)
    all_reference_images = _feed_reference_images(row, request_data)
    all_reference_videos = _feed_reference_videos(row, request_data)
    public_reference_images = all_reference_images if references_visible else []
    public_reference_videos = all_reference_videos if references_visible else []
    references_count = len(all_reference_images) + len(all_reference_videos)
    preview_url = feed_urls[0] if feed_urls else ""
    if preview_url and str(row["type"]) == "image":
        try:
            from bot.services.feed_persist import feed_thumbnail_url_for

            preview_url = feed_thumbnail_url_for(preview_url) or preview_url
        except Exception:
            logger.exception("Failed to resolve feed thumbnail url")
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "task_id": row["task_id"],
        "model": row["model"] or row["preset_id"],
        "gen_type": row["type"],
        "result_url": feed_urls[0] if feed_urls else "",
        "preview_url": preview_url,
        "result_urls": feed_urls,
        "media_unavailable": media_unavailable,
        "prompt": "" if prompt_hidden else str(row["prompt"] or ""),
        "likes_count": int(row["likes_count"] or 0),
        "shares_count": int(row["shares_count"] or 0),
        "comments_count": comments_count,
        "aspect_ratio": row["aspect_ratio"] or "",
        "duration": row["duration"] if "duration" in row.keys() else None,
        "scenario": request_data.get("v_type") or request_data.get("generation_type"),
        "reference_images": public_reference_images,
        "reference_videos": public_reference_videos,
        "references_count": references_count,
        "references_hidden": bool(references_count and not references_visible),
        "author": author,
        "author_referral_code": (
            row["author_referral_code"]
            if "author_referral_code" in row.keys()
            else None
        ),
        "author_photo_url": (
            row["author_photo_url"]
            if "author_photo_url" in row.keys() and row["author_photo_url"]
            else None
        ),
        "is_mine": viewer_is_owner,
        "remixes": remix_count,
        "score": _calculate_feed_score(row),
        "created_at": row["created_at"],
        "prompt_hidden": prompt_hidden,
        "prompt_actions_allowed": not prompt_hidden,
        "feed_prompt_visible": generation_feed_prompt_visible(row),
        "feed_references_visible": references_visible,
        "feed_blurred": generation_feed_blurred(row),
        "is_profile_visible": generation_profile_visible(row),
        "is_adult_content": generation_adult_content(row),
        "publication_scope": generation_publication_scope(row),
        "feed_interactions_enabled": generation_profile_visible(row),
    }


async def get_feed_generations(
    *,
    limit: int = 0,
    offset: int = 0,
    source: str = "recent",
    viewer_user_id: Optional[int] = None,
    include_unavailable: bool = False,
    models: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Return public feed items for the requested source."""
    source = source if source in {"recent", "top_day", "top"} else "recent"
    limit = max(0, int(limit or 0))
    offset = max(0, int(offset or 0))
    where = [
        "gt.type IN ('image', 'video')",
        "gt.status = 'completed'",
        "gt.result_url IS NOT NULL",
        "gt.is_public_feed = 1",
        "COALESCE(gt.is_adult_content, 0) = 0",
    ]
    if source == "top_day":
        where.append("gt.created_at >= datetime('now', '-1 day')")
    model_values = [str(model).strip() for model in (models or ()) if str(model).strip()]
    if model_values:
        placeholders = ",".join("?" for _ in model_values)
        where.append(
            f"COALESCE(NULLIF(gt.model, ''), gt.preset_id) IN ({placeholders})"
        )

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        base_query = f"""
            SELECT gt.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code,
                   u.photo_url AS author_photo_url,
                   (
                       SELECT COUNT(*)
                       FROM generation_tasks child
                       WHERE child.parent_generation_id = gt.id
                         AND child.status = 'completed'
                   ) AS remix_count,
                   (
                       SELECT COUNT(*)
                       FROM feed_comments fc
                       WHERE fc.generation_id = gt.id
                   ) AS comments_count
            FROM generation_tasks gt
            LEFT JOIN users u ON u.id = gt.user_id
            WHERE {' AND '.join(where)}
        """
        if source == "recent":
            query = f"""
                {base_query}
                ORDER BY COALESCE(gt.feed_published_at, gt.created_at) DESC, gt.created_at DESC
                {"LIMIT ? OFFSET ?" if limit else ""}
            """
        else:
            query = f"""
                SELECT ranked.*
                FROM ({base_query}) AS ranked
                ORDER BY (
                    COALESCE(ranked.likes_count, 0)
                    + COALESCE(ranked.shares_count, 0) * 5
                    + COALESCE(ranked.remix_count, 0) * 7
                    + 4
                ) * CASE
                    WHEN ranked.created_at >= datetime('now', '-2 hours')
                      OR ranked.updated_at >= datetime('now', '-2 hours')
                    THEN 1.5 ELSE 1
                END DESC,
                COALESCE(ranked.feed_published_at, ranked.created_at) DESC
                {"LIMIT ? OFFSET ?" if limit else ""}
            """
        params: list[Any] = [*model_values, *([limit, offset] if limit else [])]
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    cards = [
        card
        for row in rows
        if (card := _generation_row_to_card(row, viewer_user_id=viewer_user_id, include_unavailable=include_unavailable))
    ]
    return cards


async def get_user_feed_generations(
    user_id: int,
    limit: int = 120,
    offset: int = 0,
    *,
    include_unpublished_owned: bool = False,
    profile_visible_only: bool = False,
    include_unavailable: bool = False,
) -> list[dict[str, Any]]:
    """Return publications for a user profile or the legacy public-only view."""
    limit = max(0, int(limit or 0))
    offset = max(0, int(offset or 0))
    where_clause = """
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND gt.is_public_feed = 1
              AND COALESCE(gt.is_adult_content, 0) = 0
    """
    if profile_visible_only:
        where_clause = """
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND (COALESCE(gt.is_profile_visible, 0) = 1 OR gt.is_public_feed = 1)
        """
    elif include_unpublished_owned:
        where_clause = """
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND gt.source_feed_gen_id IS NULL
        """
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        query = f"""
            SELECT gt.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code,
                   u.photo_url AS author_photo_url,
                   (
                       SELECT COUNT(*)
                       FROM generation_tasks child
                       WHERE child.parent_generation_id = gt.id
                         AND child.status = 'completed'
                   ) AS remix_count,
                   (
                       SELECT COUNT(*)
                       FROM feed_comments fc
                       WHERE fc.generation_id = gt.id
                   ) AS comments_count
            FROM generation_tasks gt
            LEFT JOIN users u ON u.id = gt.user_id
            {where_clause}
            ORDER BY COALESCE(gt.feed_published_at, gt.created_at) DESC, gt.created_at DESC
            {"LIMIT ? OFFSET ?" if limit else ""}
        """
        params: tuple[Any, ...] = (user_id, limit, offset) if limit else (user_id,)
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    cards = [
        card
        for row in rows
        if (card := _generation_row_to_card(row, viewer_user_id=user_id, include_unavailable=include_unavailable))
    ]
    return cards


async def get_user_feed_summary(user_id: int) -> dict[str, int]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS posts_count,
                COALESCE(SUM(COALESCE(gt.likes_count, 0)), 0) AS likes_count,
                COALESCE(SUM(COALESCE(gt.shares_count, 0)), 0) AS shares_count,
                COALESCE(SUM((
                    SELECT COUNT(*)
                    FROM generation_tasks child
                    WHERE child.parent_generation_id = gt.id
                      AND child.status = 'completed'
                )), 0) AS remixes_count
            FROM generation_tasks gt
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND (COALESCE(gt.is_profile_visible, 0) = 1 OR gt.is_public_feed = 1)
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
    return {
        "posts_count": int(row["posts_count"] or 0) if row else 0,
        "likes_count": int(row["likes_count"] or 0) if row else 0,
        "shares_count": int(row["shares_count"] or 0) if row else 0,
        "remixes_count": int(row["remixes_count"] or 0) if row else 0,
    }


async def get_top_day_generations(limit: int = 40) -> list[dict[str, Any]]:
    return await get_feed_generations(limit=limit, source="top_day")


async def get_feed_generation_card(
    gen_id: int | str,
    *,
    viewer_user_id: Optional[int] = None,
    include_unavailable: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        value = str(gen_id).strip()
        if value.isdigit():
            clause, param = "gt.id = ?", int(value)
        else:
            clause, param = "gt.task_id = ?", value
        cursor = await db.execute(
            f"""
            SELECT gt.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code,
                   u.photo_url AS author_photo_url,
                   (
                       SELECT COUNT(*)
                       FROM generation_tasks child
                       WHERE child.parent_generation_id = gt.id
                         AND child.status = 'completed'
                   ) AS remix_count,
                   (
                       SELECT COUNT(*)
                       FROM feed_comments fc
                       WHERE fc.generation_id = gt.id
                   ) AS comments_count
            FROM generation_tasks gt
            LEFT JOIN users u ON u.id = gt.user_id
            WHERE {clause}
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND gt.is_public_feed = 1
              AND COALESCE(gt.is_adult_content, 0) = 0
            LIMIT 1
            """,
            (param,),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return _generation_row_to_card(row, viewer_user_id=viewer_user_id, include_unavailable=include_unavailable)


async def get_profile_generation_card(
    gen_id: int | str,
    *,
    viewer_user_id: Optional[int] = None,
    include_unavailable: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        value = str(gen_id).strip()
        if value.isdigit():
            clause, param = "gt.id = ?", int(value)
        else:
            clause, param = "gt.task_id = ?", value
        cursor = await db.execute(
            f"""
            SELECT gt.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code,
                   u.photo_url AS author_photo_url,
                   (
                       SELECT COUNT(*)
                       FROM generation_tasks child
                       WHERE child.parent_generation_id = gt.id
                         AND child.status = 'completed'
                   ) AS remix_count,
                   (
                       SELECT COUNT(*)
                       FROM feed_comments fc
                       WHERE fc.generation_id = gt.id
                   ) AS comments_count
            FROM generation_tasks gt
            LEFT JOIN users u ON u.id = gt.user_id
            WHERE {clause}
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND (COALESCE(gt.is_profile_visible, 0) = 1 OR gt.is_public_feed = 1)
            LIMIT 1
            """,
            (param,),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return _generation_row_to_card(
        row,
        viewer_user_id=viewer_user_id,
        include_unavailable=include_unavailable,
    )


async def get_public_feed_generation(gen_id: int | str) -> Optional[dict[str, Any]]:
    return await get_feed_generation_card(gen_id)


def _feed_comment_row_to_payload(
    row: db_backend.Row,
    *,
    viewer_user_id: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "id": row["id"],
        "gen_id": row["generation_id"],
        "text": row["text"],
        "author": _author_display_name(row),
        "author_referral_code": (
            row["author_referral_code"]
            if "author_referral_code" in row.keys()
            else None
        ),
        "is_mine": bool(viewer_user_id and row["user_id"] == viewer_user_id),
        "created_at": row["created_at"],
    }


async def get_feed_comments(
    gen_id: int | str,
    *,
    limit: int = 80,
    viewer_user_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 80), 1), 150)
    try:
        internal_id = int(gen_id)
    except (TypeError, ValueError):
        return []
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT fc.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code
            FROM feed_comments fc
            LEFT JOIN users u ON u.id = fc.user_id
            WHERE fc.generation_id = ?
            ORDER BY fc.created_at DESC, fc.id DESC
            LIMIT ?
            """,
            (internal_id, safe_limit),
        )
        rows = await cursor.fetchall()
    return [
        _feed_comment_row_to_payload(row, viewer_user_id=viewer_user_id)
        for row in reversed(rows)
    ]


async def add_feed_comment(
    gen_id: int | str,
    user_id: int,
    text: str,
    *,
    allow_profile: bool = False,
) -> Optional[dict[str, Any]]:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return None
    normalized = normalized[:500]
    try:
        internal_id = int(gen_id)
    except (TypeError, ValueError):
        return None

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        generation = await _fetch_generation_row(
            db,
            internal_id,
            public_only=not allow_profile,
        )
        if (
            not generation
            or (allow_profile and not generation_profile_visible(generation))
            or not _feed_result_urls(generation)
        ):
            return None

        cursor = await db.execute(
            """
            INSERT INTO feed_comments (generation_id, user_id, text)
            VALUES (?, ?, ?)
            """,
            (internal_id, user_id, normalized),
        )
        comment_id = cursor.lastrowid
        await db.commit()

        row_cursor = await db.execute(
            """
            SELECT fc.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code
            FROM feed_comments fc
            LEFT JOIN users u ON u.id = fc.user_id
            WHERE fc.id = ?
            """,
            (comment_id,),
        )
        row = await row_cursor.fetchone()
    return _feed_comment_row_to_payload(row, viewer_user_id=user_id) if row else None


async def get_generation_task_payload(
    gen_id: int | str,
    *,
    user_id: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, user_id=user_id)
        if not row:
            return None
        payload = dict(row)
        payload["result_urls"] = _generation_result_urls(row)
        payload["request_data"] = _parse_json_dict(row["request_data"])
        return payload


async def share_to_feed(
    gen_id: int | str,
    user_id: int,
    *,
    prompt_visible: bool = False,
    references_visible: bool = False,
    blurred: Optional[bool] = None,
    publication_scope: str = "feed",
    adult_content: bool = False,
) -> Optional[dict[str, Any]]:
    normalized_scope = str(publication_scope or "feed").strip().lower()
    if normalized_scope not in {"feed", "profile"}:
        normalized_scope = "feed"

    adult_content = bool(adult_content)
    if adult_content:
        normalized_scope = "profile"

    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, user_id=user_id)
        if (
            not row
            or row["type"] not in FEED_PUBLIC_TYPES
            or row["status"] != "completed"
            or not row["result_url"]
            or row["source_feed_gen_id"] is not None
            or not _feed_result_urls(row)
        ):
            return None

        result_urls = _generation_result_urls(row)
        if result_urls:
            from bot.services.feed_persist import persist_feed_result_urls

            persisted = await persist_feed_result_urls(
                result_urls,
                require_local=row["type"] == "image",
            )
            if row["type"] == "image" and len(persisted) != len(result_urls):
                logger.warning(
                    "Feed publication aborted: image storage failed for generation %s",
                    row["id"],
                )
                return None
            result_url = persisted[0] if persisted else row["result_url"]
            result_urls_json = json.dumps(persisted, ensure_ascii=False) if persisted else None
        else:
            result_url = row["result_url"]
            result_urls_json = None

        published_at = datetime.utcnow().isoformat(sep=" ", timespec="microseconds")
        next_blurred = generation_feed_blurred(row) if blurred is None else bool(blurred)
        is_public_feed = normalized_scope == "feed" and not adult_content
        await db.execute(
            """
            UPDATE generation_tasks
            SET is_public_feed = ?,
                is_profile_visible = ?,
                is_adult_content = ?,
                feed_prompt_visible = ?,
                feed_references_visible = ?,
                feed_blurred = ?,
                feed_published_at = ?,
                result_url = ?,
                result_urls = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(is_public_feed),
                True,
                int(adult_content),
                int(bool(prompt_visible)),
                int(bool(references_visible)),
                int(next_blurred),
                published_at,
                result_url,
                result_urls_json,
                row["id"],
            ),
        )
        await db.commit()
        internal_id = row["id"]

    if is_public_feed:
        return await get_feed_generation_card(internal_id, viewer_user_id=user_id)
    return await get_profile_generation_card(internal_id, viewer_user_id=user_id)


async def set_feed_blurred(
    gen_id: int | str,
    user_id: int,
    blurred: bool,
    *,
    allow_any_user: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(
            db,
            gen_id,
            user_id=None if allow_any_user else user_id,
        )
        if not row or not generation_profile_visible(row):
            return None
        next_blurred = bool(blurred)
        await db.execute(
            "UPDATE generation_tasks SET feed_blurred = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(next_blurred), row["id"]),
        )
        await db.commit()
        internal_id = row["id"]

    if generation_publication_scope(row) == "feed":
        return await get_feed_generation_card(internal_id, viewer_user_id=user_id)
    return await get_profile_generation_card(internal_id, viewer_user_id=user_id)


async def remove_from_feed(
    gen_id: int | str,
    user_id: int,
    *,
    allow_any_user: bool = False,
) -> bool:
    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(
            db,
            gen_id,
            user_id=None if allow_any_user else user_id,
            public_only=allow_any_user,
        )
        if not row:
            return False
        await db.execute(
            """
            UPDATE generation_tasks
            SET is_public_feed = 0,
                is_profile_visible = 0,
                is_adult_content = 0,
                feed_published_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )
        await db.commit()
        return True


async def share_to_library(gen_id: int | str, user_id: int) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, user_id=user_id)
        if (
            not row
            or row["type"] != "image"
            or row["status"] != "completed"
            or not row["result_url"]
            or not str(row["prompt"] or "").strip()
            or row["source_feed_gen_id"] is not None
        ):
            return None
        prompt_text = str(row["prompt"] or "").strip()
        tags = infer_tags(prompt_text)
        category = infer_category(prompt_text, tags)
        await db.execute(
            "UPDATE generation_tasks SET is_prompt_library = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )
        existing_cursor = await db.execute(
            """
            SELECT id
            FROM user_prompts
            WHERE author_id = ?
              AND (
                source_generation_id = ?
                OR (
                  prompt_text = ?
                  AND COALESCE(preview_url, '') = ?
                  AND COALESCE(model, '') = ?
                )
              )
              AND status != 'deactivated'
            LIMIT 1
            """,
            (
                user_id,
                row["id"],
                prompt_text,
                str(row["result_url"] or ""),
                str(row["model"] or ""),
            ),
        )
        existing = await existing_cursor.fetchone()
        if existing:
            await db.execute(
                """
                UPDATE user_prompts
                SET is_public = 1,
                    status = 'approved',
                    reject_reason = NULL,
                    source_generation_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"], existing["id"]),
            )
        else:
            await db.execute(
                """
                INSERT INTO user_prompts (
                    author_id, title, description, category, prompt_text,
                    preview_url, model, tags, source_generation_id, is_public, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'approved')
                """,
                (
                    user_id,
                    derive_title(prompt_text),
                    derive_description(prompt_text),
                    category,
                    prompt_text,
                    row["result_url"],
                    row["model"],
                    json.dumps(tags, ensure_ascii=False),
                    row["id"],
                ),
            )
        await db.commit()
    return await get_generation_task_payload(gen_id, user_id=user_id)


async def remove_from_library(gen_id: int | str, user_id: int) -> bool:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, user_id=user_id)
        if not row:
            return False
        prompt_text = str(row["prompt"] or "").strip()
        await db.execute(
            "UPDATE generation_tasks SET is_prompt_library = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )
        if prompt_text:
            await db.execute(
                """
                UPDATE user_prompts
                SET status = 'deactivated',
                    is_public = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE author_id = ?
                  AND (
                    source_generation_id = ?
                    OR (
                      prompt_text = ?
                      AND COALESCE(preview_url, '') = ?
                      AND COALESCE(model, '') = ?
                    )
                  )
                  AND status != 'deactivated'
                """,
                (
                    user_id,
                    row["id"],
                    prompt_text,
                    str(row["result_url"] or ""),
                    str(row["model"] or ""),
                ),
            )
        await db.commit()
        return True


async def like_feed_generation(
    gen_id: int | str,
    user_id: int,
    *,
    allow_profile: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, public_only=not allow_profile)
        if (
            not row
            or (allow_profile and not generation_profile_visible(row))
            or not _feed_result_urls(row)
        ):
            return None
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO feed_generation_likes (user_id, generation_task_id)
            VALUES (?, ?)
            """,
            (user_id, row["id"]),
        )
        if cursor.rowcount > 0:
            await db.execute(
                "UPDATE generation_tasks SET likes_count = likes_count + 1 WHERE id = ?",
                (row["id"],),
            )
        await db.commit()
        internal_id = row["id"]
        scope = generation_publication_scope(row)
    if scope == "feed":
        return await get_feed_generation_card(internal_id, viewer_user_id=user_id)
    return await get_profile_generation_card(internal_id, viewer_user_id=user_id)


async def increment_feed_share(
    gen_id: int | str,
    *,
    allow_profile: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, public_only=not allow_profile)
        if (
            not row
            or (allow_profile and not generation_profile_visible(row))
            or not _feed_result_urls(row)
        ):
            return None
        await db.execute(
            "UPDATE generation_tasks SET shares_count = shares_count + 1 WHERE id = ?",
            (row["id"],),
        )
        await db.commit()
        internal_id = row["id"]
        scope = generation_publication_scope(row)
    if scope == "feed":
        return await get_feed_generation_card(internal_id)
    return await get_profile_generation_card(internal_id)


async def create_feed_remix_event(remix_task_id: int | str) -> bool:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, remix_task_id)
        if not row or row["source_feed_gen_id"] is None:
            return False
        cursor = await db.execute(
            "SELECT * FROM generation_tasks WHERE id = ? LIMIT 1",
            (row["source_feed_gen_id"],),
        )
        source = await cursor.fetchone()
        if not source or source["user_id"] == row["user_id"]:
            return False
        credits_spent = float(row["cost"] or 0)
        if credits_spent <= 0:
            return False
        royalty = round(credits_spent * 0.05, 3)
        await db.execute(
            """
            INSERT OR IGNORE INTO feed_remix_events (
                source_generation_task_id, remix_generation_task_id,
                source_author_id, remix_author_id, credits_spent, royalty_credits
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source["id"],
                row["id"],
                source["user_id"],
                row["user_id"],
                credits_spent,
                royalty,
            ),
        )
        await db.commit()
        return True


async def add_generation_history(
    user_id: int, preset_id: str, prompt: str, cost: int
) -> bool:
    """Добавляет запись в историю генераций"""
    async with db_backend.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO generation_history 
               (user_id, preset_id, prompt, cost) 
               VALUES (?, ?, ?, ?)""",
            (user_id, preset_id, prompt, cost),
        )
        await db.commit()
        return True


async def get_user_stats(telegram_id: int) -> dict:
    """Получает статистику пользователя"""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        # Получаем пользователя
        user = await get_or_create_user(telegram_id)

        # Считаем количество генераций
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM generation_history WHERE user_id = ?",
            (user.id,),
        )
        gen_row = await cursor.fetchone()

        # Считаем потраченные кредиты
        cursor = await db.execute(
            "SELECT SUM(cost) as total FROM generation_history WHERE user_id = ?",
            (user.id,),
        )
        cost_row = await cursor.fetchone()

        referral_stats = await get_referral_stats(telegram_id)

        return {
            "credits": user.credits,
            "generations": gen_row["count"] or 0,
            "total_spent": cost_row["total"] or 0,
            "member_since": user.created_at.strftime("%d.%m.%Y"),
            "username": user.username or "",
            "referral_code": referral_stats["referral_code"],
            "referrals_count": referral_stats["referrals_count"],
            "referral_earned": referral_stats["referral_earned"],
        }


async def get_admin_stats() -> dict:
    """Получает общую статистику для админа"""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        # Всего пользователей
        cursor = await db.execute("SELECT COUNT(*) as count FROM users")
        users_row = await cursor.fetchone()

        # Всего генераций
        # Исторически часть запусков писалась в generation_history,
        # а актуальный поток пишет задачи в generation_tasks.
        cursor = await db.execute("SELECT COUNT(*) as count FROM generation_history")
        gen_history_row = await cursor.fetchone()
        cursor = await db.execute("SELECT COUNT(*) as count FROM generation_tasks")
        gen_tasks_row = await cursor.fetchone()

        # Всего транзакций
        cursor = await db.execute(
            "SELECT COUNT(*) as count, SUM(amount_rub) as total FROM transactions WHERE status = 'completed'"
        )
        trans_row = await cursor.fetchone()

        # Пакетных генераций
        cursor = await db.execute("SELECT COUNT(*) as count FROM batch_jobs")
        batch_row = await cursor.fetchone()

        cursor = await db.execute("SELECT COUNT(*) as count FROM referrals")
        referrals_row = await cursor.fetchone()

        return {
            "total_users": users_row["count"] or 0,
            "total_generations": max(
                gen_history_row["count"] or 0,
                gen_tasks_row["count"] or 0,
            ),
            "total_revenue": trans_row["total"] or 0,
            "total_transactions": trans_row["count"] or 0,
            "total_batch_jobs": batch_row["count"] or 0,
            "total_referrals": referrals_row["count"] or 0,
        }


async def _ensure_bot_settings_table(db: db_backend.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_by_telegram_id INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


_BOT_SETTING_CACHE: dict[str, tuple[float, str | None]] = {}
_BOT_SETTING_CACHE_TTL_SECONDS = 5.0


async def get_bot_setting(key: str, default: str | None = None) -> str | None:
    """Возвращает значение глобальной настройки бота."""
    setting_key = str(key or "").strip()[:80]
    if not setting_key:
        return default

    now = time.monotonic()
    cached = _BOT_SETTING_CACHE.get(setting_key)
    if cached and cached[0] > now:
        return cached[1] if cached[1] is not None else default

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await _ensure_bot_settings_table(db)
        cursor = await db.execute(
            "SELECT value FROM bot_settings WHERE key = ? LIMIT 1",
            (setting_key,),
        )
        row = await cursor.fetchone()
        value = row["value"] if row else None
        _BOT_SETTING_CACHE[setting_key] = (now + _BOT_SETTING_CACHE_TTL_SECONDS, value)
        return value if value is not None else default


async def set_bot_setting(
    key: str,
    value: str | int | float | bool,
    *,
    updated_by_telegram_id: int | None = None,
) -> bool:
    """Сохраняет глобальную настройку бота."""
    setting_key = str(key or "").strip()[:80]
    if not setting_key:
        return False

    setting_value = "1" if value is True else "0" if value is False else str(value)

    async with db_backend.connect(DATABASE_PATH) as db:
        await _ensure_bot_settings_table(db)
        await db.execute(
            """
            INSERT INTO bot_settings (key, value, updated_by_telegram_id, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_by_telegram_id = excluded.updated_by_telegram_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                setting_key,
                setting_value,
                int(updated_by_telegram_id) if updated_by_telegram_id else None,
            ),
        )
        await db.commit()
        _BOT_SETTING_CACHE.pop(setting_key, None)
        return True


async def is_maintenance_mode_enabled() -> bool:
    return (await get_bot_setting("maintenance_mode", "0")) == "1"


async def set_maintenance_mode(
    enabled: bool,
    *,
    updated_by_telegram_id: int | None = None,
) -> bool:
    return await set_bot_setting(
        "maintenance_mode",
        "1" if enabled else "0",
        updated_by_telegram_id=updated_by_telegram_id,
    )


async def is_channel_subscription_required() -> bool:
    return (await get_bot_setting("required_channel_subscription", "0")) == "1"


async def set_channel_subscription_required(
    enabled: bool,
    *,
    updated_by_telegram_id: int | None = None,
) -> bool:
    return await set_bot_setting(
        "required_channel_subscription",
        "1" if enabled else "0",
        updated_by_telegram_id=updated_by_telegram_id,
    )


async def is_user_banned(telegram_id: int) -> bool:
    """Проверяет, заблокирован ли пользователь на уровне бота."""
    try:
        async with db_backend.connect(DATABASE_PATH) as db:
            db.row_factory = db_backend.Row
            cursor = await db.execute(
                "SELECT COALESCE(is_banned, 0) AS is_banned FROM users WHERE telegram_id = ? LIMIT 1",
                (int(telegram_id),),
            )
            row = await cursor.fetchone()
            return bool(row and row["is_banned"])
    except db_backend.OperationalError:
        return False


async def set_user_banned(
    telegram_id: int,
    banned: bool,
    *,
    admin_id: int | None = None,
) -> bool:
    """Ставит или снимает бан без создания нового пользователя."""
    async with db_backend.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE users
            SET is_banned = ?,
                banned_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END,
                banned_by_telegram_id = CASE WHEN ? = 1 THEN ? ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
            """,
            (
                1 if banned else 0,
                1 if banned else 0,
                1 if banned else 0,
                int(admin_id) if admin_id else None,
                int(telegram_id),
            ),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_existing_user_stats(telegram_id: int) -> Optional[dict[str, Any]]:
    """Возвращает статистику только для существующего пользователя."""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT COALESCE(is_banned, 0) AS is_banned
            FROM users
            WHERE telegram_id = ?
            LIMIT 1
            """,
            (int(telegram_id),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        is_banned_value = bool(row["is_banned"])

    stats = await get_user_stats(telegram_id)
    stats["is_banned"] = is_banned_value
    return stats


async def export_users_for_admin(limit: int = 50000) -> list[dict[str, Any]]:
    """Возвращает ограниченный список пользователей для подтверждённого экспорта."""
    safe_limit = max(1, min(int(limit or 50000), 50000))
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT
                telegram_id,
                username,
                first_name,
                last_name,
                credits,
                COALESCE(is_banned, 0) AS is_banned,
                referral_code,
                referred_by,
                has_paid,
                created_at,
                updated_at
            FROM users
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        return _sqlite_rows_to_dicts(await cursor.fetchall())


async def save_batch_job(
    job_id: str,
    user_id: int,
    mode: str,
    total_cost: int,
    results_count: int,
    duration: Optional[float] = None,
) -> bool:
    """Сохраняет результаты пакетной генерации"""
    async with db_backend.connect(DATABASE_PATH) as db:
        try:
            # Создаём таблицу если не существует
            await db.execute("""
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    total_cost INTEGER NOT NULL,
                    results_count INTEGER DEFAULT 0,
                    duration REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            await db.execute(
                """INSERT INTO batch_jobs 
                   (job_id, user_id, mode, total_cost, results_count, duration) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (job_id, user_id, mode, total_cost, results_count, duration),
            )
            await db.commit()
            logger.info(f"Saved batch job: {job_id}")
            return True
        except db_backend.IntegrityError:
            logger.warning(f"Batch job already exists: {job_id}")
            return False


async def get_batch_jobs_by_user(telegram_id: int, limit: int = 10) -> list:
    """Получает историю пакетных генераций пользователя"""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        user = await get_or_create_user(telegram_id)

        cursor = await db.execute(
            """SELECT * FROM batch_jobs 
               WHERE user_id = ? 
               ORDER BY created_at DESC 
               LIMIT ?""",
            (user.id, limit),
        )
        rows = await cursor.fetchall()

        return [
            {
                "job_id": row["job_id"],
                "mode": row["mode"],
                "total_cost": row["total_cost"],
                "results_count": row["results_count"],
                "duration": row["duration"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


async def get_user_last_generation(user_id: int, limit: int = 1) -> Optional[dict]:
    """Получает последнюю(ие) генерацию(и) пользователя"""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        cursor = await db.execute(
            """SELECT * FROM generation_tasks 
               WHERE user_id = ? 
               ORDER BY created_at DESC 
               LIMIT ?""",
            (user_id, limit),
        )
        rows = await cursor.fetchall()

        if not rows:
            return None

        if limit == 1:
            row = rows[0]
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "type": row["type"],
                "preset_id": row["preset_id"],
                "status": row["status"],
                "result_url": row["result_url"],
                "created_at": row["created_at"],
            }

        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "type": row["type"],
                "preset_id": row["preset_id"],
                "status": row["status"],
                "result_url": row["result_url"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


async def _ensure_user_settings_table(db):
    """Создает таблицу user_settings если она не существует (миграция)"""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            preferred_model TEXT DEFAULT 'flash',
            preferred_video_model TEXT DEFAULT 'v3_std',
            preferred_i2v_model TEXT DEFAULT 'v3_std',
            image_service TEXT DEFAULT 'nanobanana',
            referral_purchase_notifications_enabled BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    # Миграция: добавляем колонку image_service если её нет
    try:
        await db.execute(
            "ALTER TABLE user_settings ADD COLUMN image_service TEXT DEFAULT 'nanobanana'"
        )
    except db_backend.OperationalError:
        pass  # Колонка уже существует
    try:
        await db.execute(
            "ALTER TABLE user_settings ADD COLUMN referral_purchase_notifications_enabled BOOLEAN DEFAULT 1"
        )
    except db_backend.OperationalError:
        pass  # Колонка уже существует
    await db.commit()


async def get_user_settings(telegram_id: int) -> dict:
    """Получает настройки пользователя из БД"""
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row

        # Создаем таблицу если не существует
        await _ensure_user_settings_table(db)

        # Получаем внутренний user_id
        user = await get_or_create_user(telegram_id)

        cursor = await db.execute(
            """SELECT preferred_model, preferred_video_model, preferred_i2v_model, image_service,
                      referral_purchase_notifications_enabled
               FROM user_settings WHERE user_id = ?""",
            (user.id,),
        )
        row = await cursor.fetchone()

        if row:
            return {
                "preferred_model": row["preferred_model"],
                "preferred_video_model": row["preferred_video_model"],
                "preferred_i2v_model": row["preferred_i2v_model"],
                "image_service": (
                    row["image_service"]
                    if "image_service" in row.keys()
                    else "nanobanana"
                ),
                "referral_purchase_notifications_enabled": (
                    bool(row["referral_purchase_notifications_enabled"])
                    if "referral_purchase_notifications_enabled" in row.keys()
                    and row["referral_purchase_notifications_enabled"] is not None
                    else True
                ),
            }

        # Если настроек нет, возвращаем значения по умолчанию
        return {
            "preferred_model": "flash",
            "preferred_video_model": "v3_std",
            "preferred_i2v_model": "v3_std",
            "image_service": "nanobanana",
            "referral_purchase_notifications_enabled": True,
        }


async def save_user_settings(
    telegram_id: int,
    preferred_model: str = None,
    preferred_video_model: str = None,
    preferred_i2v_model: str = None,
    image_service: str = None,
    referral_purchase_notifications_enabled: Optional[bool] = None,
) -> bool:
    """Сохраняет настройки пользователя в БД"""
    async with db_backend.connect(DATABASE_PATH) as db:
        # Создаем таблицу если не существует
        await _ensure_user_settings_table(db)

        # Получаем внутренний user_id
        user = await get_or_create_user(telegram_id)

        # Получаем текущие настройки
        cursor = await db.execute(
            "SELECT * FROM user_settings WHERE user_id = ?",
            (user.id,),
        )
        existing = await cursor.fetchone()

        if existing:
            # Обновляем только переданные значения
            updates = []
            params = []
            if preferred_model is not None:
                updates.append("preferred_model = ?")
                params.append(preferred_model)
            if preferred_video_model is not None:
                updates.append("preferred_video_model = ?")
                params.append(preferred_video_model)
            if preferred_i2v_model is not None:
                updates.append("preferred_i2v_model = ?")
                params.append(preferred_i2v_model)
            if image_service is not None:
                updates.append("image_service = ?")
                params.append(image_service)
            if referral_purchase_notifications_enabled is not None:
                updates.append("referral_purchase_notifications_enabled = ?")
                params.append(1 if referral_purchase_notifications_enabled else 0)

            if updates:
                params.append(user.id)
                await db.execute(
                    f"""UPDATE user_settings 
                        SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP 
                        WHERE user_id = ?""",
                    params,
                )
                await db.commit()
                logger.info(f"Updated settings for user {telegram_id}")
        else:
            # Создаём новую запись с переданными значениями
            await db.execute(
                """INSERT INTO user_settings 
                   (user_id, preferred_model, preferred_video_model, preferred_i2v_model, image_service,
                    referral_purchase_notifications_enabled) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user.id,
                    preferred_model or "flash",
                    preferred_video_model or "v3_std",
                    preferred_i2v_model or "v3_std",
                    image_service or "nanobanana",
                    1
                    if referral_purchase_notifications_enabled is None
                    else 1 if referral_purchase_notifications_enabled else 0,
                ),
            )
            await db.commit()
            logger.info(f"Created settings for user {telegram_id}")

        return True
