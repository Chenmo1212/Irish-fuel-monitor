from unittest.mock import patch, MagicMock
from fuel_monitor.notifier import send_telegram_to, format_message


def _mock_ok():
    r = MagicMock()
    r.ok = True
    return r


def _mock_fail():
    r = MagicMock()
    r.ok = False
    r.status_code = 400
    r.text = "bad request"
    return r


def test_send_telegram_to_success():
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_ok()) as mock_post:
        result = send_telegram_to(
            chat_id="12345",
            title="Test",
            body="Hello",
            maps_url=None,
            token="fake-token",
        )
    assert result is True
    call_kwargs = mock_post.call_args
    assert "botfake-token" in call_kwargs[0][0]
    payload = call_kwargs[1]["json"]
    assert payload["chat_id"] == "12345"


def test_send_telegram_to_failure():
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_fail()):
        result = send_telegram_to(
            chat_id="12345",
            title="Test",
            body="Hello",
            maps_url=None,
            token="fake-token",
        )
    assert result is False


def test_send_telegram_to_with_maps_url():
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_ok()) as mock_post:
        send_telegram_to(
            chat_id="12345",
            title="Test",
            body="Hello",
            maps_url="https://maps.google.com/?q=1,2",
            token="fake-token",
        )
    payload = mock_post.call_args[1]["json"]
    assert "reply_markup" in payload


def test_send_telegram_to_includes_quick_action_buttons():
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_ok()) as mock_post:
        send_telegram_to("12345", "Test", "Hello", "https://maps.google.com/?q=1,2", "fake-token")
    rows = mock_post.call_args[1]["json"]["reply_markup"]["inline_keyboard"]
    assert rows[0] == [{"text": "📍 Navigate", "url": "https://maps.google.com/?q=1,2"}]
    assert [b["callback_data"] for b in rows[1]] == ["act:check", "act:check_now", "act:fuel"]


def test_send_telegram_to_quick_actions_without_maps_url():
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_ok()) as mock_post:
        send_telegram_to("12345", "Test", "Hello", None, "fake-token")
    rows = mock_post.call_args[1]["json"]["reply_markup"]["inline_keyboard"]
    assert len(rows) == 1
    assert all("callback_data" in b for b in rows[0])


def test_format_message_includes_at_most_three_other_options():
    title, body, maps_url = format_message(
        station={"name": "Best", "distance_km": 1.0, "current_price": 179.9, "latitude": 53.3, "longitude": -6.2},
        analysis={"current_price": 179.9, "score": None},
        forecasts=None,
        recommendation={"action": "FILL NOW", "reason": "Lowest current price"},
        typical_fill_litres=40.0,
        alternatives=[
            {"name": "Other 1", "distance_km": 2.0, "current_price": 180.4},
            {"name": "Other 2", "distance_km": 3.0, "current_price": 180.8},
            {"name": "Other 3", "distance_km": 4.0, "current_price": 181.0},
            {"name": "Other 4", "distance_km": 5.0, "current_price": 181.2},
        ],
    )
    assert "Other options" in body
    assert "Other 1" in body and "180.4" in body and "2.0 km" in body
    assert "Other 2" in body and "Other 3" in body
    assert "Other 4" not in body


def test_format_message_no_other_options_when_alternatives_empty():
    title, body, maps_url = format_message(
        station={"name": "Best", "distance_km": 1.0, "current_price": 179.9, "latitude": 53.3, "longitude": -6.2},
        analysis={"current_price": 179.9, "score": None},
        forecasts=None,
        recommendation={"action": "FILL NOW", "reason": "Lowest current price"},
        typical_fill_litres=40.0,
        alternatives=[],
    )
    assert "Other options" not in body


def test_format_message_no_other_options_when_alternatives_none():
    title, body, maps_url = format_message(
        station={"name": "Best", "distance_km": 1.0, "current_price": 179.9, "latitude": 53.3, "longitude": -6.2},
        analysis={"current_price": 179.9, "score": None},
        forecasts=None,
        recommendation={"action": "FILL NOW", "reason": "Lowest current price"},
        typical_fill_litres=40.0,
    )
    assert "Other options" not in body


def test_format_message_no_saving_section_for_negative_total_saving():
    """Forecast-rise FILL NOW: predicted_total_saving is negative — section must not appear."""
    title, body, maps_url = format_message(
        station={"name": "Best", "distance_km": 1.0, "current_price": 180.0, "latitude": 53.3, "longitude": -6.2},
        analysis={"current_price": 180.0, "score": None},
        forecasts=[{"horizon_days": 3, "expected": 183.0, "low": 181.0, "high": 185.0}],
        recommendation={
            "action": "FILL NOW",
            "reason": "Price expected to rise by 3.0c/L in ~3 days — fill now to avoid ~€1.20 increase on 40L",
            "predicted_saving_per_litre": -3.0,
            "predicted_total_saving": -1.20,
            "forecast_used": {"horizon_days": 3, "expected": 183.0},
        },
        typical_fill_litres=40.0,
    )
    assert "Potential saving" not in body
    assert "FILL NOW" in body
