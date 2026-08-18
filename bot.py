#!/usr/bin/env python3
"""
FuelBot — multi-user Telegram bot entry point.
Run: python bot.py
"""
import logging
import os
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from fuel_monitor.bot_handlers import build_application
from fuel_monitor.database import Database
from fuel_monitor.scheduler import run_scheduled_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fuelbot")


def main() -> None:
    load_dotenv()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    admin_chat_id = os.environ.get("ADMIN_CHAT_ID", "").strip()
    if not admin_chat_id:
        logger.warning("ADMIN_CHAT_ID not set — /admin command will be inaccessible")

    db_path = Path(__file__).parent / "data" / "fuel.db"
    db = Database(str(db_path))
    db.init_schema()
    db.init_users_schema()

    # Hourly background scan
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_scan,
        trigger="interval",
        hours=1,
        args=[db, token],
        id="hourly_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Hourly scheduler started")

    app = build_application(db, token, admin_chat_id)
    logger.info("FuelBot starting (polling mode)…")
    try:
        app.run_polling(drop_pending_updates=True)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
