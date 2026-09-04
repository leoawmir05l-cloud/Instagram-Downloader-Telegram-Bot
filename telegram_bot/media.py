from __future__ import annotations

import mimetypes
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from .models import ExtractedMedia, MediaType

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif", "heic"}
VIDEO_EXTENSIONS = {"mp4", "m4v", "mov", "webm", "mkv", "avi"}


def _extension(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    path = parsed.path.rsplit("/", 1)[-1]
    if "." not in path:
        return ""
    return path.rsplit(".", 1)[-1].lower()


def _has_video_stream(info: dict[str, Any]) -> bool:
    for key in ("vcodec", "video_codec"):
        if info.get(key) and info[key] not in {"none", "null"}:
            return True
    for key in ("formats", "requested_formats", "requested_downloads"):
        values = info.get(key) or []
        if isinstance(values, dict):
            values = [values]
        if any(
            isinstance(item, dict)
            and item.get("vcodec")
            and item.get("vcodec") != "none"
            for item in values
        ):
            return True
    return _extension(str(info.get("ext", ""))) in VIDEO_EXTENSIONS


def _has_image_source(info: dict[str, Any]) -> bool:
    candidates: list[str] = []
    for key in ("url", "original_url", "webpage_url"):
        if isinstance(info.get(key), str):
            candidates.append(info[key])
    for key in ("formats", "thumbnails"):
        values = info.get(key) or []
        if isinstance(values, dict):
            values = [values]
        for value in values:
            if isinstance(value, dict) and isinstance(value.get("url"), str):
                candidates.append(value["url"])
    return any(_extension(candidate) in IMAGE_EXTENSIONS for candidate in candidates) or any(
        (mimetypes.guess_type(candidate)[0] or "").startswith("image/")
        for candidate in candidates
    )


def classify_entry(info: dict[str, Any]) -> MediaType:
    """Classify metadata without assuming every Instagram item is a video."""
    if info.get("entries"):
        return MediaType.CAROUSEL
    if _has_video_stream(info):
        return MediaType.VIDEO
    if _has_image_source(info) or info.get("thumbnail") or info.get("image"):
        return MediaType.PHOTO
    # A direct URL with no video metadata is still treated as a photo candidate;
    # the downloader will validate it and surface a precise failure if invalid.
    if info.get("url"):
        return MediaType.PHOTO
    raise ValueError("yt-dlp metadata contains no usable media source")


def iter_entries(info: dict[str, Any]) -> list[dict[str, Any]]:
    entries = info.get("entries")
    if not entries:
        return [info]
    result: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict):
            result.append(entry)
    if not result:
        raise ValueError("yt-dlp returned an empty carousel")
    return result


def classify_extraction(info: dict[str, Any], source_url: str) -> ExtractedMedia:
    entries = iter_entries(info)
    media_type = MediaType.CAROUSEL if len(entries) > 1 or info.get("entries") else classify_entry(entries[0])
    is_reel = "/reel/" in source_url or "/reels/" in source_url
    return ExtractedMedia(media_type=media_type, entries=entries, is_reel=is_reel)


def source_image_url(info: dict[str, Any]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for key, score in (("url", 100), ("original_url", 90), ("image", 80), ("thumbnail", 10)):
        value = info.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            candidates.append((score, value))
    for key in ("formats", "thumbnails"):
        values = info.get(key) or []
        if isinstance(values, dict):
            values = [values]
        for value in values:
            if not isinstance(value, dict) or not isinstance(value.get("url"), str):
                continue
            score = 50 + int(value.get("width") or 0) // 1000
            candidates.append((score, value["url"]))
    declared_ext = str(info.get("ext") or "").lower()
    image_candidates = [
        (score, value)
        for score, value in candidates
        if _extension(value) in IMAGE_EXTENSIONS
        or (score >= 80 and declared_ext in IMAGE_EXTENSIONS)
        or (mimetypes.guess_type(value)[0] or "").startswith("image/")
    ]
    if not image_candidates:
        return None
    return max(image_candidates, key=lambda pair: pair[0])[1]


def entry_source_url(info: dict[str, Any], fallback: str) -> str:
    for key in ("webpage_url", "original_url", "url"):
        if isinstance(info.get(key), str) and info[key]:
            return info[key]
    return fallback