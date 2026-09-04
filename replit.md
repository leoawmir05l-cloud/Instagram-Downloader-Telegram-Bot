# Instagram Downloader Telegram Bot

Python Telegram bot that downloads public Instagram photos, videos, Reels, and mixed carousels with exact ordering and reply-to-source behavior.

## Run & Operate

- `python main.py` — run the Telegram long-polling bot
- `python -m pytest -q` — run the Python test suite
- `python -m compileall -q telegram_bot tests` — syntax check
- Required secret: `BOT_TOKEN`
- Required environment value: `ADMIN_ID`
- Optional environment values are documented in `README.md`.

## Stack

- Python 3.12, python-telegram-bot 22.x, yt-dlp, FFmpeg/FFprobe, SQLite, asyncio, httpx, Pillow
- The original pnpm workspace artifacts remain available but are not part of the bot runtime.

## Where things live

- `telegram_bot/bot.py` — application assembly and polling entry point
- `telegram_bot/handlers.py` — user flows, media sending, callbacks, admin actions
- `telegram_bot/downloader.py` — yt-dlp/HTTP photo download, FFmpeg/FFprobe validation, cleanup
- `telegram_bot/media.py` — media classification and image-source selection
- `telegram_bot/database.py` — SQLite schema and persistence
- `tests/` — offline unit and integration-style tests

## Architecture decisions

- Photos are classified and downloaded independently from videos; no video stream is required.
- Carousel entry index is the ordering source of truth; media groups are intentionally not used.
- Every media send uses Telegram `reply_parameters` pointing to the source message.
- Each job receives an isolated temporary directory and is removed on success or failure.
- Telegram transport logs are kept above INFO so bot tokens cannot appear in request URLs.

## Product

Users send a public Instagram URL in a private chat or group and receive validated media in Persian, with personal download statistics and an admin panel for moderation, broadcasts, and required channels.

## User preferences

- Build the complete specification from the beginning rather than leaving placeholder buttons or deferred core features.

## Gotchas

- Live Instagram and Telegram API tests are not part of the offline suite; they require public URLs and real Telegram chats.
- Never enable `httpx` INFO logs because Telegram Bot API URLs include the bot token.

## Pointers

- See `README.md` for configuration and operational details.
