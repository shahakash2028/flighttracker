import os
from datetime import datetime
from dotenv import load_dotenv
from serpapi import GoogleSearch
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def format_flight_time(date_str: str) -> str:
    """Formats '2026-12-11 10:30' into 'Fri, December 11 • 10:30'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%a, %B %d • %H:%M")
    except Exception:
        return date_str


def build_leg_card(flights: list[dict]) -> str:
    if not flights:
        return ""
    first_leg = flights[0]
    last_leg = flights[-1]

    dep = first_leg.get("departure_airport", {})
    arr = last_leg.get("arrival_airport", {})

    stops = len(flights) - 1
    dep_time = format_flight_time(dep.get("time", ""))
    arr_time = format_flight_time(arr.get("time", ""))

    return (
        f"<b>{dep.get('name', 'Origin')} ({dep.get('id', '')}) - "
        f"{arr.get('name', 'Destination')} ({arr.get('id', '')})</b>\n"
        f"🔄 Stops: {stops}\n"
        f"🕒 Departure: {dep_time}\n"
        f"🕒 Arrival: {arr_time}\n"
    )


def search_flight_deal(origin: str, dest: str, depart_date: str, return_date: str | None = None) -> str:
    is_round_trip = bool(return_date)

    params = {
        "engine": "google_flights",
        "departure_id": origin.upper(),
        "arrival_id": dest.upper(),
        "outbound_date": depart_date,
        "currency": "USD",
        "hl": "en",
        "api_key": SERPAPI_KEY,
        "type": 1 if is_round_trip else 2,
    }

    if is_round_trip:
        params["return_date"] = return_date

    try:
        results = GoogleSearch(params).get_dict()
    except Exception as e:
        return f"❌ Request error: {e}"

    if "error" in results:
        return f"❌ SerpApi error: {results['error']}"

    all_options = (results.get("best_flights") or []) + (results.get("other_flights") or [])
    valid_options = [opt for opt in all_options if opt.get("price") is not None]

    if not valid_options:
        trip_desc = f"round-trip ({depart_date} to {return_date})" if is_round_trip else f"on {depart_date}"
        return f"❌ No flights found for {origin.upper()} ➔ {dest.upper()} {trip_desc}."

    cheapest = min(valid_options, key=lambda opt: float(opt.get("price", float("inf"))))
    price = float(cheapest["price"])
    legs = cheapest.get("flights", [])

    if not legs:
        return "❌ Incomplete flight data returned."

    first_airport = legs[0].get("departure_airport", {}).get("name", origin.upper())
    last_airport = legs[-1].get("arrival_airport", {}).get("name", dest.upper())
    vendor = legs[0].get("airline", "Google Flights")

    booking_token = cheapest.get("booking_token")
    if booking_token:
        direct_url = f"https://www.google.com/travel/flights/booking?token={booking_token}"
    else:
        direct_url = (
            f"https://www.google.com/travel/flights?q=Flights%20to%20{dest.upper()}"
            f"%20from%20{origin.upper()}%20on%20{depart_date}"
        )
        if is_round_trip:
            direct_url += f"%20through%20{return_date}"

    return (
        f"📍 <b>{first_airport} - {last_airport}</b>\n\n"
        f"{build_leg_card(legs)}\n"
        f"🎫 <b>{vendor}</b>: <b>${price:.2f} USD</b>\n"
        f"💳 <a href=\"{direct_url}\"><b>Buy ticket</b></a>"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "✈️ <b>Flight Search Bot</b>\n\n"
        "Commands:\n"
        "• <b>One-way:</b>\n"
        "<code>/flight ORIGIN DESTINATION DEPART_DATE</code>\n"
        "<i>Example:</i> <code>/flight KTM DEL 2026-11-20</code>\n\n"
        "• <b>Round-trip:</b>\n"
        "<code>/flight ORIGIN DESTINATION DEPART_DATE RETURN_DATE</code>\n"
        "<i>Example:</i> <code>/flight ORD DEL 2026-12-11 2027-01-04</code>"
    )
    await update.message.reply_html(welcome)


async def flight_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_html(
            "⚠️ <b>Invalid command usage!</b>\n\n"
            "Format:\n"
            "<code>/flight ORIGIN DESTINATION YYYY-MM-DD [RETURN_YYYY-MM-DD]</code>\n\n"
            "Examples:\n"
            "• <code>/flight ORD DEL 2026-12-11</code>\n"
            "• <code>/flight ORD DEL 2026-12-11 2027-01-04</code>"
        )
        return

    origin = args[0]
    destination = args[1]
    depart_date = args[2]
    return_date = args[3] if len(args) >= 4 else None

    trip_label = f"{origin.upper()} ➔ {destination.upper()} ({depart_date})"
    if return_date:
        trip_label += f" returning {return_date}"

    wait_msg = await update.message.reply_text(f"🔍 Searching live flights for {trip_label}...")
    flight_card = search_flight_deal(origin, destination, depart_date, return_date)
    await wait_msg.edit_text(flight_card, parse_mode="HTML", disable_web_page_preview=True)


def main():
    if not TELEGRAM_BOT_TOKEN or not SERPAPI_KEY:
        print("Missing TELEGRAM_BOT_TOKEN or SERPAPI_API_KEY in environment.")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("flight", flight_command))

    print("🤖 Bot listener online. Send /flight commands in Telegram...")
    app.run_polling()


if __name__ == "__main__":
    main()
