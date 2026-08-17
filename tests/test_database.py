import os
import pytest
from datetime import datetime, timedelta, timezone
from fuel_monitor.database import Database

@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    d.init_schema()
    return d

def test_init_schema_creates_tables(db):
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "stations" in tables
    assert "price_history" in tables
    assert "alert_log" in tables

def test_upsert_station(db):
    db.upsert_station({
        "station_id": "ie-001",
        "name": "Circle K Dublin",
        "brand": "Circle K",
        "address": "O'Connell St",
        "town": "Dublin",
        "county": "Dublin",
        "latitude": 53.35,
        "longitude": -6.26,
    })
    history = db.get_price_history("ie-001", "E10", datetime(2000, 1, 1, tzinfo=timezone.utc))
    # No prices yet but station exists — no error
    assert history == []

def test_save_observation_new(db):
    db.upsert_station({"station_id": "ie-001", "name": "Test", "brand": None,
                       "address": "", "town": "", "county": "",
                       "latitude": 53.0, "longitude": -6.0})
    now = datetime.now(timezone.utc)
    saved = db.save_observation("ie-001", "E10", 1.799, now)
    assert saved is True

def test_save_observation_dedup_same_price_within_60min(db):
    db.upsert_station({"station_id": "ie-001", "name": "Test", "brand": None,
                       "address": "", "town": "", "county": "",
                       "latitude": 53.0, "longitude": -6.0})
    now = datetime.now(timezone.utc)
    db.save_observation("ie-001", "E10", 1.799, now)
    saved_again = db.save_observation("ie-001", "E10", 1.799, now + timedelta(minutes=30))
    assert saved_again is False

def test_save_observation_different_price_always_saved(db):
    db.upsert_station({"station_id": "ie-001", "name": "Test", "brand": None,
                       "address": "", "town": "", "county": "",
                       "latitude": 53.0, "longitude": -6.0})
    now = datetime.now(timezone.utc)
    db.save_observation("ie-001", "E10", 1.799, now)
    saved = db.save_observation("ie-001", "E10", 1.789, now + timedelta(minutes=30))
    assert saved is True

def test_get_price_history_filters_by_since(db):
    db.upsert_station({"station_id": "ie-001", "name": "Test", "brand": None,
                       "address": "", "town": "", "county": "",
                       "latitude": 53.0, "longitude": -6.0})
    old = datetime.now(timezone.utc) - timedelta(days=40)
    recent = datetime.now(timezone.utc) - timedelta(days=5)
    db.save_observation("ie-001", "E10", 1.800, old)
    db.save_observation("ie-001", "E10", 1.750, recent)
    since = datetime.now(timezone.utc) - timedelta(days=30)
    rows = db.get_price_history("ie-001", "E10", since)
    assert len(rows) == 1
    assert abs(rows[0]["price"] - 1.750) < 0.001

def test_log_alert_and_get_last_alert(db):
    now = datetime.now(timezone.utc)
    db.log_alert("ie-001", 1.799, 92.0, now)
    last = db.get_last_alert("ie-001")
    assert last is not None
    assert abs(last["price"] - 1.799) < 0.001
    assert abs(last["score"] - 92.0) < 0.01
