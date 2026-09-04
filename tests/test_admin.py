from telegram_bot.database import Database


def test_required_channel_supports_id_username_and_invite_url(tmp_path):
    db = Database(tmp_path / "admin.sqlite3")
    db.add_required_channel(-100, "@public", "Public", "https://t.me/public")
    db.add_required_channel(None, None, "Private", "https://t.me/+private")
    channels = db.list_required_channels()
    assert [channel["chat_id"] for channel in channels] == [-100, None]
    assert db.delete_required_channel(channels[0]["id"])
    assert len(db.list_required_channels()) == 1
    db.close()