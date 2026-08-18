import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from fuel_monitor.database import Database
from fuel_monitor import scheduler as sched

logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_FUEL = 0
WAITING_LOCATION = 1
WAITING_LOCATION_CHECK_NOW = 2

FUEL_LABELS = {
    "E10":        "⛽ Petrol (E10)",
    "B7":         "🛢 Diesel (B7)",
    "E5_98":      "✨ Petrol Plus (E5/98)",
    "B7_PREMIUM": "💎 Diesel Plus (Premium)",
}


def _fuel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⛽ Petrol (E10)", callback_data="fuel:E10"),
            InlineKeyboardButton("🛢 Diesel (B7)",  callback_data="fuel:B7"),
        ],
        [
            InlineKeyboardButton("✨ Petrol Plus (E5/98)",    callback_data="fuel:E5_98"),
            InlineKeyboardButton("💎 Diesel Plus (Premium)", callback_data="fuel:B7_PREMIUM"),
        ],
    ])


def _location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Share my location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)
    db.upsert_user(chat_id, None, None, None)
    db.touch_user(chat_id)
    await update.message.reply_text(
        "👋 Welcome to FuelBot!\n\nFirst, pick your fuel type:",
        reply_markup=_fuel_keyboard(),
    )
    return CHOOSING_FUEL


async def cb_fuel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    db: Database = context.bot_data["db"]
    chat_id = str(query.from_user.id)
    fuel_code = query.data.split(":")[1]  # e.g. "E10"
    context.user_data["pending_fuel"] = fuel_code
    label = FUEL_LABELS.get(fuel_code, fuel_code)
    await query.edit_message_text(f"Got it — {label}.\n\nNow share your location:")
    await context.bot.send_message(
        chat_id=chat_id,
        text="Tap the button below to share your location 👇",
        reply_markup=_location_keyboard(),
    )
    return WAITING_LOCATION


async def msg_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)
    loc = update.message.location
    fuel_code = context.user_data.get("pending_fuel")
    if fuel_code:
        db.upsert_user(chat_id, fuel_code, loc.latitude, loc.longitude)
        context.user_data.pop("pending_fuel", None)
        label = FUEL_LABELS.get(fuel_code, fuel_code)
        await update.message.reply_text(
            f"✅ You're all set!\n\nFuel: {label}\nLocation saved ({loc.latitude:.4f}, {loc.longitude:.4f})\n\n"
            "You'll receive automatic alerts when prices near you look good.\n"
            "Use /check to query anytime.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        # /location command flow — just update location
        user = db.get_user(chat_id)
        if user:
            db.upsert_user(chat_id, user.get("fuel_type"), loc.latitude, loc.longitude)
        await update.message.reply_text(
            f"📍 Location updated ({loc.latitude:.4f}, {loc.longitude:.4f}).",
            reply_markup=ReplyKeyboardRemove(),
        )
    return ConversationHandler.END


async def cmd_fuel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)
    db.touch_user(chat_id)
    await update.message.reply_text("Choose your fuel type:", reply_markup=_fuel_keyboard())
    return CHOOSING_FUEL


async def cb_fuel_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fuel selection when entered via /fuel — update fuel only, no location prompt."""
    query = update.callback_query
    await query.answer()
    db: Database = context.bot_data["db"]
    chat_id = str(query.from_user.id)
    fuel_code = query.data.split(":")[1]
    user = db.get_user(chat_id)
    if user:
        db.upsert_user(chat_id, fuel_code, user.get("latitude"), user.get("longitude"))
        label = FUEL_LABELS.get(fuel_code, fuel_code)
        await query.edit_message_text(f"✅ Fuel type updated to {label}.")
    else:
        await query.edit_message_text("You're not registered yet. Use /start first.")
    return ConversationHandler.END


async def cmd_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)
    db.touch_user(chat_id)
    await update.message.reply_text(
        "Share your current location 👇",
        reply_markup=_location_keyboard(),
    )
    return WAITING_LOCATION


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db: Database = context.bot_data["db"]
    token: str = context.bot_data["token"]
    chat_id = str(update.effective_chat.id)
    db.touch_user(chat_id)

    args = context.args or []
    if args and args[0].lower() == "now":
        await update.message.reply_text(
            "Share your location for a fresh check 👇",
            reply_markup=_location_keyboard(),
        )
        return WAITING_LOCATION_CHECK_NOW

    user = db.get_user(chat_id)
    if not user or user.get("latitude") is None:
        await update.message.reply_text(
            "No saved location. Use /start to set one, or /check now to share fresh."
        )
        return ConversationHandler.END
    if not user.get("fuel_type"):
        await update.message.reply_text("No fuel type set. Use /start to configure.")
        return ConversationHandler.END

    await update.message.reply_text("🔍 Checking prices near you…")
    sent = sched.run_check_for_user(
        user=user,
        db=db,
        token=token,
        horizons=sched.HORIZONS,
        typical_fill=sched.TYPICAL_FILL,
        sig_drop_cents=sched.SIG_DROP_CENTS,
        cooldown_hours=sched.COOLDOWN_HOURS,
        min_score=sched.MIN_SCORE,
        bypass_cooldown=True,
    )
    if not sent:
        await update.message.reply_text(
            "😕 No results — either no stations found nearby or not enough price history yet."
        )
    return ConversationHandler.END


async def msg_location_check_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db: Database = context.bot_data["db"]
    token: str = context.bot_data["token"]
    chat_id = str(update.effective_chat.id)
    loc = update.message.location
    user = db.get_user(chat_id)
    if not user:
        await update.message.reply_text("Not registered. Use /start first.")
        return ConversationHandler.END

    # Use the fresh location without overwriting the saved one
    fresh_user = {**user, "latitude": loc.latitude, "longitude": loc.longitude}
    await update.message.reply_text("🔍 Checking prices near you…", reply_markup=ReplyKeyboardRemove())
    sent = sched.run_check_for_user(
        user=fresh_user,
        db=db,
        token=token,
        horizons=sched.HORIZONS,
        typical_fill=sched.TYPICAL_FILL,
        sig_drop_cents=sched.SIG_DROP_CENTS,
        cooldown_hours=sched.COOLDOWN_HOURS,
        min_score=sched.MIN_SCORE,
        bypass_cooldown=True,
    )
    if not sent:
        await update.message.reply_text(
            "😕 No results — either no stations found nearby or not enough price history yet."
        )
    return ConversationHandler.END


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)
    db.touch_user(chat_id)
    user = db.get_user(chat_id)
    if not user:
        await update.message.reply_text("You're not registered. Use /start to set up.")
        return
    fuel = FUEL_LABELS.get(user.get("fuel_type", ""), "Not set")
    lat = user.get("latitude")
    lng = user.get("longitude")
    loc_str = f"{lat:.4f}, {lng:.4f}" if lat is not None else "Not set"
    await update.message.reply_text(
        f"⚙️ Your settings:\n\nFuel type: {fuel}\nLocation: {loc_str}\nRadius: 20 km"
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    chat_id = str(update.effective_chat.id)
    db.delete_user(chat_id)
    await update.message.reply_text(
        "👋 You've been unregistered. No more alerts.\nUse /start anytime to sign up again."
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_chat_id: str = context.bot_data["admin_chat_id"]
    chat_id = str(update.effective_chat.id)
    if chat_id != admin_chat_id:
        await update.message.reply_text("⛔ Not authorised.")
        return
    db: Database = context.bot_data["db"]
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("No users registered yet.")
        return
    lines = [f"👥 {len(users)} registered users:\n"]
    for u in users:
        lat = u.get("latitude")
        lng = u.get("longitude")
        loc = f"{lat:.3f},{lng:.3f}" if lat is not None else "no location"
        lines.append(
            f"• {u['chat_id']} | {u.get('fuel_type','?')} | {loc} | since {u['registered_at'][:10]}"
        )
    await update.message.reply_text("\n".join(lines))


def build_application(db: Database, token: str, admin_chat_id: str) -> Application:
    app = Application.builder().token(token).build()
    app.bot_data["db"] = db
    app.bot_data["token"] = token
    app.bot_data["admin_chat_id"] = admin_chat_id

    # Single conversation handler covering /start, /fuel, /location, /check flows
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("fuel", cmd_fuel),
            CommandHandler("location", cmd_location),
            CommandHandler("check", cmd_check),
        ],
        states={
            CHOOSING_FUEL: [CallbackQueryHandler(cb_fuel_chosen, pattern=r"^fuel:")],
            WAITING_LOCATION: [MessageHandler(filters.LOCATION, msg_location_received)],
            WAITING_LOCATION_CHECK_NOW: [MessageHandler(filters.LOCATION, msg_location_check_now)],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("admin", cmd_admin))

    return app
