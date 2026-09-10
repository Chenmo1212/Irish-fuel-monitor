"""
Scan the entire Ireland bounding box with a grid of nearby-API calls
to collect every station ID that Pick A Pump exposes.

Usage:
    python scripts/scan_all_stations.py --token <bearer_token> [--output stations.json] [--radius 50]

The Bearer token is required — the API returns 429 "Login to see more
station information" for unauthenticated requests.  Pass it via:
  --token <value>          command-line argument, OR
  PICKAPUMP_TOKEN env var  environment variable / .env file

Anti-rate-limit strategy:
  - Large default radius (50 km) → ~30 grid points for Ireland
  - Randomised delay between requests (1–3 s by default)
  - Exponential back-off with jitter on 429 / 5xx (up to 5 retries)
  - Progress checkpoint saved after every request for resume support
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sys
import time
from pathlib import Path

import requests

# Coloured output when the terminal supports it
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_BLUE   = "\033[34m"

def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if _supports_color() else text


class _PrettyFormatter(logging.Formatter):
    """Compact, colour-coded log formatter."""
    _LEVEL_STYLES = {
        "DEBUG":    (_DIM,    "DBG"),
        "INFO":     (_CYAN,   "INF"),
        "WARNING":  (_YELLOW, "WRN"),
        "ERROR":    (_RED,    "ERR"),
        "CRITICAL": (_RED + _BOLD, "CRT"),
    }

    def format(self, record: logging.LogRecord) -> str:
        colour, tag = self._LEVEL_STYLES.get(record.levelname, ("", record.levelname[:3]))
        ts = self.formatTime(record, "%H:%M:%S")
        level_str = _c(colour, f"[{tag}]") if _supports_color() else f"[{tag}]"
        return f"{_c(_DIM, ts)} {level_str} {record.getMessage()}"


def _setup_logging(verbose: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_PrettyFormatter())
    root.handlers.clear()
    root.addHandler(handler)


logger = logging.getLogger(__name__)

# Ireland bounding box
LAT_MIN, LAT_MAX = 51.3, 55.5
LNG_MIN, LNG_MAX = -10.6, -5.4

BASE_URL = "https://api.pickapump.com/v1/stations/nearby"

# Rotate through a few realistic browser User-Agent strings to avoid
# a single fingerprint being throttled.
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_BASE_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://pickapump.com",
    "Referer": "https://pickapump.com/",
    "X-App-Version": "4.3.1",
    "X-Platform": "web",
}

MAX_RETRIES = 5
# Base wait for 429: starts at 30 s, doubles each retry + random jitter
BACKOFF_BASE = 30


def _headers(token: str | None = None) -> dict:
    h = {**_BASE_HEADERS, "User-Agent": random.choice(_USER_AGENTS)}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _km_to_deg_lat(km: float) -> float:
    return km / 111.0


def _km_to_deg_lng(km: float, lat: float) -> float:
    return km / (111.0 * math.cos(math.radians(lat)))


def build_grid(radius_km: float) -> list[tuple[float, float]]:
    """
    Return (lat, lng) grid centres that tile Ireland.
    Spacing = radius (not radius*sqrt(2)/2) so circles genuinely overlap
    and the total point count stays low (~30 for radius=50km).
    """
    lat_step = _km_to_deg_lat(radius_km)
    points: list[tuple[float, float]] = []
    lat = LAT_MIN
    while lat <= LAT_MAX:
        lng_step = _km_to_deg_lng(radius_km, lat)
        lng = LNG_MIN
        while lng <= LNG_MAX:
            points.append((round(lat, 5), round(lng, 5)))
            lng += lng_step
        lat += lat_step
    return points


def fetch_stations(lat: float, lng: float, radius_km: float, token: str | None = None) -> list[dict] | None:
    """
    Fetch raw station list for one grid cell.
    Returns the list on success, None if all retries exhausted.
    Uses exponential back-off with full jitter on 429 / 5xx.
    """
    url = f"{BASE_URL}?lat={lat}&lng={lng}&radius={radius_km}"
    logger.debug("  → GET %s", url)

    for attempt in range(MAX_RETRIES):
        try:
            t0 = time.monotonic()
            resp = requests.get(url, headers=_headers(token), timeout=20)
            elapsed = time.monotonic() - t0
            logger.debug("  ← HTTP %s in %.2fs", resp.status_code, elapsed)

            if resp.status_code == 429 or resp.status_code >= 500:
                wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 10)
                logger.warning(
                    "  ⚠ HTTP %s (attempt %d/%d) — rate limited or server error. "
                    "Backing off %.0fs before retry …",
                    resp.status_code, attempt + 1, MAX_RETRIES, wait,
                )
                _countdown(wait)
                continue

            if not resp.ok:
                logger.error(
                    "  ✗ HTTP %s — unexpected client error, skipping this grid point",
                    resp.status_code,
                )
                return []

            data = resp.json()
            if isinstance(data, list):
                return data

            logger.error(
                "  ✗ Unexpected response shape: %s — body: %.200s",
                type(data).__name__, str(data),
            )
            return []

        except requests.Timeout:
            wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 5)
            logger.error("  ✗ Request timed out (attempt %d/%d) — sleeping %.0fs …", attempt + 1, MAX_RETRIES, wait)
            _countdown(wait)
        except requests.ConnectionError as exc:
            wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 5)
            logger.error("  ✗ Connection error: %s (attempt %d/%d) — sleeping %.0fs …", exc, attempt + 1, MAX_RETRIES, wait)
            _countdown(wait)
        except (requests.RequestException, ValueError) as exc:
            wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 5)
            logger.error("  ✗ Request error: %s (attempt %d/%d) — sleeping %.0fs …", exc, attempt + 1, MAX_RETRIES, wait)
            _countdown(wait)

    logger.error("  ✗ All %d retries exhausted — giving up on this grid point", MAX_RETRIES)
    return None


def _countdown(seconds: float) -> None:
    """Sleep while printing a live countdown so the user knows we're waiting."""
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            break
        print(
            _c(_YELLOW, f"  ⏳ resuming in {remaining:.0f}s …") + "   \r",
            end="",
            flush=True,
        )
        time.sleep(min(1.0, remaining))
    print(" " * 40 + "\r", end="", flush=True)  # clear the line


def _print_new_stations(stations: list[dict]) -> None:
    """Print a formatted table of newly found stations."""
    for s in stations:
        brand = f"[{s['brand']}] " if s.get("brand") else ""
        location = ", ".join(filter(None, [s.get("town"), s.get("county")]))
        logger.info(
            "    %s  %s%s  %s  (%s)",
            _c(_GREEN, s["station_id"]),
            _c(_BOLD, brand),
            s["name"],
            _c(_DIM, location),
            _c(_DIM, f"{s['latitude']:.4f}, {s['longitude']:.4f}"),
        )


def scan(
    radius_km: float = 50.0,
    delay_min: float = 1.0,
    delay_max: float = 3.0,
    checkpoint_path: str = "scan_checkpoint.json",
    output_path: str = "stations.json",
    token: str | None = None,
    verbose: bool = False,
) -> list[dict]:
    """
    Scan all grid points, writing a checkpoint after every request.
    Resumes from checkpoint if one exists.
    """
    grid = build_grid(radius_km)

    print()
    print(_c(_BOLD, "=" * 60))
    print(_c(_BOLD, " Pick A Pump — Ireland Station Scanner"))
    print(_c(_BOLD, "=" * 60))
    logger.info("Radius: %.0f km  |  Grid points: %d  |  Delay: %.1f–%.1f s",
                radius_km, len(grid), delay_min, delay_max)
    print()

    # Load checkpoint if present
    seen: dict[str, dict] = {}
    completed_indices: set[int] = set()
    cp = Path(checkpoint_path)
    if cp.exists():
        try:
            saved = json.loads(cp.read_text(encoding="utf-8"))
            seen = {s["station_id"]: s for s in saved.get("stations", [])}
            completed_indices = set(saved.get("completed", []))
            logger.info(
                "Resuming from checkpoint: %d stations already collected, "
                "%d/%d grid points already done",
                len(seen), len(completed_indices), len(grid),
            )
            print()
        except Exception as exc:
            logger.warning("Could not read checkpoint (%s) — starting fresh", exc)

    failed_points: list[tuple[float, float]] = []

    for i, (lat, lng) in enumerate(grid):
        if i in completed_indices:
            logger.debug("[%d/%d] Skipping already-completed point (%.4f, %.4f)", i + 1, len(grid), lat, lng)
            continue

        print(_c(_BLUE, f"─── Grid point {i + 1}/{len(grid)}  ({lat:.4f}, {lng:.4f}) ───"))
        raw = fetch_stations(lat, lng, radius_km, token=token)

        if raw is None:
            # All retries exhausted — record and continue rather than abort
            failed_points.append((lat, lng))
            logger.error(
                "  ✗ FAILED (%.4f, %.4f) — all retries exhausted, point skipped. "
                "Run again to retry.",
                lat, lng,
            )
        else:
            new_stations: list[dict] = []
            skipped_country = 0
            for s in raw:
                if not isinstance(s, dict):
                    continue
                if s.get("country") != "ROI":
                    skipped_country += 1
                    continue
                coords = s.get("coords") or {}
                lat_s = coords.get("lat")
                lng_s = coords.get("lng")
                if lat_s is None or lng_s is None:
                    continue
                station_id = str(s.get("id", "")).strip()
                if not station_id:
                    continue
                if station_id not in seen:
                    station = {
                        "station_id": station_id,
                        "name": (s.get("stationName") or f"Station {station_id}").strip(),
                        "brand": (s.get("brand") or "").strip() or None,
                        "address": (s.get("address") or "").strip(),
                        "town": (s.get("town") or "").strip(),
                        "county": (s.get("county") or "").strip(),
                        "latitude": lat_s,
                        "longitude": lng_s,
                    }
                    seen[station_id] = station
                    new_stations.append(station)

            completed_indices.add(i)

            summary_parts = [
                f"{len(raw)} returned",
                _c(_GREEN, f"+{len(new_stations)} new") if new_stations else _c(_DIM, "+0 new"),
                _c(_DIM, f"{len(raw) - len(new_stations) - skipped_country} already known"),
            ]
            if skipped_country:
                summary_parts.append(_c(_DIM, f"{skipped_country} non-ROI skipped"))

            logger.info(
                "  ✓ %s  |  total collected: %s",
                "  ".join(summary_parts),
                _c(_BOLD, str(len(seen))),
            )

            if new_stations:
                _print_new_stations(new_stations)
            else:
                logger.info("  (no new stations in this grid cell)")

        print()

        # Save checkpoint after every point (whether success or failure)
        cp.write_text(
            json.dumps(
                {"stations": list(seen.values()), "completed": list(completed_indices)},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # Randomised delay between requests
        if i < len(grid) - 1:
            wait = random.uniform(delay_min, delay_max)
            logger.debug("Sleeping %.1fs before next request …", wait)
            time.sleep(wait)

    stations = list(seen.values())

    # Final summary
    print(_c(_BOLD, "=" * 60))
    if failed_points:
        logger.warning(
            "Scan complete with %d failed grid point(s): %s",
            len(failed_points), failed_points,
        )
        logger.warning("Re-run the script to retry the failed points.")
    else:
        logger.info("Scan complete — no failures.")

    logger.info(
        "Total unique stations collected: %s  →  saved to %s",
        _c(_BOLD + _GREEN, str(len(stations))),
        output_path,
    )
    print(_c(_BOLD, "=" * 60))
    print()

    # Write final output
    Path(output_path).write_text(
        json.dumps(stations, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Clean up checkpoint on success (no failures)
    if not failed_points and cp.exists():
        cp.unlink()
        logger.debug("Checkpoint file removed.")

    return stations


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan all Pick A Pump stations in Ireland",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The Bearer token can also be supplied via the PICKAPUMP_TOKEN environment variable.",
    )
    parser.add_argument("--token",       default=None,                  help="Pick A Pump Bearer token (or set PICKAPUMP_TOKEN env var)")
    parser.add_argument("--output",      default="stations.json",       help="Output JSON file (default: stations.json)")
    parser.add_argument("--checkpoint",  default="scan_checkpoint.json",help="Checkpoint file for resuming")
    parser.add_argument("--radius",      type=float, default=50.0,      help="Search radius km (default: 50)")
    parser.add_argument("--delay-min",   type=float, default=1.0,       help="Min seconds between requests (default: 1.0)")
    parser.add_argument("--delay-max",   type=float, default=3.0,       help="Max seconds between requests (default: 3.0)")
    parser.add_argument("--verbose", "-v", action="store_true",         help="Show DEBUG-level logs (request URLs, sleep timings, …)")
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    token = args.token or os.environ.get("PICKAPUMP_TOKEN")
    if not token:
        logger.warning(
            "No Bearer token provided. Requests will likely hit 429 immediately. "
            "Pass --token <value> or set PICKAPUMP_TOKEN."
        )

    scan(
        radius_km=args.radius,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        checkpoint_path=args.checkpoint,
        output_path=args.output,
        token=token,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
