from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
import yt_dlp

from .media import classify_extraction
from .models import ExtractedMedia, MediaType

logger = logging.getLogger(__name__)
SHORTCODE_RE = re.compile(r"/(?:p|reel|reels|tv)/([^/?#]+)", re.IGNORECASE)
EMBED_MEDIA_RE = re.compile(
    r'is_video\\":(?P<is_video>true|false),\\"display_url\\":\\"(?P<url>.*?)(?=\\"[,}])'
)
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)


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
        try:
            info = await asyncio.wait_for(asyncio.to_thread(self._extract_sync, url), timeout=self.timeout)
            if not isinstance(info, dict):
                raise ValueError("yt-dlp returned non-object metadata")
            extracted = classify_extraction(info, url)
            if extracted.entries:
                return extracted
        except Exception as primary_error:
            logger.warning("yt-dlp extraction failed; trying official Instagram embed metadata: %s", primary_error)
        return await self._extract_from_official_page(url)

    @staticmethod
    def _decode_embedded_url(value: str) -> str:
        value = html.unescape(value)
        value = value.replace("\\\\/", "/").replace("\\/", "/")
        value = re.sub(r"\\\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), value)
        value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), value)
        return value.replace("\\\\", "\\")

    def _parse_official_page(self, page: str, source_url: str) -> ExtractedMedia:
        media: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in EMBED_MEDIA_RE.finditer(page):
            media_url = self._decode_embedded_url(match.group("url"))
            if not media_url.startswith(("https://", "http://")) or media_url in seen:
                continue
            seen.add(media_url)
            is_video = match.group("is_video") == "true"
            media.append(
                {
                    "url": media_url,
                    "ext": "mp4" if is_video else "jpg",
                    "vcodec": "h264" if is_video else "none",
                    "acodec": "aac" if is_video else "none",
                    "webpage_url": source_url,
                    "original_url": source_url,
                }
            )
        if not media:
            match = OG_IMAGE_RE.search(page)
            if match:
                media_url = html.unescape(match.group(1)).replace("&amp;", "&")
                if media_url.startswith(("https://", "http://")):
                    media.append(
                        {
                            "url": media_url,
                            "ext": "jpg",
                            "webpage_url": source_url,
                            "original_url": source_url,
                        }
                    )
        if not media:
            raise ValueError("official Instagram page exposed no usable media metadata")
        return ExtractedMedia(
            media_type=MediaType.CAROUSEL if len(media) > 1 else MediaType.PHOTO,
            entries=media,
            is_reel="/reel/" in source_url or "/reels/" in source_url,
        )

    async def _extract_from_official_page(self, source_url: str) -> ExtractedMedia:
        match = SHORTCODE_RE.search(urlsplit(source_url).path)
        if not match:
            raise ValueError("invalid Instagram URL path")
        shortcode = match.group(1)
        path_prefix = "reel" if "/reel/" in source_url or "/reels/" in source_url else "p"
        embed_url = f"https://www.instagram.com/{path_prefix}/{shortcode}/embed/"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "*/*",
            "X-IG-App-ID": "936619743392459",
        }
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
                response = await client.get(embed_url, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError("official Instagram metadata request failed") from exc
        return self._parse_official_page(response.text, source_url)