from __future__ import annotations

import asyncio
import html
import logging
import re
import time
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
IMAGE_ATTRIBUTE_RE = re.compile(r'(?:srcset|src)=["\']([^"\']+)["\']', re.IGNORECASE)


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
        started = time.perf_counter()
        try:
            info = await asyncio.wait_for(asyncio.to_thread(self._extract_sync, url), timeout=self.timeout)
            if not isinstance(info, dict):
                raise ValueError("yt-dlp returned non-object metadata")
            extracted = classify_extraction(info, url)
            if extracted.entries:
                logger.info(
                    "[EXTRACT] source_type=%s entries=%s elapsed=%.2fs",
                    extracted.media_type.value,
                    len(extracted.entries),
                    time.perf_counter() - started,
                )
                return extracted
        except Exception as primary_error:
            logger.warning("yt-dlp extraction failed; trying official Instagram embed metadata: %s", primary_error)
        extracted = await self._extract_from_official_page(url)
        logger.info(
            "[EXTRACT] fallback source_type=%s entries=%s elapsed=%.2fs",
            extracted.media_type.value,
            len(extracted.entries),
            time.perf_counter() - started,
        )
        return extracted

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
            media = self._parse_full_frame_image_sources(page, source_url)
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

    @classmethod
    def _parse_full_frame_image_sources(cls, page: str, source_url: str) -> list[dict[str, Any]]:
        grouped: dict[str, list[str]] = {}
        order: list[str] = []
        for attribute in IMAGE_ATTRIBUTE_RE.findall(page):
            for token in attribute.split(","):
                raw_url = token.strip().split(" ", 1)[0]
                media_url = cls._decode_embedded_url(raw_url)
                if not media_url.startswith(("https://", "http://")):
                    continue
                parsed = urlsplit(media_url)
                filename = parsed.path.rsplit("/", 1)[-1]
                if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    continue
                if filename not in grouped:
                    grouped[filename] = []
                    order.append(filename)
                if media_url not in grouped[filename]:
                    grouped[filename].append(media_url)

        def source_score(media_url: str) -> tuple[int, int]:
            query = urlsplit(media_url).query
            stp = query.split("&", 1)[0].removeprefix("stp=")
            # An untransformed dst-jpg source is preferred over p/s resized
            # variants and c cropped variants. The dimensions are preserved.
            if "dst-jpg" in stp and not re.search(r"(?:^|_)(?:p|s|c)\d", stp):
                return (3, 0)
            sizes = re.findall(r"(?:p|s)(\d+)x(\d+)", stp)
            largest = max((int(width) * int(height) for width, height in sizes), default=0)
            if "c" in stp:
                return (1, largest)
            return (2, largest)

        selected: list[dict[str, Any]] = []
        for filename in order:
            candidates = grouped[filename]
            best = max(candidates, key=source_score)
            # Profile/avatar resources have only tiny single-size variants;
            # post media normally has a source plus a responsive srcset.
            if len(candidates) == 1 and source_score(best)[1] and source_score(best)[1] <= 100 * 100:
                continue
            selected.append(
                {
                    "url": best,
                    "ext": "jpg",
                    "webpage_url": source_url,
                    "original_url": source_url,
                }
            )
        # When the embed does not expose structured media entries, its first
        # responsive image group is the post media; later groups are often
        # recommendation/profile images from the embed page.
        return selected[:1]

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
                try:
                    return self._parse_official_page(response.text, source_url)
                except ValueError:
                    # Some public photo posts expose only standard Open Graph
                    # metadata on the normal page, not the embed payload.
                    page_url = f"https://www.instagram.com/{path_prefix}/{shortcode}/?output=1"
                    response = await client.get(page_url, headers=headers)
                    response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError("official Instagram metadata request failed") from exc
        return self._parse_official_page(response.text, source_url)