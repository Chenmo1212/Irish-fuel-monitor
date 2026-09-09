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
                r["current_price"],
                0 if r["score"] is not None else 1,
                -(r["score"] or 0),
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
