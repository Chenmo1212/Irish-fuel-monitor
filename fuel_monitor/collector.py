import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.pickapump.com/v1/stations/nearby"

FUEL_FIELD_MAP = [
    ("petrol",     "E10"),
    ("diesel",     "B7"),
    ("petrolplus", "E5_98"),
    ("dieselplus",  "B7_PREMIUM"),
    ("hvo",        "HVO"),
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
            time.sleep(5)
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

    if not isinstance(data, list):
        logger.error("Pick A Pump unexpected response shape: %s", type(data).__name__)
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
        if lat_s is None or lng_s is None:
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
            if val <= 0 or val > 500:  # cents; max ~€5/L
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
