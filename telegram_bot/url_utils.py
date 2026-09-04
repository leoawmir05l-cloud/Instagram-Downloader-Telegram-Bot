from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


INSTAGRAM_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/[A-Za-z0-9_-]+(?:/)?(?:\?[^\s<>\"]*)?",
    re.IGNORECASE,
)
TRAILING_PUNCTUATION = ".,!?;:'\"،؛؟)]}»"


def normalize_instagram_url(raw_url: str) -> str:
    value = raw_url.strip().strip("<>")
    while value and value[-1] in TRAILING_PUNCTUATION:
        value = value[:-1]
    parts = urlsplit(value)
    host = parts.netloc.lower()
    if host == "www.instagram.com":
        host = "www.instagram.com"
    elif host == "instagram.com":
        host = "www.instagram.com"
    path = parts.path
    if parts.fragment and not parts.query:
        path = path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, parts.query, ""))


def extract_instagram_urls(text: str | None) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in INSTAGRAM_URL_RE.finditer(text):
        normalized = normalize_instagram_url(match.group(0))
        if normalized not in seen:
            seen.add(normalized)
            found.append(normalized)
    return found


def extract_url_from_message(message: object) -> str | None:
    """Extract the first URL from a message and its quoted/replied message."""
    current_text = getattr(message, "text", None) or getattr(message, "caption", None)
    urls = extract_instagram_urls(current_text)
    if urls:
        return urls[0]
    quoted = getattr(message, "reply_to_message", None)
    if quoted is not None:
        quoted_text = getattr(quoted, "text", None) or getattr(quoted, "caption", None)
        urls = extract_instagram_urls(quoted_text)
        if urls:
            return urls[0]
    return None