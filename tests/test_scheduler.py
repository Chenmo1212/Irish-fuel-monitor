import pytest
import tempfile
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fuel_monitor.database import Database
from fuel_monitor.scheduler import run_check_for_user


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    d = Database(path)
    d.init_schema()
    d.init_users_schema()
    yield d
    os.unlink(path)


def _make_user(fuel_type="E10", lat=53.3, lng=-6.2):
    return {
        "chat_id": "test-chat",
        "fuel_type": fuel_type,
        "latitude": lat,
        "longitude": lng,
        "radius_km": 20.0,
    }


def _fake_collect(lat, lng, radius_km):
    station = {
        "station_id": "s1",
        "name": "Test Station",
        "brand": "BP",
        "address": "1 Main St",
        "town": "Dublin",
        "county": "Dublin",
        "latitude": lat + 0.01,
        "longitude": lng + 0.01,
    }
    obs = [{"station_id": "s1", "fuel_type": "E10", "price": 1.799, "observed_at": datetime.now(timezone.utc)}]
    return [station], obs


def test_run_check_sends_notification(db):
    user = _make_user()
    with (
        patch("fuel_monitor.scheduler.collect", side_effect=_fake_collect),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as mock_send,
    ):
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=0.0, bypass_cooldown=False,
        )
    assert sent is True
    assert mock_send.called


def test_run_check_skips_wrong_fuel_type(db):
    """User wants diesel but only petrol observations available — no send."""
    user = _make_user(fuel_type="B7")
    with (
        patch("fuel_monitor.scheduler.collect", side_effect=_fake_collect),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as mock_send,
    ):
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=0.0, bypass_cooldown=False,
        )
    assert sent is False
    assert not mock_send.called


def test_run_check_respects_cooldown(db):
    user = _make_user()
    # Log a recent alert for station s1
    db.log_user_alert("test-chat", "s1", 1.799, 60.0, datetime.now(timezone.utc))

    with (
        patch("fuel_monitor.scheduler.collect", side_effect=_fake_collect),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as mock_send,
    ):
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=0.0, bypass_cooldown=False,
        )
    assert sent is False
    assert not mock_send.called


def test_run_check_bypass_cooldown(db):
    user = _make_user()
    db.log_user_alert("test-chat", "s1", 1.799, 60.0, datetime.now(timezone.utc))

    with (
        patch("fuel_monitor.scheduler.collect", side_effect=_fake_collect),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as mock_send,
    ):
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=0.0, bypass_cooldown=True,
        )
    assert sent is True
    assert mock_send.called


def test_run_check_no_stations_returns_false(db):
    user = _make_user()
    with (
        patch("fuel_monitor.scheduler.collect", return_value=([], [])),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as mock_send,
    ):
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=0.0, bypass_cooldown=False,
        )
    assert sent is False
    assert not mock_send.called
