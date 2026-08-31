from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from bot.max_api import MaxApiError


class MaxVideoTransport(Protocol):
    async def _request_json(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MaxResolvedVideo:
    url: str
    duration_seconds: int | None


class MaxCreatorClient:
    """Creator-specific MAX API adapter over the shared authenticated client."""

    def __init__(self, transport: MaxVideoTransport) -> None:
        self.transport = transport

    async def get_video_details(self, video_token: str) -> dict[str, Any]:
        token = str(video_token or "").strip()
        if not token:
            raise MaxApiError("MAX video token is required")
        return await self.transport._request_json(
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
                "mp4_1080",
                "mp4_720",
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

    async def resolve_video_attachment(self, video_token: str) -> MaxResolvedVideo:
        details = await self.get_video_details(video_token)
        url = self.first_https_url(details.get("urls") or details)
        if not url:
            raise MaxApiError("MAX video details did not contain a downloadable URL")

        raw_duration = details.get("duration")
        try:
            duration = (
                round(float(raw_duration))
                if raw_duration not in (None, "")
                else None
            )
        except (TypeError, ValueError):
            duration = None
        return MaxResolvedVideo(url=url, duration_seconds=duration)
