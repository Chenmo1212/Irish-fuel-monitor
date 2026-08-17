from datetime import datetime, timedelta, timezone
from fuel_monitor.predictor import forecast


def make_history(prices_and_days_ago: list[tuple[float, float]]) -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {
            "price": price,
            "observed_at": (now - timedelta(days=days_ago)).isoformat(),
        }
        for price, days_ago in prices_and_days_ago
    ]


def test_forecast_returns_none_for_insufficient_data():
    history = make_history([(1.800, 1), (1.790, 0.5)])  # all within 1 day
    result = forecast(history, [1, 3, 7])
    assert result is None


def test_forecast_returns_correct_number_of_horizons():
    # 10 daily observations spanning 10 days
    history = make_history([(1.800 - i * 0.002, i) for i in range(10)])
    result = forecast(history, [1, 3, 7])
    assert result is not None
    assert len(result) == 3
    assert [r["horizon_days"] for r in result] == [1, 3, 7]


def test_forecast_uncertainty_grows_with_horizon():
    history = make_history([(1.800 - i * 0.002, i) for i in range(14)])
    result = forecast(history, [1, 3, 7])
    assert result is not None
    ranges = [r["high"] - r["low"] for r in result]
    # uncertainty should grow (or at least not shrink) as horizon increases
    assert ranges[0] <= ranges[1] <= ranges[2]


def test_forecast_expected_is_between_low_and_high():
    history = make_history([(1.800 - i * 0.001, i) for i in range(14)])
    result = forecast(history, [1, 2, 3, 7])
    assert result is not None
    for r in result:
        assert r["low"] <= r["expected"] <= r["high"]


def test_forecast_detects_falling_trend():
    # Prices falling by 0.5c per day for 14 days: oldest=1.865 (14 days ago), newest=1.800 (most recent)
    history = make_history([(1.800 + i * 0.005, i) for i in range(14)])
    result = forecast(history, [3])
    assert result is not None
    # 3-day forecast should be lower than current price
    current = 1.800  # most recent price (days_ago=0)
    assert result[0]["expected"] < current


def test_forecast_detects_rising_trend():
    # Prices rising by 0.5c per day for 14 days
    history = make_history([(1.700 + i * 0.005, 14 - i) for i in range(14)])
    result = forecast(history, [3])
    assert result is not None
    current = 1.700 + 13 * 0.005  # most recent price
    assert result[0]["expected"] > current
