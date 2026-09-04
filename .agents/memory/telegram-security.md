---
name: Telegram transport logging
description: Prevent bot credentials from appearing in Telegram API request logs.
---

Telegram Bot API request URLs contain the bot token, so HTTP transport logging must remain at WARNING or lower verbosity in production.

**Why:** INFO-level HTTP client logs can include the full request URL during startup and polling.

**How to apply:** Keep `httpx` and `httpcore` above INFO in the bot logging configuration and never include token-bearing URLs in diagnostics.