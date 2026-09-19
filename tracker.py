import logging
import os
import sys
from importlib import import_module

import requests

try:
    GoogleSearch = import_module("serpapi").GoogleSearch
except (ImportError, AttributeError):
    GoogleSearch = None

try:
    load_dotenv = import_module("dotenv").load_dotenv
except (ImportError, AttributeError):
    def load_dotenv() -> None:
        """Allow the tracker to run when python-dotenv is not installed."""
        return None


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


def fetch_flights(api_key: str, origin: str, destination: str, depart_date: str) -> dict:
    if GoogleSearch is None:
        raise SystemExit(
            "The 'serpapi' package is required. Install it with: pip install serpapi"
        )
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": depart_date,
        "type": 2,  # one-way
        "currency": "USD",
        "hl": "en",
        "api_key": api_key,
    }
    return GoogleSearch(params).get_dict()


def lowest_fare(results: dict) -> float | None:
    prices: list[float] = []
    for key in ("best_flights", "other_flights"):
        for offer in results.get(key) or []:
            price = offer.get("price")
            if price is not None:
                prices.append(float(price))
    return min(prices) if prices else None


def send_telegram_alert(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
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

    price = lowest_fare(results)
    if price is None:
        logging.warning("No flight prices found in best_flights or other_flights.")
        sys.exit(0)

    logging.info(
        "Lowest fare %s -> %s on %s: $%.2f (threshold $%.2f)",
        config["ORIGIN"],
        config["DESTINATION"],
        config["DEPART_DATE"],
        price,
        threshold,
    )

    if price < threshold:
        message = (
            f"Flight alert: {config['ORIGIN']} → {config['DESTINATION']} "
            f"on {config['DEPART_DATE']}\n"
            f"Lowest fare: ${price:.2f} (below ${threshold:.2f})"
        )
        send_telegram_alert(
            config["TELEGRAM_BOT_TOKEN"],
            config["TELEGRAM_CHAT_ID"],
            message,
        )
        logging.info("Telegram alert sent.")
    else:
        logging.info("Price is not below threshold; no alert sent.")


if __name__ == "__main__":
    main()
