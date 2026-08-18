# FuelBot — Ireland Fuel Price Monitor

A self-hosted Telegram bot that watches petrol/diesel prices near you across Ireland, scores them against recent history, and pushes you an alert when prices are meaningfully good.

Data source: [Pick A Pump](https://pickapump.com) (Republic of Ireland only).

---

## How it works

1. Every 6 hours the bot fetches nearby station prices from Pick A Pump.
2. Each price is scored 0–100 against the station's own 30-day history.
3. If the score passes the configured threshold and the user's cooldown has elapsed, a Telegram message is sent.
4. Users can also query on-demand at any time with `/check`.

---

## Quick start

### 1. Prerequisites

- Python 3.11+
- A Telegram bot token — create one via [@BotFather](https://t.me/BotFather)
- Your Telegram chat ID — send any message to [@userinfobot](https://t.me/userinfobot)

### 2. Clone and install

```bash
git clone <repo-url>
cd fuel-monitor

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Configure secrets

```bash
cp .env.example .env
```

Open `.env` and fill in:

```dotenv
TELEGRAM_BOT_TOKEN=123456:ABC-your-token-here
ADMIN_CHAT_ID=987654321          # your own chat ID — gates the /admin command
```

> `TELEGRAM_CHAT_ID` and `NOTIFICATION_API_*` are only needed if you use the legacy `main.py` single-user mode. Leave them blank for the bot.

### 4. Configure location and preferences

Edit [`config.yaml`](config.yaml):

```yaml
location:
  latitude: 53.2753       # your latitude
  longitude: -6.2031      # your longitude
  radius_km: 20           # search radius

fuel:
  type: petrol            # petrol | petrolplus | diesel | dieselplus

alert:
  minimum_score: 0        # 0 = notify on any result; raise to e.g. 60 for good deals only
  cooldown_hours: 24      # minimum hours between alerts per user
```

> Secrets (tokens, API keys) go in `.env` only — never in `config.yaml`.

### 5. Start the bot

```bash
python bot.py
```

Open Telegram, find your bot, and send `/start` to register.

---

## Telegram commands

| Command | Description |
|---------|-------------|
| `/start` | Register and set your fuel type + location |
| `/fuel` | Change your fuel type |
| `/location` | Update your saved location |
| `/check` | Query best nearby price (uses saved location) |
| `/check now` | Share fresh location, then query |
| `/status` | View your current settings |
| `/stop` | Unregister and stop alerts |
| `/help` | Show command reference |
| `/admin` | *(owner only)* List all registered users |

---

## Running as a background service

### systemd (Linux)

Create `/etc/systemd/system/fuelbot.service`:

```ini
[Unit]
Description=FuelBot Telegram Bot
After=network.target

[Service]
WorkingDirectory=/path/to/fuel-monitor
ExecStart=/path/to/fuel-monitor/.venv/bin/python bot.py
Restart=always
RestartSec=10
EnvironmentFile=/path/to/fuel-monitor/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable fuelbot
sudo systemctl start fuelbot
sudo systemctl status fuelbot
```

### macOS launchd

Create `~/Library/LaunchAgents/com.fuelbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>        <string>com.fuelbot</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/fuel-monitor/.venv/bin/python</string>
    <string>/path/to/fuel-monitor/bot.py</string>
  </array>
  <key>WorkingDirectory</key> <string>/path/to/fuel-monitor</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TELEGRAM_BOT_TOKEN</key> <string>your-token</string>
    <key>ADMIN_CHAT_ID</key>      <string>your-chat-id</string>
  </dict>
  <key>RunAtLoad</key>    <true/>
  <key>KeepAlive</key>    <true/>
  <key>StandardOutPath</key> <string>/tmp/fuelbot.log</string>
  <key>StandardErrorPath</key><string>/tmp/fuelbot.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.fuelbot.plist
```

---

## Single-user CLI mode (`main.py`)

If you don't want the bot and just want a script you run manually or via cron:

```bash
# requires TELEGRAM_CHAT_ID (or NOTIFICATION_API_URL) in .env
python main.py
```

Cron example (every 6 hours):

```cron
0 */6 * * * cd /path/to/fuel-monitor && .venv/bin/python main.py >> logs/fuel.log 2>&1
```

---

## Scoring explained

Each station price gets a `score` (0–100) measuring how good it is relative to **that station's own recent history** — not a global average.

| Component | Weight | What it measures |
|-----------|--------|-----------------|
| 30-day percentile | 50% | How cheap vs. the past month |
| vs. 7-day average | 25% | Short-term trend |
| vs. 30-day average | 25% | Long-term trend |

Score labels:

| Score | Label |
|-------|-------|
| 90–100 | Excellent |
| 75–89 | Very good |
| 50–74 | Normal |
| 25–49 | Expensive |
| 0–24 | Very expensive |

Score is `None` (shown as "insufficient history") until a station has:
- ≥ 3 observations in the last 30 days
- ≥ 2 observations in the last 7 days

Predictions improve noticeably after ~7 days of data collection.

### Station ranking

When multiple stations are nearby:

1. Stations **with** a score rank above those without.
2. Among scored stations, **higher score wins**.
3. Without a score, **lower price wins**.
4. Distance is a tiebreaker only.

---

## Fuel type reference

| `config.yaml` value | Telegram label | API code |
|---------------------|----------------|----------|
| `petrol` | ⛽ Petrol (E10) | `E10` |
| `petrolplus` | ✨ Petrol Plus (E5/98) | `E5_98` |
| `diesel` | 🛢 Diesel (B7) | `B7` |
| `dieselplus` | 💎 Diesel Plus (Premium) | `B7_PREMIUM` |

---

## Data

SQLite database at `data/fuel.db` (created automatically on first run). Stores station metadata, price observations, and per-user alert history.

---

## Running tests

```bash
pytest
```
