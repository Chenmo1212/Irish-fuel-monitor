#!/usr/bin/env python3
"""
Fuel Monitor — entry point.
Run: python main.py
"""
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from fuel_monitor.analysis import analyse, haversine_km
from fuel_monitor.collector import collect
from fuel_monitor.config import load_config
from fuel_monitor.database import Database
from fuel_monitor.decision import decide
from fuel_monitor.notifier import format_message, send_notification
from fuel_monitor.predictor import forecast

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fuel_monitor")


def main() -> int:
    load_dotenv()

    # ------------------------------------------------------------------
    # 1. Config
    # ------------------------------------------------------------------
    config_path = Path(__file__).parent / "config.yaml"
    cfg = load_config(str(config_path))

    lat = cfg["location"]["latitude"]
    lng = cfg["location"]["longitude"]
    radius_km = cfg["location"]["radius_km"]
    fuel_type_cfg = cfg["fuel"]["type"]  # "petrol" or "diesel"
    fuel_type_code = "E10" if fuel_type_cfg == "petrol" else "B7"
    typical_fill = cfg["vehicle"]["typical_fill_litres"]
    horizons = cfg["prediction"]["horizons"]
    min_score = cfg["alert"]["minimum_score"]
    cooldown_hours = cfg["alert"]["cooldown_hours"]
    sig_drop_cents = cfg["alert"]["significant_price_drop_cents"]
    notif_enabled = cfg["notification"]["enabled"]
    notif_source = cfg["notification"]["source"]

    # ------------------------------------------------------------------
    # 2. Database
    # ------------------------------------------------------------------
    db_path = Path(__file__).parent / "data" / "fuel.db"
    db = Database(str(db_path))
    db.init_schema()

    # ------------------------------------------------------------------
    # 3. Collect
    # ------------------------------------------------------------------
    print(f"Fetching fuel prices within {radius_km}km of ({lat}, {lng})...")
    stations, observations = collect(lat, lng, radius_km)

    if not stations:
        print("No stations returned. Exiting.")
        return 1

    # Filter to configured fuel type
    fuel_observations = [o for o in observations if o["fuel_type"] == fuel_type_code]
    print(f"Found {len(stations)} stations, {len(fuel_observations)} {fuel_type_cfg} price observations.")

    # ------------------------------------------------------------------
    # 4. Save to database
    # ------------------------------------------------------------------
    saved_count = 0
    for s in stations:
        db.upsert_station(s)
    for o in fuel_observations:
        if db.save_observation(o["station_id"], o["fuel_type"], o["price"], o["observed_at"]):
            saved_count += 1
    print(f"Saved {saved_count} new observations (duplicates skipped).")

    # ------------------------------------------------------------------
    # 5. Build per-station analysis
    # ------------------------------------------------------------------
    since_30d = datetime.now(timezone.utc) - timedelta(days=30)

    station_results = []
    obs_by_station = {o["station_id"]: o["price"] for o in fuel_observations}

    for s in stations:
        sid = s["station_id"]
        current_price = obs_by_station.get(sid)
        if current_price is None:
            continue  # no price for this station this run

        distance_km = haversine_km(lat, lng, s["latitude"], s["longitude"])

        history = db.get_price_history(sid, fuel_type_code, since_30d)
        result = analyse(current_price, history)
        result["current_price"] = current_price

        station_results.append({
            "station": {**s, "distance_km": distance_km, "current_price": current_price},
            "analysis": result,
            "history": history,
        })

    if not station_results:
        print("No stations with prices found. Exiting.")
        return 0

    # ------------------------------------------------------------------
    # 6. Rank stations: score descending, distance ascending as tiebreaker
    # ------------------------------------------------------------------
    def sort_key(r):
        score = r["analysis"].get("score")
        dist = r["station"]["distance_km"]
        return (-(score if score is not None else -1), dist)

    station_results.sort(key=sort_key)
    best = station_results[0]

    # ------------------------------------------------------------------
    # 7. Forecast on best station
    # ------------------------------------------------------------------
    forecasts = forecast(best["history"], horizons)

    # ------------------------------------------------------------------
    # 8. Decision
    # ------------------------------------------------------------------
    recommendation = decide(
        best["station"]["current_price"],
        forecasts,
        typical_fill,
        sig_drop_cents,
    )

    # ------------------------------------------------------------------
    # 9. Print summary
    # ------------------------------------------------------------------
    st = best["station"]
    a = best["analysis"]
    print()
    print("=" * 50)
    print("Best nearby station:")
    print(f"  {st['name']}  ({st['distance_km']:.1f} km)")
    print(f"  Current:  €{st['current_price']:.3f}/L")
    if a["score"] is not None:
        print(f"  Score:    {a['score']:.0f}/100  ({a['score_label']})")
    if a["percentile_30d"] is not None:
        print(f"  30d pct:  {a['percentile_30d']:.0f}%")
    if a["avg_7d"] is not None:
        print(f"  7d avg:   €{a['avg_7d']:.3f}/L")
    if a["avg_30d"] is not None:
        print(f"  30d avg:  €{a['avg_30d']:.3f}/L")
    if a["low_30d"] is not None:
        print(f"  30d low:  €{a['low_30d']:.3f}/L")

    if forecasts:
        print()
        print("Forecast:")
        for fc in forecasts:
            h = fc["horizon_days"]
            label = "Tomorrow" if h == 1 else f"{h} days "
            print(f"  {label}: €{fc['expected']:.3f}  (€{fc['low']:.3f}–€{fc['high']:.3f})")
    else:
        print()
        print("Forecast: Insufficient historical data")

    print()
    print(f"Recommendation: {recommendation['action']}")
    print(f"  {recommendation['reason']}")
    print("=" * 50)

    # ------------------------------------------------------------------
    # 10. Notification — check score threshold + cooldown
    # ------------------------------------------------------------------
    score = a.get("score")

    if score is not None and score >= min_score:
        last_alert = db.get_last_alert(st["station_id"])
        should_send = True

        if last_alert:
            last_sent = datetime.fromisoformat(last_alert["sent_at"])
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            hours_since = (datetime.now(timezone.utc) - last_sent).total_seconds() / 3600
            price_improvement = (last_alert["price"] - st["current_price"]) * 100

            if hours_since < cooldown_hours and price_improvement < sig_drop_cents:
                should_send = False
                print(f"\nNotification: suppressed (cooldown, {hours_since:.1f}h since last alert)")

        if should_send:
            title, body = format_message(st, a, forecasts, recommendation, typical_fill)
            priority = "high" if recommendation["action"] == "FILL NOW" else "medium"
            sent = send_notification(title, body, priority, notif_source, notif_enabled)
            if sent:
                db.log_alert(st["station_id"], st["current_price"], score, datetime.now(timezone.utc))
                print("\nNotification: sent ✓")
            else:
                print("\nNotification: failed to send")
    else:
        if score is None:
            print("\nNotification: suppressed (insufficient data for score)")
        else:
            print(f"\nNotification: suppressed (score {score:.0f} < threshold {min_score})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
