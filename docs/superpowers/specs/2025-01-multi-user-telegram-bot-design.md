# Multi-User Telegram Bot — Design Spec

## Goal

Transform the existing single-user fuel monitor into a multi-user Telegram bot where anyone can register, set their preferred fuel type, share their location, and receive automatic price alerts as well as on-demand queries.

---

## Background

The existing system is a cron-driven script (`main.py`) that reads a single location and fuel type from `config.yaml`, queries the Pick A Pump API, and pushes one Telegram notification to a hardcoded `TELEGRAM_CHAT_ID`. All core logic (collection, analysis, forecasting, decision, notification formatting) is already implemented and reusable.

---

## Requirements

### User Registration & Onboarding
- Any Telegram user who messages the bot can self-register via `/start`
- `/start` guides the user through: (1) selecting fuel type, (2) sharing their location
- A user is not considered fully registered until both fuel type and location are saved
- Users can re-run `/start` to reset their preferences

### User Preferences
- **Fuel type**: one of `petrol` (E10), `diesel` (B7), `petrolplus` (E5_98), `dieselplus` (B7_PREMIUM)
- **Location**: latitude + longitude from a Telegram location share message
- **Radius**: fixed at 20 km (not configurable by user)
- **Tank size**: fixed at 40 L (not configurable by user — used for savings estimate in notifications)

### Bot Commands
| Command | Behaviour |
|---------|-----------|
| `/start` | Register or reset preferences; step through fuel type selection then location share |
| `/fuel` | Change fuel type via inline keyboard |
| `/location` | Update saved location (prompts user to share location) |
| `/check` | Query best nearby station using cached location; reply immediately |
| `/check now` | Prompt user to share a fresh location, then query and reply |
| `/status` | Show current fuel type and saved location (town/county if available, else lat/lng) |
| `/stop` | Delete user record and stop all notifications |
| `/admin` | List all registered users (chat_id, fuel type, location, last seen). Only accessible to the admin chat ID defined in env var `ADMIN_CHAT_ID` |

### Automatic Alerts
- A background scheduler runs every hour
- For each registered user with a saved location and fuel type:
  - Collect stations within 20 km of their location
  - Analyse prices and compute scores
  - Apply per-user cooldown (24 h default, bypass if price drops ≥ 1 cent vs last alert)
  - If best station score ≥ 0: send notification
- Alert cooldown and log are stored per user (keyed by `chat_id + station_id`)

### On-Demand Query (`/check`)
- Uses the same pipeline as automatic alerts but bypasses score threshold and cooldown
- Always responds, even if data is insufficient (gracefully says "not enough data for a score yet")
- `/check` uses the cached location
- `/check now` sends an inline "Share Location" button, waits for the location message, then runs the query

### Admin
- `/admin` is restricted to the `ADMIN_CHAT_ID` env var
- Returns a plain-text list: one line per user with chat_id, fuel type, lat/lng, registered date, last seen date
- If no users are registered, replies "No users registered yet."

### Deployment
- Runs as a **long-lived polling process** — no webhook, no public interface required
- Entry point: `bot.py` (alongside existing `main.py`)
- `main.py` remains unchanged for single-user/cron use
- Process managed by `systemd` or equivalent on the host server

---

## Architecture

### New Files
| File | Responsibility |
|------|---------------|
| `bot.py` | Entry point: initialise bot, register handlers, start polling + scheduler |
| `fuel_monitor/bot_handlers.py` | All Telegram command and message handlers (conversation flows) |
| `fuel_monitor/scheduler.py` | Hourly scan: iterate users, run pipeline, push alerts |
| `fuel_monitor/user_store.py` | User CRUD on the `users` table in `fuel.db` |

### Modified Files
| File | Change |
|------|--------|
| `fuel_monitor/database.py` | Add `init_users_schema()`, keep existing methods untouched |
| `fuel_monitor/notifier.py` | `_send_telegram()` accepts explicit `token` + `chat_id` params instead of reading env vars |

### Unchanged Files
`main.py`, `fuel_monitor/collector.py`, `fuel_monitor/analysis.py`, `fuel_monitor/decision.py`, `fuel_monitor/predictor.py`, `fuel_monitor/config.py`

---

## Database Schema Addition

```sql
CREATE TABLE IF NOT EXISTS users (
    chat_id       TEXT PRIMARY KEY,
    fuel_type     TEXT,              -- E10 | B7 | E5_98 | B7_PREMIUM | NULL if not set yet
    latitude      REAL,              -- NULL if not set yet
    longitude     REAL,
    radius_km     REAL DEFAULT 20,
    registered_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_alert_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,
    station_id  TEXT NOT NULL,
    price       REAL NOT NULL,
    score       REAL NOT NULL,
    sent_at     TEXT NOT NULL
);
```

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `TELEGRAM_BOT_TOKEN` | Already exists — reused |
| `ADMIN_CHAT_ID` | Your Telegram chat ID; gates `/admin` command |

`TELEGRAM_CHAT_ID` is no longer required by the bot (only by legacy `main.py`).

---

## Dependencies

Add to `requirements.txt`:
- `python-telegram-bot>=21.0` — async Telegram bot library (polling mode)
- `apscheduler>=3.10` — background scheduler for hourly alerts

---

## Fuel Type Mapping

| User-facing label | Internal code |
|-------------------|--------------|
| ⛽ Petrol (E10) | `E10` |
| 🛢 Diesel (B7) | `B7` |
| ✨ Petrol Plus (E5/98) | `E5_98` |
| 💎 Diesel Plus (Premium) | `B7_PREMIUM` |

These map to the existing `FUEL_FIELD_MAP` codes in `collector.py`.

---

## Constraints
- Python 3.11+
- SQLite (existing `data/fuel.db` — no new DB file)
- `python-telegram-bot>=21.0` (asyncio-based)
- `apscheduler>=3.10`
- Polling mode only — no webhook
- All existing tests must continue to pass
- `main.py` behaviour must remain unchanged
