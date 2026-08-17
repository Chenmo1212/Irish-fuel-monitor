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
.venv/bin/python main.py
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

## Price selection and scoring

### Data source and fuel mapping

Prices are fetched from Pick A Pump's nearby-stations API in
[`fuel_monitor/collector.py`](fuel_monitor/collector.py).

Configured fuel types in [`config.yaml`](config.yaml) map to API fuel codes as follows:

- `petrol` → `E10`
- `petrolplus` → `E5_98`
- `diesel` → `B7`
- `dieselplus` → `B7_PREMIUM`

### What `score` means

`score` is a 0-100 value indicating how good the current station price is
relative to that same station's recent history. Higher is better.

It is computed from three components:

- 50%: how cheap the current price is within the last 30 days
- 25%: how far below the 7-day average the current price is
- 25%: how far below the 30-day average the current price is

Labels are:

- `90+` → `Excellent`
- `75+` → `Very good`
- `50+` → `Normal`
- `25+` → `Expensive`
- `<25` → `Very expensive`

### When `score` is unavailable

`score` is not calculated unless there is enough local history for that
station and fuel type:

- at least 3 observations in the last 30 days for percentile calculation
- at least 2 observations in the last 7 days for the 7-day average
- at least 2 observations in the last 30 days for the 30-day average

If those conditions are not met, the score is `None`.

### Ranking strategy

When choosing the "Best nearby station":

1. Stations with a score are ranked ahead of stations without a score.
2. Among scored stations, higher score wins.
3. If score is unavailable, lower current price wins.
4. Distance is only used as a tiebreaker.
