from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import main


def test_main_prefers_lowest_price_when_scores_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)

    Path("config.yaml").write_text(
        """
location:
  latitude: 53.2753
  longitude: -6.203
  radius_km: 20
fuel:
  type: petrol
vehicle:
  typical_fill_litres: 40
prediction:
  horizons: [1]
alert:
  minimum_score: 85
  cooldown_hours: 24
  significant_price_drop_cents: 1.0
notification:
  enabled: false
  source: fuel-monitor
""".strip()
    )

    station_close = {
        "station_id": "close",
        "name": "Close Expensive",
        "brand": None,
        "address": "",
        "town": "",
        "county": "",
        "latitude": 53.2880,
        "longitude": -6.2030,
    }
    station_far = {
        "station_id": "far",
        "name": "Far Cheaper",
        "brand": None,
        "address": "",
        "town": "",
        "county": "",
        "latitude": 53.2954,
        "longitude": -6.2040,
    }

    observed_at = datetime(2026, 8, 17, 22, 33, 32, tzinfo=timezone.utc)
    observations = [
        {
            "station_id": "close",
            "fuel_type": "E10",
            "price": 1.927,
            "observed_at": observed_at,
        },
        {
            "station_id": "far",
            "fuel_type": "E10",
            "price": 1.818,
            "observed_at": observed_at,
        },
    ]

    monkeypatch.setattr("main.collect", lambda lat, lng, radius_km: ([station_close, station_far], observations))
    monkeypatch.setattr("main.forecast", lambda history, horizons: [])
    monkeypatch.setattr("main.decide", lambda current_price, forecasts, typical_fill, sig_drop_cents: {
        "action": "FILL NOW",
        "reason": "test",
    })

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Best nearby station:" in captured.out
    assert "Far Cheaper" in captured.out
    assert "€1.818/L" in captured.out
