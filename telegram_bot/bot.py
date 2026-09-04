from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .config import Settings
from .database import Database
from .downloader import MediaDownloader
from .handlers import (
    handle_admin_command,
    handle_ban_command,
    handle_callback,
    handle_message,
    handle_start,
    handle_unban_command,
)
from .instagram import InstagramExtractor


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or Settings.from_env()
    db = Database(settings.database_path)
    extractor = InstagramExtractor(settings.download_timeout_seconds)
    downloader = MediaDownloader(
        settings.work_root,
        timeout=settings.download_timeout_seconds,
        concurrency=settings.max_concurrent_downloads,
    )
    application = Application.builder().token(settings.bot_token).concurrent_updates(True).build()
    application.bot_data.update(db=db, extractor=extractor, downloader=downloader, settings=settings)
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("admin", handle_admin_command))
    application.add_handler(CommandHandler("ban", handle_ban_command))
    application.add_handler(CommandHandler("unban", handle_unban_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    async def error_handler(update: object, context: object) -> None:
        logging.getLogger(__name__).exception("uncaught Telegram update error", exc_info=context.error if hasattr(context, "error") else None)

    application.add_error_handler(error_handler)
    return application


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx includes the full Telegram API URL at INFO level; that URL contains
    # the bot token, so transport logs must never be enabled in production.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    application = build_application()
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()