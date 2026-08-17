import math
from datetime import datetime, timezone

import numpy as np


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def forecast(history: list[dict], horizons: list[int]) -> list[dict] | None:
    """
    Forecast fuel prices for given horizon days.

    Returns None if insufficient history (< 3 days span).
    Otherwise returns list of {"horizon_days", "expected", "low", "high"}.
    """
    if not history:
        return None

    now = datetime.now(timezone.utc)

    # Sort by time ascending
    sorted_history = sorted(history, key=lambda r: _parse_dt(r["observed_at"]))

    oldest = _parse_dt(sorted_history[0]["observed_at"])
    newest = _parse_dt(sorted_history[-1]["observed_at"])
    span_days = (newest - oldest).total_seconds() / 86400

    if span_days < 3:
        return None

    # Resample to daily medians
    # Group observations by day offset from now
    day_buckets: dict[int, list[float]] = {}
    for row in sorted_history:
        dt = _parse_dt(row["observed_at"])
        days_ago = (now - dt).total_seconds() / 86400
        bucket = int(days_ago)  # floor to day
        day_buckets.setdefault(bucket, []).append(row["price"])

    # Sort buckets oldest-first (highest days_ago first)
    sorted_days = sorted(day_buckets.keys(), reverse=True)
    daily_medians = [float(np.median(day_buckets[d])) for d in sorted_days]

    if len(daily_medians) < 2:
        return None

    # Compute EMA
    span = min(7, len(daily_medians))
    alpha = 2 / (span + 1)
    ema = daily_medians[0]
    for price in daily_medians[1:]:
        ema = alpha * price + (1 - alpha) * ema
    last_ema = ema

    # Linear regression slope over last 7 daily medians
    lookback = min(7, len(daily_medians))
    recent = daily_medians[-lookback:]
    x = np.arange(len(recent), dtype=float)
    slope = float(np.polyfit(x, recent, 1)[0])

    # Uncertainty: std of residuals from linear fit, minimum 0.005 €/L
    coeffs = np.polyfit(x, recent, 1)
    fitted = np.polyval(coeffs, x)
    residuals = np.array(recent) - fitted
    base_std = max(float(np.std(residuals)), 0.005)

    results = []
    for h in horizons:
        expected = last_ema + slope * h
        uncertainty = base_std * math.sqrt(h)
        results.append({
            "horizon_days": h,
            "expected": round(expected, 4),
            "low": round(expected - uncertainty, 4),
            "high": round(expected + uncertainty, 4),
        })

    return results
