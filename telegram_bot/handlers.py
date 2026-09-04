from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    ReplyParameters,
    Update,
)
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from .config import Settings
from .database import Database
from .downloader import DownloadError, MediaDownloader
from .instagram import InstagramExtractor
from .models import DownloadBundle, MediaType
from .telegram_ui import (
    ABOUT_TEXT,
    CAPTION,
    CB_ABOUT,
    CB_ADD_GROUP,
    CB_ADMIN,
    CB_ADMIN_ADD_CHANNEL,
    CB_ADMIN_ADD_CHANNEL_ID,
    CB_ADMIN_ADD_CHANNEL_LINK,
    CB_ADMIN_ADD_CHANNEL_USERNAME,
    CB_ADMIN_BACK,
    CB_ADMIN_BROADCAST,
    CB_ADMIN_CHANNELS,
    CB_ADMIN_REMOVE_CHANNEL,
    CB_ADMIN_REQUIRED,
    CB_ADMIN_SETTINGS,
    CB_ADMIN_STATS,
    CB_ADMIN_USERS,
    CB_ADMIN_PUBLIC_CHANNEL,
    CB_BACK,
    CB_CHANNEL,
    CB_DOWNLOAD,
    CB_HELP,
    CB_MEMBERSHIP,
    CB_STATS,
    HELP_TEXT,
    START_TEXT,
    admin_menu,
    back_markup,
    inline_main_menu,
    reply_menu,
    required_menu,
)
from .url_utils import extract_url_from_message

logger = logging.getLogger(__name__)


def services(context: ContextTypes.DEFAULT_TYPE) -> tuple[Database, InstagramExtractor, MediaDownloader, Settings]:
    data = context.application.bot_data
    return data["db"], data["extractor"], data["downloader"], data["settings"]


def source_reply(message: Any) -> ReplyParameters:
    return ReplyParameters(message_id=message.message_id, allow_sending_without_reply=True)


def register_user(db: Database, update: Update) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if user and chat:
        db.upsert_user(user.id, chat.id, user.username, user.first_name)


def is_admin(update: Update, settings: Settings) -> bool:
    return bool(update.effective_user and update.effective_user.id == settings.admin_id)


async def missing_required_channels(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> list[dict[str, Any]]:
    db, _, _, _ = services(context)
    user = update.effective_user
    if not user:
        return []
    missing: list[dict[str, Any]] = []
    for channel in db.list_required_channels():
        if not channel["chat_id"]:
            # Telegram Bot API cannot resolve a private invite link to a chat ID.
            # It is still shown, but it cannot be falsely reported as verified.
            continue
        try:
            member = await context.bot.get_chat_member(channel["chat_id"], user.id)
            if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
                missing.append(channel)
        except TelegramError:
            logger.exception("membership check failed for required channel %s", channel["id"])
            missing.append(channel)
    return missing


def required_channels_markup(channels: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"📢 عضویت در {channel['title']}", url=channel["join_url"])]
        for channel in channels
    ]
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data=CB_MEMBERSHIP)])
    return InlineKeyboardMarkup(rows)


async def send_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    db, _, _, settings = services(context)
    register_user(db, update)
    if db.is_banned(update.effective_user.id if update.effective_user else 0):
        await message.reply_text("⛔ دسترسی شما به ربات مسدود شده است.")
        return
    missing = await missing_required_channels(update, context)
    if missing:
        await message.reply_text(
            "🔒 برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:",
            reply_markup=required_channels_markup(missing),
            reply_parameters=source_reply(message),
        )
        return
    markup = reply_menu() if update.effective_chat and update.effective_chat.type == "private" else None
    await message.reply_text(
        START_TEXT,
        reply_markup=markup,
        reply_parameters=source_reply(message),
    )
    await message.reply_text(
        "از گزینه‌های زیر انتخاب کن:",
        reply_markup=inline_main_menu(),
        reply_parameters=source_reply(message),
    )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_start(update, context)


def stats_text(stats: dict[str, Any]) -> str:
    return (
        "📊 آمار من\n\n"
        f"📥 کل دانلودها: {stats['downloads']}\n"
        f"✅ موفق: {stats['successful']}\n"
        f"❌ ناموفق: {stats['failed']}\n\n"
        f"🖼️ عکس‌ها: {stats['photos']}\n"
        f"🎬 ویدئوها: {stats['videos']}\n"
        f"🎞️ ریلزها: {stats['reels']}\n"
        f"🖼️🎬 آیتم‌های Carousel: {stats['carousel_items']}"
    )


async def show_personal_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _, _, _ = services(context)
    user_id = update.effective_user.id
    text = stats_text(db.get_user_stats(user_id))
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=back_markup())
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=back_markup(), reply_parameters=source_reply(update.effective_message))


async def check_user_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    db, _, _, _ = services(context)
    user_id = update.effective_user.id if update.effective_user else 0
    if db.is_banned(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ دسترسی شما به ربات مسدود شده است.")
        return False
    missing = await missing_required_channels(update, context)
    if missing:
        message = update.effective_message
        if message:
            await message.reply_text(
                "🔒 ابتدا در کانال‌های اجباری عضو شوید.",
                reply_markup=required_channels_markup(missing),
                reply_parameters=source_reply(message),
            )
        return False
    return True


async def _thumbnail(video: Path, directory: Path) -> Path | None:
    from .downloader import probe_video

    try:
        metadata = probe_video(video)
        duration = float((metadata.get("format") or {}).get("duration") or 0)
    except (DownloadError, ValueError, TypeError):
        duration = 0
    sample_times = [max(duration * ratio, 0.05) for ratio in (0.1, 0.5, 0.9)] if duration else [1.0]
    for attempt, timestamp in enumerate(sample_times):
        destination = directory / f"{video.stem}_{attempt}.jpg"
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(destination),
        ]
        result = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
            return destination
    return None


async def send_bundle(message: Any, bundle: DownloadBundle, downloader: MediaDownloader, settings: Settings) -> None:
    for item in sorted(bundle.items, key=lambda media: media.index):
        reply = source_reply(message)
        if item.media_type == MediaType.PHOTO:
            try:
                with item.path.open("rb") as photo:
                    await message.reply_photo(photo=InputFile(photo, filename=item.path.name), caption=CAPTION, reply_parameters=reply)
            except (BadRequest, TelegramError):
                with tempfile.TemporaryDirectory(dir=bundle.job_directory) as temp_dir:
                    compatible = downloader.make_telegram_photo_copy(item.path, Path(temp_dir))
                    with compatible.open("rb") as photo:
                        await message.reply_photo(photo=InputFile(photo, filename=compatible.name), caption=CAPTION, reply_parameters=reply)
            with item.path.open("rb") as document:
                await message.reply_document(document=InputFile(document, filename=item.path.name), caption=CAPTION, reply_parameters=reply)
        else:
            from .downloader import probe_video

            metadata = probe_video(item.path)
            video_stream = next(stream for stream in metadata["streams"] if stream.get("codec_type") == "video")
            duration = float((metadata.get("format") or {}).get("duration") or 0)
            thumbnail = await _thumbnail(item.path, bundle.job_directory)
            with item.path.open("rb") as video:
                video_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{settings.bot_username}?startgroup=true")]]
                )
                if thumbnail:
                    with thumbnail.open("rb") as thumb:
                        await message.reply_video(
                            video=InputFile(video, filename=item.path.name),
                            thumbnail=InputFile(thumb, filename=thumbnail.name),
                            caption=CAPTION,
                            supports_streaming=True,
                            width=int(video_stream.get("width") or 0) or None,
                            height=int(video_stream.get("height") or 0) or None,
                            duration=max(1, round(duration)) if duration else None,
                            reply_markup=video_markup,
                            reply_parameters=reply,
                        )
                else:
                    await message.reply_video(
                        video=InputFile(video, filename=item.path.name),
                        caption=CAPTION,
                        supports_streaming=True,
                        width=int(video_stream.get("width") or 0) or None,
                        height=int(video_stream.get("height") or 0) or None,
                        duration=max(1, round(duration)) if duration else None,
                        reply_markup=video_markup,
                        reply_parameters=reply,
                    )


async def process_download(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    message = update.effective_message
    if not message or not await check_user_access(update, context):
        return
    db, extractor, downloader, settings = services(context)
    user_id = update.effective_user.id
    download_id = db.record_download_start(user_id, url)
    status = await message.reply_text(
        "📥 لینک دریافت شد!\n⏳ در حال آماده‌سازی محتوا…",
        reply_parameters=source_reply(message),
    )
    bundle: DownloadBundle | None = None
    try:
        await status.edit_text("🔎 در حال بررسی محتوا…")
        extracted = await extractor.extract(url)
        await status.edit_text("⏳ در حال دانلود…")
        bundle = await downloader.download(url, extracted)
        await status.edit_text("📤 در حال ارسال…")
        await send_bundle(message, bundle, downloader, settings)
        db.record_download_result(
            download_id,
            user_id,
            extracted.media_type.value,
            len(bundle.items),
            True,
            is_reel=extracted.is_reel,
            item_types=[item.media_type.value for item in bundle.items],
        )
        await status.delete()
    except asyncio.TimeoutError:
        logger.exception("download timed out for %s", url)
        db.record_download_result(download_id, user_id, None, 0, False, "timeout")
        await status.edit_text("⌛ آماده‌سازی محتوا بیش از حد طول کشید. دوباره تلاش کن.")
    except DownloadError as exc:
        logger.exception("download failed (%s) for %s", exc.code, url)
        db.record_download_result(download_id, user_id, None, 0, False, exc.code)
        await status.edit_text("⚠️ دانلود این محتوا انجام نشد. لینک عمومی و سالمی را امتحان کن.")
    except TelegramError:
        logger.exception("Telegram upload failed for %s", url)
        db.record_download_result(download_id, user_id, None, 0, False, "telegram_upload_error")
        await status.edit_text("⚠️ ارسال فایل به تلگرام ناموفق بود.")
    except Exception:
        logger.exception("unexpected download error for %s", url)
        db.record_download_result(download_id, user_id, None, 0, False, "unexpected_error")
        await status.edit_text("⚠️ خطای غیرمنتظره‌ای رخ داد. دوباره تلاش کن.")
    finally:
        if bundle:
            downloader.cleanup(bundle)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not update.effective_user:
        return
    db, _, _, settings = services(context)
    register_user(db, update)
    if db.is_banned(update.effective_user.id):
        await message.reply_text("⛔ دسترسی شما به ربات مسدود شده است.")
        return

    state = context.user_data.get("admin_state")
    if is_admin(update, settings) and state:
        if state == "add_channel":
            await complete_add_channel(update, context)
            return
        if state == "broadcast":
            await complete_broadcast(update, context)
            return

    text = message.text or ""
    if text in {"📥 دانلود", "📥 دانلود Instagram"}:
        await message.reply_text("لینک Instagram را بفرست.", reply_parameters=source_reply(message))
        return
    if text == "📖 راهنما":
        await message.reply_text(HELP_TEXT, reply_markup=back_markup(), reply_parameters=source_reply(message))
        return
    if text == "📊 آمار من":
        await show_personal_stats(update, context)
        return
    if text == "➕ افزودن به گروه":
        await message.reply_text(
            f"https://t.me/{settings.bot_username}?startgroup=true",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ افزودن ربات", url=f"https://t.me/{settings.bot_username}?startgroup=true")]]),
            reply_parameters=source_reply(message),
        )
        return

    url = extract_url_from_message(message)
    if not url:
        return
    if not db.claim_update(message.chat_id, message.message_id, url):
        logger.info("duplicate update ignored chat=%s message=%s", message.chat_id, message.message_id)
        return
    await process_download(update, context, url)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    db, _, _, settings = services(context)
    data = query.data or ""
    if data.startswith("admin:") and not is_admin(update, settings):
        await query.edit_message_text("⛔ این بخش فقط برای مدیر ربات است.", reply_markup=back_markup())
        return

    if data == CB_BACK:
        await query.edit_message_text(START_TEXT, reply_markup=inline_main_menu())
    elif data == CB_DOWNLOAD:
        await query.edit_message_text("📥 لینک عمومی Instagram را بفرست.", reply_markup=back_markup())
    elif data == CB_HELP:
        await query.edit_message_text(HELP_TEXT, reply_markup=back_markup())
    elif data == CB_STATS:
        await query.edit_message_text(stats_text(db.get_user_stats(update.effective_user.id)), reply_markup=back_markup())
    elif data == CB_ADD_GROUP:
        await query.edit_message_text(
            "برای افزودن ربات به گروه روی دکمه زیر بزن.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{settings.bot_username}?startgroup=true")], [InlineKeyboardButton("⬅️ برگشت", callback_data=CB_BACK)]]
            ),
        )
    elif data == CB_CHANNEL:
        if settings.channel_url:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("📢 ورود به کانال", url=settings.channel_url)], [InlineKeyboardButton("⬅️ برگشت", callback_data=CB_BACK)]])
        else:
            markup = back_markup()
        await query.edit_message_text("📢 کانال ما هنوز تنظیم نشده است." if not settings.channel_url else "📢 کانال ما:", reply_markup=markup)
    elif data == CB_ABOUT:
        await query.edit_message_text(ABOUT_TEXT, reply_markup=back_markup())
    elif data == CB_MEMBERSHIP:
        missing = await missing_required_channels(update, context)
        if missing:
            await query.edit_message_text("🔒 هنوز عضویت کامل نشده است.", reply_markup=required_channels_markup(missing))
        else:
            await query.edit_message_text(START_TEXT, reply_markup=inline_main_menu())
    elif data == CB_ADMIN:
        await show_admin_panel(query)
    elif data == CB_ADMIN_BACK:
        await show_admin_panel(query)
    elif data == CB_ADMIN_USERS:
        users = db.list_users()
        lines = ["👥 کاربران", ""]
        for user in users[:30]:
            label = f"@{user['username']}" if user["username"] else str(user["user_id"])
            lines.append(f"{label} — دانلود: {user['downloads']}")
        await query.edit_message_text("\n".join(lines), reply_markup=back_markup(CB_ADMIN_BACK))
    elif data == CB_ADMIN_STATS:
        stats = db.global_stats()
        await query.edit_message_text(
            "📊 آمار کلی\n\n"
            f"کاربران: {stats['users']}\nدانلودها: {stats['downloads']}\nموفق: {stats['successful']}\n"
            f"ناموفق: {stats['failed']}\nعکس: {stats['photos']}\nویدئو: {stats['videos']}\n"
            f"Reel: {stats['reels']}\nآیتم Carousel: {stats['carousel_items']}",
            reply_markup=back_markup(CB_ADMIN_BACK),
        )
    elif data == CB_ADMIN_REQUIRED:
        await query.edit_message_text("🔒 مدیریت جوین اجباری", reply_markup=required_menu())
    elif data == CB_ADMIN_CHANNELS:
        channels = db.list_required_channels()
        text = "📋 کانال‌های اجباری\n\n" + ("\n".join(f"{c['id']}. {c['title']} — {c['join_url']}" for c in channels) or "کانالی ثبت نشده است.")
        await query.edit_message_text(text, reply_markup=required_menu())
    elif data == CB_ADMIN_PUBLIC_CHANNEL:
        channel_text = settings.channel_url or "تنظیم نشده است"
        await query.edit_message_text(
            f"📢 کانال ما\n\nآدرس فعلی: {channel_text}\n\nبرای تغییر این مقدار، CHANNEL_URL را در تنظیمات محیطی به‌روزرسانی کنید.",
            reply_markup=back_markup(CB_ADMIN_BACK),
        )
    elif data == CB_ADMIN_ADD_CHANNEL:
        context.user_data["admin_state"] = "add_channel"
        await query.edit_message_text("یکی از روش‌های افزودن کانال را انتخاب کن.", reply_markup=required_menu())
    elif data in {CB_ADMIN_ADD_CHANNEL_ID, CB_ADMIN_ADD_CHANNEL_LINK, CB_ADMIN_ADD_CHANNEL_USERNAME}:
        state_by_callback = {
            CB_ADMIN_ADD_CHANNEL_ID: ("add_channel_id", "شناسه عددی کانال را ارسال کن، مانند -1001234567890."),
            CB_ADMIN_ADD_CHANNEL_LINK: ("add_channel_link", "لینک دعوت خصوصی کانال را ارسال کن، مانند https://t.me/+xxxxxxxx."),
            CB_ADMIN_ADD_CHANNEL_USERNAME: ("add_channel_username", "یوزرنیم عمومی کانال را ارسال کن، مانند @channelname."),
        }
        state, prompt = state_by_callback[data]
        context.user_data["admin_state"] = state
        await query.edit_message_text(prompt, reply_markup=back_markup(CB_ADMIN_BACK))
    elif data == CB_ADMIN_REMOVE_CHANNEL:
        channels = db.list_required_channels()
        buttons = [[InlineKeyboardButton(f"🗑️ {c['title']}", callback_data=f"admin:remove:{c['id']}")] for c in channels]
        buttons.append([InlineKeyboardButton("⬅️ برگشت", callback_data=CB_ADMIN_REQUIRED)])
        await query.edit_message_text("کانال موردنظر برای حذف را انتخاب کن.", reply_markup=InlineKeyboardMarkup(buttons))
    elif data.startswith("admin:remove:"):
        channel_id = int(data.rsplit(":", 1)[1])
        db.delete_required_channel(channel_id)
        await query.edit_message_text("کانال حذف شد.", reply_markup=required_menu())
    elif data == CB_ADMIN_BROADCAST:
        context.user_data["admin_state"] = "broadcast"
        await query.edit_message_text("پیام همگانی را ارسال کن. برای لغو /cancel را بفرست.", reply_markup=back_markup(CB_ADMIN_BACK))
    elif data == CB_ADMIN_SETTINGS:
        await query.edit_message_text("⚙️ تنظیمات\n\nتنظیمات حساس از متغیرهای محیطی خوانده می‌شوند.\nمدیریت کانال عمومی از بخش «کانال ما» انجام می‌شود.", reply_markup=back_markup(CB_ADMIN_BACK))
    else:
        logger.warning("unhandled callback_data=%s", data)


async def show_admin_panel(query: Any) -> None:
    await query.edit_message_text(
        "👑 پنل مدیریت ربات\n\nبه بخش مدیریت خوش آمدید.\nاز گزینه‌های زیر می‌توانید کاربران، آمار، کانال‌های اجباری و تنظیمات ربات را مدیریت کنید.",
        reply_markup=admin_menu(),
    )


async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, settings = services(context)
    if not is_admin(update, settings):
        await update.effective_message.reply_text("⛔ دسترسی ندارید.")
        return
    await update.effective_message.reply_text(
        "👑 پنل مدیریت ربات\n\nبه بخش مدیریت خوش آمدید.\nاز گزینه‌های زیر می‌توانید کاربران، آمار، کانال‌های اجباری و تنظیمات ربات را مدیریت کنید.",
        reply_markup=admin_menu(),
        reply_parameters=source_reply(update.effective_message),
    )


async def handle_ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, settings = services(context)
    if not is_admin(update, settings):
        await update.effective_message.reply_text("⛔ دسترسی ندارید.")
        return
    await set_ban(update, context, True)


async def handle_unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, _, _, settings = services(context)
    if not is_admin(update, settings):
        await update.effective_message.reply_text("⛔ دسترسی ندارید.")
        return
    await set_ban(update, context, False)


async def set_ban(update: Update, context: ContextTypes.DEFAULT_TYPE, banned: bool) -> None:
    db, _, _, _ = services(context)
    args = context.args or []
    try:
        user_id = int(args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_text("فرمت صحیح: /ban USER_ID یا /unban USER_ID")
        return
    db.set_banned(user_id, banned)
    await update.effective_message.reply_text("✅ انجام شد." if banned else "✅ مسدودی برداشته شد.")


async def complete_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _, _, _ = services(context)
    message = update.effective_message
    raw = (message.text or "").strip()
    state = context.user_data.get("admin_state")
    if raw == "/cancel":
        context.user_data.pop("admin_state", None)
        await message.reply_text("لغو شد.")
        return
    context.user_data.pop("admin_state", None)
    if state == "add_channel_link" and raw.startswith(("https://t.me/+", "https://t.me/joinchat/")):
        db.add_required_channel(None, None, "کانال خصوصی", raw)
        await message.reply_text("✅ لینک دعوت خصوصی ذخیره شد.")
        return
    if state == "add_channel_link":
        await message.reply_text("⚠️ لینک خصوصی معتبر نیست. عملیات لغو شد.")
        return
    if state == "add_channel_id" and not re.fullmatch(r"-?\d+", raw):
        await message.reply_text("⚠️ Chat ID باید عددی باشد. عملیات لغو شد.")
        return
    if state == "add_channel_username" and not re.fullmatch(r"@?[A-Za-z0-9_]{5,}", raw):
        await message.reply_text("⚠️ Username عمومی معتبر نیست. عملیات لغو شد.")
        return
    try:
        chat = await context.bot.get_chat(int(raw) if re.fullmatch(r"-?\d+", raw) else raw.lstrip("@"))
    except TelegramError:
        await message.reply_text("⚠️ کانال پیدا نشد یا ربات به آن دسترسی ندارد.")
        return
    username = f"@{chat.username}" if chat.username else None
    join_url = f"https://t.me/{chat.username}" if chat.username else raw
    db.add_required_channel(chat.id, username, chat.title or username or raw, join_url)
    await message.reply_text("✅ کانال ذخیره شد.")


async def complete_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _, _, _ = services(context)
    message = update.effective_message
    if (message.text or "").strip() == "/cancel":
        context.user_data.pop("admin_state", None)
        await message.reply_text("لغو شد.")
        return
    context.user_data.pop("admin_state", None)
    sent = failed = 0
    for user_id in db.all_user_ids():
        try:
            await message.copy(chat_id=user_id)
            sent += 1
            await asyncio.sleep(0.05)
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after))
            try:
                await message.copy(chat_id=user_id)
                sent += 1
            except TelegramError:
                failed += 1
        except (Forbidden, TelegramError):
            failed += 1
    await message.reply_text(f"📣 ارسال همگانی تمام شد.\nارسال موفق: {sent}\nناموفق: {failed}")