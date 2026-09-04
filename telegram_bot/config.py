from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_id: int
    database_path: Path
    bot_username: str
    channel_url: str
    download_timeout_seconds: int
    max_concurrent_downloads: int
    work_root: Path

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required")
        admin_id_raw = os.getenv("ADMIN_ID", "").strip()
        try:
            admin_id = int(admin_id_raw)
        except ValueError as exc:
            raise RuntimeError("ADMIN_ID must be a numeric Telegram user ID") from exc

        database_path = Path(os.getenv("BOT_DATABASE_PATH", "data/bot.sqlite3"))
        work_root = Path(os.getenv("BOT_WORK_ROOT", "data/jobs"))
        return cls(
            bot_token=token,
            admin_id=admin_id,
            database_path=database_path,
            bot_username=os.getenv("BOT_USERNAME", "inestaMardom_bot").lstrip("@"),
            channel_url=os.getenv("CHANNEL_URL", "").strip(),
            download_timeout_seconds=max(30, int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "300"))),
            max_concurrent_downloads=max(1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))),
            work_root=work_root,
        )