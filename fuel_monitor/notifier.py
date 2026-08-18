import logging
import os

import requests

logger = logging.getLogger(__name__)


def _build_telegram_payload(chat_id: str, title: str, body: str, maps_url: str | None) -> dict:
    text = f"*{title}*\n\n{body}"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if maps_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "📍 Navigate", "url": maps_url}]]
        }
    return payload


def send_telegram_to(
    chat_id: str,
    title: str,
    body: str,
    maps_url: str | None,
    token: str,
) -> bool:
    """
    Send a Telegram message to an explicit chat_id using an explicit token.
    Returns True on success, False on any failure. Never raises.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = _build_telegram_payload(chat_id, title, body, maps_url)
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            logger.info("Telegram notification sent to chat_id=%s: %s", chat_id, title)
            return True
        logger.error("Telegram API HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    except requests.RequestException as exc:
        logger.error("Telegram request failed: %s", exc)
        return False


def _send_telegram(title: str, body: str, maps_url: str | None = None) -> bool:
    """
    Send via env vars TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.
    Backward-compat wrapper used by main.py.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set — cannot send Telegram notification.")
        return False
    if not chat_id:
        logger.error("TELEGRAM_CHAT_ID not set — cannot send Telegram notification.")
        return False
    return send_telegram_to(chat_id, title, body, maps_url, token)


def send_notification(
    title: str,
    body: str,
    priority: str,
    source: str,
    enabled: bool,
    maps_url: str | None = None,
) -> bool:
    """
    Send a notification via the configured channel.
    Set notification.source to "telegram" in config.yaml to use Telegram.
    Returns True on success, False on any failure. Never raises.
    """
    if not enabled:
        logger.info("Notifications disabled — skipping send.")
        return False

    if source == "telegram":
        return _send_telegram(title, body, maps_url)

    api_url = os.environ.get("NOTIFICATION_API_URL", "").strip()
    if not api_url:
        logger.error("NOTIFICATION_API_URL not set — cannot send notification.")
        return False

    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("NOTIFICATION_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "type": "notification",
        "source": source,
        "metadata": {
            "title": title,
            "content": body,
            "priority": priority,
        },
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
        if resp.ok:
            logger.info("Notification sent: %s", title)
            return True
        else:
            logger.error("Notification API returned HTTP %s: %s", resp.status_code, resp.text[:200])
            return False
    except requests.RequestException as exc:
        logger.error("Notification request failed: %s", exc)
        return False


def format_message(
    station: dict,
    analysis: dict,
    forecasts: list[dict] | None,
    recommendation: dict,
    typical_fill_litres: float,
) -> tuple[str, str, str | None]:
    """
    Format a Telegram-style notification message.
    Returns (title, body, maps_url).
    maps_url is the Google Maps link for the station, or None if unavailable.
    """
    name = station.get("name", "Unknown station")
    dist = station.get("distance_km")
    dist_str = f"{dist:.1f} km" if dist is not None else "unknown distance"

    price = analysis.get("current_price")
    if price is None:
        price = station.get("current_price", 0)
    score = analysis.get("score")
    score_label = analysis.get("score_label", "")
    pct = analysis.get("percentile_30d")
    avg_7d = analysis.get("avg_7d")
    avg_30d = analysis.get("avg_30d")
    low_30d = analysis.get("low_30d")

    action = recommendation.get("action", "FILL NOW")
    reason = recommendation.get("reason", "")
    total_saving = recommendation.get("predicted_total_saving")

    emoji = "🟢" if action == "FILL NOW" else "🟡"
    title = f"⛽ Fuel Alert — {name}"

    lat = station.get("latitude")
    lng = station.get("longitude")
    maps_link = f"https://www.google.com/maps?q={lat},{lng}" if lat is not None and lng is not None else None

    lines = ["⛽ Fuel Alert", ""]
    lines += ["Best station nearby:", f"{name} ({dist_str})", ""]
    lines += [f"Current price:   €{price:.3f}/L"]
    if score is not None:
        lines += [f"Fuel Score:      {score:.0f}/100  ({score_label})"]
    if pct is not None:
        lines += [f"30d percentile:  {pct:.0f}%"]
    if avg_7d is not None:
        lines += [f"7d average:      €{avg_7d:.3f}/L"]
    if avg_30d is not None:
        lines += [f"30d average:     €{avg_30d:.3f}/L"]
    if low_30d is not None:
        lines += [f"30d low:         €{low_30d:.3f}/L"]

    if analysis.get("score_reasons"):
        lines += ["", "Why:"]
        for r in analysis["score_reasons"]:
            lines += [f"  • {r}"]

    if forecasts:
        lines += ["", "Forecast:"]
        for fc in forecasts:
            h = fc["horizon_days"]
            label = "Tomorrow" if h == 1 else f"{h} days"
            lines += [f"  {label}:  €{fc['expected']:.3f}  (€{fc['low']:.3f}–€{fc['high']:.3f})"]

    if total_saving is not None:
        lines += ["", "Potential saving vs fill now:"]
        lines += [f"  ~€{total_saving:.2f} on {typical_fill_litres:.0f}L"]

    lines += ["", f"{emoji} {action}", reason]

    return title, "\n".join(lines), maps_link
