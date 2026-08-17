def decide(
    current_price: float,
    forecasts: list[dict] | None,
    typical_fill_litres: float,
    significant_price_drop_cents: float,
) -> dict:
    """
    Determine whether to fill up now or wait.

    Args:
        current_price: current price EUR/L
        forecasts: output of predictor.forecast(), or None
        typical_fill_litres: vehicle tank fill size
        significant_price_drop_cents: minimum per-litre saving in cents to recommend waiting

    Returns:
        dict with action, reason, predicted_saving_per_litre,
        predicted_total_saving, forecast_used
    """
    threshold_eur = significant_price_drop_cents / 100.0

    if not forecasts:
        return {
            "action": "FILL NOW",
            "reason": "No forecast available — good price now, fill up",
            "predicted_saving_per_litre": None,
            "predicted_total_saving": None,
            "forecast_used": None,
        }

    # Prefer 3-day forecast; fall back to shortest available
    forecast_used = next((f for f in forecasts if f["horizon_days"] == 3), None)
    if forecast_used is None:
        forecast_used = min(forecasts, key=lambda f: f["horizon_days"])

    saving_per_litre = current_price - forecast_used["expected"]
    total_saving = saving_per_litre * typical_fill_litres

    if saving_per_litre > threshold_eur:
        return {
            "action": "WAIT",
            "reason": (
                f"Price expected to drop by {saving_per_litre * 100:.1f}c/L "
                f"in ~{forecast_used['horizon_days']} days "
                f"(saving ~€{total_saving:.2f} on {typical_fill_litres:.0f}L)"
            ),
            "predicted_saving_per_litre": round(saving_per_litre, 4),
            "predicted_total_saving": round(total_saving, 2),
            "forecast_used": forecast_used,
        }
    else:
        return {
            "action": "FILL NOW",
            "reason": "Predicted saving too small to justify waiting",
            "predicted_saving_per_litre": round(saving_per_litre, 4),
            "predicted_total_saving": round(total_saving, 2),
            "forecast_used": forecast_used,
        }
