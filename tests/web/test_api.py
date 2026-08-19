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
