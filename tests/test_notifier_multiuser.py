from unittest.mock import patch, MagicMock
from fuel_monitor.notifier import send_telegram_to, _send_telegram


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


def test_send_telegram_backward_compat_uses_env(monkeypatch):
    """_send_telegram with no explicit params still reads from env vars."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_ok()) as mock_post:
        result = _send_telegram("T", "B")
    assert result is True
    url = mock_post.call_args[0][0]
    assert "env-token" in url
