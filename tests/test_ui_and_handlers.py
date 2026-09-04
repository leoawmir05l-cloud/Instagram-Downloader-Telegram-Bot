from telegram import ReplyParameters

from telegram_bot.handlers import source_reply
from telegram_bot.telegram_ui import (
    CB_ABOUT,
    CB_ADD_GROUP,
    CB_CHANNEL,
    CB_DOWNLOAD,
    CB_HELP,
    CB_STATS,
    CB_ADMIN_ADD_CHANNEL_ID,
    CB_ADMIN_ADD_CHANNEL_LINK,
    CB_ADMIN_ADD_CHANNEL_USERNAME,
    inline_main_menu,
    required_menu,
    reply_menu,
)


class Message:
    message_id = 42


def test_all_start_buttons_are_real_callbacks():
    callback_values = {
        button.callback_data
        for row in inline_main_menu().inline_keyboard
        for button in row
        if button.callback_data
    }
    assert {CB_DOWNLOAD, CB_HELP, CB_STATS, CB_ADD_GROUP, CB_CHANNEL, CB_ABOUT} <= callback_values


def test_reply_keyboard_is_separate_from_inline_keyboard():
    keyboard = reply_menu().keyboard
    assert keyboard[0][0].text == "📥 دانلود"
    assert not hasattr(keyboard[0][0], "callback_data")


def test_media_reply_points_to_exact_source_message():
    params = source_reply(Message())
    assert isinstance(params, ReplyParameters)
    assert params.message_id == 42
    assert params.allow_sending_without_reply is True


def test_required_channel_menu_has_three_dedicated_add_methods():
    callback_values = {
        button.callback_data
        for row in required_menu().inline_keyboard
        for button in row
        if button.callback_data
    }
    assert {CB_ADMIN_ADD_CHANNEL_ID, CB_ADMIN_ADD_CHANNEL_LINK, CB_ADMIN_ADD_CHANNEL_USERNAME} <= callback_values