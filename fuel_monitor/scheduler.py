import logging
from datetime import datetime, timedelta, timezone

from fuel_monitor.analysis import analyse, haversine_km
from fuel_monitor.collector import collect
from fuel_monitor.database import Database
from fuel_monitor.decision import decide
from fuel_monitor.notifier import format_message, send_telegram_to
from fuel_monitor.predictor import forecast

logger = logging.getLogger(__name__)

HORIZONS = [1, 2, 3, 7]
TYPICAL_FILL = 40.0
SIG_DROP_CENTS = 1.0
COOLDOWN_HOURS = 24.0
MIN_SCORE = 0.0

FUEL_CODE_MAP = {
    "petrol":     "E10",
    "diesel":     "B7",
    "petrolplus": "E5_98",
    "dieselplus":  "B7_PREMIUM",
}
# Reverse: internal code → collector field name
COLLECTOR_FUEL_MAP = {v: k for k, v in FUEL_CODE_MAP.items()}


def run_check_for_user(
    user: dict,
    db: Database,
    token: str,
    horizons: list[int],
    typical_fill: float,
    sig_drop_cents: float,
    cooldown_hours: float,
    min_score: float,
    bypass_cooldown: bool,
) -> bool:
    """
    Run the full fuel-check pipeline for a single user.
    Returns True if a notification was sent, False otherwise.
    """
    chat_id = user["chat_id"]
    fuel_type = user["fuel_type"]  # internal code e.g. "E10"
    lat = user["latitude"]
    lng = user["longitude"]
    radius_km = user.get("radius_km", 20.0)

    if not fuel_type or lat is None or lng is None:
        logger.debug("User %s missing fuel_type or location — skipping", chat_id)
        return False

    stations, observations = collect(lat, lng, radius_km)
    if not stations:
        logger.debug("No stations returned for user %s", chat_id)
        return False

    fuel_obs = [o for o in observations if o["fuel_type"] == fuel_type]
    if not fuel_obs:
        logger.debug("No %s observations for user %s", fuel_type, chat_id)
        return False

    for s in stations:
        db.upsert_station(s)
    since_30d = datetime.now(timezone.utc) - timedelta(days=30)
    obs_by_station = {o["station_id"]: o["price"] for o in fuel_obs}

    station_results = []
    for s in stations:
        sid = s["station_id"]
        current_price = obs_by_station.get(sid)
        if current_price is None:
            continue
        db.save_observation(sid, fuel_type, current_price, datetime.now(timezone.utc))
        distance_km = haversine_km(lat, lng, s["latitude"], s["longitude"])
        history = db.get_price_history(sid, fuel_type, since_30d)
        result = analyse(current_price, history)
        result["current_price"] = current_price
        station_results.append({
            "station": {**s, "distance_km": distance_km, "current_price": current_price},
            "analysis": result,
            "history": history,
        })

    if not station_results:
        return False

    station_results.sort(
        key=lambda r: (
            0 if r["analysis"].get("score") is not None else 1,
            -(r["analysis"]["score"] or 0),
            r["station"]["current_price"],
            r["station"]["distance_km"],
        )
    )
    best = station_results[0]
    st = best["station"]
    a = best["analysis"]
    score = a.get("score")

    # score is None means insufficient history — always let it through; cooldown gate
    # only applies to scored results that fall below the threshold.
    if not bypass_cooldown and score is not None and score < min_score:
        logger.debug("User %s: score %.0f < min_score %.0f — suppressed", chat_id, score, min_score)
        return False

    if not bypass_cooldown:
        last_alert = db.get_last_user_alert(chat_id, st["station_id"])
        if last_alert:
            last_sent = datetime.fromisoformat(last_alert["sent_at"])
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            hours_since = (datetime.now(timezone.utc) - last_sent).total_seconds() / 3600
            price_improvement = (last_alert["price"] - st["current_price"]) * 100
            if hours_since < cooldown_hours and price_improvement < sig_drop_cents:
                logger.debug("User %s: cooldown active (%.1fh) — suppressed", chat_id, hours_since)
                return False

    forecasts = forecast(best["history"], horizons)
    recommendation = decide(st["current_price"], forecasts, typical_fill, sig_drop_cents)
    title, body, maps_url = format_message(st, a, forecasts, recommendation, typical_fill)

    sent = send_telegram_to(chat_id, title, body, maps_url, token)
    if sent:
        db.log_user_alert(chat_id, st["station_id"], st["current_price"], score or 0.0, datetime.now(timezone.utc))
    return sent


def run_scheduled_scan(db: Database, token: str) -> None:
    """Iterate all registered users and run the fuel-check pipeline for each."""
    users = db.get_all_users()
    logger.info("Scheduled scan: %d users to check", len(users))
    sent_count = 0
    for user in users:
        try:
            if run_check_for_user(
                user=user,
                db=db,
                token=token,
                horizons=HORIZONS,
                typical_fill=TYPICAL_FILL,
                sig_drop_cents=SIG_DROP_CENTS,
                cooldown_hours=COOLDOWN_HOURS,
                min_score=MIN_SCORE,
                bypass_cooldown=False,
            ):
                sent_count += 1
        except Exception as exc:
            logger.error("Error checking user %s: %s", user.get("chat_id"), exc)
    logger.info("Scheduled scan complete: %d notifications sent", sent_count)
