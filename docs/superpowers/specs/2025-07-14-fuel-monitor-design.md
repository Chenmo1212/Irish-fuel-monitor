# Fuel Monitor — Design Spec

**Date:** 2025-07-14
**Status:** Approved

---

## 1. Goal

A lightweight personal Python script that periodically fetches Ireland petrol prices near a configured location, accumulates historical observations in a local SQLite database, scores the current price against recent history, produces a short-term price forecast, and sends a notification when the price is meaningfully attractive.

Single entry point: `python main.py`. Designed to be scheduled via cron/systemd/GitHub Actions.

---

## 2. Project Structure

```
fuel-monitor/
├── main.py                  # Entry point — orchestrates all modules
├── config.yaml              # User-facing configuration (no secrets)
├── .env.example             # Documents required env vars
├── requirements.txt
├── fuel_monitor/
│   ├── collector.py         # Pick A Pump API → raw station + price data
│   ├── database.py          # SQLite schema, reads, writes, dedup
│   ├── analysis.py          # Stats: 7d avg, 30d avg, percentile, score
│   ├── predictor.py         # EMA + linear trend forecast
│   ├── decision.py          # Fill-now-vs-wait, savings estimate
│   └── notifier.py          # HTTP POST to notification API
├── data/
│   └── fuel.db              # SQLite database (git-ignored)
└── tests/
    ├── test_analysis.py
    ├── test_predictor.py
    └── test_decision.py
```

---

## 3. Configuration

### `config.yaml`

```yaml
location:
  latitude: 53.27
  longitude: -6.15
  radius_km: 10

fuel:
  type: petrol          # petrol | diesel

vehicle:
  typical_fill_litres: 40

prediction:
  horizons: [1, 2, 3, 7]   # days ahead to forecast

alert:
  minimum_score: 85
  cooldown_hours: 24
  significant_price_drop_cents: 1.0   # re-alert threshold

notification:
  enabled: true
  source: fuel-monitor     # sent as `source` field to API
```

### Environment variables (secrets — never in config.yaml)

```
NOTIFICATION_API_URL    # e.g. https://api.chenmo1212.cn/message/entries
NOTIFICATION_API_KEY    # if required by the API (optional header)
```

Loaded via `python-dotenv` from `.env` (git-ignored).

---

## 4. Data Collection (`collector.py`)

### API

```
GET https://api.pickapump.com/v1/stations/nearby?lat={lat}&lng={lng}&radius={radius_km}
```

- No authentication required
- Required headers: `Accept: application/json`, `Origin: https://pickapump.com`, `User-Agent: Mozilla/5.0 (compatible; fuel-monitor/1.0)`
- Returns up to 200 stations within the radius
- Prices in euro cents (179.9 → €1.799/L)
- Timeout: 15 seconds
- On 429: wait 5s and retry once
- On any other error: log and return empty result (never crash)

### Fuel type mapping

| API field   | Fuel type code | Label             |
|-------------|----------------|-------------------|
| `petrol`    | `E10`          | Petrol (standard) |
| `diesel`    | `B7`           | Diesel            |
| `petrolplus`| `E5_98`        | Petrol 98 octane  |
| `dieselplus`| `B7_PREMIUM`   | Premium diesel    |
| `hvo`       | `HVO`          | HVO diesel        |

### Output types

```python
@dataclass
class Station:
    station_id: str       # Pick A Pump `id`
    name: str
    brand: str | None
    address: str
    town: str
    county: str
    latitude: float
    longitude: float

@dataclass
class PriceObservation:
    station_id: str
    fuel_type: str        # "E10", "B7", etc.
    price: float          # EUR/L
    observed_at: datetime # UTC
```

---

## 5. Storage (`database.py`)

### Schema

```sql
CREATE TABLE IF NOT EXISTS stations (
    station_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    brand        TEXT,
    address      TEXT,
    town         TEXT,
    county       TEXT,
    latitude     REAL NOT NULL,
    longitude    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id   TEXT NOT NULL REFERENCES stations(station_id),
    fuel_type    TEXT NOT NULL,
    price        REAL NOT NULL,
    observed_at  TEXT NOT NULL   -- ISO 8601 UTC
);

CREATE TABLE IF NOT EXISTS alert_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id   TEXT NOT NULL,
    price        REAL NOT NULL,
    score        REAL NOT NULL,
    sent_at      TEXT NOT NULL   -- ISO 8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_price_history_station_fuel
    ON price_history(station_id, fuel_type, observed_at);
```

### Dedup logic

A price observation is skipped if an identical `(station_id, fuel_type, price)` was already recorded within the last 60 minutes. This allows genuine price changes to always be recorded while preventing duplicate rows from frequent runs.

### Database path

Resolved from: `data/fuel.db` relative to the project root. Created on first run.

---

## 6. Analysis (`analysis.py`)

Given a list of historical price observations for a single station+fuel_type:

```python
@dataclass
class StationAnalysis:
    station: Station
    current_price: float
    distance_km: float
    obs_count: int
    avg_7d: float | None       # None if < 2 observations in window
    avg_30d: float | None
    low_30d: float | None
    percentile_30d: float | None   # 0–100; lower = cheaper
    score: float | None            # 0–100 Fuel Score
    score_reasons: list[str]
```

### Fuel Score formula

```
score = (
    0.50 × (100 - percentile_30d)
  + 0.25 × below_7d_signal
  + 0.25 × below_30d_signal
)
```

Where:
- `below_7d_signal = clamp((avg_7d - current) / avg_7d * 100, 0, 100)`  (signal=100 if 1%+ below avg, 0 if at/above avg)
- `below_30d_signal` = same using `avg_30d`
- All components require their respective averages to be available; if any are missing the score is `None`

### Score bands

| Score   | Label       |
|---------|-------------|
| 90–100  | Excellent   |
| 75–89   | Very good   |
| 50–74   | Normal      |
| 25–49   | Expensive   |
| 0–24    | Very expensive |

### Score reasons (human-readable, included in notification)

Generated strings like:
- `"Current price is in the cheapest 8% of the last 30 days"`
- `"2.4c/L below the 7-day average"`
- `"0.8c/L above the 30-day low"`

---

## 7. Prediction (`predictor.py`)

### Data maturity tiers

| History available | Behaviour |
|---|---|
| < 3 days | Return `None` — "Insufficient historical data" |
| 3–7 days | EMA-only forecast, wide uncertainty |
| ≥ 7 days | EMA + linear regression slope combined |

### Algorithm

1. Resample observations to daily medians
2. Fit EMA (span=3 for short history, span=7 for longer)
3. Compute linear regression slope over the last 7 days of daily medians
4. Project forward: `forecast[d] = last_ema + slope * d`
5. Uncertainty: `±(base_std * sqrt(d))` where `base_std` = std of last 7 daily residuals (min 0.005 €/L)

### Output

```python
@dataclass
class Forecast:
    horizon_days: int
    expected: float    # EUR/L
    low: float         # expected - uncertainty
    high: float        # expected + uncertainty
```

Uses only `numpy` (no sklearn dependency).

---

## 8. Decision Engine (`decision.py`)

### Fill-now-vs-wait logic

```python
@dataclass
class Recommendation:
    action: Literal["FILL NOW", "WAIT"]
    reason: str
    predicted_saving_per_litre: float | None   # EUR, positive = waiting saves money
    predicted_total_saving: float | None        # EUR on typical_fill_litres
    forecast_used: Forecast | None             # the 3-day forecast used
```

Logic:
```
best_forecast = forecast at horizon=3 (fall back to horizon=1 if unavailable)

if best_forecast is None:
    action = "FILL NOW"   # no data to support waiting
    reason = "No forecast available — good price now, fill up"
elif current_price - best_forecast.expected > significant_threshold_eur:
    # significant_threshold_eur = significant_price_drop_cents / 100
    action = "WAIT"
    reason = "Price expected to drop by {X}c/L in ~3 days"
else:
    action = "FILL NOW"
    reason = "Predicted saving too small to wait"
```

`significant_threshold_eur` = `alert.significant_price_drop_cents / 100`

---

## 9. Notification (`notifier.py`)

### API call

```
POST https://api.chenmo1212.cn/message/entries
Content-Type: application/json

{
  "type": "notification",
  "source": "fuel-monitor",
  "metadata": {
    "title": "⛽ Fuel Alert — {station_name}",
    "content": "...",
    "priority": "high" | "medium"
  }
}
```

`priority = "high"` when `action == "FILL NOW"`, `"medium"` when `action == "WAIT"`.

`NOTIFICATION_API_URL` and optionally `NOTIFICATION_API_KEY` (sent as `Authorization: Bearer {key}` header if set) come from env vars.

### Cooldown logic

Before sending, check `alert_log` for this station:
- If last alert was within `cooldown_hours` AND `last_alert_price - current_price < significant_price_drop_cents / 100` → suppress
- Otherwise → send and log to `alert_log`

### Notification content format

```
⛽ Fuel Alert

Best station nearby:
{name} ({distance_km:.1f} km)

Current price:   €{price:.3f}/L
Fuel Score:      {score}/100  ({label})
30d percentile:  {percentile:.0f}%
7d average:      €{avg_7d:.3f}/L
30d average:     €{avg_30d:.3f}/L
30d low:         €{low_30d:.3f}/L

Forecast:
  Tomorrow:  €{f1.expected:.3f}  (€{f1.low:.3f}–€{f1.high:.3f})
  3 days:    €{f3.expected:.3f}  (€{f3.low:.3f}–€{f3.high:.3f})
  7 days:    €{f7.expected:.3f}  (€{f7.low:.3f}–€{f7.high:.3f})

Potential saving vs fill now:
  ~€{total_saving:.2f} on {litres}L

{emoji} {ACTION}
{reason}
```

`emoji = 🟢` for FILL NOW, `🟡` for WAIT.

---

## 10. Orchestration (`main.py`)

Steps run in order:
1. Load config + env vars
2. Init database (create tables if not exist)
3. Fetch stations + prices from Pick A Pump
4. Save new observations (with dedup)
5. For each nearby station with petrol price: run analysis
6. Rank stations by score (descending), distance as tiebreaker
7. Run forecast on best-scored station
8. Run decision engine
9. Check cooldown / send notification if appropriate
10. Print stdout summary

Exit cleanly with status 0 on success, 1 on fatal error.

---

## 11. Scheduling

The script is designed for external scheduling. Recommended: every 6 hours.

```bash
# cron example
0 */6 * * * cd /path/to/fuel-monitor && python main.py >> logs/fuel.log 2>&1
```

No daemon, no background process.

---

## 12. Security & Secrets

- `.env` is git-ignored
- `config.yaml` contains no secrets
- `.env.example` documents required vars without values
- API key sent as `Authorization: Bearer` header if set; never logged

---

## 13. Dependencies

```
requests>=2.32.0
pyyaml>=6.0.2
python-dotenv>=1.0.1
numpy>=2.0.0
pandas>=2.2.0
```

No web framework. No ORM. No sklearn.

---

## 14. Data Maturity Handling

The system gracefully degrades at all data maturity levels:

| History | Score | Forecast | Notification |
|---|---|---|---|
| 0 observations | None | None | Suppressed |
| 1–2 obs | None | None | Suppressed |
| 3–6 days | Partial (percentile only) | EMA-only | Allowed if score available |
| 7–29 days | Full | EMA + trend | Full |
| ≥ 30 days | Full (30d stats) | Full | Full |

Score requires at minimum: 3 observations in last 30 days to compute percentile.
