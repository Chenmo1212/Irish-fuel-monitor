#!/usr/bin/env python3
"""
FuelBot Web App entry point.

Development:  python web_app.py
Production:   gunicorn "web.app:create_app()" --bind 127.0.0.1:5000
"""
import logging
import os
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from fuel_monitor.database import Database
from web.app import create_app
from web.push import get_vapid_keys, run_web_push_scan, init_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fuelweb")


def main() -> None:
    load_dotenv()

    db_path = str(Path(__file__).parent / "data" / "fuel.db")

    # Initialise all DB schemas
    db = Database(db_path)
    db.init_schema()
    db.init_users_schema()
    init_schema(db_path)

    # Warn if VAPID keys not configured
    pub, priv = get_vapid_keys()
    vapid_email = os.environ.get("VAPID_EMAIL", "").strip()
    if not pub or not priv or not vapid_email:
        logger.warning(
            "VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_EMAIL not set. "
            "Web Push notifications will be disabled. "
            "Generate keys with: python web/gen_vapid.py"
        )

    # Background scan every 6 hours
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_web_push_scan,
        trigger="interval",
        hours=6,
        args=[db_path],
        id="web_push_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Web push scan scheduler started (every 6 h)")

    app = create_app(db_path)
    logger.info("FuelBot Web App starting on http://127.0.0.1:5000")
    try:
        app.run(host="127.0.0.1", port=5000, debug=False)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
