from __future__ import annotations

import time

from bot import db as db_backend
from bot.instagram_generation import ensure_instagram_generation_schema


async def ensure_instagram_video_draft(identity_id: int) -> None:
    """Create an empty durable creator session before the paid video paywall."""
    if identity_id <= 0:
        raise ValueError("identity_id must be positive")

    await ensure_instagram_generation_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        await db.execute(
            """
            INSERT INTO instagram_generation_sessions (
                identity_id, image_url, prompt, state, updated_at_epoch
            ) VALUES (?, '', '', 'idle', ?)
            ON CONFLICT(identity_id) DO NOTHING
            """,
            (identity_id, now),
        )
        await db.commit()
