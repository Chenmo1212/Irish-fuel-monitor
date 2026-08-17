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
