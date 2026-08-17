import pytest
from datetime import datetime, timedelta, timezone
from fuel_monitor.analysis import analyse, haversine_km


def make_history(prices_and_days_ago: list[tuple[float, int]]) -> list[dict]:
    """Helper: creates history rows from (price, days_ago) pairs."""
    rows = []
    now = datetime.now(timezone.utc)
    for price, days_ago in prices_and_days_ago:
        rows.append({
            "price": price,
            "observed_at": (now - timedelta(days=days_ago)).isoformat(),
        })
    return rows


def test_analyse_returns_none_for_insufficient_data():
    result = analyse(1.750, [])
    assert result["score"] is None
    assert result["avg_7d"] is None
    assert result["avg_30d"] is None

def test_analyse_returns_none_score_with_only_one_observation():
    history = make_history([(1.800, 1)])
    result = analyse(1.750, history)
    # 1 observation is not enough for percentile
    assert result["score"] is None

def test_analyse_computes_30d_percentile_correctly():
    # 10 historical prices: 1.700, 1.710, ..., 1.790
    history = make_history([(1.700 + i * 0.010, i + 1) for i in range(10)])
    current = 1.710  # second cheapest — should be around 10th percentile
    result = analyse(current, history)
    assert result["percentile_30d"] is not None
    # current is cheaper than ~90% of history (10 obs, only 1.700 is cheaper)
    assert result["percentile_30d"] < 20

def test_analyse_7d_average_only_includes_last_7_days():
    history = make_history([
        (1.800, 2),   # within 7 days
        (1.810, 5),   # within 7 days
        (1.900, 15),  # outside 7 days — should not affect 7d avg
    ])
    result = analyse(1.750, history)
    assert result["avg_7d"] is not None
    assert abs(result["avg_7d"] - 1.805) < 0.001

def test_analyse_score_is_high_for_cheap_price():
    # history of 10 prices all higher than current
    history = make_history([(1.800 + i * 0.005, i + 1) for i in range(10)])
    current = 1.750  # cheaper than all history
    result = analyse(current, history)
    assert result["score"] is not None
    assert result["score"] >= 50  # should be a good score (spec weights 0.50/0.25/0.25, no *10)

def test_analyse_score_is_low_for_expensive_price():
    # history of 10 prices all lower than current
    history = make_history([(1.600 + i * 0.005, i + 1) for i in range(10)])
    current = 1.750  # more expensive than all history
    result = analyse(current, history)
    assert result["score"] is not None
    assert result["score"] <= 25  # should be expensive

def test_analyse_score_reasons_are_non_empty_when_score_available():
    history = make_history([(1.800 + i * 0.005, i + 1) for i in range(10)])
    result = analyse(1.750, history)
    if result["score"] is not None:
        assert len(result["score_reasons"]) > 0

def test_haversine_km_dublin_to_cork():
    # Dublin ~53.33, -6.25 / Cork ~51.90, -8.47 — roughly 220km
    dist = haversine_km(53.33, -6.25, 51.90, -8.47)
    assert 200 < dist < 240

def test_haversine_km_same_point():
    assert haversine_km(53.33, -6.25, 53.33, -6.25) == pytest.approx(0.0, abs=0.01)
