---
name: Telegram video delivery
description: Constraints that affect whether a valid MP4 presents correctly as a Telegram video.
---

Telegram video previews require a small JPEG cover/thumbnail; a full-resolution portrait frame may be silently omitted even when `sendVideo` accepts the MP4.

**Why:** A valid H.264/AAC upload returned without preview metadata when its 1080×1920 frame was used directly; a 180×320 JPEG supplied through both cover fields was preserved.

**How to apply:** Generate a representative frame no larger than 320px on either side, pass it as both the modern cover and legacy thumbnail, and inspect the returned Telegram video metadata during delivery diagnostics.