from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    downloads INTEGER NOT NULL DEFAULT 0,
                    successful INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    photos INTEGER NOT NULL DEFAULT 0,
                    videos INTEGER NOT NULL DEFAULT 0,
                    reels INTEGER NOT NULL DEFAULT 0,
                    carousel_items INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS required_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    username TEXT,
                    title TEXT NOT NULL,
                    join_url TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_updates (
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (chat_id, message_id, url)
                );
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    media_type TEXT,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    created_at REAL NOT NULL
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def upsert_user(self, user_id: int, chat_id: int, username: str | None, first_name: str | None) -> None:
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO users(user_id, chat_id, username, first_name, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    chat_id=excluded.chat_id, username=excluded.username,
                    first_name=excluded.first_name, updated_at=excluded.updated_at
                """,
                (user_id, chat_id, username, first_name, now, now),
            )

    def is_banned(self, user_id: int) -> bool:
        row = self._connection.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["is_banned"])

    def set_banned(self, user_id: int, banned: bool) -> None:
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO users(user_id, chat_id, is_banned, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET is_banned=excluded.is_banned, updated_at=excluded.updated_at
                """,
                (user_id, user_id, int(banned), now, now),
            )

    def claim_update(self, chat_id: int, message_id: int, url: str, ttl_seconds: int = 3600) -> bool:
        cutoff = time.time() - ttl_seconds
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM processed_updates WHERE created_at < ?", (cutoff,))
            try:
                self._connection.execute(
                    "INSERT INTO processed_updates(chat_id, message_id, url, created_at) VALUES(?, ?, ?, ?)",
                    (chat_id, message_id, url, time.time()),
                )
            except sqlite3.IntegrityError:
                return False
            return True

    def record_download_start(self, user_id: int, url: str) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO downloads(user_id, url, created_at) VALUES(?, ?, ?)",
                (user_id, url, time.time()),
            )
            return int(cursor.lastrowid)

    def record_download_result(
        self,
        download_id: int,
        user_id: int,
        media_type: str | None,
        item_count: int,
        success: bool,
        error_code: str | None = None,
        *,
        is_reel: bool = False,
        item_types: list[str] | None = None,
    ) -> None:
        photo_count = int(success and media_type == "photo")
        video_count = int(success and media_type == "video")
        carousel_item_count = int(success and media_type == "carousel" and item_count > 0) * item_count
        if success and media_type == "carousel" and item_types:
            photo_count = sum(item_type == "photo" for item_type in item_types)
            video_count = sum(item_type == "video" for item_type in item_types)
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE downloads SET media_type=?, item_count=?, success=?, error_code=? WHERE id=?",
                (media_type, item_count, int(success), error_code, download_id),
            )
            self._connection.execute(
                """
                UPDATE users SET
                    downloads=downloads+1,
                    successful=successful+?,
                    failed=failed+?,
                    photos=photos+?,
                    videos=videos+?,
                    reels=reels+?,
                    carousel_items=carousel_items+?
                WHERE user_id=?
                """,
                (
                    int(success),
                    int(not success),
                    photo_count,
                    video_count,
                    int(success and is_reel),
                    carousel_item_count,
                    user_id,
                ),
            )

    def get_user_stats(self, user_id: int) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT downloads, successful, failed, photos, videos, reels, carousel_items FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return {key: 0 for key in ("downloads", "successful", "failed", "photos", "videos", "reels", "carousel_items")}
        return dict(row)

    def global_stats(self) -> dict[str, int]:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS users, COALESCE(SUM(downloads), 0) AS downloads,
                   COALESCE(SUM(successful), 0) AS successful,
                   COALESCE(SUM(failed), 0) AS failed,
                   COALESCE(SUM(photos), 0) AS photos,
                   COALESCE(SUM(videos), 0) AS videos,
                   COALESCE(SUM(reels), 0) AS reels,
                   COALESCE(SUM(carousel_items), 0) AS carousel_items
            FROM users
            """
        ).fetchone()
        return dict(row)

    def all_user_ids(self) -> list[int]:
        rows = self._connection.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()
        return [int(row["user_id"]) for row in rows]

    def list_users(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT user_id, username, first_name, is_banned, downloads, updated_at FROM users ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_required_channel(
        self, chat_id: int | None, username: str | None, title: str, join_url: str
    ) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO required_channels(chat_id, username, title, join_url, created_at) VALUES(?, ?, ?, ?, ?)",
                (chat_id, username, title, join_url, time.time()),
            )
            return int(cursor.lastrowid)

    def list_required_channels(self) -> list[dict[str, Any]]:
        rows = self._connection.execute("SELECT * FROM required_channels ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def delete_required_channel(self, channel_id: int) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM required_channels WHERE id=?", (channel_id,))
            return cursor.rowcount > 0

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )