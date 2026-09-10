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
