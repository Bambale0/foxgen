"""
Handlers for the Telegram bot.
"""

from aiogram import Router

from bot import keyboards as keyboards_module
from bot.services.lava_binding_schema_compat import (
    install_lava_binding_schema_compat,
)
from bot.services.lava_invoice_compat import install_lava_invoice_compat
from bot.services.lava_payment_safety import install_lava_payment_safety
from bot.services.partner_approval_service import install_partner_referral_approval_guard
from bot.services.prompt_fragment_coalescer import PromptFragmentCoalescingMiddleware
from bot.services.publication_scope_postgres_compat import (
    install_publication_scope_postgres_compat,
)

from . import trends_compat as trends_compat_module
from .feed_model_filter_compat import install_feed_model_filter_compat
from .feed_model_filter_compat import router as feed_model_filter_compat_router
from .miniapp_regression_safety import install_miniapp_regression_safety
from .miniapp_video_continuity_compat import install_miniapp_video_continuity_compat
from .own_profile_feed_compat import install_own_profile_feed_compat
from .profile_feed_deeplink_compat import install_profile_feed_deeplink_compat

from .publication_scope_compat import (
    install_common_publication_scope_compat,
    install_publication_scope_compat,
)
from .publication_scope_compat import router as publication_scope_compat_router
from .trend_text_upload import install_text_trend_upload
from .trend_text_upload import router as trend_text_upload_router
from .trend_video_compat import install_trend_video_compat
from .trend_video_compat import router as trend_video_compat_router
from .trends_compat import install_trends_compat
from .trends_compat import router as trends_compat_router

install_publication_scope_postgres_compat()
install_publication_scope_compat()

from . import admin as admin_module
from . import common as common_module
from . import generation as generation_module
from . import lava_checkout as lava_checkout_module
from . import payments as payments_module
from .admin_user_ban import router as admin_user_ban_router
from .batch_generation import router as batch_generation_router
from .freekassa_payments import router as freekassa_payments_router
from .image_analyzer import router as legacy_image_analyzer_router
from .instagram_account_link import router as instagram_account_link_router
from .notification_campaigns import router as notification_campaigns_router
from .partner_approval import admin_router as partner_approval_admin_router
from .partner_approval import user_router as partner_approval_user_router
from .photo_prompt_vk_result_compat import install_vk_photo_prompt_result_compat
from .prompt_analyzer_v2 import router as prompt_analyzer_v2_router
from .repeat_result_compat import router as repeat_result_compat_router
from .seedance_25_chunk_upload import install_seedance_25_chunk_upload
from .seedance_25_client_compat import install_seedance_25_client_compat
from .seedance_25_fullstack import install_seedance_25_fullstack
from .seedance_25_fullstack import router as seedance_25_fullstack_router
from .seedance_25_new_priority import install_seedance_25_new_priority
from .seedance_25_preview import install_seedance_25_preview
from .seedance_25_preview import router as seedance_25_preview_router
from .seedance_25_public_release import install_seedance_25_public_release
from .seedance_25_telegram_compat import install_seedance_25_telegram_compat
from .seedance_25_telegram_compat import router as seedance_25_telegram_compat_router
from .seedance_25_upload_compat import install_seedance_25_upload_compat
from .seedance_25_video_ref_pricing import install_seedance_25_video_ref_pricing
from .seedance_multimodal_compat import install_seedance_multimodal_runtime_compat
from .seedance_multimodal_compat import router as seedance_multimodal_compat_router
from .suno import router as suno_router
from .suno_admin import router as suno_admin_router
from .suno_menu_compat import install_suno_menu_compat
from .suno_priority import router as suno_priority_router
from .support import router as support_router
from .trend_route_compat import install_trend_route_compat
from .trend_seedance_25_compat import install_trend_seedance_25_compat

install_suno_menu_compat(common_module, admin_module, keyboards_module)

admin_router = Router()
admin_router.include_router(partner_approval_admin_router)
admin_router.include_router(admin_user_ban_router)
admin_router.include_router(suno_admin_router)
admin_router.include_router(admin_module.router)

install_lava_binding_schema_compat()
install_lava_payment_safety(payments_module)
install_lava_invoice_compat(payments_module, lava_checkout_module)
legacy_payments_router = payments_module.router
lava_checkout_router = lava_checkout_module.router
legacy_common_router = common_module.router

prompt_fragment_coalescer = PromptFragmentCoalescingMiddleware()
generation_module.router.message.middleware(prompt_fragment_coalescer)
batch_generation_router.message.middleware(prompt_fragment_coalescer)

install_vk_photo_prompt_result_compat()

image_analyzer_router = Router()
image_analyzer_router.include_router(prompt_analyzer_v2_router)
image_analyzer_router.include_router(legacy_image_analyzer_router)

install_seedance_multimodal_runtime_compat()
install_seedance_25_upload_compat()
install_seedance_25_fullstack()
install_seedance_25_chunk_upload()
install_seedance_25_preview()
install_seedance_25_video_ref_pricing()
install_seedance_25_public_release()
install_seedance_25_client_compat()
install_seedance_25_telegram_compat()
install_seedance_25_new_priority()
install_miniapp_video_continuity_compat()
install_trend_seedance_25_compat()
generation_router = Router()
generation_router.include_router(publication_scope_compat_router)
generation_router.include_router(seedance_25_telegram_compat_router)
generation_router.include_router(seedance_25_fullstack_router)
generation_router.include_router(seedance_25_preview_router)
generation_router.include_router(seedance_multimodal_compat_router)
generation_router.include_router(generation_module.router)

payments_router = Router()
payments_router.include_router(lava_checkout_router)
payments_router.include_router(freekassa_payments_router)
payments_router.include_router(legacy_payments_router)

install_common_publication_scope_compat(common_module)
install_profile_feed_deeplink_compat(common_module)
install_trends_compat(common_module, generation_module, admin_module)
install_text_trend_upload(trends_compat_module)
install_trend_video_compat(trends_compat_module)
install_feed_model_filter_compat(common_module)
install_own_profile_feed_compat()
install_partner_referral_approval_guard()
install_miniapp_regression_safety()
install_trend_route_compat()
common_router = Router()
common_router.include_router(partner_approval_user_router)
# These handlers intentionally go first: lyrics/sounds/tools use their own FSM
# and must not be swallowed by the generic Suno generation text state.
common_router.include_router(suno_priority_router)
common_router.include_router(suno_router)
common_router.include_router(trend_video_compat_router)
common_router.include_router(trend_text_upload_router)
common_router.include_router(trends_compat_router)
common_router.include_router(feed_model_filter_compat_router)
common_router.include_router(notification_campaigns_router)
common_router.include_router(repeat_result_compat_router)
common_router.include_router(support_router)
common_router.include_router(instagram_account_link_router)
common_router.include_router(legacy_common_router)

__all__ = [
    "admin_router",
    "batch_generation_router",
    "common_router",
    "feed_model_filter_compat_router",
    "freekassa_payments_router",
    "generation_router",
    "image_analyzer_router",
    "instagram_account_link_router",
    "lava_checkout_router",
    "notification_campaigns_router",
    "payments_router",
    "prompt_analyzer_v2_router",
    "publication_scope_compat_router",
    "repeat_result_compat_router",
    "seedance_25_fullstack_router",
    "seedance_25_preview_router",
    "seedance_25_telegram_compat_router",
    "seedance_multimodal_compat_router",
    "suno_admin_router",
    "suno_priority_router",
    "suno_router",
    "support_router",
    "trend_text_upload_router",
    "trend_video_compat_router",
    "trends_compat_router",
]
