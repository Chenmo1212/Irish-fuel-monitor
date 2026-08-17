# Fuel Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal Ireland petrol-price monitoring script that fetches prices from Pick A Pump, scores them against 30-day history, forecasts short-term trends, and sends a notification when a meaningfully good price is detected.

**Architecture:** Single Python entry point (`main.py`) orchestrating five focused modules: collector, database, analysis, predictor, decision, notifier. SQLite for local storage. No web framework, no daemon.

**Tech Stack:** Python 3.11+, SQLite (stdlib), requests, pyyaml, python-dotenv, numpy, pandas

**Spec:** `docs/superpowers/specs/2025-07-14-fuel-monitor-design.md`

## Global Constraints

- Python 3.11+ only
- No web framework, no ORM, no sklearn
- All secrets via env vars (`.env` file); never in `config.yaml`
- SQLite database at `data/fuel.db` relative to project root
- All times stored as ISO 8601 UTC strings in SQLite
- requests>=2.32.0, pyyaml>=6.0.2, python-dotenv>=1.0.1, numpy>=2.0.0, pandas>=2.2.0
- `data/` and `.env` must be git-ignored
- Entry point: `python main.py` from the `fuel-monitor/` directory

---

### Task 1: Project Scaffold & Git Init

**Files:**
- Create: `fuel-monitor/.gitignore`
- Create: `fuel-monitor/requirements.txt`
- Create: `fuel-monitor/.env.example`
- Create: `fuel-monitor/config.yaml`
- Create: `fuel-monitor/fuel_monitor/__init__.py`
- Create: `fuel-monitor/tests/__init__.py`
- Create: `fuel-monitor/data/.gitkeep`

**Interfaces:**
- Produces: `load_config(path: str) -> dict` in `fuel_monitor/config.py` (used by all later tasks)

- [ ] **Step 1: Initialise git repo**

```bash
cd fuel-monitor
git init
```

- [ ] **Step 2: Create `.gitignore`**

```
.env
data/*.db
__pycache__/
*.pyc
*.pyo
.pytest_cache/
*.egg-info/
dist/
build/
.venv/
venv/
logs/
*.log
```

- [ ] **Step 3: Create `requirements.txt`**

```
requests>=2.32.0
pyyaml>=6.0.2
python-dotenv>=1.0.1
numpy>=2.0.0
pandas>=2.2.0
pytest>=8.0.0
```

- [ ] **Step 4: Create `.env.example`**

```
# Required: notification API endpoint
NOTIFICATION_API_URL=https://api.chenmo1212.cn/message/entries

# Optional: sent as "Authorization: Bearer <key>" if set
NOTIFICATION_API_KEY=
```

- [ ] **Step 5: Create `config.yaml`**

```yaml
location:
  latitude: 53.27
  longitude: -6.15
  radius_km: 10

fuel:
  type: petrol

vehicle:
  typical_fill_litres: 40

prediction:
  horizons:
    - 1
    - 2
    - 3
    - 7

alert:
  minimum_score: 85
  cooldown_hours: 24
  significant_price_drop_cents: 1.0

notification:
  enabled: true
  source: fuel-monitor
```

- [ ] **Step 6: Create `fuel_monitor/__init__.py`** (empty)

- [ ] **Step 7: Create `fuel_monitor/config.py`**

```python
import yaml

def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)
```

- [ ] **Step 8: Create `tests/__init__.py`** (empty)

- [ ] **Step 9: Create `data/.gitkeep`** (empty file so git tracks the directory)

- [ ] **Step 10: Install dependencies**

```bash
pip install -r requirements.txt
```

- [ ] **Step 11: Verify yaml loads**

```bash
python -c "from fuel_monitor.config import load_config; c = load_config(); print(c['location'])"
```

Expected output: `{'latitude': 53.27, 'longitude': -6.15, 'radius_km': 10}`

- [ ] **Step 12: Initial commit**

```bash
git add .
git commit -m "chore: project scaffold"
```

---

### Task 2: Database Module

**Files:**
- Create: `fuel_monitor/database.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `Database(db_path: str)` — class
  - `db.init_schema()` — creates tables if not exist
  - `db.upsert_station(station: dict)` — inserts or updates station row
  - `db.save_observation(station_id: str, fuel_type: str, price: float, observed_at: datetime) -> bool` — returns True if saved, False if deduped
  - `db.get_price_history(station_id: str, fuel_type: str, since: datetime) -> list[dict]` — returns rows with `price`, `observed_at`
  - `db.get_last_alert(station_id: str) -> dict | None` — most recent alert_log row
  - `db.log_alert(station_id: str, price: float, score: float, sent_at: datetime)`

- [ ] **Step 1: Write failing tests**

Create `tests/test_database.py`:

```python
import os
import pytest
from datetime import datetime, timedelta, timezone
from fuel_monitor.database import Database

@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    d.init_schema()
    return d

def test_init_schema_creates_tables(db):
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "stations" in tables
    assert "price_history" in tables
    assert "alert_log" in tables

def test_upsert_station(db):
    db.upsert_station({
        "station_id": "ie-001",
        "name": "Circle K Dublin",
        "brand": "Circle K",
        "address": "O'Connell St",
        "town": "Dublin",
        "county": "Dublin",
        "latitude": 53.35,
        "longitude": -6.26,
    })
    history = db.get_price_history("ie-001", "E10", datetime(2000, 1, 1, tzinfo=timezone.utc))
    # No prices yet but station exists — no error
    assert history == []

def test_save_observation_new(db):
    db.upsert_station({"station_id": "ie-001", "name": "Test", "brand": None,
                       "address": "", "town": "", "county": "",
                       "latitude": 53.0, "longitude": -6.0})
    now = datetime.now(timezone.utc)
    saved = db.save_observation("ie-001", "E10", 1.799, now)
    assert saved is True

def test_save_observation_dedup_same_price_within_60min(db):
    db.upsert_station({"station_id": "ie-001", "name": "Test", "brand": None,
                       "address": "", "town": "", "county": "",
                       "latitude": 53.0, "longitude": -6.0})
    now = datetime.now(timezone.utc)
    db.save_observation("ie-001", "E10", 1.799, now)
    saved_again = db.save_observation("ie-001", "E10", 1.799, now + timedelta(minutes=30))
    assert saved_again is False

def test_save_observation_different_price_always_saved(db):
    db.upsert_station({"station_id": "ie-001", "name": "Test", "brand": None,
                       "address": "", "town": "", "county": "",
                       "latitude": 53.0, "longitude": -6.0})
    now = datetime.now(timezone.utc)
    db.save_observation("ie-001", "E10", 1.799, now)
    saved = db.save_observation("ie-001", "E10", 1.789, now + timedelta(minutes=30))
    assert saved is True

def test_get_price_history_filters_by_since(db):
    db.upsert_station({"station_id": "ie-001", "name": "Test", "brand": None,
                       "address": "", "town": "", "county": "",
                       "latitude": 53.0, "longitude": -6.0})
    old = datetime.now(timezone.utc) - timedelta(days=40)
    recent = datetime.now(timezone.utc) - timedelta(days=5)
    db.save_observation("ie-001", "E10", 1.800, old)
    db.save_observation("ie-001", "E10", 1.750, recent)
    since = datetime.now(timezone.utc) - timedelta(days=30)
    rows = db.get_price_history("ie-001", "E10", since)
    assert len(rows) == 1
    assert abs(rows[0]["price"] - 1.750) < 0.001

def test_log_alert_and_get_last_alert(db):
    now = datetime.now(timezone.utc)
    db.log_alert("ie-001", 1.799, 92.0, now)
    last = db.get_last_alert("ie-001")
    assert last is not None
    assert abs(last["price"] - 1.799) < 0.001
    assert abs(last["score"] - 92.0) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_database.py -v
```

Expected: ImportError or AttributeError — `Database` not yet defined.

- [ ] **Step 3: Implement `fuel_monitor/database.py`**

```python
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
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS stations (
                    station_id  TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    brand       TEXT,
                    address     TEXT,
                    town        TEXT,
                    county      TEXT,
                    latitude    REAL NOT NULL,
                    longitude   REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_id  TEXT NOT NULL REFERENCES stations(station_id),
                    fuel_type   TEXT NOT NULL,
                    price       REAL NOT NULL,
                    observed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_price_history_station_fuel
                    ON price_history(station_id, fuel_type, observed_at);

                CREATE TABLE IF NOT EXISTS alert_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_id  TEXT NOT NULL,
                    price       REAL NOT NULL,
                    score       REAL NOT NULL,
                    sent_at     TEXT NOT NULL
                );
            """)

    def upsert_station(self, station: dict) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO stations (station_id, name, brand, address, town, county, latitude, longitude)
                VALUES (:station_id, :name, :brand, :address, :town, :county, :latitude, :longitude)
                ON CONFLICT(station_id) DO UPDATE SET
                    name=excluded.name, brand=excluded.brand, address=excluded.address,
                    town=excluded.town, county=excluded.county,
                    latitude=excluded.latitude, longitude=excluded.longitude
            """, station)

    def save_observation(self, station_id: str, fuel_type: str, price: float, observed_at: datetime) -> bool:
        cutoff = (observed_at - timedelta(minutes=60)).isoformat()
        with self._connect() as conn:
            existing = conn.execute("""
                SELECT 1 FROM price_history
                WHERE station_id=? AND fuel_type=? AND price=? AND observed_at >= ?
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_database.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fuel_monitor/database.py tests/test_database.py fuel_monitor/config.py
git commit -m "feat: database module with schema and dedup logic"
```

---

### Task 3: Collector Module

**Files:**
- Create: `fuel_monitor/collector.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure HTTP + data transformation)
- Produces:
  - `collect(lat: float, lng: float, radius_km: float) -> tuple[list[dict], list[dict]]`
    - Returns `(stations, observations)` where:
    - `station = {"station_id", "name", "brand", "address", "town", "county", "latitude", "longitude"}`
    - `observation = {"station_id", "fuel_type", "price", "observed_at"}` (`observed_at` is `datetime` UTC)

- [ ] **Step 1: Create `fuel_monitor/collector.py`**

No automated unit test for the live API — the collector is tested manually. We will write an integration smoke-test at the end of this task.

```python
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.pickapump.com/v1/stations/nearby"

FUEL_FIELD_MAP = [
    ("petrol",      "E10"),
    ("diesel",      "B7"),
    ("petrolplus",  "E5_98"),
    ("dieselplus",  "B7_PREMIUM"),
    ("hvo",         "HVO"),
]

HEADERS = {
    "Accept": "application/json",
    "Origin": "https://pickapump.com",
    "User-Agent": "Mozilla/5.0 (compatible; fuel-monitor/1.0)",
}


def collect(lat: float, lng: float, radius_km: float) -> tuple[list[dict], list[dict]]:
    """
    Fetch nearby fuel stations from Pick A Pump.
    Returns (stations, observations) — empty lists on any error.
    """
    url = f"{BASE_URL}?lat={lat}&lng={lng}&radius={radius_km}"
    observed_at = datetime.now(timezone.utc)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 429:
            logger.warning("Pick A Pump rate limited (429). Retrying in 5s...")
            import time; time.sleep(5)
            resp = requests.get(url, headers=HEADERS, timeout=15)
        if not resp.ok:
            logger.error("Pick A Pump returned HTTP %s", resp.status_code)
            return [], []
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("Pick A Pump request failed: %s", exc)
        return [], []
    except ValueError as exc:
        logger.error("Pick A Pump response not valid JSON: %s", exc)
        return [], []

    stations: list[dict] = []
    observations: list[dict] = []
    seen_station_ids: set[str] = set()

    for s in data:
        if not isinstance(s, dict):
            continue
        if s.get("country") != "ROI":
            continue

        coords = s.get("coords") or {}
        lat_s = coords.get("lat")
        lng_s = coords.get("lng")
        if not lat_s or not lng_s:
            continue
        # Ireland bounding box sanity check
        if not (51.3 <= lat_s <= 55.5 and -10.6 <= lng_s <= -5.4):
            continue

        station_id = str(s.get("id", "")).strip()
        if not station_id:
            continue

        if station_id not in seen_station_ids:
            seen_station_ids.add(station_id)
            stations.append({
                "station_id": station_id,
                "name": (s.get("stationName") or f"Station {station_id}").strip(),
                "brand": (s.get("brand") or "").strip() or None,
                "address": (s.get("address") or "").strip(),
                "town": (s.get("town") or "").strip(),
                "county": (s.get("county") or "").strip(),
                "latitude": lat_s,
                "longitude": lng_s,
            })

        prices = s.get("prices") or {}
        for field, fuel_type in FUEL_FIELD_MAP:
            val = prices.get(field)
            if not isinstance(val, (int, float)):
                continue
            if val <= 0 or val > 500:   # cents; max ~€5/L
                continue
            price_eur = val / 100.0
            observations.append({
                "station_id": station_id,
                "fuel_type": fuel_type,
                "price": price_eur,
                "observed_at": observed_at,
            })

    logger.info("Collected %d stations, %d price observations", len(stations), len(observations))
    return stations, observations
```

- [ ] **Step 2: Smoke-test the collector manually**

```bash
python -c "
from fuel_monitor.collector import collect
stations, obs = collect(53.27, -6.15, 5)
print(f'Stations: {len(stations)}, Observations: {len(obs)}')
if stations:
    print('First station:', stations[0])
if obs:
    petrol = [o for o in obs if o['fuel_type'] == 'E10']
    print(f'Petrol prices: {[o[\"price\"] for o in petrol[:5]]}')
"
```

Expected: at least a few stations printed (requires internet access).

- [ ] **Step 3: Commit**

```bash
git add fuel_monitor/collector.py
git commit -m "feat: Pick A Pump collector"
```

---

### Task 4: Analysis Module

**Files:**
- Create: `fuel_monitor/analysis.py`
- Test: `tests/test_analysis.py`

**Interfaces:**
- Consumes: price history rows `list[dict]` with `"price"` (float) and `"observed_at"` (str ISO 8601) keys
- Produces:
  - `analyse(current_price: float, history: list[dict]) -> dict` — returns analysis dict with keys:
    - `"obs_count"` (int), `"avg_7d"` (float|None), `"avg_30d"` (float|None), `"low_30d"` (float|None), `"percentile_30d"` (float|None), `"score"` (float|None), `"score_label"` (str|None), `"score_reasons"` (list[str])
  - `haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float`

- [ ] **Step 1: Write failing tests**

Create `tests/test_analysis.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone
from fuel_monitor.analysis import analyse, haversine_km


def make_history(prices_and_days_ago: list[tuple[float, int]]) -> list[dict]:
    """Helper: creates history rows from (price, days_ago) pairs."""
    rows = []
    now = datetime.now(timezone.utc)
    for price, days_ago in prices_and_days_ago:
        rows.append({
            "price": price,
            "observed_at": (now - timedelta(days=days_ago)).isoformat(),
        })
    return rows


def test_analyse_returns_none_for_insufficient_data():
    result = analyse(1.750, [])
    assert result["score"] is None
    assert result["avg_7d"] is None
    assert result["avg_30d"] is None

def test_analyse_returns_none_score_with_only_one_observation():
    history = make_history([(1.800, 1)])
    result = analyse(1.750, history)
    # 1 observation is not enough for percentile
    assert result["score"] is None

def test_analyse_computes_30d_percentile_correctly():
    # 10 historical prices: 1.700, 1.710, ..., 1.790
    history = make_history([(1.700 + i * 0.010, i + 1) for i in range(10)])
    current = 1.710  # second cheapest — should be around 10th percentile
    result = analyse(current, history)
    assert result["percentile_30d"] is not None
    # current is cheaper than ~90% of history (10 obs, only 1.700 is cheaper)
    assert result["percentile_30d"] < 20

def test_analyse_7d_average_only_includes_last_7_days():
    history = make_history([
        (1.800, 2),   # within 7 days
        (1.810, 5),   # within 7 days
        (1.900, 15),  # outside 7 days — should not affect 7d avg
    ])
    result = analyse(1.750, history)
    assert result["avg_7d"] is not None
    assert abs(result["avg_7d"] - 1.805) < 0.001

def test_analyse_score_is_high_for_cheap_price():
    # history of 10 prices all higher than current
    history = make_history([(1.800 + i * 0.005, i + 1) for i in range(10)])
    current = 1.750  # cheaper than all history
    result = analyse(current, history)
    assert result["score"] is not None
    assert result["score"] >= 75  # should be very good

def test_analyse_score_is_low_for_expensive_price():
    # history of 10 prices all lower than current
    history = make_history([(1.600 + i * 0.005, i + 1) for i in range(10)])
    current = 1.750  # more expensive than all history
    result = analyse(current, history)
    assert result["score"] is not None
    assert result["score"] <= 25  # should be expensive

def test_analyse_score_reasons_are_non_empty_when_score_available():
    history = make_history([(1.800 + i * 0.005, i + 1) for i in range(10)])
    result = analyse(1.750, history)
    if result["score"] is not None:
        assert len(result["score_reasons"]) > 0

def test_haversine_km_dublin_to_cork():
    # Dublin ~53.33, -6.25 / Cork ~51.90, -8.47 — roughly 220km
    dist = haversine_km(53.33, -6.25, 51.90, -8.47)
    assert 200 < dist < 240

def test_haversine_km_same_point():
    assert haversine_km(53.33, -6.25, 53.33, -6.25) == pytest.approx(0.0, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_analysis.py -v
```

Expected: ImportError — `analysis` module not yet defined.

- [ ] **Step 3: Implement `fuel_monitor/analysis.py`**

```python
import math
from datetime import datetime, timedelta, timezone


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def analyse(current_price: float, history: list[dict]) -> dict:
    """
    Compute analysis statistics for a single station + fuel type.

    Args:
        current_price: current price in EUR/L
        history: list of {"price": float, "observed_at": str ISO 8601} dicts
                 covering at least the last 30 days (caller's responsibility)

    Returns:
        dict with keys: obs_count, avg_7d, avg_30d, low_30d,
                        percentile_30d, score, score_label, score_reasons
    """
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    prices_30d = [r["price"] for r in history if _parse_dt(r["observed_at"]) >= cutoff_30d]
    prices_7d  = [r["price"] for r in history if _parse_dt(r["observed_at"]) >= cutoff_7d]

    obs_count = len(prices_30d)
    avg_7d    = (sum(prices_7d) / len(prices_7d))   if len(prices_7d) >= 2  else None
    avg_30d   = (sum(prices_30d) / len(prices_30d)) if len(prices_30d) >= 2 else None
    low_30d   = min(prices_30d) if prices_30d else None

    # Percentile: % of 30d observations >= current price
    # Low percentile = cheap price (current is cheaper than most history)
    percentile_30d: float | None = None
    if len(prices_30d) >= 3:
        count_above_or_equal = sum(1 for p in prices_30d if p >= current_price)
        percentile_30d = (1 - count_above_or_equal / len(prices_30d)) * 100

    score: float | None = None
    score_label: str | None = None
    score_reasons: list[str] = []

    if percentile_30d is not None and avg_7d is not None and avg_30d is not None:
        # Percentile component: low percentile → high score
        pct_component = 100 - percentile_30d

        # Below-7d-avg component (normalised 0–100, clamped)
        diff_7d = avg_7d - current_price  # positive = cheaper than avg
        below_7d = min(max((diff_7d / avg_7d) * 100 * 10, 0), 100)

        # Below-30d-avg component
        diff_30d = avg_30d - current_price
        below_30d = min(max((diff_30d / avg_30d) * 100 * 10, 0), 100)

        score = 0.50 * pct_component + 0.25 * below_7d + 0.25 * below_30d
        score = min(max(score, 0), 100)

        # Label
        if score >= 90:
            score_label = "Excellent"
        elif score >= 75:
            score_label = "Very good"
        elif score >= 50:
            score_label = "Normal"
        elif score >= 25:
            score_label = "Expensive"
        else:
            score_label = "Very expensive"

        # Human-readable reasons
        if percentile_30d is not None:
            pct_rank = round(percentile_30d)
            score_reasons.append(
                f"Current price is in the cheapest {100 - pct_rank}% of the last 30 days"
                if pct_rank < 50
                else f"Current price is in the most expensive {pct_rank}% of the last 30 days"
            )
        if avg_7d is not None:
            diff_c = (avg_7d - current_price) * 100
            if abs(diff_c) >= 0.1:
                direction = "below" if diff_c > 0 else "above"
                score_reasons.append(f"{abs(diff_c):.1f}c/L {direction} the 7-day average")
        if low_30d is not None:
            diff_low_c = (current_price - low_30d) * 100
            score_reasons.append(f"{diff_low_c:.1f}c/L above the 30-day low")

    return {
        "obs_count": obs_count,
        "avg_7d": avg_7d,
        "avg_30d": avg_30d,
        "low_30d": low_30d,
        "percentile_30d": percentile_30d,
        "score": round(score, 1) if score is not None else None,
        "score_label": score_label,
        "score_reasons": score_reasons,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_analysis.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fuel_monitor/analysis.py tests/test_analysis.py
git commit -m "feat: analysis module — percentile, score, haversine"
```

---

### Task 5: Predictor Module

**Files:**
- Create: `fuel_monitor/predictor.py`
- Test: `tests/test_predictor.py`

**Interfaces:**
- Consumes: price history rows `list[dict]` with `"price"` (float) and `"observed_at"` (str ISO 8601) keys
- Produces:
  - `forecast(history: list[dict], horizons: list[int]) -> list[dict] | None`
    - Returns `None` if insufficient data (< 3 days of observations)
    - Returns list of `{"horizon_days": int, "expected": float, "low": float, "high": float}` dicts

- [ ] **Step 1: Write failing tests**

Create `tests/test_predictor.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone
from fuel_monitor.predictor import forecast


def make_history(prices_and_days_ago: list[tuple[float, float]]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {
            "price": price,
            "observed_at": (now - timedelta(days=days_ago)).isoformat(),
        }
        for price, days_ago in prices_and_days_ago
    ]


def test_forecast_returns_none_for_insufficient_data():
    history = make_history([(1.800, 1), (1.790, 0.5)])  # all within 1 day
    result = forecast(history, [1, 3, 7])
    assert result is None


def test_forecast_returns_correct_number_of_horizons():
    # 10 daily observations spanning 10 days
    history = make_history([(1.800 - i * 0.002, i) for i in range(10)])
    result = forecast(history, [1, 3, 7])
    assert result is not None
    assert len(result) == 3
    assert [r["horizon_days"] for r in result] == [1, 3, 7]


def test_forecast_uncertainty_grows_with_horizon():
    history = make_history([(1.800 - i * 0.002, i) for i in range(14)])
    result = forecast(history, [1, 3, 7])
    assert result is not None
    ranges = [r["high"] - r["low"] for r in result]
    # uncertainty should grow (or at least not shrink) as horizon increases
    assert ranges[0] <= ranges[1] <= ranges[2]


def test_forecast_expected_is_between_low_and_high():
    history = make_history([(1.800 - i * 0.001, i) for i in range(14)])
    result = forecast(history, [1, 2, 3, 7])
    assert result is not None
    for r in result:
        assert r["low"] <= r["expected"] <= r["high"]


def test_forecast_detects_falling_trend():
    # Prices falling by 0.5c per day for 14 days
    history = make_history([(1.800 - i * 0.005, i) for i in range(14)])
    result = forecast(history, [3])
    assert result is not None
    # 3-day forecast should be lower than current price
    current = 1.800 - 0 * 0.005  # most recent
    assert result[0]["expected"] < current


def test_forecast_detects_rising_trend():
    # Prices rising by 0.5c per day for 14 days
    history = make_history([(1.700 + i * 0.005, 14 - i) for i in range(14)])
    result = forecast(history, [3])
    assert result is not None
    current = 1.700 + 13 * 0.005  # most recent price
    assert result[0]["expected"] > current
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_predictor.py -v
```

Expected: ImportError — `predictor` not yet defined.

- [ ] **Step 3: Implement `fuel_monitor/predictor.py`**

```python
import math
from datetime import datetime, timedelta, timezone
import numpy as np


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def forecast(history: list[dict], horizons: list[int]) -> list[dict] | None:
    """
    Forecast fuel prices for given horizon days.

    Returns None if insufficient history (< 3 days span).
    Otherwise returns list of {"horizon_days", "expected", "low", "high"}.
    """
    if not history:
        return None

    now = datetime.now(timezone.utc)

    # Sort by time ascending
    sorted_history = sorted(history, key=lambda r: _parse_dt(r["observed_at"]))

    oldest = _parse_dt(sorted_history[0]["observed_at"])
    newest = _parse_dt(sorted_history[-1]["observed_at"])
    span_days = (newest - oldest).total_seconds() / 86400

    if span_days < 3:
        return None

    # Resample to daily medians
    # Group observations by day offset from now
    day_buckets: dict[int, list[float]] = {}
    for row in sorted_history:
        dt = _parse_dt(row["observed_at"])
        days_ago = (now - dt).total_seconds() / 86400
        bucket = int(days_ago)  # floor to day
        day_buckets.setdefault(bucket, []).append(row["price"])

    # Sort buckets oldest-first (highest days_ago first)
    sorted_days = sorted(day_buckets.keys(), reverse=True)
    daily_medians = [float(np.median(day_buckets[d])) for d in sorted_days]

    if len(daily_medians) < 2:
        return None

    # Compute EMA
    span = min(7, len(daily_medians))
    alpha = 2 / (span + 1)
    ema = daily_medians[0]
    for price in daily_medians[1:]:
        ema = alpha * price + (1 - alpha) * ema
    last_ema = ema

    # Linear regression slope over last 7 daily medians
    lookback = min(7, len(daily_medians))
    recent = daily_medians[-lookback:]
    x = np.arange(len(recent), dtype=float)
    slope = float(np.polyfit(x, recent, 1)[0])

    # Uncertainty: std of residuals from linear fit, minimum 0.005 €/L
    fitted = np.polyval(np.polyfit(x, recent, 1), x)
    residuals = np.array(recent) - fitted
    base_std = max(float(np.std(residuals)), 0.005)

    results = []
    for h in horizons:
        expected = last_ema + slope * h
        uncertainty = base_std * math.sqrt(h)
        results.append({
            "horizon_days": h,
            "expected": round(expected, 4),
            "low": round(expected - uncertainty, 4),
            "high": round(expected + uncertainty, 4),
        })

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_predictor.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fuel_monitor/predictor.py tests/test_predictor.py
git commit -m "feat: predictor module — EMA + linear trend forecast"
```

---

### Task 6: Decision Module

**Files:**
- Create: `fuel_monitor/decision.py`
- Test: `tests/test_decision.py`

**Interfaces:**
- Consumes:
  - `current_price: float`
  - `forecasts: list[dict] | None` — from `predictor.forecast()`; each dict has `horizon_days`, `expected`, `low`, `high`
  - `typical_fill_litres: float`
  - `significant_price_drop_cents: float` — from config
- Produces:
  - `decide(current_price, forecasts, typical_fill_litres, significant_price_drop_cents) -> dict`
    - Returns dict with keys: `"action"` (str: "FILL NOW"|"WAIT"), `"reason"` (str), `"predicted_saving_per_litre"` (float|None), `"predicted_total_saving"` (float|None), `"forecast_used"` (dict|None)

- [ ] **Step 1: Write failing tests**

Create `tests/test_decision.py`:

```python
import pytest
from fuel_monitor.decision import decide


def test_decide_fill_now_when_no_forecast():
    result = decide(1.750, None, 40, 1.0)
    assert result["action"] == "FILL NOW"
    assert result["predicted_saving_per_litre"] is None
    assert result["predicted_total_saving"] is None


def test_decide_fill_now_when_saving_is_small():
    # Predicted price only 0.3c/L cheaper (below 1.0 threshold)
    forecasts = [
        {"horizon_days": 1, "expected": 1.748, "low": 1.740, "high": 1.756},
        {"horizon_days": 3, "expected": 1.747, "low": 1.739, "high": 1.755},
        {"horizon_days": 7, "expected": 1.745, "low": 1.737, "high": 1.753},
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    assert result["action"] == "FILL NOW"


def test_decide_wait_when_saving_is_significant():
    # Predicted price 2c/L cheaper in 3 days (above 1.0 threshold)
    forecasts = [
        {"horizon_days": 1, "expected": 1.740, "low": 1.730, "high": 1.750},
        {"horizon_days": 3, "expected": 1.730, "low": 1.720, "high": 1.740},
        {"horizon_days": 7, "expected": 1.720, "low": 1.710, "high": 1.730},
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    assert result["action"] == "WAIT"
    assert result["predicted_saving_per_litre"] is not None
    assert result["predicted_saving_per_litre"] > 0


def test_decide_total_saving_calculation():
    forecasts = [
        {"horizon_days": 1, "expected": 1.740, "low": 1.730, "high": 1.750},
        {"horizon_days": 3, "expected": 1.720, "low": 1.710, "high": 1.730},  # 3c/L cheaper
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    # saving = 0.030 EUR/L × 40L = 1.20 EUR
    if result["action"] == "WAIT":
        assert result["predicted_total_saving"] is not None
        assert abs(result["predicted_total_saving"] - 1.20) < 0.05


def test_decide_uses_3day_forecast_as_primary():
    # 1-day forecast is slightly cheaper, 3-day is more expensive
    forecasts = [
        {"horizon_days": 1, "expected": 1.730, "low": 1.720, "high": 1.740},  # 2c cheaper
        {"horizon_days": 3, "expected": 1.755, "low": 1.745, "high": 1.765},  # 0.5c more expensive
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    # 3-day forecast shows no saving → FILL NOW
    assert result["action"] == "FILL NOW"
    assert result["forecast_used"]["horizon_days"] == 3


def test_decide_falls_back_to_1day_if_no_3day_forecast():
    forecasts = [
        {"horizon_days": 1, "expected": 1.720, "low": 1.710, "high": 1.730},  # 3c/L cheaper
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    assert result["forecast_used"]["horizon_days"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_decision.py -v
```

Expected: ImportError — `decision` not yet defined.

- [ ] **Step 3: Implement `fuel_monitor/decision.py`**

```python
def decide(
    current_price: float,
    forecasts: list[dict] | None,
    typical_fill_litres: float,
    significant_price_drop_cents: float,
) -> dict:
    """
    Determine whether to fill up now or wait.

    Args:
        current_price: current price EUR/L
        forecasts: output of predictor.forecast(), or None
        typical_fill_litres: vehicle tank fill size
        significant_price_drop_cents: minimum per-litre saving in cents to recommend waiting

    Returns:
        dict with action, reason, predicted_saving_per_litre,
        predicted_total_saving, forecast_used
    """
    threshold_eur = significant_price_drop_cents / 100.0

    if not forecasts:
        return {
            "action": "FILL NOW",
            "reason": "No forecast available — good price now, fill up",
            "predicted_saving_per_litre": None,
            "predicted_total_saving": None,
            "forecast_used": None,
        }

    # Prefer 3-day forecast; fall back to shortest available
    forecast_used = next((f for f in forecasts if f["horizon_days"] == 3), None)
    if forecast_used is None:
        forecast_used = min(forecasts, key=lambda f: f["horizon_days"])

    saving_per_litre = current_price - forecast_used["expected"]
    total_saving = saving_per_litre * typical_fill_litres

    if saving_per_litre > threshold_eur:
        return {
            "action": "WAIT",
            "reason": (
                f"Price expected to drop by {saving_per_litre * 100:.1f}c/L "
                f"in ~{forecast_used['horizon_days']} days "
                f"(saving ~€{total_saving:.2f} on {typical_fill_litres:.0f}L)"
            ),
            "predicted_saving_per_litre": round(saving_per_litre, 4),
            "predicted_total_saving": round(total_saving, 2),
            "forecast_used": forecast_used,
        }
    else:
        return {
            "action": "FILL NOW",
            "reason": "Predicted saving too small to justify waiting",
            "predicted_saving_per_litre": round(saving_per_litre, 4),
            "predicted_total_saving": round(total_saving, 2),
            "forecast_used": forecast_used,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_decision.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fuel_monitor/decision.py tests/test_decision.py
git commit -m "feat: decision module — fill now vs wait logic"
```

---

### Task 7: Notifier Module

**Files:**
- Create: `fuel_monitor/notifier.py`

**Interfaces:**
- Consumes:
  - `title: str`, `body: str`, `priority: str` ("high"|"medium"|"low")
  - Env vars: `NOTIFICATION_API_URL`, `NOTIFICATION_API_KEY` (optional)
  - Config: `notification.source` (str), `notification.enabled` (bool)
- Produces:
  - `send_notification(title: str, body: str, priority: str, source: str, enabled: bool) -> bool`
    - Returns True if sent successfully, False otherwise (never raises)
  - `format_message(station: dict, analysis: dict, forecasts: list[dict] | None, recommendation: dict, typical_fill_litres: float) -> tuple[str, str]`
    - Returns `(title, body)` for the notification

No automated test (requires live API). Verified by manual smoke test.

- [ ] **Step 1: Create `fuel_monitor/notifier.py`**

```python
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
```

- [ ] **Step 2: Smoke-test the notifier format locally**

```bash
python -c "
from fuel_monitor.notifier import format_message
station = {'name': 'Circle K Sandyford', 'distance_km': 3.2, 'current_price': 1.689}
analysis = {
    'current_price': 1.689, 'score': 92, 'score_label': 'Excellent',
    'percentile_30d': 8, 'avg_7d': 1.713, 'avg_30d': 1.724,
    'low_30d': 1.681,
    'score_reasons': ['Current price is in the cheapest 8% of the last 30 days', '2.4c/L below the 7-day average']
}
forecasts = [
    {'horizon_days': 1, 'expected': 1.682, 'low': 1.674, 'high': 1.690},
    {'horizon_days': 3, 'expected': 1.678, 'low': 1.668, 'high': 1.688},
]
rec = {'action': 'FILL NOW', 'reason': 'Predicted saving too small to justify waiting', 'predicted_total_saving': 0.44}
title, body = format_message(station, analysis, forecasts, rec, 40)
print(title)
print()
print(body)
"
```

Expected: well-formatted notification message printed to stdout.

- [ ] **Step 3: Commit**

```bash
git add fuel_monitor/notifier.py
git commit -m "feat: notifier module — format and send via personal API"
```

---

### Task 8: Main Orchestrator

**Files:**
- Create: `main.py`

**Interfaces:**
- Consumes: all five modules + config + database
- Produces: coordinated run, stdout summary, notification if appropriate

- [ ] **Step 1: Create `main.py`**

```python
#!/usr/bin/env python3
"""
Fuel Monitor — entry point.
Run: python main.py
"""
import logging
import os
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
    since_7d = datetime.now(timezone.utc) - timedelta(days=7)

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
    s = best["station"]
    a = best["analysis"]
    print()
    print("=" * 50)
    print("Best nearby station:")
    print(f"  {s['name']}  ({s['distance_km']:.1f} km)")
    print(f"  Current:  €{s['current_price']:.3f}/L")
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
        for f in forecasts:
            h = f["horizon_days"]
            label = "Tomorrow" if h == 1 else f"{h} days "
            print(f"  {label}: €{f['expected']:.3f}  (€{f['low']:.3f}–€{f['high']:.3f})")
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
    notification_sent = False

    if score is not None and score >= min_score:
        last_alert = db.get_last_alert(s["station_id"])
        should_send = True

        if last_alert:
            last_sent = datetime.fromisoformat(last_alert["sent_at"])
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            hours_since = (datetime.now(timezone.utc) - last_sent).total_seconds() / 3600
            price_improvement = (last_alert["price"] - s["current_price"]) * 100

            if hours_since < cooldown_hours and price_improvement < sig_drop_cents:
                should_send = False
                print(f"\nNotification: suppressed (cooldown, {hours_since:.1f}h since last alert)")

        if should_send:
            title, body = format_message(s, a, forecasts, recommendation, typical_fill)
            priority = "high" if recommendation["action"] == "FILL NOW" else "medium"
            sent = send_notification(title, body, priority, notif_source, notif_enabled)
            if sent:
                db.log_alert(s["station_id"], s["current_price"], score, datetime.now(timezone.utc))
                notification_sent = True
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
```

- [ ] **Step 2: Run end-to-end smoke test**

```bash
python main.py
```

Expected: fetches real prices, prints summary, suppresses notification (score likely below threshold or no history). No unhandled exceptions.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main orchestrator — end-to-end run"
```

---

### Task 9: Run Full Test Suite & Final Wiring

**Files:**
- Modify: `fuel_monitor/notifier.py` — verify `format_message` receives `current_price` from analysis dict correctly

**Interfaces:**
- Consumes: all previous tasks
- Produces: green test suite, working `python main.py`

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass across `test_database.py`, `test_analysis.py`, `test_predictor.py`, `test_decision.py`.

- [ ] **Step 2: Add scheduling note to README**

Create `README.md`:

```markdown
# Fuel Monitor

Personal Ireland petrol-price monitor. Fetches prices from Pick A Pump,
scores them against 30-day history, and sends a notification when a
meaningfully good price is detected.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your NOTIFICATION_API_URL
# Edit config.yaml with your location
```

## Run

```bash
python main.py
```

## Schedule (cron — every 6 hours)

```cron
0 */6 * * * cd /path/to/fuel-monitor && python main.py >> logs/fuel.log 2>&1
```

## Configuration

Edit `config.yaml`. See comments for all options.
Secrets go in `.env` only — never in `config.yaml`.

## Data

SQLite database at `data/fuel.db`. Accumulates price history over time.
Predictions improve as more history is collected (useful after ~7 days).
```

- [ ] **Step 3: Final commit**

```bash
git add README.md
git commit -m "docs: add README with setup and scheduling instructions"
git tag v0.1.0
```
