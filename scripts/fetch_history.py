"""
Fetch price history for every station in stations_all.json.

Usage:
    python scripts/fetch_history.py --token <bearer_token> [options]

    PICKAPUMP_TOKEN env var is also accepted instead of --token.

Output:
    data/history/          one JSON file per station: <station_id>.json
    data/history_index.json  summary: {station_id: record_count}

The API returns all records in a single page (no real pagination).
One request per station. With default 3–8 s jitter this takes ~2–3 h
for 1500 stations, which keeps well below any observed rate limit.

Sleep behaviour (--sleep-when-done, macOS only):
    The script wraps itself with `caffeinate -i` so macOS does NOT
    auto-sleep during the run (active network I/O can sometimes wake
    the sleep timer). Once all stations are fetched successfully, it
    calls `pmset sleepnow` to put the machine to sleep immediately.
    If any station failed, sleep is skipped so you can review errors.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import requests

# ── colour logging ────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_BOLD  = "\033[1m"
_DIM   = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED   = "\033[31m"
_CYAN  = "\033[36m"
_BLUE  = "\033[34m"


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if _supports_color() else text


class _PrettyFormatter(logging.Formatter):
    _STYLES = {
        "DEBUG":   (_DIM,    "DBG"),
        "INFO":    (_CYAN,   "INF"),
        "WARNING": (_YELLOW, "WRN"),
        "ERROR":   (_RED,    "ERR"),
    }

    def format(self, record: logging.LogRecord) -> str:
        colour, tag = self._STYLES.get(record.levelname, ("", record.levelname[:3]))
        ts = self.formatTime(record, "%H:%M:%S")
        level = _c(colour, f"[{tag}]") if _supports_color() else f"[{tag}]"
        return f"{_c(_DIM, ts)} {level} {record.getMessage()}"


def _setup_logging(verbose: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_PrettyFormatter())
    root.handlers.clear()
    root.addHandler(h)


logger = logging.getLogger(__name__)

# ── API constants ─────────────────────────────────────────────────────────────

BASE_URL = "https://api.pickapump.com/v1/fuel"

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0",
]

_BASE_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://pickapump.com",
    "Referer": "https://pickapump.com/",
    "X-App-Version": "4.3.1",
    "X-Platform": "web",
}

MAX_RETRIES = 5
BACKOFF_BASE = 45  # seconds; doubles each retry


def _headers(token: str | None) -> dict:
    h = {**_BASE_HEADERS, "User-Agent": random.choice(_USER_AGENTS)}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ── fetch logic ───────────────────────────────────────────────────────────────

def _countdown(seconds: float) -> None:
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            break
        print(
            _c(_YELLOW, f"  ⏳ resuming in {remaining:.0f}s …") + "   \r",
            end="", flush=True,
        )
        time.sleep(min(1.0, remaining))
    print(" " * 40 + "\r", end="", flush=True)


def fetch_history(station_id: str, token: str | None) -> list[dict] | None:
    """
    Fetch price history for one station.
    Returns list of result dicts on success, None if all retries exhausted.
    """
    url = f"{BASE_URL}/{station_id}/history?page=1"
    logger.debug("  → GET %s", url)

    for attempt in range(MAX_RETRIES):
        try:
            t0 = time.monotonic()
            resp = requests.get(url, headers=_headers(token), timeout=20)
            elapsed = time.monotonic() - t0
            logger.debug("  ← HTTP %s  %.2fs", resp.status_code, elapsed)

            if resp.status_code == 429 or resp.status_code >= 500:
                wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 15)
                logger.warning(
                    "  ⚠ HTTP %s (attempt %d/%d) — backing off %.0fs …",
                    resp.status_code, attempt + 1, MAX_RETRIES, wait,
                )
                _countdown(wait)
                continue

            if not resp.ok:
                logger.error("  ✗ HTTP %s — skipping station", resp.status_code)
                return []

            data = resp.json()

            # Normal "no history" response: {"data": [], "message": "No price history…"}
            if isinstance(data, dict) and "message" in data:
                logger.debug("  · No history: %s", data.get("message", ""))
                return []

            results = data.get("results")
            if isinstance(results, list):
                return results

            logger.error("  ✗ Unexpected shape: %s — %.200s", type(data).__name__, str(data))
            return []

        except requests.Timeout:
            wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 10)
            logger.error("  ✗ Timeout (attempt %d/%d) — sleeping %.0fs …", attempt + 1, MAX_RETRIES, wait)
            _countdown(wait)
        except requests.ConnectionError as exc:
            wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 10)
            logger.error("  ✗ Connection error: %s (attempt %d/%d) — sleeping %.0fs …", exc, attempt + 1, MAX_RETRIES, wait)
            _countdown(wait)
        except (requests.RequestException, ValueError) as exc:
            wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 10)
            logger.error("  ✗ Error: %s (attempt %d/%d) — sleeping %.0fs …", exc, attempt + 1, MAX_RETRIES, wait)
            _countdown(wait)

    logger.error("  ✗ All retries exhausted — skipping station %s", station_id)
    return None


# ── main scan ─────────────────────────────────────────────────────────────────

def fetch_all(
    stations: list[dict],
    token: str | None,
    out_dir: Path,
    checkpoint_path: Path,
    delay_min: float,
    delay_max: float,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(stations)

    # Load checkpoint: set of already-completed station IDs
    completed: set[str] = set()
    failed: set[str] = set()
    if checkpoint_path.exists():
        try:
            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            completed = set(saved.get("completed", []))
            failed = set(saved.get("failed", []))
            logger.info(
                "Resuming: %d/%d done, %d failed",
                len(completed), total, len(failed),
            )
        except Exception as exc:
            logger.warning("Could not read checkpoint (%s) — starting fresh", exc)

    def _save_checkpoint() -> None:
        checkpoint_path.write_text(
            json.dumps({"completed": list(completed), "failed": list(failed)}, ensure_ascii=False),
            encoding="utf-8",
        )

    remaining = [s for s in stations if s["station_id"] not in completed]
    logger.info(
        "Stations to fetch: %s  |  delay: %.1f–%.1f s  |  est. time: %s",
        _c(_BOLD, str(len(remaining))),
        delay_min, delay_max,
        _eta(len(remaining), delay_min, delay_max),
    )
    print()

    for i, station in enumerate(remaining):
        sid = station["station_id"]
        name = station.get("name", sid)
        town = station.get("town", "")
        county = station.get("county", "")
        location = ", ".join(filter(None, [town, county]))

        print(_c(_BLUE, f"─── [{len(completed)+1}/{total}]  {name}  {_c(_DIM, location)} ───"))

        results = fetch_history(sid, token)

        if results is None:
            failed.add(sid)
            logger.error("  ✗ Skipped (all retries exhausted)")
        else:
            # Write individual file
            out_file = out_dir / f"{sid}.json"
            out_file.write_text(
                json.dumps(results, ensure_ascii=False),
                encoding="utf-8",
            )
            completed.add(sid)
            failed.discard(sid)  # success clears any previous failure

            if results:
                newest = results[0].get("date_added", "?")[:10]
                oldest = results[-1].get("date_added", "?")[:10]
                logger.info(
                    "  ✓ %s records  (%s → %s)",
                    _c(_GREEN, str(len(results))),
                    oldest, newest,
                )
            else:
                logger.info("  ✓ 0 records (no history)")

        _save_checkpoint()
        print()

        # Randomised delay — skip after last station
        if i < len(remaining) - 1:
            wait = random.uniform(delay_min, delay_max)
            logger.debug("Sleeping %.1fs …", wait)
            time.sleep(wait)

    # Final summary
    print(_c(_BOLD, "=" * 60))
    logger.info("Done. %s/%s stations fetched.", _c(_GREEN, str(len(completed))), total)
    if failed:
        logger.warning("%d stations failed — re-run to retry: %s", len(failed), list(failed)[:5])
    print(_c(_BOLD, "=" * 60))

    # Write index file
    index: dict[str, int] = {}
    for f in out_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            index[f.stem] = len(data)
        except Exception:
            pass
    index_path = out_dir.parent / "history_index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Index written → %s  (%d entries)", index_path, len(index))

    if not failed and checkpoint_path.exists():
        checkpoint_path.unlink()
        logger.debug("Checkpoint removed.")

    return len(failed) == 0




def _eta(n: int, dmin: float, dmax: float) -> str:
    avg = (dmin + dmax) / 2
    secs = int(n * avg)
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f"~{h}h {m}m" if h else f"~{m}m"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Pick A Pump price history for all stations",
        epilog="Token can also be set via PICKAPUMP_TOKEN env var.",
    )
    parser.add_argument("--token",       default=None,                        help="Bearer token")
    parser.add_argument("--stations",    default="data/stations_all.json",    help="Station list JSON (default: data/stations_all.json)")
    parser.add_argument("--out-dir",     default="data/history",              help="Output directory (default: data/history)")
    parser.add_argument("--checkpoint",  default="history_checkpoint.json",   help="Checkpoint file")
    parser.add_argument("--delay-min",   type=float, default=3.0,             help="Min seconds between requests (default: 3)")
    parser.add_argument("--delay-max",   type=float, default=8.0,             help="Max seconds between requests (default: 8)")
    parser.add_argument("--caffeinate",      action="store_true",             help="Prevent macOS from sleeping during the fetch (caffeinate -i)")
    parser.add_argument("--verbose", "-v", action="store_true",               help="Show DEBUG logs")
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    token = args.token or os.environ.get("PICKAPUMP_TOKEN")
    if not token:
        logger.warning("No token — will likely hit 429 immediately. Pass --token or set PICKAPUMP_TOKEN.")

    stations_path = Path(args.stations)
    if not stations_path.exists():
        logger.error("Station file not found: %s", stations_path)
        sys.exit(1)

    stations = json.loads(stations_path.read_text(encoding="utf-8"))
    logger.info("Loaded %d stations from %s", len(stations), stations_path)

    # On macOS, re-exec under caffeinate -i so the system won't idle-sleep
    # during the long-running fetch. execvp replaces this process in-place;
    # the env var guard prevents infinite re-exec loops.
    if args.caffeinate and sys.platform == "darwin":
        import shutil
        if shutil.which("caffeinate"):
            if "1" not in os.environ.get("_CAFFEINATED", ""):
                os.environ["_CAFFEINATED"] = "1"
                logger.info("Re-launching under caffeinate -i (idle sleep prevented) …")
                os.execvp("caffeinate", ["caffeinate", "-i", sys.executable] + sys.argv)
        else:
            logger.warning("caffeinate not found — system may auto-sleep during the run.")

    print()
    print(_c(_BOLD, "=" * 60))
    print(_c(_BOLD, " Pick A Pump — History Fetcher"))
    print(_c(_BOLD, "=" * 60))
    print()

    success = fetch_all(
        stations=stations,
        token=token,
        out_dir=Path(args.out_dir),
        checkpoint_path=Path(args.checkpoint),
        delay_min=args.delay_min,
        delay_max=args.delay_max,
    )



if __name__ == "__main__":
    main()
