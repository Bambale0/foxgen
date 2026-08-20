# ruff: noqa: I001
"""Register Seedance 2.5-specific Mini App upload kinds.

The generic Mini App upload cap is 50 MB. Seedance 2.5 allows video references
up to 200 MB, while image/audio limits are 30/15 MB. Separate file kinds keep
those larger limits isolated from every other model. Large videos are uploaded
in small temporary chunks so Cloudflare/Nginx request-size ceilings do not make
the provider's 200 MB input limit unreachable.
"""

from __future__ import annotations


_DEF = {
    "seedance25_image_reference": {
        "prefix": "image/",
        "fallback_ext": "png",
        "group": "image",
        "max_bytes": 30 * 1024 * 1024,
        "durable_reference": True,
        "source": "miniapp_seedance25",
    },
    "seedance25_video_reference": {
        "prefix": "video/",
        "fallback_ext": "mp4",
        "group": "video",
        "max_bytes": 45 * 1024 * 1024,
        "durable_reference": True,
        "source": "miniapp_seedance25",
    },
    "seedance25_video_chunk": {
        "prefix": "video/",
        "fallback_ext": "part",
        "group": "video",
        "max_bytes": 8 * 1024 * 1024,
        "durable_reference": False,
        "source": "miniapp_seedance25_chunk",
    },
    "seedance25_audio_reference": {
        "prefix": "audio/",
        "fallback_ext": "mp3",
        "group": "audio",
        "max_bytes": 15 * 1024 * 1024,
        "durable_reference": True,
        "source": "miniapp_seedance25",
    },
}


def install_seedance_25_upload_compat() -> None:
    import bot.miniapp as miniapp_module

    for key, value in _DEF.items():
        miniapp_module.FILE_KIND_MAP.setdefault(key, dict(value))
