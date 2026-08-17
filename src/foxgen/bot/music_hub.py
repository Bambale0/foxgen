from aiogram import Router

from foxgen.bot.suno_extend_flow import router as extend_router
from foxgen.bot.suno_upload_cover_flow import router as cover_router


router = Router(name="music-suno-extend")
router.include_router(cover_router)
router.include_router(extend_router)
