import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class Database:
    def __init__(self, db_path: str = "data/fuel.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self) -> None:
        # Use individual execute() calls so PRAGMA foreign_keys stays active
        # (executescript issues an implicit COMMIT and resets session pragmas)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stations (
                    station_id  TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    brand       TEXT,
                    address     TEXT,
                    town        TEXT,
                    county      TEXT,
                    latitude    REAL NOT NULL,
                    longitude   REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_id  TEXT NOT NULL REFERENCES stations(station_id),
                    fuel_type   TEXT NOT NULL,
                    price       REAL NOT NULL,
                    observed_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_history_station_fuel
                    ON price_history(station_id, fuel_type, observed_at)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_id  TEXT NOT NULL,
                    price       REAL NOT NULL,
                    score       REAL NOT NULL,
                    sent_at     TEXT NOT NULL
                )
            """)

    def upsert_station(self, station: dict) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO stations (station_id, name, brand, address, town, county, latitude, longitude)
                VALUES (:station_id, :name, :brand, :address, :town, :county, :latitude, :longitude)
            """, station)

    def save_observation(self, station_id: str, fuel_type: str, price: float, observed_at: datetime) -> bool:
        cutoff = (observed_at - timedelta(minutes=60)).isoformat()
        with self._connect() as conn:
            existing = conn.execute("""
                SELECT 1 FROM price_history
                WHERE station_id=? AND fuel_type=? AND ABS(price - ?) < 0.0001 AND observed_at > ?
                LIMIT 1
            """, (station_id, fuel_type, price, cutoff)).fetchone()
            if existing:
                return False
            conn.execute("""
                INSERT INTO price_history (station_id, fuel_type, price, observed_at)
                VALUES (?, ?, ?, ?)
            """, (station_id, fuel_type, price, observed_at.isoformat()))
            return True

    def get_price_history(self, station_id: str, fuel_type: str, since: datetime) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT price, observed_at FROM price_history
                WHERE station_id=? AND fuel_type=? AND observed_at >= ?
                ORDER BY observed_at ASC
            """, (station_id, fuel_type, since.isoformat())).fetchall()
            return [dict(r) for r in rows]

    def get_last_alert(self, station_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT station_id, price, score, sent_at FROM alert_log
                WHERE station_id=? ORDER BY sent_at DESC LIMIT 1
            """, (station_id,)).fetchone()
            return dict(row) if row else None

    def log_alert(self, station_id: str, price: float, score: float, sent_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO alert_log (station_id, price, score, sent_at)
                VALUES (?, ?, ?, ?)
            """, (station_id, price, score, sent_at.isoformat()))

    # ------------------------------------------------------------------
    # Multi-user support
    # ------------------------------------------------------------------

    def init_users_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id       TEXT PRIMARY KEY,
                    fuel_type     TEXT,
                    latitude      REAL,
                    longitude     REAL,
                    radius_km     REAL DEFAULT 20,
                    registered_at TEXT NOT NULL,
                    last_seen_at  TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_alert_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id     TEXT NOT NULL,
                    station_id  TEXT NOT NULL,
                    price       REAL NOT NULL,
                    score       REAL NOT NULL,
                    sent_at     TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_alert_log_chat_station
                    ON user_alert_log(chat_id, station_id, sent_at)
            """)

    def upsert_user(
        self,
        chat_id: str,
        fuel_type: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT registered_at FROM users WHERE chat_id=?", (chat_id,)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE users SET fuel_type=?, latitude=?, longitude=?, last_seen_at=?
                    WHERE chat_id=?
                """, (fuel_type, latitude, longitude, now, chat_id))
            else:
                conn.execute("""
                    INSERT INTO users (chat_id, fuel_type, latitude, longitude, radius_km, registered_at, last_seen_at)
                    VALUES (?, ?, ?, ?, 20, ?, ?)
                """, (chat_id, fuel_type, latitude, longitude, now, now))

    def get_user(self, chat_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE chat_id=?", (chat_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_users(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
            return [dict(r) for r in rows]

    def delete_user(self, chat_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id,))

    def touch_user(self, chat_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET last_seen_at=? WHERE chat_id=?", (now, chat_id)
            )

    def log_user_alert(
        self,
        chat_id: str,
        station_id: str,
        price: float,
        score: float,
        sent_at: datetime,
    ) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO user_alert_log (chat_id, station_id, price, score, sent_at)
                VALUES (?, ?, ?, ?, ?)
            """, (chat_id, station_id, price, score, sent_at.isoformat()))

    def get_last_user_alert(self, chat_id: str, station_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT chat_id, station_id, price, score, sent_at FROM user_alert_log
                WHERE chat_id=? AND station_id=?
                ORDER BY sent_at DESC LIMIT 1
            """, (chat_id, station_id)).fetchone()
            return dict(row) if row else None
