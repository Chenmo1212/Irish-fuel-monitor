# Task 3 — Report

## Summary

Task 3 adds **forecast-gated automatic alerts**: the scheduler's `run_check_for_user` now
suppresses a notification when the forecast does not recommend filling now, avoiding wasteful
alerts when prices are expected to drop.

---

## Changes committed

| File | Change |
|---|---|
| `fuel_monitor/scheduler.py` | Added 4-line early-return guard: when `bypass_cooldown=False` (scheduled scan) and `recommendation["action"] != "FILL NOW"`, return `False` and skip the notification. |
| `tests/test_scheduler.py` | Three new tests covering the three automatic-alert scenarios (rise → send, drop → suppress, score-below-minimum → suppress). |
| `README.md` | Updated *Station ranking* section; added *Forecast-based alerts* and *Alternatives in /check* sections. |

---

## Test run — `pytest tests/test_scheduler.py tests/test_decision.py`

```
============================= test session starts ==============================
platform darwin -- Python 3.13.2, pytest-9.1.1, pluggy-1.6.0
collected 21 items

tests/test_scheduler.py::test_run_check_sends_notification                PASSED
tests/test_scheduler.py::test_run_check_skips_wrong_fuel_type             PASSED
tests/test_scheduler.py::test_run_check_respects_cooldown                 PASSED
tests/test_scheduler.py::test_run_check_bypass_cooldown                   PASSED
tests/test_scheduler.py::test_run_check_no_stations_returns_false         PASSED
tests/test_scheduler.py::test_run_check_prefers_lowest_current_price_over_score PASSED
tests/test_scheduler.py::test_run_check_uses_distance_as_price_tiebreaker PASSED
tests/test_scheduler.py::test_run_check_passes_three_alternatives         PASSED
tests/test_scheduler.py::test_run_check_scheduled_no_alternatives         PASSED
tests/test_scheduler.py::test_automatic_alert_sent_for_meaningful_price_increase PASSED
tests/test_scheduler.py::test_automatic_alert_suppressed_for_predicted_price_drop PASSED
tests/test_scheduler.py::test_automatic_alert_suppressed_when_score_below_minimum PASSED
tests/test_decision.py::test_decide_fill_now_when_no_forecast             PASSED
tests/test_decision.py::test_decide_fill_now_when_saving_is_small         PASSED
tests/test_decision.py::test_decide_wait_when_saving_is_significant       PASSED
tests/test_decision.py::test_decide_total_saving_calculation              PASSED
tests/test_decision.py::test_decide_uses_3day_forecast_as_primary         PASSED
tests/test_decision.py::test_decide_falls_back_to_1day_if_no_3day_forecast PASSED
tests/test_decision.py::test_decide_recommends_fill_now_when_forecast_rises PASSED
tests/test_decision.py::test_decide_recommends_wait_when_forecast_falls_meaningfully PASSED
tests/test_decision.py::test_decide_does_not_make_strong_timing_claim_for_small_change PASSED

============================== 21 passed in 0.16s ==============================
```

**Result: 21/21 passed. No failures, no warnings.**

---

## Behaviour summary

| Scenario | `bypass_cooldown` | `recommendation["action"]` | Notification sent? |
|---|---|---|---|
| Forecast: price rising (FILL NOW) | `False` | `FILL NOW` | ✅ Yes |
| Forecast: price dropping (WAIT) | `False` | `WAIT` | ❌ No |
| Station score below `min_score` | `False` | *(exits before forecast)* | ❌ No |
| Manual `/check` | `True` | any | ✅ Always |

---

## Implementation note

The guard is placed **after** `decide()` and **before** `format_message()` /
`send_telegram_to()`, so:

- No message is formatted or sent when suppressed (efficient).
- `bypass_cooldown=True` (manual `/check`) skips the guard entirely — users always get
  a response when they ask manually.
