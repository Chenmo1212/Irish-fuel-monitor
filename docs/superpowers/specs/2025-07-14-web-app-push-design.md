# FuelBot Web App + Web Push — Design Spec

**Date:** 2025-07-14  
**Status:** Approved

---

## 1. Goal

Add a Web App + Web Push layer to the existing FuelBot project. Users open a webpage to see current fuel prices, nearby stations, price history, and set alert targets — without touching the existing Telegram bot, scraper, SQLite schema, prediction, or monitoring logic.

---

## 2. Constraints

- **Do not modify** any file in `fuel_monitor/` (collector, database, analysis, predictor, decision, notifier, scheduler, bot_handlers, config).
- **Do not modify** `bot.py` or `main.py`.
- The existing `data/fuel.db` is shared; the web layer adds one new table to it.
- Python 3.11+. Flask ≥ 3.0. Vite ≥ 5. React ≥ 18.
- All new Python dependencies added to `requirements.txt`.
- No auth. Preferences are stored per-browser (localStorage) + server-side in the push subscriptions table.
- Production security: Flask must bind to `127.0.0.1` only. VAPID keys stored in `.env`, never in code.

---

## 3. Architecture

```
fuel-monitor/
├── fuel_monitor/          ← UNTOUCHED
├── web/
│   ├── app.py             ← Flask application factory + REST API routes
│   ├── push.py            ← VAPID helpers, push subscription CRUD, push dispatch
│   ├── static/            ← built React dist (git-ignored; produced by npm run build)
│   └── frontend/          ← Vite + React source
│       ├── src/
│       │   ├── main.jsx
│       │   ├── App.jsx
│       │   ├── api.js          ← thin fetch wrappers for all API endpoints
│       │   ├── pages/
│       │   │   ├── Dashboard.jsx
│       │   │   ├── Stations.jsx
│       │   │   ├── History.jsx
│       │   │   └── Settings.jsx
│       │   └── components/
│       │       ├── PriceCard.jsx
│       │       ├── StationList.jsx
│       │       ├── PriceChart.jsx
│       │       └── PushToggle.jsx
│       ├── public/
│       │   ├── sw.js           ← service worker (receives push, shows notification)
│       │   └── manifest.json
│       └── package.json
├── web_app.py             ← entry point: starts Flask + APScheduler web scan
└── .env                   ← VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_EMAIL (added)
```

`web_app.py` is the **new** entry point for the web layer. It starts Flask (dev server via `flask run` or production via a WSGI server) and an APScheduler background job that runs the web-push scan every 6 hours. It does **not** start the Telegram bot — that remains `bot.py`. Both can run concurrently pointing at the same `data/fuel.db` (SQLite WAL mode is already enabled).

---

## 4. REST API

All endpoints are prefixed `/api/`. Flask serves the React `index.html` for every non-`/api/` route (SPA catch-all).

### 4.1 Stations

**`GET /api/stations`**

Query params: `lat` (float), `lng` (float), `radius` (float, km, default 20), `fuel` (string, one of `E10 | B7 | E5_98 | B7_PREMIUM`, default `E10`)

Calls `collector.collect(lat, lng, radius)` to get live data, persists stations + observations via `db.upsert_station` / `db.save_observation`, runs `analysis.analyse()` for each station, returns ranked list.

Response:
```json
[
  {
    "station_id": "123",
    "name": "Circle K Donnybrook",
    "brand": "Circle K",
    "address": "...",
    "town": "Dublin",
    "county": "Dublin",
    "latitude": 53.32,
    "longitude": -6.23,
    "distance_km": 1.4,
    "current_price": 1.789,
    "fuel_type": "E10",
    "score": 72.5,
    "score_label": "Normal",
    "avg_7d": 1.801,
    "avg_30d": 1.810,
    "low_30d": 1.769
  }
]
```

Ranked by: scored stations first (descending score), then unscored (ascending price), distance as tiebreaker.

---

**`GET /api/stations/<station_id>/history`**

Query params: `fuel` (string), `days` (int, default 30, max 90)

Returns the price history for a single station.

Response:
```json
[
  { "price": 1.789, "observed_at": "2025-07-01T10:00:00+00:00" }
]
```

---

### 4.2 Regional Summary

**`GET /api/prices/summary`**

Query params: `lat`, `lng`, `radius`, `fuel`

Returns daily aggregates (median price across all stations in the radius) for the last 30 days, plus the cheapest station today.

Response:
```json
{
  "daily_avg": [
    { "date": "2025-06-14", "median_price": 1.812 }
  ],
  "cheapest_today": {
    "station_id": "456",
    "name": "Applegreen Sandyford",
    "current_price": 1.769,
    "distance_km": 3.1
  }
}
```

---

### 4.3 Web Push

**`GET /api/vapid-public-key`**

Returns `{ "publicKey": "<base64url>" }`. Used by the frontend to create a push subscription.

---

**`POST /api/push/subscribe`**

Body:
```json
{
  "subscription": {
    "endpoint": "https://fcm.googleapis.com/...",
    "keys": { "p256dh": "...", "auth": "..." }
  },
  "prefs": {
    "fuel_type": "E10",
    "latitude": 53.32,
    "longitude": -6.23,
    "radius_km": 20,
    "petrol_target": 1.75,
    "diesel_target": null
  }
}
```

Upserts (by endpoint) into `web_push_subscriptions`. Returns `{ "ok": true }`.

---

**`DELETE /api/push/subscribe`**

Body: `{ "endpoint": "..." }`

Deletes the subscription row. Returns `{ "ok": true }`.

---

### 4.4 SPA Catch-all

**`GET /*`** → serves `web/static/index.html`

---

## 5. Database — New Table

Added to `web/push.py` via `Database.init_web_push_schema()` (a new method on the existing `Database` class — but added in `web/push.py` via monkey-patch or direct SQL, NOT by modifying `database.py`).

Actually: `web/push.py` creates and manages this table itself using a direct `sqlite3` connection to the same `data/fuel.db`. It does not subclass or modify `Database`.

```sql
CREATE TABLE IF NOT EXISTS web_push_subscriptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint       TEXT NOT NULL UNIQUE,
    p256dh         TEXT NOT NULL,
    auth           TEXT NOT NULL,
    fuel_type      TEXT NOT NULL,
    latitude       REAL NOT NULL,
    longitude      REAL NOT NULL,
    radius_km      REAL NOT NULL DEFAULT 20,
    petrol_target  REAL,
    diesel_target  REAL,
    created_at     TEXT NOT NULL
)
```

---

## 6. Web Push Flow

### Subscription lifecycle

1. User opens Settings page, clicks "Enable notifications".
2. Browser asks permission.
3. Frontend calls `navigator.serviceWorker.ready` → `registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: vapidPublicKey })`.
4. Frontend POSTs subscription object + user prefs to `POST /api/push/subscribe`.
5. Server upserts into `web_push_subscriptions`.

### Push dispatch (scheduler)

Every 6 hours `web_app.py`'s APScheduler job calls `web_push.run_web_push_scan(db_path)`:

1. Load all rows from `web_push_subscriptions`.
2. Deduplicate locations: group subscriptions by `(round(lat,2), round(lng,2), radius_km)`.
3. For each unique location group, call `collector.collect(lat, lng, radius)`.
4. Persist new stations + observations to DB.
5. For each subscription in the group:
   a. Filter observations to the subscription's `fuel_type`.
   b. Find cheapest current price among nearby stations.
   c. Compare against `petrol_target` / `diesel_target` (whichever is set for that fuel_type).
   d. If price ≤ target → send Web Push.
6. Web Push payload: `{ title, body, url }` — body includes station name, price, score.
7. On HTTP 410 (Gone) from push service → delete the subscription row.

### Service Worker

`public/sw.js` listens for `push` events, shows a notification with `self.registration.showNotification(title, { body, icon, data: { url } })`. On `notificationclick` → opens/focuses the app URL.

---

## 7. Frontend Pages

### Dashboard
- Location input: lat/lng text fields OR "Use my location" button (Geolocation API).
- Fuel type selector: 4 options (E10, B7, E5_98, B7_PREMIUM).
- On submit: calls `GET /api/stations`, shows the **best station** card with price, score badge, score label, 7d avg, fill-now/wait recommendation (using `decision.decide()` result — computed server-side and included in the station response, or computed client-side from the forecast).
- Forecast for best station: call `GET /api/stations/<id>/history`, compute client-side using a simple linear trend display (not re-implementing predictor — just show the chart). The `FILL NOW / WAIT` recommendation is fetched from the server.

Actually: recommendation is computed server-side in `GET /api/stations` for the top result, and included in the response as `recommendation: { action, reason }`.

### Stations
- Full list of nearby stations from `GET /api/stations`.
- Each row: name, price, score badge, distance.
- Click a station → opens a detail drawer/modal with a 30-day price chart (`GET /api/stations/<id>/history`).

### History
- `GET /api/prices/summary` → regional median trend chart (line chart, 30 days).
- Overlay: cheapest station's daily price.
- Uses [Recharts](https://recharts.org/) for charts.

### Settings
- Petrol target price input (€/L).
- Diesel target price input (€/L).
- Radius slider (5–50 km, default 20).
- Push notifications toggle (PushToggle component).
- All prefs persisted to `localStorage`. When push is toggled on, subscribes and POSTs prefs to server.

---

## 8. Frontend Tech Stack

| Concern | Choice |
|---------|--------|
| Build tool | Vite 5 |
| Framework | React 18 |
| Routing | React Router v6 |
| Charts | Recharts 2 |
| HTTP | fetch (native) |
| Styling | plain CSS modules |
| No UI component library | keep it lean |

---

## 9. VAPID Key Generation

On first run, if `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` are not set, `web/push.py` generates them using `py_vapid` and logs instructions to add them to `.env`. In production the keys must be set before starting; the app refuses to start the push feature without them (graceful degradation: push subscribe endpoint returns 503).

---

## 10. New Entry Point: `web_app.py`

```python
# Starts Flask dev server + APScheduler web-push scan
# Usage: python web_app.py
# Production: gunicorn web.app:create_app() --bind 127.0.0.1:5000
```

- Loads `.env`
- Calls `db.init_schema()` + `db.init_users_schema()` + `push.init_schema(db_path)`
- Registers APScheduler job: `web_push.run_web_push_scan` every 6 hours
- Runs Flask on `127.0.0.1:5000` (dev) or exports `app` for WSGI

---

## 11. New Dependencies

```
flask>=3.0
flask-cors>=4.0
pywebpush>=2.0
```

---

## 12. Security

- Flask binds to `127.0.0.1` only (not `0.0.0.0`).
- VAPID keys in `.env` only, loaded via `python-dotenv` (already a dependency).
- `.env` already in `.gitignore`.
- Push subscription endpoint + auth keys are never logged.
- No user PII beyond lat/lng + fuel preferences.

---

## 13. Development Workflow

```bash
# Terminal 1 — Flask API
cd fuel-monitor
python web_app.py

# Terminal 2 — Vite dev server (proxies /api to :5000)
cd fuel-monitor/web/frontend
npm run dev   # → http://localhost:5173
```

Vite `vite.config.js` proxies `/api` → `http://127.0.0.1:5000`.

```bash
# Production build
cd fuel-monitor/web/frontend
npm run build  # outputs to ../static/
```

---

## 14. Out of Scope

- User accounts / login
- Telegram bot changes
- Admin dashboard
- Price alerts by email or SMS
- Mobile app (PWA installability is a bonus if manifest is set up, not a requirement)
