from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

CAPTION = "📥 Downloaded by @inestaMardom_bot"

CB_DOWNLOAD = "menu:download"
CB_HELP = "menu:help"
CB_STATS = "menu:stats"
CB_ADD_GROUP = "menu:add_group"
CB_CHANNEL = "menu:channel"
CB_ABOUT = "menu:about"
CB_BACK = "menu:back"
CB_MEMBERSHIP = "membership:check"
CB_ADMIN = "admin:panel"
CB_ADMIN_USERS = "admin:users"
CB_ADMIN_STATS = "admin:stats"
CB_ADMIN_REQUIRED = "admin:required"
CB_ADMIN_CHANNELS = "admin:channels"
CB_ADMIN_PUBLIC_CHANNEL = "admin:public_channel"
CB_ADMIN_ADD_CHANNEL_ID = "admin:add_channel_id"
CB_ADMIN_ADD_CHANNEL_LINK = "admin:add_channel_link"
CB_ADMIN_ADD_CHANNEL_USERNAME = "admin:add_channel_username"
CB_ADMIN_ADD_CHANNEL = "admin:add_channel"
CB_ADMIN_REMOVE_CHANNEL = "admin:remove_channel"
CB_ADMIN_BROADCAST = "admin:broadcast"
CB_ADMIN_SETTINGS = "admin:settings"
CB_ADMIN_BACK = "admin:back"

START_TEXT = (
    "👋 سلام! خوش اومدی 🌟\n\n"
    "📥 لینک Instagram رو بفرست تا عکس، ویدئو، Reel یا Carousel رو با بهترین کیفیت برات آماده کنم."
)
HELP_TEXT = (
    "📖 راهنما\n\n"
    "لینک عمومی پست، Reel، TV یا Carousel اینستاگرام را همین‌جا بفرست.\n"
    "لینک می‌تواند داخل متن، کپشن یا پیام ریپلای‌شده باشد."
)
ABOUT_TEXT = "ℹ️ درباره ربات\n\nاین ربات رسانه‌های عمومی Instagram را با کیفیت مناسب برایت آماده می‌کند."


def inline_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📥 دانلود Instagram", callback_data=CB_DOWNLOAD)],
            [InlineKeyboardButton("📖 راهنما", callback_data=CB_HELP), InlineKeyboardButton("📊 آمار من", callback_data=CB_STATS)],
            [InlineKeyboardButton("➕ افزودن به گروه", callback_data=CB_ADD_GROUP)],
            [InlineKeyboardButton("📢 کانال ما", callback_data=CB_CHANNEL), InlineKeyboardButton("ℹ️ درباره ربات", callback_data=CB_ABOUT)],
        ]
    )


def reply_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📥 دانلود"), KeyboardButton("📖 راهنما")],
            [KeyboardButton("📊 آمار من"), KeyboardButton("➕ افزودن به گروه")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def back_markup(callback_data: str = CB_BACK) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ برگشت", callback_data=callback_data)]])


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👥 کاربران", callback_data=CB_ADMIN_USERS), InlineKeyboardButton("📊 آمار کلی", callback_data=CB_ADMIN_STATS)],
            [InlineKeyboardButton("🔒 جوین اجباری", callback_data=CB_ADMIN_REQUIRED), InlineKeyboardButton("📢 کانال ما", callback_data=CB_ADMIN_PUBLIC_CHANNEL)],
            [InlineKeyboardButton("📣 ارسال همگانی", callback_data=CB_ADMIN_BROADCAST), InlineKeyboardButton("⚙️ تنظیمات", callback_data=CB_ADMIN_SETTINGS)],
        ]
    )


def required_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🆔 افزودن با Chat ID", callback_data=CB_ADMIN_ADD_CHANNEL_ID),
                InlineKeyboardButton("👤 افزودن با Username", callback_data=CB_ADMIN_ADD_CHANNEL_USERNAME),
            ],
            [InlineKeyboardButton("🔗 افزودن با لینک خصوصی", callback_data=CB_ADMIN_ADD_CHANNEL_LINK)],
            [InlineKeyboardButton("📋 کانال‌های اجباری", callback_data=CB_ADMIN_CHANNELS)],
            [InlineKeyboardButton("🗑️ حذف کانال", callback_data=CB_ADMIN_REMOVE_CHANNEL)],
            [InlineKeyboardButton("⬅️ برگشت", callback_data=CB_ADMIN_BACK)],
        ]
    )