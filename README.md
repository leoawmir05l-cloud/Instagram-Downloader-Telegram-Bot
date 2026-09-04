# Instagram Downloader Telegram Bot

A production-oriented Python 3.12 Telegram long-polling bot for downloading public Instagram photos, videos, Reels, and mixed carousels.

## Features

- Public Instagram `p`, `reel`, `reels`, and `tv` URLs found anywhere in messages, captions, or quoted messages.
- Photo extraction is independent from video extraction. A photo with no video stream is still a photo.
- Mixed carousel items are downloaded and sent in exact Instagram order.
- Each photo is sent both as a Telegram Photo and as the untouched original Document.
- Videos use yt-dlp's best practical video/audio selection, FFmpeg remuxing, FFprobe validation, fast-start MP4 output, and generated thumbnails.
- Every media message includes `📥 Downloaded by @inestaMardom_bot` and replies to the original URL message.
- Persian `/start`, real inline callback buttons, private-chat reply keyboard, personal statistics, admin panel, bans, broadcast, and required-channel checks.
- SQLite persistence with WAL, busy timeout, duplicate-update protection, per-job temporary directories, and cleanup on every outcome.

## Configuration

Required Replit environment values:

- `BOT_TOKEN` — Telegram BotFather token stored as a secret.
- `ADMIN_ID` — numeric Telegram user ID for the administrator.

Optional values:

- `BOT_USERNAME` (default `inestaMardom_bot`)
- `CHANNEL_URL` (public channel button)
- `BOT_DATABASE_PATH` (default `data/bot.sqlite3`)
- `BOT_WORK_ROOT` (default `data/jobs`)
- `DOWNLOAD_TIMEOUT_SECONDS` (default `300`)
- `MAX_CONCURRENT_DOWNLOADS` (default `3`)

## Run

```bash
python main.py
```

The bot uses long polling and requires FFmpeg/FFprobe on the host.

## Test

```bash
pytest -q
```

The test suite covers URL extraction, photo-without-video classification, mixed carousel order, image and video validation, reply parameters, callbacks, SQLite persistence, required channels, and duplicate protection. Live Instagram and Telegram API tests are intentionally not run during local verification because they require external accounts and can mutate Telegram chats.