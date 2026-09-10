import pytest
from fuel_monitor.decision import decide


def test_decide_fill_now_when_no_forecast():
    result = decide(175.0, None, 40, 1.0)
    assert result["action"] == "FILL NOW"
    assert result["predicted_saving_per_litre"] is None
    assert result["predicted_total_saving"] is None


def test_decide_fill_now_when_saving_is_small():
    # Predicted price only 0.3c/L cheaper (below 1.0c threshold)
    forecasts = [
        {"horizon_days": 1, "expected": 174.8, "low": 174.0, "high": 175.6},
        {"horizon_days": 3, "expected": 174.7, "low": 173.9, "high": 175.5},
        {"horizon_days": 7, "expected": 174.5, "low": 173.7, "high": 175.3},
    ]
    result = decide(175.0, forecasts, 40, 1.0)
    assert result["action"] == "FILL NOW"


def test_decide_wait_when_saving_is_significant():
    # Predicted price 2c/L cheaper in 3 days (above 1.0c threshold)
    forecasts = [
        {"horizon_days": 1, "expected": 174.0, "low": 173.0, "high": 175.0},
        {"horizon_days": 3, "expected": 173.0, "low": 172.0, "high": 174.0},
        {"horizon_days": 7, "expected": 172.0, "low": 171.0, "high": 173.0},
    ]
    result = decide(175.0, forecasts, 40, 1.0)
    assert result["action"] == "WAIT"
    assert result["predicted_saving_per_litre"] is not None
    assert result["predicted_saving_per_litre"] > 0


def test_decide_total_saving_calculation():
    forecasts = [
        {"horizon_days": 1, "expected": 174.0, "low": 173.0, "high": 175.0},
        {"horizon_days": 3, "expected": 172.0, "low": 171.0, "high": 173.0},  # 3c/L cheaper
    ]
    result = decide(175.0, forecasts, 40, 1.0)
    # saving = 3c/L ÷ 100 × 40L = €1.20
    if result["action"] == "WAIT":
        assert result["predicted_total_saving"] is not None
        assert abs(result["predicted_total_saving"] - 1.20) < 0.05


def test_decide_uses_3day_forecast_as_primary():
    # 1-day forecast is slightly cheaper, 3-day is more expensive
    forecasts = [
        {"horizon_days": 1, "expected": 173.0, "low": 172.0, "high": 174.0},  # 2c cheaper
        {"horizon_days": 3, "expected": 175.5, "low": 174.5, "high": 176.5},  # 0.5c more expensive
    ]
    result = decide(175.0, forecasts, 40, 1.0)
    # 3-day forecast shows no saving → FILL NOW
    assert result["action"] == "FILL NOW"
    assert result["forecast_used"]["horizon_days"] == 3


def test_decide_falls_back_to_1day_if_no_3day_forecast():
    forecasts = [
        {"horizon_days": 1, "expected": 172.0, "low": 171.0, "high": 173.0},  # 3c/L cheaper
    ]
    result = decide(175.0, forecasts, 40, 1.0)
    assert result["forecast_used"]["horizon_days"] == 1
