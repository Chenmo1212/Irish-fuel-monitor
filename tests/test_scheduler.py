import pytest
import tempfile
import os
from datetime import datetime, timezone
from unittest.mock import patch
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


def test_run_check_prefers_lowest_current_price_over_score(db):
    user = _make_user()
    stations = [
        {"station_id": "cheap", "name": "Cheap Station", "brand": "A", "address": "", "town": "", "county": "", "latitude": 53.31, "longitude": -6.19},
        {"station_id": "scored", "name": "High Score Station", "brand": "B", "address": "", "town": "", "county": "", "latitude": 53.30, "longitude": -6.20},
    ]
    observations = [
        {"station_id": "cheap", "fuel_type": "E10", "price": 179.9, "observed_at": datetime.now(timezone.utc)},
        {"station_id": "scored", "fuel_type": "E10", "price": 181.9, "observed_at": datetime.now(timezone.utc)},
    ]
    with patch("fuel_monitor.scheduler.collect", return_value=(stations, observations)), patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as send:
        assert run_check_for_user(user, db, "tok", [1, 3, 7], 40.0, 1.0, 24.0, 0.0, False)
    assert "Cheap Station" in send.call_args.args[1]


def test_run_check_uses_distance_as_price_tiebreaker(db):
    user = _make_user()
    stations = [
        {"station_id": "far", "name": "Far Station", "brand": "A", "address": "", "town": "", "county": "", "latitude": 53.40, "longitude": -6.19},
        {"station_id": "near", "name": "Near Station", "brand": "B", "address": "", "town": "", "county": "", "latitude": 53.31, "longitude": -6.20},
    ]
    observations = [
        {"station_id": "far", "fuel_type": "E10", "price": 179.9, "observed_at": datetime.now(timezone.utc)},
        {"station_id": "near", "fuel_type": "E10", "price": 179.9, "observed_at": datetime.now(timezone.utc)},
    ]
    with patch("fuel_monitor.scheduler.collect", return_value=(stations, observations)), patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as send:
        assert run_check_for_user(user, db, "tok", [1, 3, 7], 40.0, 1.0, 24.0, 0.0, False)
    assert "Near Station" in send.call_args.args[1]


def test_run_check_passes_three_alternatives(db):
    user = _make_user()
    stations = [
        {"station_id": "s1", "name": "Cheapest", "brand": "A", "address": "", "town": "", "county": "", "latitude": 53.31, "longitude": -6.19},
        {"station_id": "s2", "name": "Second",   "brand": "B", "address": "", "town": "", "county": "", "latitude": 53.31, "longitude": -6.19},
        {"station_id": "s3", "name": "Third",    "brand": "C", "address": "", "town": "", "county": "", "latitude": 53.31, "longitude": -6.19},
        {"station_id": "s4", "name": "Fourth",   "brand": "D", "address": "", "town": "", "county": "", "latitude": 53.31, "longitude": -6.19},
    ]
    observations = [
        {"station_id": "s1", "fuel_type": "E10", "price": 179.9, "observed_at": datetime.now(timezone.utc)},
        {"station_id": "s2", "fuel_type": "E10", "price": 180.4, "observed_at": datetime.now(timezone.utc)},
        {"station_id": "s3", "fuel_type": "E10", "price": 180.8, "observed_at": datetime.now(timezone.utc)},
        {"station_id": "s4", "fuel_type": "E10", "price": 181.2, "observed_at": datetime.now(timezone.utc)},
    ]

    with (
        patch("fuel_monitor.scheduler.collect", return_value=(stations, observations)),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True),
        patch("fuel_monitor.scheduler.format_message", wraps=__import__("fuel_monitor.notifier", fromlist=["format_message"]).format_message) as mock_fmt,
    ):
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=0.0, bypass_cooldown=True, show_alternatives=True,
        )

    assert sent is True
    alts = mock_fmt.call_args.kwargs["alternatives"]
    assert len(alts) == 3
    assert alts[0]["name"] == "Second"
    assert alts[1]["name"] == "Third"
    assert alts[2]["name"] == "Fourth"


def test_run_check_scheduled_no_alternatives(db):
    """Scheduled calls (show_alternatives=False default) pass alternatives=None to format_message."""
    user = _make_user()
    stations = [
        {"station_id": "s1", "name": "Cheapest", "brand": "A", "address": "", "town": "", "county": "", "latitude": 53.31, "longitude": -6.19},
        {"station_id": "s2", "name": "Second",   "brand": "B", "address": "", "town": "", "county": "", "latitude": 53.31, "longitude": -6.19},
    ]
    observations = [
        {"station_id": "s1", "fuel_type": "E10", "price": 179.9, "observed_at": datetime.now(timezone.utc)},
        {"station_id": "s2", "fuel_type": "E10", "price": 180.4, "observed_at": datetime.now(timezone.utc)},
    ]

    with (
        patch("fuel_monitor.scheduler.collect", return_value=(stations, observations)),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True),
        patch("fuel_monitor.scheduler.format_message", wraps=__import__("fuel_monitor.notifier", fromlist=["format_message"]).format_message) as mock_fmt,
    ):
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=0.0, bypass_cooldown=True,
        )

    assert sent is True
    assert mock_fmt.call_args.kwargs["alternatives"] is None


def test_automatic_alert_sent_for_meaningful_price_increase(db):
    """Scheduled scan notifies when forecast predicts a meaningful price rise (FILL NOW)."""
    user = _make_user()
    # Current price 1.799 EUR/L; forecast 2.850 EUR/L — rise of ~1.05 EUR/L exceeds threshold
    # decide() returns action="FILL NOW" (price expected to rise)
    rising_forecast = [{"horizon_days": 3, "expected": 2.850, "low": 2.83, "high": 2.87}]
    with (
        patch("fuel_monitor.scheduler.collect", side_effect=_fake_collect),
        patch("fuel_monitor.scheduler.forecast", return_value=rising_forecast),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as mock_send,
    ):
        # bypass_cooldown=False → automatic scheduled scan path
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=0.0, bypass_cooldown=False,
        )
    assert sent is True
    assert mock_send.called


def test_automatic_alert_suppressed_for_predicted_price_drop(db):
    """Scheduled scan does NOT notify when forecast predicts a significant price drop (WAIT)."""
    user = _make_user()
    # Current price 1.799 EUR/L; forecast 0.750 EUR/L — drop of ~1.05 EUR/L exceeds threshold
    # decide() returns action="WAIT" — user should wait, no automatic alert needed
    dropping_forecast = [{"horizon_days": 3, "expected": 0.750, "low": 0.73, "high": 0.77}]
    with (
        patch("fuel_monitor.scheduler.collect", side_effect=_fake_collect),
        patch("fuel_monitor.scheduler.forecast", return_value=dropping_forecast),
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


def test_automatic_alert_suppressed_when_score_below_minimum(db):
    """Scheduled scan does NOT notify when station score is below configured min_score."""
    user = _make_user()
    with (
        patch("fuel_monitor.scheduler.collect", side_effect=_fake_collect),
        patch("fuel_monitor.scheduler.analyse", return_value={"score": 30.0, "current_price": 179.9}),
        patch("fuel_monitor.scheduler.send_telegram_to", return_value=True) as mock_send,
    ):
        sent = run_check_for_user(
            user=user, db=db, token="tok",
            horizons=[1, 3, 7], typical_fill=40.0,
            sig_drop_cents=1.0, cooldown_hours=24.0,
            min_score=70.0, bypass_cooldown=False,
        )
    assert sent is False
    assert not mock_send.called
