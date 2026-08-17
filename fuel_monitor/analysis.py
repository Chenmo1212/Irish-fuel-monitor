import math
from datetime import datetime, timedelta, timezone


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def analyse(current_price: float, history: list[dict]) -> dict:
    """
    Compute analysis statistics for a single station + fuel type.

    Args:
        current_price: current price in EUR/L
        history: list of {"price": float, "observed_at": str ISO 8601} dicts
                 covering at least the last 30 days (caller's responsibility)

    Returns:
        dict with keys: obs_count, avg_7d, avg_30d, low_30d,
                        percentile_30d, score, score_label, score_reasons
    """
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    prices_30d = [r["price"] for r in history if _parse_dt(r["observed_at"]) >= cutoff_30d]
    prices_7d  = [r["price"] for r in history if _parse_dt(r["observed_at"]) >= cutoff_7d]

    obs_count = len(prices_30d)
    avg_7d    = (sum(prices_7d) / len(prices_7d))   if len(prices_7d) >= 2  else None
    avg_30d   = (sum(prices_30d) / len(prices_30d)) if len(prices_30d) >= 2 else None
    low_30d   = min(prices_30d) if prices_30d else None

    # Percentile: % of 30d observations strictly below current price
    # Low percentile = cheap price (current is cheaper than most history)
    percentile_30d: float | None = None
    if len(prices_30d) >= 3:
        count_above_or_equal = sum(1 for p in prices_30d if p >= current_price)
        percentile_30d = (1 - count_above_or_equal / len(prices_30d)) * 100

    score: float | None = None
    score_label: str | None = None
    score_reasons: list[str] = []

    if percentile_30d is not None and avg_7d is not None and avg_30d is not None:
        # Percentile component: low percentile → high score
        pct_component = 100 - percentile_30d

        # Below-7d-avg component (R-001: no * 10 multiplier)
        # clamp((avg_7d - current) / avg_7d * 100, 0, 100)
        below_7d = min(max((avg_7d - current_price) / avg_7d * 100, 0), 100)

        # Below-30d-avg component (same formula)
        below_30d = min(max((avg_30d - current_price) / avg_30d * 100, 0), 100)

        score = 0.50 * pct_component + 0.25 * below_7d + 0.25 * below_30d
        score = min(max(score, 0), 100)

        # Label
        if score >= 90:
            score_label = "Excellent"
        elif score >= 75:
            score_label = "Very good"
        elif score >= 50:
            score_label = "Normal"
        elif score >= 25:
            score_label = "Expensive"
        else:
            score_label = "Very expensive"

        # Human-readable reasons
        if percentile_30d is not None:
            pct_rank = round(percentile_30d)
            score_reasons.append(
                f"Current price is in the cheapest {100 - pct_rank}% of the last 30 days"
                if pct_rank < 50
                else f"Current price is in the most expensive {pct_rank}% of the last 30 days"
            )
        if avg_7d is not None:
            diff_c = (avg_7d - current_price) * 100
            if abs(diff_c) >= 0.1:
                direction = "below" if diff_c > 0 else "above"
                score_reasons.append(f"{abs(diff_c):.1f}c/L {direction} the 7-day average")
        if low_30d is not None:
            diff_low_c = (current_price - low_30d) * 100
            score_reasons.append(f"{diff_low_c:.1f}c/L above the 30-day low")

    return {
        "obs_count": obs_count,
        "avg_7d": avg_7d,
        "avg_30d": avg_30d,
        "low_30d": low_30d,
        "percentile_30d": percentile_30d,
        "score": round(score, 1) if score is not None else None,
        "score_label": score_label,
        "score_reasons": score_reasons,
    }
