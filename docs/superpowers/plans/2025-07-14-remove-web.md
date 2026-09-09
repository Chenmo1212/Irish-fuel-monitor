# Remove Web Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Before dispatching subagents, analyze tasks for parallelism and group into batches. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip all web-related code, dependencies, and tests from the project, leaving a clean Telegram-only codebase.

**Architecture:** The project has two parallel execution paths sharing `fuel_monitor/` core logic — `bot.py` (Telegram) and `web_app.py` (Flask + React). We delete the web path entirely: `web/`, `web_app.py`, the React frontend, web tests, and web-specific dependencies. We also remove `main.py` (legacy single-user CLI) and slim down `fuel_monitor/notifier.py` to drop the legacy HTTP API and generic `send_notification()` wrapper that were only needed by `main.py`. Everything in `fuel_monitor/` that `bot.py` depends on stays untouched.

**Tech Stack:** Python 3.11+, python-telegram-bot, APScheduler, SQLite

**Spec:** No external spec — scope defined by user request: keep only the Telegram bot, remove all web content.

## What stays (Telegram-only surface)

| File | Role |
|------|------|
| `bot.py` | Entry point — builds and runs the Telegram bot |
| `fuel_monitor/bot_handlers.py` | All Telegram command handlers |
| `fuel_monitor/scheduler.py` | Scheduled scan + per-user check pipeline |
| `fuel_monitor/notifier.py` | `send_telegram_to()` + `format_message()` (trim legacy code) |
| `fuel_monitor/database.py` | SQLite access (stations, price history, users, alerts) |
| `fuel_monitor/analysis.py` | Price scoring |
| `fuel_monitor/collector.py` | Pick-a-Pump API client |
| `fuel_monitor/decision.py` | FILL NOW / WAIT decision |
| `fuel_monitor/predictor.py` | Price forecasting |
| `fuel_monitor/config.py` | YAML loader |
| `config.yaml` | Runtime configuration (trim web/notif blocks) |
| `.env.example` | Trim to only Telegram vars |
| `requirements.txt` | Remove Flask, flask-cors, pywebpush |
| `README.md` | Remove Web App section |
| `tests/` (non-web) | All existing non-web tests stay and must pass |

## What gets deleted

| Path | Reason |
|------|--------|
| `web/` | Entire Flask API + Web Push module |
| `web_app.py` | Web entry point |
| `web/frontend/` | React + Vite application |
| `tests/web/` | Web API + push schema tests |
| `main.py` | Legacy single-user CLI (uses `send_notification()`) |
| `tests/test_main.py` | Tests for `main.py` |

## Global Constraints

- Python 3.11+
- Do not modify any file inside `fuel_monitor/` except `notifier.py` (slim it)
- Do not modify `bot.py`, `fuel_monitor/bot_handlers.py`, `fuel_monitor/scheduler.py`, `fuel_monitor/database.py`
- All non-web tests must remain green after changes (`pytest tests/ --ignore=tests/web`)
- No new features — only deletions and cleanup

---

## Task 1: Delete web directories and files

**Files:**
- Delete: `web/` (entire directory)
- Delete: `web_app.py`
- Delete: `tests/web/` (entire directory)
- Delete: `main.py`
- Delete: `tests/test_main.py`

**Interfaces:**
- Produces: clean file tree with no web or legacy CLI artifacts

- [ ] **Step 1: Delete web package and entry point**

```bash
rm -rf web/ web_app.py
```

- [ ] **Step 2: Delete legacy CLI entry point**

```bash
rm main.py
```

- [ ] **Step 3: Delete web tests and legacy CLI test**

```bash
rm -rf tests/web/ tests/test_main.py
```

- [ ] **Step 4: Verify remaining test suite still collects without import errors**

```bash
source .venv/bin/activate && pytest tests/ --collect-only -q
```

Expected: all test items listed, zero errors, zero items from `tests/web/` or `tests/test_main.py`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: delete web layer and legacy CLI entry point"
```

---

## Task 2: Slim `fuel_monitor/notifier.py`

**Files:**
- Modify: `fuel_monitor/notifier.py`

**Interfaces:**
- Consumes: nothing new — this is already imported by `fuel_monitor/scheduler.py` as `from fuel_monitor.notifier import format_message, send_telegram_to`
- Produces: `notifier.py` exports only `send_telegram_to(chat_id, title, body, maps_url, token) -> bool` and `format_message(station, analysis, forecasts, recommendation, typical_fill_litres) -> tuple[str, str, str | None]`

The following functions are only called by `main.py` (now deleted) and can be removed:
- `_send_telegram()` — env-var wrapper, used only by `main.py`
- `send_notification()` — generic HTTP API dispatcher, used only by `main.py`
- The `requests` call for the custom HTTP API inside `send_notification()`

`send_telegram_to()` and `format_message()` are called by `fuel_monitor/scheduler.py` and must be kept exactly as-is.

- [ ] **Step 1: Replace `fuel_monitor/notifier.py` with the trimmed version**

The new file keeps only `send_telegram_to` and `format_message`, plus the private `_build_telegram_payload` helper they depend on:

```python
import logging

import requests

logger = logging.getLogger(__name__)


def _build_telegram_payload(chat_id: str, title: str, body: str, maps_url: str | None) -> dict:
    text = f"*{title}*\n\n{body}"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if maps_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "📍 Navigate", "url": maps_url}]]
        }
    return payload


def send_telegram_to(
    chat_id: str,
    title: str,
    body: str,
    maps_url: str | None,
    token: str,
) -> bool:
    """
    Send a Telegram message to an explicit chat_id using an explicit token.
    Returns True on success, False on any failure. Never raises.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = _build_telegram_payload(chat_id, title, body, maps_url)
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            logger.info("Telegram notification sent to chat_id=%s: %s", chat_id, title)
            return True
        logger.error("Telegram API HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    except requests.RequestException as exc:
        logger.error("Telegram request failed: %s", exc)
        return False


def format_message(
    station: dict,
    analysis: dict,
    forecasts: list[dict] | None,
    recommendation: dict,
    typical_fill_litres: float,
) -> tuple[str, str, str | None]:
    """
    Format a Telegram-style notification message.
    Returns (title, body, maps_url).
    maps_url is the Google Maps link for the station, or None if unavailable.
    """
    name = station.get("name", "Unknown station")
    dist = station.get("distance_km")
    dist_str = f"{dist:.1f} km" if dist is not None else "unknown distance"

    price = analysis.get("current_price")
    if price is None:
        price = station.get("current_price", 0)
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

    lat = station.get("latitude")
    lng = station.get("longitude")
    maps_link = f"https://www.google.com/maps?q={lat},{lng}" if lat is not None and lng is not None else None

    lines = ["⛽ Fuel Alert", ""]
    lines += ["Best station nearby:", f"{name} ({dist_str})", ""]
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
        for fc in forecasts:
            h = fc["horizon_days"]
            label = "Tomorrow" if h == 1 else f"{h} days"
            lines += [f"  {label}:  €{fc['expected']:.3f}  (€{fc['low']:.3f}–€{fc['high']:.3f})"]

    if total_saving is not None:
        lines += ["", "Potential saving vs fill now:"]
        lines += [f"  ~€{total_saving:.2f} on {typical_fill_litres:.0f}L"]

    lines += ["", f"{emoji} {action}", reason]

    return title, "\n".join(lines), maps_link
```

- [ ] **Step 2: Run notifier tests to verify nothing broke**

```bash
source .venv/bin/activate && pytest tests/test_notifier_multiuser.py -v
```

Expected: all tests pass. Note: `test_send_telegram_backward_compat_uses_env` tests `_send_telegram` which we removed — this test will now fail with an `ImportError`. Proceed to Step 3.

- [ ] **Step 3: Update `tests/test_notifier_multiuser.py` to remove the deleted import and test**

Remove the import of `_send_telegram` and the `test_send_telegram_backward_compat_uses_env` test — that function no longer exists.

The updated file:

```python
from unittest.mock import patch, MagicMock
from fuel_monitor.notifier import send_telegram_to


def _mock_ok():
    r = MagicMock()
    r.ok = True
    return r


def _mock_fail():
    r = MagicMock()
    r.ok = False
    r.status_code = 400
    r.text = "bad request"
    return r


def test_send_telegram_to_success():
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_ok()) as mock_post:
        result = send_telegram_to(
            chat_id="12345",
            title="Test",
            body="Hello",
            maps_url=None,
            token="fake-token",
        )
    assert result is True
    call_kwargs = mock_post.call_args
    assert "botfake-token" in call_kwargs[0][0]
    payload = call_kwargs[1]["json"]
    assert payload["chat_id"] == "12345"


def test_send_telegram_to_failure():
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_fail()):
        result = send_telegram_to(
            chat_id="12345",
            title="Test",
            body="Hello",
            maps_url=None,
            token="fake-token",
        )
    assert result is False


def test_send_telegram_to_with_maps_url():
    with patch("fuel_monitor.notifier.requests.post", return_value=_mock_ok()) as mock_post:
        send_telegram_to(
            chat_id="12345",
            title="Test",
            body="Hello",
            maps_url="https://maps.google.com/?q=1,2",
            token="fake-token",
        )
    payload = mock_post.call_args[1]["json"]
    assert "reply_markup" in payload
```

- [ ] **Step 4: Run the full test suite**

```bash
source .venv/bin/activate && pytest tests/ -v
```

Expected: all tests pass, no import errors.

- [ ] **Step 5: Commit**

```bash
git add fuel_monitor/notifier.py tests/test_notifier_multiuser.py
git commit -m "chore: slim notifier.py — remove legacy HTTP API and env-var wrapper"
```

---

## Task 3: Clean up `requirements.txt`, `config.yaml`, `.env.example`, and `README.md`

**Files:**
- Modify: `requirements.txt`
- Modify: `config.yaml`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Produces: config files with no web/VAPID/legacy-notification references

- [ ] **Step 1: Update `requirements.txt` — remove web dependencies**

Remove `flask>=3.0`, `flask-cors>=4.0`, `pywebpush>=2.0`. The new file:

```
requests>=2.32.0
pyyaml>=6.0.2
python-dotenv>=1.0.1
numpy>=2.0.0
pandas>=2.2.0
pytest>=8.0.0
python-telegram-bot>=21.0
apscheduler>=3.10
```

- [ ] **Step 2: Update `config.yaml` — remove `notification` block**

`main.py` (now deleted) was the only consumer of `notification.source`, `notification.enabled`, and `notification.test_mode`. The bot reads nothing from this section. Remove it entirely. New file:

```yaml
location:
  latitude: 53.2753
  longitude: -6.203
  radius_km: 20

fuel:
  # petrol = E10 (cheaper, most common)
  # petrolplus = E5/98 (premium, higher octane)
  # diesel = B7
  # dieselplus = B7 Premium
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
  minimum_score: 0
  cooldown_hours: 24
  significant_price_drop_cents: 1.0
```

- [ ] **Step 3: Update `.env.example` — remove VAPID and legacy HTTP vars**

`NOTIFICATION_API_URL`, `NOTIFICATION_API_KEY`, and `VAPID_*` keys are no longer used. New file:

```dotenv
# Telegram bot token — from @BotFather
TELEGRAM_BOT_TOKEN=

# Your own Telegram chat ID — gates the /admin command
ADMIN_CHAT_ID=
```

- [ ] **Step 4: Update `README.md` — remove Web App section and Single-user CLI section**

Remove the `## Web App` section (lines 243–304 in the current file) and the `## Single-user CLI mode (\`main.py\`)` section (lines 166–179). Keep all other sections intact.

The remaining top-level sections after edit:

```
# FuelBot — Ireland Fuel Price Monitor
## How it works
## Quick start
## Telegram commands
## Running as a background service
## Scoring explained
## Fuel type reference
## Data
## Running tests
```

- [ ] **Step 5: Run the full test suite to confirm nothing broke**

```bash
source .venv/bin/activate && pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt config.yaml .env.example README.md
git commit -m "chore: remove web/VAPID config, slim README to Telegram-only"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|---|---|
| Delete `web/` directory | Task 1 Step 1 |
| Delete `web_app.py` | Task 1 Step 1 |
| Delete React frontend | Task 1 Step 1 (inside `web/`) |
| Delete `tests/web/` | Task 1 Step 3 |
| Delete `main.py` | Task 1 Step 2 |
| Delete `tests/test_main.py` | Task 1 Step 3 |
| Slim `fuel_monitor/notifier.py` | Task 2 |
| Remove broken test import | Task 2 Step 3 |
| Clean `requirements.txt` | Task 3 Step 1 |
| Clean `config.yaml` | Task 3 Step 2 |
| Clean `.env.example` | Task 3 Step 3 |
| Clean `README.md` | Task 3 Step 4 |
| All remaining tests pass | Task 1 Step 4, Task 2 Step 4, Task 3 Step 5 |

### Placeholder scan

No TBD, TODO, or placeholder patterns. All code blocks contain exact file contents.

### Type consistency

`send_telegram_to` and `format_message` signatures in Task 2 match the existing call sites in `fuel_monitor/scheduler.py` exactly (`from fuel_monitor.notifier import format_message, send_telegram_to`). No renames.
