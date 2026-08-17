import logging
import os

import requests

logger = logging.getLogger(__name__)


def send_notification(
    title: str,
    body: str,
    priority: str,
    source: str,
    enabled: bool,
) -> bool:
    """
    Send a notification via the personal API.
    Returns True on success, False on any failure. Never raises.
    """
    if not enabled:
        logger.info("Notifications disabled — skipping send.")
        return False

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
) -> tuple[str, str]:
    """
    Format a Telegram-style notification message.
    Returns (title, body).
    """
    name = station.get("name", "Unknown station")
    dist = station.get("distance_km")
    dist_str = f"{dist:.1f} km" if dist is not None else "unknown distance"

    price = analysis.get("current_price") or station.get("current_price", 0)
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

    lines = ["⛽ Fuel Alert", ""]
    lines += [f"Best station nearby:", f"{name} ({dist_str})", ""]
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
        for f in forecasts:
            h = f["horizon_days"]
            label = "Tomorrow" if h == 1 else f"{h} days"
            lines += [f"  {label}:  €{f['expected']:.3f}  (€{f['low']:.3f}–€{f['high']:.3f})"]

    if total_saving is not None:
        lines += ["", f"Potential saving vs fill now:"]
        lines += [f"  ~€{total_saving:.2f} on {typical_fill_litres:.0f}L"]

    lines += ["", f"{emoji} {action}", reason]

    return title, "\n".join(lines)
