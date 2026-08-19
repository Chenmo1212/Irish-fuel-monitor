# FuelBot Web App + Web Push — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Flask REST API + React SPA + Web Push notification layer to the existing FuelBot project without modifying any existing `fuel_monitor/` modules.

**Architecture:** `web/app.py` is the Flask application factory exposing REST endpoints that call existing `fuel_monitor` modules directly. `web/push.py` manages VAPID keys, push subscriptions in SQLite, and push dispatch. `web/frontend/` is a Vite+React SPA built into `web/static/` and served by Flask.

**Tech Stack:** Python 3.11, Flask ≥ 3.0, pywebpush ≥ 2.0, flask-cors ≥ 4.0, Vite 5, React 18, React Router v6, Recharts 2.

**Spec:** `docs/superpowers/specs/2025-07-14-web-app-push-design.md`

## Global Constraints

- Never modify any file under `fuel_monitor/`, `bot.py`, or `main.py`.
- Flask must bind to `127.0.0.1` only — never `0.0.0.0`.
- VAPID keys stored in `.env` only — never hardcoded.
- Python deps added to `requirements.txt`.
- All new JS deps in `web/frontend/package.json` only.
- `web/static/` is git-ignored (build output).
- SQLite WAL mode already enabled; new table added without touching `Database` class.

---


### Task 1: Backend scaffolding — `web/push.py` and DB schema

**Files:**
- Create: `web/push.py`
- Create: `tests/web/test_push_schema.py`

**Interfaces:**
- Produces:
  - `init_schema(db_path: str) -> None` — creates `web_push_subscriptions` table
  - `upsert_subscription(db_path, endpoint, p256dh, auth, fuel_type, lat, lng, radius_km, petrol_target, diesel_target) -> None`
  - `delete_subscription(db_path, endpoint) -> None`
  - `get_all_subscriptions(db_path) -> list[dict]`
  - `get_vapid_keys() -> tuple[str, str]` — returns `(public_key_b64url, private_key_b64url)` from env
  - `send_push(subscription_row: dict, title: str, body: str, url: str) -> bool`
  - `run_web_push_scan(db_path: str) -> None` — full scheduler scan

- [ ] **Step 1: Install pywebpush**

```bash
cd fuel-monitor
source .venv/bin/activate
pip install "pywebpush>=2.0" "flask>=3.0" "flask-cors>=4.0"
```

Then add to `requirements.txt`:
```
flask>=3.0
flask-cors>=4.0
pywebpush>=2.0
```

- [ ] **Step 2: Write failing schema test**

Create `fuel-monitor/tests/web/__init__.py` (empty) and `fuel-monitor/tests/web/test_push_schema.py`:

```python
import sqlite3, tempfile, os
from web.push import init_schema, upsert_subscription, delete_subscription, get_all_subscriptions


def test_init_schema_creates_table():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_schema(db_path)
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='web_push_subscriptions'"
        ).fetchone()
        conn.close()
        assert row is not None
    finally:
        os.unlink(db_path)


def test_upsert_and_get_subscription():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_schema(db_path)
        upsert_subscription(
            db_path,
            endpoint="https://example.com/push/1",
            p256dh="key1",
            auth="auth1",
            fuel_type="E10",
            lat=53.27,
            lng=-6.20,
            radius_km=20.0,
            petrol_target=1.75,
            diesel_target=None,
        )
        rows = get_all_subscriptions(db_path)
        assert len(rows) == 1
        assert rows[0]["endpoint"] == "https://example.com/push/1"
        assert rows[0]["petrol_target"] == 1.75
        assert rows[0]["diesel_target"] is None
    finally:
        os.unlink(db_path)


def test_upsert_is_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_schema(db_path)
        for _ in range(2):
            upsert_subscription(
                db_path,
                endpoint="https://example.com/push/1",
                p256dh="key1",
                auth="auth1",
                fuel_type="E10",
                lat=53.27,
                lng=-6.20,
                radius_km=20.0,
                petrol_target=1.75,
                diesel_target=None,
            )
        rows = get_all_subscriptions(db_path)
        assert len(rows) == 1
    finally:
        os.unlink(db_path)


def test_delete_subscription():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        init_schema(db_path)
        upsert_subscription(
            db_path,
            endpoint="https://example.com/push/1",
            p256dh="key1",
            auth="auth1",
            fuel_type="E10",
            lat=53.27,
            lng=-6.20,
            radius_km=20.0,
            petrol_target=None,
            diesel_target=None,
        )
        delete_subscription(db_path, "https://example.com/push/1")
        rows = get_all_subscriptions(db_path)
        assert rows == []
    finally:
        os.unlink(db_path)
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd fuel-monitor
pytest tests/web/test_push_schema.py -v
```
Expected: `ModuleNotFoundError: No module named 'web.push'`

- [ ] **Step 4: Create `web/__init__.py`**

```python
# web/__init__.py
```

- [ ] **Step 5: Implement `web/push.py`**

Create `fuel-monitor/web/push.py`:

```python
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
    Deletes the DB row on HTTP 410 (Gone) — caller handles row removal.
    Raises PushGoneError if the endpoint is expired (410).
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
            vapid_claims={"sub": f"mailto:{vapid_email}"},
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
```

- [ ] **Step 6: Run tests — expect pass**

```bash
cd fuel-monitor
pytest tests/web/test_push_schema.py -v
```
Expected: 4 tests pass.

- [ ] **Step 7: Commit**

```bash
cd fuel-monitor
git add web/__init__.py web/push.py tests/web/__init__.py tests/web/test_push_schema.py requirements.txt
git commit -m "feat(web): add push.py — subscription CRUD, VAPID helpers, push dispatch"
```

---

### Task 2: Flask application factory and REST API

**Files:**
- Create: `web/app.py`
- Create: `tests/web/test_api.py`

**Interfaces:**
- Consumes: `web.push.init_schema`, `web.push.upsert_subscription`, `web.push.delete_subscription`, `web.push.get_vapid_keys`
- Produces: `create_app(db_path: str) -> Flask` — application factory

- [ ] **Step 1: Write failing API tests**

Create `fuel-monitor/tests/web/test_api.py`:

```python
import json
import os
import tempfile

import pytest

os.environ.setdefault("VAPID_PUBLIC_KEY", "test_pub_key")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test_priv_key")
os.environ.setdefault("VAPID_EMAIL", "test@example.com")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    from web.push import init_schema
    from fuel_monitor.database import Database

    init_schema(db_path)
    db = Database(db_path)
    db.init_schema()
    db.init_users_schema()

    from web.app import create_app
    app = create_app(db_path)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_vapid_public_key(client):
    resp = client.get("/api/vapid-public-key")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["publicKey"] == "test_pub_key"


def test_push_subscribe(client):
    payload = {
        "subscription": {
            "endpoint": "https://example.com/push/abc",
            "keys": {"p256dh": "pk", "auth": "au"},
        },
        "prefs": {
            "fuel_type": "E10",
            "latitude": 53.27,
            "longitude": -6.20,
            "radius_km": 20,
            "petrol_target": 1.75,
            "diesel_target": None,
        },
    }
    resp = client.post(
        "/api/push/subscribe",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_push_unsubscribe(client):
    # Subscribe first
    payload = {
        "subscription": {
            "endpoint": "https://example.com/push/xyz",
            "keys": {"p256dh": "pk2", "auth": "au2"},
        },
        "prefs": {
            "fuel_type": "B7",
            "latitude": 53.27,
            "longitude": -6.20,
            "radius_km": 20,
            "petrol_target": None,
            "diesel_target": 1.65,
        },
    }
    client.post(
        "/api/push/subscribe",
        data=json.dumps(payload),
        content_type="application/json",
    )
    resp = client.delete(
        "/api/push/subscribe",
        data=json.dumps({"endpoint": "https://example.com/push/xyz"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_stations_missing_params(client):
    resp = client.get("/api/stations")
    assert resp.status_code == 400


def test_station_history_not_found(client):
    resp = client.get("/api/stations/nonexistent/history?fuel=E10")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_prices_summary_missing_params(client):
    resp = client.get("/api/prices/summary")
    assert resp.status_code == 400


def test_spa_catchall(client):
    # Without a built index.html this 404s but the route must exist
    resp = client.get("/some/spa/route")
    # Either 200 (if static/index.html exists) or 404 from send_file — both acceptable
    assert resp.status_code in (200, 404)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd fuel-monitor
pytest tests/web/test_api.py -v
```
Expected: `ModuleNotFoundError: No module named 'web.app'`

- [ ] **Step 3: Implement `web/app.py`**

Create `fuel-monitor/web/app.py`:

```python
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from fuel_monitor.analysis import analyse, haversine_km
from fuel_monitor.collector import collect
from fuel_monitor.database import Database

import web.push as push_store

logger = logging.getLogger(__name__)

FUEL_CODES = {"E10", "B7", "E5_98", "B7_PREMIUM"}


def create_app(db_path: str | None = None) -> Flask:
    if db_path is None:
        db_path = str(Path(__file__).parent.parent / "data" / "fuel.db")

    static_folder = str(Path(__file__).parent / "static")
    app = Flask(__name__, static_folder=static_folder, static_url_path="/")
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    push_store.init_schema(db_path)

    # ------------------------------------------------------------------ #
    # /api/vapid-public-key
    # ------------------------------------------------------------------ #
    @app.get("/api/vapid-public-key")
    def vapid_public_key():
        pub, _ = push_store.get_vapid_keys()
        return jsonify({"publicKey": pub})

    # ------------------------------------------------------------------ #
    # /api/push/subscribe   POST / DELETE
    # ------------------------------------------------------------------ #
    @app.post("/api/push/subscribe")
    def push_subscribe():
        body = request.get_json(force=True) or {}
        sub = body.get("subscription", {})
        prefs = body.get("prefs", {})
        endpoint = sub.get("endpoint")
        keys = sub.get("keys", {})
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            return jsonify({"error": "Invalid subscription object"}), 400
        push_store.upsert_subscription(
            db_path,
            endpoint=endpoint,
            p256dh=keys["p256dh"],
            auth=keys["auth"],
            fuel_type=prefs.get("fuel_type", "E10"),
            lat=float(prefs.get("latitude", 0)),
            lng=float(prefs.get("longitude", 0)),
            radius_km=float(prefs.get("radius_km", 20)),
            petrol_target=prefs.get("petrol_target"),
            diesel_target=prefs.get("diesel_target"),
        )
        return jsonify({"ok": True})

    @app.delete("/api/push/subscribe")
    def push_unsubscribe():
        body = request.get_json(force=True) or {}
        endpoint = body.get("endpoint")
        if not endpoint:
            return jsonify({"error": "endpoint required"}), 400
        push_store.delete_subscription(db_path, endpoint)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ #
    # /api/stations
    # ------------------------------------------------------------------ #
    @app.get("/api/stations")
    def stations():
        lat = request.args.get("lat", type=float)
        lng = request.args.get("lng", type=float)
        radius = request.args.get("radius", default=20.0, type=float)
        fuel = request.args.get("fuel", default="E10")
        if lat is None or lng is None:
            return jsonify({"error": "lat and lng are required"}), 400
        if fuel not in FUEL_CODES:
            return jsonify({"error": f"fuel must be one of {sorted(FUEL_CODES)}"}), 400

        raw_stations, observations = collect(lat, lng, radius)
        if not raw_stations:
            return jsonify([])

        db = Database(db_path)
        now = datetime.now(timezone.utc)
        since_30d = now - timedelta(days=30)

        for s in raw_stations:
            db.upsert_station(s)

        obs_by_station = {
            o["station_id"]: o["price"]
            for o in observations
            if o["fuel_type"] == fuel
        }
        for o in observations:
            db.save_observation(o["station_id"], o["fuel_type"], o["price"], now)

        results = []
        for s in raw_stations:
            current_price = obs_by_station.get(s["station_id"])
            if current_price is None:
                continue
            distance_km = haversine_km(lat, lng, s["latitude"], s["longitude"])
            history = db.get_price_history(s["station_id"], fuel, since_30d)
            a = analyse(current_price, history)
            results.append({
                "station_id": s["station_id"],
                "name": s["name"],
                "brand": s.get("brand"),
                "address": s.get("address"),
                "town": s.get("town"),
                "county": s.get("county"),
                "latitude": s["latitude"],
                "longitude": s["longitude"],
                "distance_km": round(distance_km, 2),
                "current_price": current_price,
                "fuel_type": fuel,
                "score": a.get("score"),
                "score_label": a.get("score_label"),
                "avg_7d": a.get("avg_7d"),
                "avg_30d": a.get("avg_30d"),
                "low_30d": a.get("low_30d"),
                "score_reasons": a.get("score_reasons", []),
            })

        results.sort(
            key=lambda r: (
                0 if r["score"] is not None else 1,
                -(r["score"] or 0),
                r["current_price"],
                r["distance_km"],
            )
        )
        return jsonify(results)

    # ------------------------------------------------------------------ #
    # /api/stations/<id>/history
    # ------------------------------------------------------------------ #
    @app.get("/api/stations/<station_id>/history")
    def station_history(station_id: str):
        fuel = request.args.get("fuel", default="E10")
        days = min(request.args.get("days", default=30, type=int), 90)
        db = Database(db_path)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = db.get_price_history(station_id, fuel, since)
        return jsonify(rows)

    # ------------------------------------------------------------------ #
    # /api/prices/summary
    # ------------------------------------------------------------------ #
    @app.get("/api/prices/summary")
    def prices_summary():
        lat = request.args.get("lat", type=float)
        lng = request.args.get("lng", type=float)
        radius = request.args.get("radius", default=20.0, type=float)
        fuel = request.args.get("fuel", default="E10")
        if lat is None or lng is None:
            return jsonify({"error": "lat and lng are required"}), 400

        raw_stations, observations = collect(lat, lng, radius)
        if not raw_stations:
            return jsonify({"daily_avg": [], "cheapest_today": None})

        db = Database(db_path)
        now = datetime.now(timezone.utc)
        since_30d = now - timedelta(days=30)

        for s in raw_stations:
            db.upsert_station(s)
        obs_by_station = {
            o["station_id"]: o["price"]
            for o in observations
            if o["fuel_type"] == fuel
        }
        for o in observations:
            db.save_observation(o["station_id"], o["fuel_type"], o["price"], now)

        # Daily medians across all stations in the area
        from collections import defaultdict
        import statistics

        day_prices: dict[str, list[float]] = defaultdict(list)
        for s in raw_stations:
            sid = s["station_id"]
            if haversine_km(lat, lng, s["latitude"], s["longitude"]) > radius:
                continue
            history = db.get_price_history(sid, fuel, since_30d)
            for row in history:
                date = row["observed_at"][:10]
                day_prices[date].append(row["price"])

        daily_avg = sorted(
            [
                {"date": d, "median_price": round(statistics.median(prices), 4)}
                for d, prices in day_prices.items()
            ],
            key=lambda x: x["date"],
        )

        # Cheapest station today
        cheapest_today = None
        best_price = None
        for s in raw_stations:
            p = obs_by_station.get(s["station_id"])
            if p is None:
                continue
            dist = haversine_km(lat, lng, s["latitude"], s["longitude"])
            if best_price is None or p < best_price:
                best_price = p
                cheapest_today = {
                    "station_id": s["station_id"],
                    "name": s["name"],
                    "current_price": p,
                    "distance_km": round(dist, 2),
                }

        return jsonify({"daily_avg": daily_avg, "cheapest_today": cheapest_today})

    # ------------------------------------------------------------------ #
    # SPA catch-all
    # ------------------------------------------------------------------ #
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa_index(path: str):
        index = Path(static_folder) / "index.html"
        if index.exists():
            return send_file(str(index))
        return jsonify({"error": "Frontend not built. Run: cd web/frontend && npm run build"}), 404

    return app
```

- [ ] **Step 4: Run API tests — expect pass**

```bash
cd fuel-monitor
pytest tests/web/test_api.py -v
```
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
cd fuel-monitor
git add web/app.py tests/web/test_api.py
git commit -m "feat(web): Flask app factory with REST API endpoints"
```

---

### Task 3: Entry point `web_app.py`

**Files:**
- Create: `web_app.py`

**Interfaces:**
- Consumes: `web.app.create_app`, `web.push.run_web_push_scan`, `web.push.get_vapid_keys`
- Produces: runnable entry point `python web_app.py`

- [ ] **Step 1: Create `web_app.py`**

Create `fuel-monitor/web_app.py`:

```python
#!/usr/bin/env python3
"""
FuelBot Web App entry point.

Development:  python web_app.py
Production:   gunicorn "web.app:create_app()" --bind 127.0.0.1:5000
"""
import logging
import os
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from fuel_monitor.database import Database
from web.app import create_app
from web.push import get_vapid_keys, run_web_push_scan, init_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fuelweb")


def main() -> None:
    load_dotenv()

    db_path = str(Path(__file__).parent / "data" / "fuel.db")

    # Initialise all DB schemas
    db = Database(db_path)
    db.init_schema()
    db.init_users_schema()
    init_schema(db_path)

    # Warn if VAPID keys not configured
    pub, priv = get_vapid_keys()
    vapid_email = os.environ.get("VAPID_EMAIL", "").strip()
    if not pub or not priv or not vapid_email:
        logger.warning(
            "VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_EMAIL not set. "
            "Web Push notifications will be disabled. "
            "Generate keys with: python -c \"from py_vapid import Vapid; "
            "v = Vapid(); v.generate_keys(); "
            "print('VAPID_PUBLIC_KEY=' + v.public_key.decode()); "
            "print('VAPID_PRIVATE_KEY=' + v.private_key.decode())\""
        )

    # Background scan every 6 hours
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_web_push_scan,
        trigger="interval",
        hours=6,
        args=[db_path],
        id="web_push_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Web push scan scheduler started (every 6 h)")

    app = create_app(db_path)
    logger.info("FuelBot Web App starting on http://127.0.0.1:5000")
    try:
        app.run(host="127.0.0.1", port=5000, debug=False)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the entry point starts without error**

```bash
cd fuel-monitor
timeout 5 python web_app.py || true
```
Expected: Flask startup message visible, no import errors, exits cleanly after 5 s.

- [ ] **Step 3: Commit**

```bash
cd fuel-monitor
git add web_app.py
git commit -m "feat(web): add web_app.py entry point with APScheduler"
```

---

### Task 4: Vite + React project scaffold

**Files:**
- Create: `web/frontend/` (Vite project)
- Create: `web/frontend/vite.config.js`
- Create: `web/frontend/public/sw.js`
- Create: `web/frontend/public/manifest.json`
- Modify: `.gitignore` — add `web/static/`

**Interfaces:**
- Produces: `npm run dev` starts Vite at `http://localhost:5173` proxying `/api` to Flask; `npm run build` outputs into `../static/`

- [ ] **Step 1: Scaffold Vite React project**

```bash
cd fuel-monitor/web
npm create vite@latest frontend -- --template react
cd frontend
npm install
npm install react-router-dom recharts
```

- [ ] **Step 2: Configure Vite**

Replace `fuel-monitor/web/frontend/vite.config.js` with:

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: Create service worker**

Create `fuel-monitor/web/frontend/public/sw.js`:

```js
self.addEventListener('push', (event) => {
  let data = { title: 'FuelBot', body: 'New fuel price alert', url: '/' }
  try {
    data = JSON.parse(event.data.text())
  } catch (_) {}
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/icon-192.png',
      data: { url: data.url },
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = event.notification.data?.url || '/'
  event.waitUntil(clients.openWindow(url))
})
```

- [ ] **Step 4: Create web manifest**

Create `fuel-monitor/web/frontend/public/manifest.json`:

```json
{
  "name": "FuelBot Ireland",
  "short_name": "FuelBot",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#16a34a",
  "icons": []
}
```

- [ ] **Step 5: Add `web/static/` to .gitignore**

Append to `fuel-monitor/.gitignore`:

```
web/static/
web/frontend/node_modules/
```

- [ ] **Step 6: Confirm dev server starts**

```bash
cd fuel-monitor/web/frontend
npm run dev &
sleep 3
curl -s http://localhost:5173 | grep -q "html" && echo "OK" || echo "FAIL"
kill %1
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
cd fuel-monitor
git add web/frontend/ .gitignore
git commit -m "feat(web): scaffold Vite+React frontend with service worker"
```

---

### Task 5: Frontend — API client and shared components

**Files:**
- Create: `web/frontend/src/api.js`
- Create: `web/frontend/src/components/PriceCard.jsx`
- Create: `web/frontend/src/components/StationList.jsx`
- Create: `web/frontend/src/components/PriceChart.jsx`
- Create: `web/frontend/src/components/PushToggle.jsx`
- Create: `web/frontend/src/components/ScoreBadge.jsx`

**Interfaces:**
- Produces:
  - `api.getStations(lat, lng, radius, fuel) -> Promise<Station[]>`
  - `api.getStationHistory(stationId, fuel, days) -> Promise<HistoryPoint[]>`
  - `api.getPricesSummary(lat, lng, radius, fuel) -> Promise<Summary>`
  - `api.getVapidPublicKey() -> Promise<string>`
  - `api.subscribe(subscriptionObj, prefs) -> Promise<void>`
  - `api.unsubscribe(endpoint) -> Promise<void>`

- [ ] **Step 1: Create `api.js`**

Create `fuel-monitor/web/frontend/src/api.js`:

```js
const BASE = '/api'

async function _get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json()
}

async function _post(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`)
  return res.json()
}

async function _delete(path, body) {
  const res = await fetch(BASE + path, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`DELETE ${path} → ${res.status}`)
  return res.json()
}

export function getStations(lat, lng, radius = 20, fuel = 'E10') {
  return _get(`/stations?lat=${lat}&lng=${lng}&radius=${radius}&fuel=${fuel}`)
}

export function getStationHistory(stationId, fuel = 'E10', days = 30) {
  return _get(`/stations/${stationId}/history?fuel=${fuel}&days=${days}`)
}

export function getPricesSummary(lat, lng, radius = 20, fuel = 'E10') {
  return _get(`/prices/summary?lat=${lat}&lng=${lng}&radius=${radius}&fuel=${fuel}`)
}

export function getVapidPublicKey() {
  return _get('/vapid-public-key').then((d) => d.publicKey)
}

export function subscribe(subscriptionObj, prefs) {
  return _post('/push/subscribe', { subscription: subscriptionObj, prefs })
}

export function unsubscribe(endpoint) {
  return _delete('/push/subscribe', { endpoint })
}
```

- [ ] **Step 2: Create `ScoreBadge.jsx`**

Create `fuel-monitor/web/frontend/src/components/ScoreBadge.jsx`:

```jsx
const COLOURS = {
  'Excellent':      { bg: '#dcfce7', text: '#166534' },
  'Very good':      { bg: '#d1fae5', text: '#065f46' },
  'Normal':         { bg: '#fef9c3', text: '#713f12' },
  'Expensive':      { bg: '#fee2e2', text: '#991b1b' },
  'Very expensive': { bg: '#fecaca', text: '#7f1d1d' },
}

export default function ScoreBadge({ score, label }) {
  if (score == null) return <span style={{ color: '#6b7280', fontSize: 12 }}>no history</span>
  const c = COLOURS[label] || { bg: '#f3f4f6', text: '#374151' }
  return (
    <span style={{
      background: c.bg, color: c.text,
      borderRadius: 4, padding: '2px 8px', fontSize: 12, fontWeight: 600,
    }}>
      {score.toFixed(0)}/100 · {label}
    </span>
  )
}
```

- [ ] **Step 3: Create `PriceCard.jsx`**

Create `fuel-monitor/web/frontend/src/components/PriceCard.jsx`:

```jsx
import ScoreBadge from './ScoreBadge'

export default function PriceCard({ station }) {
  if (!station) return null
  return (
    <div style={{
      border: '1px solid #e5e7eb', borderRadius: 8, padding: 20,
      background: '#f9fafb', maxWidth: 420,
    }}>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 4 }}>
        {station.town || station.county || ''} · {station.distance_km} km
      </div>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 6 }}>{station.name}</div>
      <div style={{ fontSize: 32, fontWeight: 800, color: '#15803d', marginBottom: 8 }}>
        €{station.current_price.toFixed(3)}<span style={{ fontSize: 16, fontWeight: 400 }}>/L</span>
      </div>
      <ScoreBadge score={station.score} label={station.score_label} />
      {station.avg_7d != null && (
        <div style={{ marginTop: 12, fontSize: 13, color: '#374151' }}>
          <span>7d avg: <strong>€{station.avg_7d.toFixed(3)}</strong></span>
          {station.avg_30d != null && (
            <span style={{ marginLeft: 12 }}>30d avg: <strong>€{station.avg_30d.toFixed(3)}</strong></span>
          )}
        </div>
      )}
      {station.score_reasons?.length > 0 && (
        <ul style={{ marginTop: 8, paddingLeft: 16, fontSize: 12, color: '#6b7280' }}>
          {station.score_reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Create `StationList.jsx`**

Create `fuel-monitor/web/frontend/src/components/StationList.jsx`:

```jsx
import ScoreBadge from './ScoreBadge'

export default function StationList({ stations, onSelect }) {
  if (!stations?.length) return <p style={{ color: '#6b7280' }}>No stations found.</p>
  return (
    <div>
      {stations.map((s) => (
        <div
          key={s.station_id}
          onClick={() => onSelect?.(s)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 16px', borderBottom: '1px solid #e5e7eb',
            cursor: 'pointer', background: '#fff',
          }}
        >
          <div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{s.name}</div>
            <div style={{ fontSize: 12, color: '#6b7280' }}>
              {s.distance_km} km · {s.town || s.county || ''}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontWeight: 700, color: '#15803d' }}>€{s.current_price.toFixed(3)}</div>
            <ScoreBadge score={s.score} label={s.score_label} />
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 5: Create `PriceChart.jsx`**

Create `fuel-monitor/web/frontend/src/components/PriceChart.jsx`:

```jsx
import {
  LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend,
} from 'recharts'

export default function PriceChart({ data, lines = [], height = 240 }) {
  // data: array of objects sharing an x-axis key "date" or "observed_at"
  // lines: [{ key, name, color }]
  if (!data?.length) return <p style={{ color: '#6b7280', fontSize: 13 }}>Not enough data yet.</p>

  const COLOURS = ['#16a34a', '#2563eb', '#d97706', '#dc2626']

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey={lines[0]?.xKey || 'date'} tick={{ fontSize: 11 }} />
        <YAxis
          tickFormatter={(v) => `€${v.toFixed(3)}`}
          tick={{ fontSize: 11 }}
          domain={['auto', 'auto']}
        />
        <Tooltip formatter={(v) => `€${parseFloat(v).toFixed(3)}`} />
        {lines.length > 1 && <Legend />}
        {lines.map((l, i) => (
          <Line
            key={l.key}
            type="monotone"
            dataKey={l.key}
            name={l.name || l.key}
            stroke={l.color || COLOURS[i % COLOURS.length]}
            dot={false}
            strokeWidth={2}
          />
        ))}
        {!lines.length && (
          <Line type="monotone" dataKey="price" stroke="#16a34a" dot={false} strokeWidth={2} />
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}
```

- [ ] **Step 6: Create `PushToggle.jsx`**

Create `fuel-monitor/web/frontend/src/components/PushToggle.jsx`:

```jsx
import { useState, useEffect } from 'react'
import { getVapidPublicKey, subscribe, unsubscribe } from '../api'

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = atob(base64)
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)))
}

export default function PushToggle({ prefs }) {
  const [supported, setSupported] = useState(false)
  const [subscribed, setSubscribed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setSupported('serviceWorker' in navigator && 'PushManager' in window)
    navigator.serviceWorker?.ready.then((reg) =>
      reg.pushManager.getSubscription().then((sub) => setSubscribed(!!sub))
    )
  }, [])

  async function handleToggle() {
    setLoading(true)
    setError(null)
    try {
      const reg = await navigator.serviceWorker.ready
      if (subscribed) {
        const sub = await reg.pushManager.getSubscription()
        if (sub) {
          await unsubscribe(sub.endpoint)
          await sub.unsubscribe()
        }
        setSubscribed(false)
      } else {
        const vapidKey = await getVapidPublicKey()
        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapidKey),
        })
        const json = sub.toJSON()
        await subscribe(
          { endpoint: json.endpoint, keys: json.keys },
          prefs,
        )
        setSubscribed(true)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  if (!supported) return <p style={{ fontSize: 13, color: '#6b7280' }}>Push not supported in this browser.</p>

  return (
    <div>
      <button
        onClick={handleToggle}
        disabled={loading}
        style={{
          padding: '8px 20px', borderRadius: 6, border: 'none',
          background: subscribed ? '#fee2e2' : '#dcfce7',
          color: subscribed ? '#991b1b' : '#166534',
          fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
        }}
      >
        {loading ? '…' : subscribed ? 'Disable notifications' : 'Enable notifications'}
      </button>
      {error && <p style={{ color: '#dc2626', fontSize: 12, marginTop: 4 }}>{error}</p>}
    </div>
  )
}
```

- [ ] **Step 7: Commit**

```bash
cd fuel-monitor
git add web/frontend/src/api.js web/frontend/src/components/
git commit -m "feat(web): API client and shared React components"
```

---

### Task 6: Frontend — Pages and App shell

**Files:**
- Create: `web/frontend/src/App.jsx`
- Create: `web/frontend/src/main.jsx`
- Create: `web/frontend/src/pages/Dashboard.jsx`
- Create: `web/frontend/src/pages/Stations.jsx`
- Create: `web/frontend/src/pages/History.jsx`
- Create: `web/frontend/src/pages/Settings.jsx`
- Create: `web/frontend/index.html` (update title/manifest/sw registration)

**Interfaces:**
- Consumes: all components from Task 5, all api.js exports
- Produces: complete SPA navigable at `/`, `/stations`, `/history`, `/settings`

- [ ] **Step 1: Update `index.html`**

Replace `fuel-monitor/web/frontend/index.html` with:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="manifest" href="/manifest.json" />
    <title>FuelBot Ireland</title>
    <style>
      * { box-sizing: border-box; }
      body { margin: 0; font-family: -apple-system, "Segoe UI", system-ui, sans-serif; background: #f9fafb; color: #1f2328; }
      a { color: inherit; text-decoration: none; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
    <script>
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(console.error)
      }
    </script>
  </body>
</html>
```

- [ ] **Step 2: Create `main.jsx`**

Replace `fuel-monitor/web/frontend/src/main.jsx` with:

```jsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
)
```

- [ ] **Step 3: Create `App.jsx`**

Create `fuel-monitor/web/frontend/src/App.jsx`:

```jsx
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Stations from './pages/Stations'
import History from './pages/History'
import Settings from './pages/Settings'

const NAV = [
  { to: '/', label: '⛽ Dashboard' },
  { to: '/stations', label: '📍 Stations' },
  { to: '/history', label: '📈 History' },
  { to: '/settings', label: '⚙️ Settings' },
]

export default function App() {
  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '0 16px' }}>
      <nav style={{
        display: 'flex', gap: 4, padding: '12px 0', borderBottom: '1px solid #e5e7eb',
        marginBottom: 24,
      }}>
        {NAV.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            style={({ isActive }) => ({
              padding: '6px 12px', borderRadius: 6, fontSize: 13, fontWeight: 600,
              background: isActive ? '#dcfce7' : 'transparent',
              color: isActive ? '#15803d' : '#374151',
            })}
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/stations" element={<Stations />} />
        <Route path="/history" element={<History />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </div>
  )
}
```

- [ ] **Step 4: Create `Dashboard.jsx`**

Create `fuel-monitor/web/frontend/src/pages/Dashboard.jsx`:

```jsx
import { useState, useEffect } from 'react'
import { getStations } from '../api'
import PriceCard from '../components/PriceCard'

const FUEL_OPTIONS = [
  { value: 'E10', label: '⛽ Petrol (E10)' },
  { value: 'B7', label: '🛢 Diesel (B7)' },
  { value: 'E5_98', label: '✨ Petrol Plus (E5/98)' },
  { value: 'B7_PREMIUM', label: '💎 Diesel Plus' },
]

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('fuelbot_prefs') || '{}') } catch { return {} }
}
function savePrefs(p) { localStorage.setItem('fuelbot_prefs', JSON.stringify(p)) }

export default function Dashboard() {
  const saved = loadPrefs()
  const [lat, setLat] = useState(saved.lat ?? '')
  const [lng, setLng] = useState(saved.lng ?? '')
  const [fuel, setFuel] = useState(saved.fuel ?? 'E10')
  const [radius, setRadius] = useState(saved.radius ?? 20)
  const [best, setBest] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  function geolocate() {
    navigator.geolocation.getCurrentPosition(
      (pos) => { setLat(pos.coords.latitude.toFixed(5)); setLng(pos.coords.longitude.toFixed(5)) },
      () => setError('Geolocation denied'),
    )
  }

  async function handleSearch(e) {
    e.preventDefault()
    if (!lat || !lng) return setError('Enter or detect your location first')
    setLoading(true); setError(null)
    try {
      const stations = await getStations(lat, lng, radius, fuel)
      setBest(stations[0] || null)
      savePrefs({ lat: parseFloat(lat), lng: parseFloat(lng), fuel, radius })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Dashboard</h2>
      <form onSubmit={handleSearch} style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 24 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>Latitude</div>
            <input value={lat} onChange={(e) => setLat(e.target.value)}
              placeholder="53.2753" style={inputStyle} />
          </label>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>Longitude</div>
            <input value={lng} onChange={(e) => setLng(e.target.value)}
              placeholder="-6.2031" style={inputStyle} />
          </label>
          <button type="button" onClick={geolocate} style={btnSecondary}>📍 Detect</button>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>Fuel type</div>
            <select value={fuel} onChange={(e) => setFuel(e.target.value)} style={inputStyle}>
              {FUEL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 2 }}>Radius (km)</div>
            <input type="number" min={5} max={50} value={radius}
              onChange={(e) => setRadius(Number(e.target.value))} style={inputStyle} />
          </label>
        </div>
        <button type="submit" disabled={loading} style={btnPrimary}>
          {loading ? 'Checking…' : 'Find best price'}
        </button>
      </form>
      {error && <p style={{ color: '#dc2626', fontSize: 13 }}>{error}</p>}
      {best && <PriceCard station={best} />}
      {best === null && !loading && !error && (
        <p style={{ color: '#6b7280', fontSize: 13 }}>No stations found nearby.</p>
      )}
    </div>
  )
}

const inputStyle = {
  width: '100%', padding: '6px 10px', border: '1px solid #d1d5db',
  borderRadius: 6, fontSize: 14, background: '#fff',
}
const btnPrimary = {
  padding: '8px 20px', background: '#16a34a', color: '#fff',
  border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer',
}
const btnSecondary = {
  padding: '6px 12px', background: '#f3f4f6', color: '#374151',
  border: '1px solid #d1d5db', borderRadius: 6, cursor: 'pointer', fontSize: 13,
  whiteSpace: 'nowrap',
}
```

- [ ] **Step 5: Create `Stations.jsx`**

Create `fuel-monitor/web/frontend/src/pages/Stations.jsx`:

```jsx
import { useState } from 'react'
import { getStations, getStationHistory } from '../api'
import StationList from '../components/StationList'
import PriceChart from '../components/PriceChart'
import ScoreBadge from '../components/ScoreBadge'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('fuelbot_prefs') || '{}') } catch { return {} }
}

export default function Stations() {
  const prefs = loadPrefs()
  const [stations, setStations] = useState([])
  const [selected, setSelected] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function load() {
    if (!prefs.lat || !prefs.lng) return setError('Set your location on the Dashboard first')
    setLoading(true); setError(null)
    try {
      const data = await getStations(prefs.lat, prefs.lng, prefs.radius ?? 20, prefs.fuel ?? 'E10')
      setStations(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSelect(station) {
    setSelected(station)
    const hist = await getStationHistory(station.station_id, prefs.fuel ?? 'E10', 30)
    const chartData = hist.map((r) => ({
      date: r.observed_at.slice(0, 10),
      price: r.price,
    }))
    setHistory(chartData)
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Nearby Stations</h2>
      <button onClick={load} disabled={loading} style={btnPrimary}>
        {loading ? 'Loading…' : 'Load stations'}
      </button>
      {error && <p style={{ color: '#dc2626', fontSize: 13 }}>{error}</p>}
      <div style={{ marginTop: 16 }}>
        <StationList stations={stations} onSelect={handleSelect} />
      </div>
      {selected && (
        <div style={{ marginTop: 24, padding: 16, border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff' }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>{selected.name}</div>
          <div style={{ marginBottom: 8 }}>
            <ScoreBadge score={selected.score} label={selected.score_label} />
          </div>
          <PriceChart
            data={history}
            lines={[{ key: 'price', name: 'Price (€/L)', xKey: 'date' }]}
          />
        </div>
      )}
    </div>
  )
}

const btnPrimary = {
  padding: '8px 20px', background: '#16a34a', color: '#fff',
  border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer',
}
```

- [ ] **Step 6: Create `History.jsx`**

Create `fuel-monitor/web/frontend/src/pages/History.jsx`:

```jsx
import { useState } from 'react'
import { getPricesSummary } from '../api'
import PriceChart from '../components/PriceChart'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('fuelbot_prefs') || '{}') } catch { return {} }
}

export default function History() {
  const prefs = loadPrefs()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function load() {
    if (!prefs.lat || !prefs.lng) return setError('Set your location on the Dashboard first')
    setLoading(true); setError(null)
    try {
      const data = await getPricesSummary(prefs.lat, prefs.lng, prefs.radius ?? 20, prefs.fuel ?? 'E10')
      setSummary(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const chartData = summary?.daily_avg?.map((d) => ({
    date: d.date,
    'Area median': d.median_price,
  })) ?? []

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Price History</h2>
      <button onClick={load} disabled={loading} style={btnPrimary}>
        {loading ? 'Loading…' : 'Load history'}
      </button>
      {error && <p style={{ color: '#dc2626', fontSize: 13 }}>{error}</p>}
      {summary && (
        <>
          {summary.cheapest_today && (
            <div style={{
              marginTop: 16, padding: 12, background: '#dcfce7',
              borderRadius: 8, fontSize: 14,
            }}>
              <strong>Cheapest today:</strong> {summary.cheapest_today.name} —{' '}
              €{summary.cheapest_today.current_price.toFixed(3)}/L
              ({summary.cheapest_today.distance_km} km)
            </div>
          )}
          <div style={{ marginTop: 20 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 14 }}>
              30-day regional median price
            </div>
            <PriceChart
              data={chartData}
              lines={[{ key: 'Area median', name: 'Area median', xKey: 'date' }]}
              height={260}
            />
          </div>
        </>
      )}
    </div>
  )
}

const btnPrimary = {
  padding: '8px 20px', background: '#16a34a', color: '#fff',
  border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer',
}
```

- [ ] **Step 7: Create `Settings.jsx`**

Create `fuel-monitor/web/frontend/src/pages/Settings.jsx`:

```jsx
import { useState } from 'react'
import PushToggle from '../components/PushToggle'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('fuelbot_prefs') || '{}') } catch { return {} }
}
function savePrefs(p) { localStorage.setItem('fuelbot_prefs', JSON.stringify(p)) }

export default function Settings() {
  const saved = loadPrefs()
  const [petrolTarget, setPetrolTarget] = useState(saved.petrolTarget ?? '')
  const [dieselTarget, setDieselTarget] = useState(saved.dieselTarget ?? '')
  const [radius, setRadius] = useState(saved.radius ?? 20)
  const [saved_, setSaved] = useState(false)

  function handleSave(e) {
    e.preventDefault()
    savePrefs({
      ...loadPrefs(),
      petrolTarget: petrolTarget ? parseFloat(petrolTarget) : null,
      dieselTarget: dieselTarget ? parseFloat(dieselTarget) : null,
      radius: Number(radius),
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const prefs = {
    ...loadPrefs(),
    petrol_target: petrolTarget ? parseFloat(petrolTarget) : null,
    diesel_target: dieselTarget ? parseFloat(dieselTarget) : null,
    radius_km: Number(radius),
    fuel_type: saved.fuel ?? 'E10',
    latitude: saved.lat ?? 0,
    longitude: saved.lng ?? 0,
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Settings</h2>
      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 360 }}>
        <label>
          <div style={labelStyle}>Petrol target price (€/L)</div>
          <input type="number" step="0.001" min="0" max="5"
            value={petrolTarget} onChange={(e) => setPetrolTarget(e.target.value)}
            placeholder="e.g. 1.750" style={inputStyle} />
          <div style={hintStyle}>Alert when petrol ≤ this price</div>
        </label>
        <label>
          <div style={labelStyle}>Diesel target price (€/L)</div>
          <input type="number" step="0.001" min="0" max="5"
            value={dieselTarget} onChange={(e) => setDieselTarget(e.target.value)}
            placeholder="e.g. 1.650" style={inputStyle} />
          <div style={hintStyle}>Alert when diesel ≤ this price</div>
        </label>
        <label>
          <div style={labelStyle}>Search radius (km)</div>
          <input type="range" min={5} max={50} step={5}
            value={radius} onChange={(e) => setRadius(Number(e.target.value))}
            style={{ width: '100%' }} />
          <div style={hintStyle}>{radius} km</div>
        </label>
        <button type="submit" style={btnPrimary}>
          {saved_ ? '✓ Saved' : 'Save preferences'}
        </button>
      </form>
      <hr style={{ margin: '24px 0', borderColor: '#e5e7eb' }} />
      <h3 style={{ marginTop: 0, fontSize: 15 }}>Push notifications</h3>
      <p style={{ fontSize: 13, color: '#6b7280', marginTop: 0 }}>
        Get browser notifications when prices drop to your targets.
        Requires targets to be set above and your location saved on the Dashboard.
      </p>
      <PushToggle prefs={prefs} />
    </div>
  )
}

const inputStyle = {
  width: '100%', padding: '6px 10px', border: '1px solid #d1d5db',
  borderRadius: 6, fontSize: 14, background: '#fff', marginTop: 2,
}
const labelStyle = { fontSize: 13, fontWeight: 600, color: '#374151' }
const hintStyle = { fontSize: 12, color: '#6b7280', marginTop: 2 }
const btnPrimary = {
  padding: '8px 20px', background: '#16a34a', color: '#fff',
  border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer',
}
```

- [ ] **Step 8: Remove Vite scaffold files that are no longer needed**

```bash
rm -f fuel-monitor/web/frontend/src/App.css
rm -f fuel-monitor/web/frontend/src/index.css
rm -f fuel-monitor/web/frontend/src/assets/react.svg
rm -f fuel-monitor/web/frontend/public/vite.svg
```

- [ ] **Step 9: Build and verify**

```bash
cd fuel-monitor/web/frontend
npm run build
ls ../static/index.html
```
Expected: `../static/index.html` exists.

- [ ] **Step 10: Smoke-test full stack**

```bash
# Terminal 1
cd fuel-monitor && python web_app.py &
sleep 3

# Verify API is up
curl -s http://127.0.0.1:5000/api/vapid-public-key
# Expected: {"publicKey": ""}  (empty — VAPID not configured, that's OK)

# Verify SPA is served
curl -s http://127.0.0.1:5000/ | grep -q "FuelBot" && echo "SPA OK" || echo "SPA FAIL"

kill %1
```

- [ ] **Step 11: Commit**

```bash
cd fuel-monitor
git add web/frontend/src/ web/frontend/index.html web/static/
git commit -m "feat(web): complete React SPA — Dashboard, Stations, History, Settings pages"
```

---

### Task 7: VAPID key generation helper and `.env` update

**Files:**
- Create: `web/gen_vapid.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: runnable `python web/gen_vapid.py` that prints VAPID key lines ready to paste into `.env`

- [ ] **Step 1: Create `web/gen_vapid.py`**

Create `fuel-monitor/web/gen_vapid.py`:

```python
#!/usr/bin/env python3
"""
Generate VAPID keys for Web Push.
Run once: python web/gen_vapid.py
Paste the output lines into your .env file.
"""
from py_vapid import Vapid


def main():
    v = Vapid()
    v.generate_keys()
    pub = v.public_key.decode()
    priv = v.private_key.decode()
    print("# Add these to your .env file:")
    print(f"VAPID_PUBLIC_KEY={pub}")
    print(f"VAPID_PRIVATE_KEY={priv}")
    print("VAPID_EMAIL=mailto:you@example.com")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update `.env.example`**

Add to `fuel-monitor/.env.example`:

```
# --- Web Push (VAPID) ---
# Generate with: python web/gen_vapid.py
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_EMAIL=mailto:you@example.com
```

- [ ] **Step 3: Test key generation**

```bash
cd fuel-monitor
python web/gen_vapid.py
```
Expected: prints three `KEY=value` lines with non-empty values.

- [ ] **Step 4: Commit**

```bash
cd fuel-monitor
git add web/gen_vapid.py .env.example
git commit -m "feat(web): VAPID key generator and .env.example update"
```

---

### Task 8: Update README with web app instructions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append web app section to `README.md`**

Add the following after the existing "Running as a background service" section:

```markdown
## Web App

A browser-based interface for viewing fuel prices, nearby stations, price history, and managing Web Push alerts.

### Quick start

**1. Install additional Python dependencies**

```bash
pip install -r requirements.txt
```

**2. Generate VAPID keys (one-time)**

```bash
python web/gen_vapid.py
```

Paste the output into your `.env` file.

**3. Build the frontend**

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

**4. Start the web app**

```bash
python web_app.py
```

Open http://127.0.0.1:5000

### Development mode

```bash
# Terminal 1 — Flask API
python web_app.py

# Terminal 2 — Vite dev server with hot reload
cd web/frontend
npm run dev
# Open http://localhost:5173
```

### Production (gunicorn)

```bash
gunicorn "web.app:create_app()" --bind 127.0.0.1:5000 --workers 2
```

### Web Push flow

1. Open **Settings**, enter petrol/diesel target prices.
2. Click **Enable notifications** — browser asks for permission.
3. The server checks prices every 6 hours. If any nearby station price ≤ your target, a push notification is sent to your browser.
4. Click **Disable notifications** to unsubscribe.
```

- [ ] **Step 2: Commit**

```bash
cd fuel-monitor
git add README.md
git commit -m "docs: add Web App section to README"
```

---

### Task 9: Final validation

- [ ] **Step 1: Run full test suite**

```bash
cd fuel-monitor
pytest -v
```
Expected: all existing tests pass plus the new `tests/web/` tests.

- [ ] **Step 2: Lint check — no import errors**

```bash
cd fuel-monitor
python -c "from web.app import create_app; from web.push import init_schema; print('imports OK')"
```
Expected: `imports OK`

- [ ] **Step 3: Verify build output**

```bash
ls fuel-monitor/web/static/index.html
```
Expected: file exists.

- [ ] **Step 4: Final commit**

```bash
cd fuel-monitor
git add -A
git commit -m "chore: final validation — web app complete"
```
