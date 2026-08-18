import pytest
import tempfile
import os
from datetime import datetime, timezone
from fuel_monitor.database import Database


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    d = Database(path)
    d.init_schema()
    d.init_users_schema()
    yield d
    os.unlink(path)


def test_upsert_and_get_user(db):
    db.upsert_user("111", "E10", 53.3, -6.2)
    user = db.get_user("111")
    assert user is not None
    assert user["chat_id"] == "111"
    assert user["fuel_type"] == "E10"
    assert user["latitude"] == pytest.approx(53.3)
    assert user["longitude"] == pytest.approx(-6.2)
    assert user["radius_km"] == pytest.approx(20.0)


def test_upsert_updates_existing(db):
    db.upsert_user("111", "E10", 53.3, -6.2)
    db.upsert_user("111", "B7", 53.4, -6.3)
    user = db.get_user("111")
    assert user["fuel_type"] == "B7"
    assert user["latitude"] == pytest.approx(53.4)


def test_get_nonexistent_user_returns_none(db):
    assert db.get_user("nonexistent") is None


def test_get_all_users(db):
    db.upsert_user("111", "E10", 53.3, -6.2)
    db.upsert_user("222", "B7", 53.0, -6.0)
    users = db.get_all_users()
    assert len(users) == 2
    chat_ids = {u["chat_id"] for u in users}
    assert chat_ids == {"111", "222"}


def test_delete_user(db):
    db.upsert_user("111", "E10", 53.3, -6.2)
    db.delete_user("111")
    assert db.get_user("111") is None


def test_touch_user_updates_last_seen(db):
    db.upsert_user("111", "E10", 53.3, -6.2)
    original = db.get_user("111")["last_seen_at"]
    import time; time.sleep(0.01)
    db.touch_user("111")
    updated = db.get_user("111")["last_seen_at"]
    assert updated > original


def test_log_and_get_user_alert(db):
    db.upsert_user("111", "E10", 53.3, -6.2)
    now = datetime.now(timezone.utc)
    db.log_user_alert("111", "station-abc", 1.799, 72.5, now)
    alert = db.get_last_user_alert("111", "station-abc")
    assert alert is not None
    assert alert["price"] == pytest.approx(1.799)
    assert alert["score"] == pytest.approx(72.5)


def test_get_last_user_alert_none_when_missing(db):
    db.upsert_user("111", "E10", 53.3, -6.2)
    assert db.get_last_user_alert("111", "no-such-station") is None
