import logging
import os
import sys
from datetime import datetime
import requests
from dotenv import load_dotenv
from serpapi import GoogleSearch

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

REQUIRED_VARS = (
    "SERPAPI_API_KEY",
    "ORIGIN",
    "DESTINATION",
    "DEPART_DATE",
    "PRICE_THRESHOLD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


def load_config() -> dict[str, str]:
    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
    return {name: os.environ[name] for name in REQUIRED_VARS}


def format_flight_time(date_str: str) -> str:
    """Formats '2026-12-11 10:30' to 'Fri, December 11 • 10:30'"""
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


def fetch_flight_data(api_key: str, origin: str, dest: str, depart_date: str, return_date: str | None = None) -> dict:
    is_round_trip = bool(return_date)
    params = {
        "engine": "google_flights",
        "departure_id": origin.upper(),
        "arrival_id": dest.upper(),
        "outbound_date": depart_date,
        "type": 1 if is_round_trip else 2,
        "currency": "USD",
        "hl": "en",
        "api_key": api_key,
    }
    if is_round_trip:
        params["return_date"] = return_date

    return GoogleSearch(params).get_dict()


def send_telegram_alert(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()


def main() -> None:
    config = load_config()
    threshold = float(config["PRICE_THRESHOLD"])
    return_date = os.getenv("RETURN_DATE")

    results = fetch_flight_data(
        config["SERPAPI_API_KEY"],
        config["ORIGIN"],
        config["DESTINATION"],
        config["DEPART_DATE"],
        return_date,
    )

    if error := results.get("error"):
        logging.error("SerpApi error: %s", error)
        sys.exit(1)

    all_options = (results.get("best_flights") or []) + (results.get("other_flights") or [])
    valid_options = [opt for opt in all_options if opt.get("price") is not None]

    if not valid_options:
        logging.warning("No flight results found.")
        sys.exit(0)

    cheapest = min(valid_options, key=lambda opt: float(opt.get("price", float("inf"))))
    price = float(cheapest["price"])
    legs = cheapest.get("flights", [])

    logging.info(
        "Lowest fare %s -> %s on %s: $%.2f (Threshold: $%.2f)",
        config["ORIGIN"],
        config["DESTINATION"],
        config["DEPART_DATE"],
        price,
        threshold,
    )

    if price < threshold:
        vendor = legs[0].get("airline", "Google Flights") if legs else "Google Flights"
        booking_token = cheapest.get("booking_token")
        if booking_token:
            direct_url = f"https://www.google.com/travel/flights/booking?token={booking_token}"
        else:
            direct_url = (
                f"https://www.google.com/travel/flights?q=Flights%20to%20{config['DESTINATION'].upper()}"
                f"%20from%20{config['ORIGIN'].upper()}%20on%20{config['DEPART_DATE']}"
            )
            if return_date:
                direct_url += f"%20through%20{return_date}"

        # Build card text
        first_airport = legs[0].get("departure_airport", {}).get("name", config["ORIGIN"])
        last_airport = legs[-1].get("arrival_airport", {}).get("name", config["DESTINATION"])

        message = (
            f"📍 <b>{first_airport} - {last_airport}</b>\n\n"
            f"{build_leg_card(legs)}\n"
            f"🎫 <b>{vendor}</b>: <b>${price:.2f} USD</b>\n"
            f"💳 <a href=\"{direct_url}\"><b>Buy ticket</b></a>"
        )

        send_telegram_alert(config["TELEGRAM_BOT_TOKEN"], config["TELEGRAM_CHAT_ID"], message)
        logging.info("Telegram alert sent successfully.")
    else:
        logging.info("Current lowest fare ($%.2f) is above threshold ($%.2f). Alert skipped.", price, threshold)


if __name__ == "__main__":
    main()
