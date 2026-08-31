from __future__ import annotations

from typing import Any
from urllib.parse import quote

from bot.max_api import MaxApiError, MaxClient, MaxSettings


class MaxCreatorClient(MaxClient):
    """MAX client extensions needed by creator input flows."""

    def __init__(self, settings: MaxSettings, **kwargs: Any) -> None:
        super().__init__(settings, **kwargs)

    async def get_video_details(self, video_token: str) -> dict[str, Any]:
        token = str(video_token or "").strip()
        if not token:
            raise ValueError("MAX video token is required")
        return await self._request_json(
            "GET",
            f"/videos/{quote(token, safe='')}",
        )

    @staticmethod
    def first_https_url(value: Any) -> str:
        if isinstance(value, str):
            candidate = value.strip()
            return candidate if candidate.startswith("https://") else ""
        if isinstance(value, list):
            for item in value:
                found = MaxCreatorClient.first_https_url(item)
                if found:
                    return found
            return ""
        if isinstance(value, dict):
            preferred_keys = (
                "download",
                "download_url",
                "mp4",
                "url",
                "play",
                "play_url",
                "hls",
            )
            for key in preferred_keys:
                if key in value:
                    found = MaxCreatorClient.first_https_url(value[key])
                    if found:
                        return found
            for nested in value.values():
                found = MaxCreatorClient.first_https_url(nested)
                if found:
                    return found
        return ""

    async def resolve_video_token(self, video_token: str) -> tuple[str, int | None]:
        details = await self.get_video_details(video_token)
        url = self.first_https_url(details.get("urls") or details)
        if not url:
            raise MaxApiError("MAX video details did not contain a downloadable URL")
        raw_duration = details.get("duration")
        try:
            duration = int(raw_duration) if raw_duration is not None else None
        except (TypeError, ValueError):
            duration = None
        return url, duration
