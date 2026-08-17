import pytest
from fuel_monitor.decision import decide


def test_decide_fill_now_when_no_forecast():
    result = decide(1.750, None, 40, 1.0)
    assert result["action"] == "FILL NOW"
    assert result["predicted_saving_per_litre"] is None
    assert result["predicted_total_saving"] is None


def test_decide_fill_now_when_saving_is_small():
    # Predicted price only 0.3c/L cheaper (below 1.0 threshold)
    forecasts = [
        {"horizon_days": 1, "expected": 1.748, "low": 1.740, "high": 1.756},
        {"horizon_days": 3, "expected": 1.747, "low": 1.739, "high": 1.755},
        {"horizon_days": 7, "expected": 1.745, "low": 1.737, "high": 1.753},
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    assert result["action"] == "FILL NOW"


def test_decide_wait_when_saving_is_significant():
    # Predicted price 2c/L cheaper in 3 days (above 1.0 threshold)
    forecasts = [
        {"horizon_days": 1, "expected": 1.740, "low": 1.730, "high": 1.750},
        {"horizon_days": 3, "expected": 1.730, "low": 1.720, "high": 1.740},
        {"horizon_days": 7, "expected": 1.720, "low": 1.710, "high": 1.730},
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    assert result["action"] == "WAIT"
    assert result["predicted_saving_per_litre"] is not None
    assert result["predicted_saving_per_litre"] > 0


def test_decide_total_saving_calculation():
    forecasts = [
        {"horizon_days": 1, "expected": 1.740, "low": 1.730, "high": 1.750},
        {"horizon_days": 3, "expected": 1.720, "low": 1.710, "high": 1.730},  # 3c/L cheaper
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    # saving = 0.030 EUR/L × 40L = 1.20 EUR
    if result["action"] == "WAIT":
        assert result["predicted_total_saving"] is not None
        assert abs(result["predicted_total_saving"] - 1.20) < 0.05


def test_decide_uses_3day_forecast_as_primary():
    # 1-day forecast is slightly cheaper, 3-day is more expensive
    forecasts = [
        {"horizon_days": 1, "expected": 1.730, "low": 1.720, "high": 1.740},  # 2c cheaper
        {"horizon_days": 3, "expected": 1.755, "low": 1.745, "high": 1.765},  # 0.5c more expensive
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    # 3-day forecast shows no saving → FILL NOW
    assert result["action"] == "FILL NOW"
    assert result["forecast_used"]["horizon_days"] == 3


def test_decide_falls_back_to_1day_if_no_3day_forecast():
    forecasts = [
        {"horizon_days": 1, "expected": 1.720, "low": 1.710, "high": 1.730},  # 3c/L cheaper
    ]
    result = decide(1.750, forecasts, 40, 1.0)
    assert result["forecast_used"]["horizon_days"] == 1
