from __future__ import annotations

import asyncio
import logging
from typing import Any

import yt_dlp

from .media import classify_extraction
from .models import ExtractedMedia

logger = logging.getLogger(__name__)


class InstagramExtractor:
    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def _extract_sync(self, url: str) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": False,
            "socket_timeout": self.timeout,
            "retries": 2,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False)

    async def extract(self, url: str) -> ExtractedMedia:
        info = await asyncio.wait_for(asyncio.to_thread(self._extract_sync, url), timeout=self.timeout)
        if not isinstance(info, dict):
            raise ValueError("yt-dlp returned non-object metadata")
        return classify_extraction(info, url)