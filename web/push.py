import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS web_push_subscriptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint       TEXT NOT NULL UNIQUE,
    p256dh         TEXT NOT NULL,
    auth           TEXT NOT NULL,
    fuel_type      TEXT NOT NULL,
    latitude       REAL NOT NULL,
    longitude      REAL NOT NULL,
    radius_km      REAL NOT NULL DEFAULT 20,
    petrol_target  REAL,
    diesel_target  REAL,
    created_at     TEXT NOT NULL
)
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(_CREATE_TABLE)


def upsert_subscription(
    db_path: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    fuel_type: str,
    lat: float,
    lng: float,
    radius_km: float,
    petrol_target: float | None,
    diesel_target: float | None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO web_push_subscriptions
                (endpoint, p256dh, auth, fuel_type, latitude, longitude,
                 radius_km, petrol_target, diesel_target, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                p256dh=excluded.p256dh,
                auth=excluded.auth,
                fuel_type=excluded.fuel_type,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                radius_km=excluded.radius_km,
                petrol_target=excluded.petrol_target,
                diesel_target=excluded.diesel_target
            """,
            (endpoint, p256dh, auth, fuel_type, lat, lng,
             radius_km, petrol_target, diesel_target, now),
        )


def delete_subscription(db_path: str, endpoint: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM web_push_subscriptions WHERE endpoint=?", (endpoint,)
        )


def get_all_subscriptions(db_path: str) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM web_push_subscriptions"
        ).fetchall()
        return [dict(r) for r in rows]


def get_vapid_keys() -> tuple[str, str]:
    """Return (public_key_b64url, private_key_b64url) from env."""
    pub = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    return pub, priv


def send_push(subscription_row: dict, title: str, body: str, url: str) -> bool:
    """
    Send a Web Push notification to one subscription.
    Returns True on success, False on failure.
    Raises _PushGoneError if the endpoint is expired (410 Gone) — caller handles row removal.
    """
    from pywebpush import webpush, WebPushException
    import json

    pub_key, priv_key = get_vapid_keys()
    if not pub_key or not priv_key:
        logger.error("VAPID keys not set — cannot send Web Push")
        return False

    vapid_email = os.environ.get("VAPID_EMAIL", "").strip()
    if not vapid_email:
        logger.error("VAPID_EMAIL not set — cannot send Web Push")
        return False

    subscription_info = {
        "endpoint": subscription_row["endpoint"],
        "keys": {
            "p256dh": subscription_row["p256dh"],
            "auth": subscription_row["auth"],
        },
    }
    data = json.dumps({"title": title, "body": body, "url": url})

    try:
        webpush(
            subscription_info=subscription_info,
            data=data,
            vapid_private_key=priv_key,
            vapid_claims={"sub": vapid_email if vapid_email.startswith(("mailto:", "https:")) else f"mailto:{vapid_email}"},
        )
        logger.info("Web Push sent to endpoint %s…", subscription_row["endpoint"][:40])
        return True
    except WebPushException as exc:
        if exc.response is not None and exc.response.status_code == 410:
            raise _PushGoneError(subscription_row["endpoint"]) from exc
        logger.error("Web Push failed: %s", exc)
        return False


class _PushGoneError(Exception):
    def __init__(self, endpoint: str):
        self.endpoint = endpoint


def run_web_push_scan(db_path: str) -> None:
    """
    Scheduler job: check prices for all push subscriptions and fire
    notifications where current price <= target.
    """
    from fuel_monitor.collector import collect
    from fuel_monitor.database import Database
    from fuel_monitor.analysis import analyse, haversine_km
    from datetime import timedelta

    subscriptions = get_all_subscriptions(db_path)
    if not subscriptions:
        logger.info("Web push scan: no subscriptions")
        return

    db = Database(db_path)

    # Deduplicate locations to avoid hammering the API
    location_groups: dict[tuple, list[dict]] = {}
    for sub in subscriptions:
        key = (round(sub["latitude"], 2), round(sub["longitude"], 2), sub["radius_km"])
        location_groups.setdefault(key, []).append(sub)

    logger.info("Web push scan: %d subscriptions, %d unique locations",
                len(subscriptions), len(location_groups))

    for (lat, lng, radius_km), group in location_groups.items():
        stations, observations = collect(lat, lng, radius_km)
        if not stations:
            continue

        for s in stations:
            db.upsert_station(s)

        now = datetime.now(timezone.utc)
        since_30d = now - timedelta(days=30)
        obs_by_station_fuel: dict[tuple, float] = {
            (o["station_id"], o["fuel_type"]): o["price"] for o in observations
        }
        for o in observations:
            db.save_observation(o["station_id"], o["fuel_type"], o["price"], now)

        for sub in group:
            fuel_type = sub["fuel_type"]
            target = sub["petrol_target"] if fuel_type in ("E10", "E5_98") else sub["diesel_target"]
            if target is None:
                continue

            # Find cheapest nearby station for this fuel type
            best_price = None
            best_station = None
            for s in stations:
                price = obs_by_station_fuel.get((s["station_id"], fuel_type))
                if price is None:
                    continue
                dist = haversine_km(lat, lng, s["latitude"], s["longitude"])
                if dist > radius_km:
                    continue
                if best_price is None or price < best_price:
                    best_price = price
                    best_station = {**s, "distance_km": dist, "current_price": price}

            if best_station is None or best_price is None:
                continue

            if best_price > target:
                continue

            # Price is at or below target — compute analysis for message
            history = db.get_price_history(best_station["station_id"], fuel_type, since_30d)
            result = analyse(best_price, history)
            score_label = result.get("score_label") or "new station"
            title = f"⛽ Fuel alert — {best_station['name']}"
            body = (
                f"{fuel_type} at €{best_price:.3f}/L ({score_label}) — "
                f"{best_station['distance_km']:.1f} km away"
            )

            try:
                send_push(sub, title, body, "/")
            except _PushGoneError as exc:
                logger.info("Subscription gone (410), removing: %s…", exc.endpoint[:40])
                delete_subscription(db_path, exc.endpoint)
