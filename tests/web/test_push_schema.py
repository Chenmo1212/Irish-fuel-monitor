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
