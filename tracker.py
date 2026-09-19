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
    """Formats '2026-12-11 10:30' into 'Fri, December 11 • 10:30'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%a, %B %d • %H:%M")
    except Exception:
        return date_str


def fetch_flights(api_key: str, origin: str, destination: str, depart_date: str) -> dict:
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": depart_date,
        "type": 2,  # 2 = one-way, 1 = round-trip
        "currency": "USD",
        "hl": "en",
        "api_key": api_key,
    }
    return GoogleSearch(params).get_dict()


def parse_best_flight(results: dict) -> dict | None:
    all_options = (results.get("best_flights") or []) + (results.get("other_flights") or [])
    valid_options = [opt for opt in all_options if opt.get("price") is not None]

    if not valid_options:
        return None

    cheapest = min(valid_options, key=lambda opt: float(opt.get("price", float("inf"))))
    legs = cheapest.get("flights", [])

    if not legs:
        return None

    first_leg = legs[0]
    last_leg = legs[-1]

    dep_airport = first_leg.get("departure_airport", {})
    arr_airport = last_leg.get("arrival_airport", {})

    dep_time_raw = dep_airport.get("time", "")
    arr_time_raw = arr_airport.get("time", "")

    # Booking provider or airline name
    airline_or_vendor = first_leg.get("airline") or "Google Flights"
    
    # Try to grab booking link from the option or generate Google Flights direct prefill
    booking_token = cheapest.get("booking_token")
    if booking_token:
        direct_booking_url = f"https://www.google.com/travel/flights/booking?token={booking_token}"
    else:
        direct_booking_url = (
            f"https://www.google.com/travel/flights?q=Flights%20to%20"
            f"{arr_airport.get('id')}%20from%20{dep_airport.get('id')}%20on%20{dep_time_raw.split()[0]}"
        )

    stops_count = len(legs) - 1

    return {
        "origin_name": dep_airport.get("name", "Origin"),
        "origin_id": dep_airport.get("id", ""),
        "dest_name": arr_airport.get("name", "Destination"),
        "dest_id": arr_airport.get("id", ""),
        "stops": stops_count,
        "departure": format_flight_time(dep_time_raw),
        "arrival": format_flight_time(arr_time_raw),
        "price": float(cheapest["price"]),
        "vendor": airline_or_vendor,
        "booking_url": direct_booking_url,
    }


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

    results = fetch_flights(
        config["SERPAPI_API_KEY"],
        config["ORIGIN"],
        config["DESTINATION"],
        config["DEPART_DATE"],
    )

    if error := results.get("error"):
        logging.error("SerpApi error: %s", error)
        sys.exit(1)

    flight = parse_best_flight(results)
    if not flight:
        logging.warning("No flights found.")
        sys.exit(0)

    price = flight["price"]
    logging.info(f"Lowest fare: ${price} (Threshold: ${threshold})")

    if price < threshold:
        # Formatted to match your screenshot layout
        message = (
            f"📍 <b>{flight['origin_name']} - {flight['dest_name']}</b>\n\n"
            f"{flight['origin_name']} ({flight['origin_id']}) - {flight['dest_name']} ({flight['dest_id']})\n"
            f"🔄 Stops: {flight['stops']}\n"
            f"🕒 Departure: {flight['departure']}\n"
            f"🕒 Arrival: {flight['arrival']}\n\n"
            f"🎫 <b>{flight['vendor']}</b>: <b>${price:.2f} USD</b>\n"
            f"💳 <a href=\"{flight['booking_url']}\"><b>Buy ticket</b></a>"
        )

        send_telegram_alert(
            config["TELEGRAM_BOT_TOKEN"],
            config["TELEGRAM_CHAT_ID"],
            message,
        )
        logging.info("Telegram notification sent.")
    else:
        logging.info("Price is above threshold; alert suppressed.")


if __name__ == "__main__":
    main()
