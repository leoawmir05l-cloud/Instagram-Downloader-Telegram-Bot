from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class MediaType(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    CAROUSEL = "carousel"


@dataclass(frozen=True)
class MediaItem:
    index: int
    media_type: MediaType
    path: Path
    source_url: str
    is_reel: bool = False


@dataclass(frozen=True)
class DownloadBundle:
    media_type: MediaType
    items: list[MediaItem]
    job_directory: Path


@dataclass(frozen=True)
class ExtractedMedia:
    media_type: MediaType
    entries: list[dict[str, Any]]
    is_reel: bool = False