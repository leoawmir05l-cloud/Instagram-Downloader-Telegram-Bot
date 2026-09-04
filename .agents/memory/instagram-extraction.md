---
name: Instagram extraction fallback
description: Why the bot needs an official embed metadata fallback for some public Instagram posts.
---

yt-dlp can return “no video formats found” for valid public photo-only posts and image carousels; the official Instagram embed page can expose ordered `is_video` and `display_url` metadata instead.

**Why:** Some current Instagram responses contain valid image media but no video formats, and ordinary page HTML may vary by User-Agent.

**How to apply:** Keep yt-dlp as the primary extractor, then use the official embed endpoint with a minimal browser User-Agent and parse only its media metadata; never invent or search for substitute URLs.