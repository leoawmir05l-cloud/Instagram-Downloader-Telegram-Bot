from telegram_bot.database import Database


def test_database_persists_stats_channels_and_duplicate_protection(tmp_path):
    path = tmp_path / "bot.sqlite3"
    db = Database(path)
    db.upsert_user(10, 20, "tester", "Test")
    download_id = db.record_download_start(10, "https://www.instagram.com/p/a")
    assert db.claim_update(20, 5, "https://www.instagram.com/p/a")
    assert not db.claim_update(20, 5, "https://www.instagram.com/p/a")
    db.record_download_result(download_id, 10, "carousel", 3, True)
    db.add_required_channel(-1001, "@channel", "Channel", "https://t.me/channel")
    db.close()

    reopened = Database(path)
    stats = reopened.get_user_stats(10)
    assert stats["downloads"] == 1
    assert stats["successful"] == 1
    assert stats["carousel_items"] == 3
    assert reopened.list_required_channels()[0]["title"] == "Channel"
    reopened.close()