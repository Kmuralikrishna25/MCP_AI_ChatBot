

import os
from datetime import date

import httpx
from dotenv import load_dotenv


load_dotenv(override=True)

DUFFEL_ACCESS_TOKEN = os.getenv("DUFFEL_ACCESS_TOKEN")
DUFFEL_BASE_URL = os.getenv(
    "DUFFEL_BASE_URL",
    "https://api.duffel.com",
).rstrip("/")


async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    cabin_class: str = "economy",
) -> dict:
    """Search one-way flights using Duffel. Airport codes must be IATA codes."""

    if not DUFFEL_ACCESS_TOKEN:
        return {"error": "DUFFEL_ACCESS_TOKEN is not configured."}

    origin = origin.strip().upper()
    destination = destination.strip().upper()

    if (
        len(origin) != 3
        or not origin.isalpha()
        or len(destination) != 3
        or not destination.isalpha()
    ):
        return {"error": "Use valid three-letter IATA airport codes."}

    if origin == destination:
        return {"error": "Origin and destination must be different."}

    try:
        travel_date = date.fromisoformat(departure_date)
    except ValueError:
        return {"error": "Date must be in YYYY-MM-DD format."}

    if travel_date < date.today():
        return {"error": "Departure date cannot be in the past."}

    if not 1 <= adults <= 9:
        return {"error": "Adults must be between 1 and 9."}

    allowed_cabins = {
        "economy",
        "premium_economy",
        "business",
        "first",
    }

    if cabin_class not in allowed_cabins:
        return {"error": "Unsupported cabin class."}

    payload = {
        "data": {
            "slices": [
                {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": departure_date,
                }
            ],
            "passengers": [
                {"type": "adult"}
                for _ in range(adults)
            ],
            "cabin_class": cabin_class,
        }
    }

    headers = {
        "Authorization": f"Bearer {DUFFEL_ACCESS_TOKEN}",
        "Duffel-Version": "v2",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{DUFFEL_BASE_URL}/air/offer_requests",
                headers=headers,
                params={
                    "return_offers": "true",
                    "supplier_timeout": 20000,
                },
                json=payload,
            )

            response.raise_for_status()

            data = response.json().get("data", {})
            offers = data.get("offers", [])

            results = []

            for offer in offers[:10]:
                slices = []

                for flight_slice in offer.get("slices", []):
                    segments = []

                    for segment in flight_slice.get("segments", []):
                        carrier = segment.get(
                            "operating_carrier", {}
                        ) or {}

                        segments.append({
                            "airline": carrier.get("name"),
                            "flight_number": (
                                segment.get("operating_carrier_flight_number")
                            ),
                            "origin": (
                                segment.get("origin", {}).get("iata_code")
                            ),
                            "destination": (
                                segment.get("destination", {}).get("iata_code")
                            ),
                            "departing_at": segment.get("departing_at"),
                            "arriving_at": segment.get("arriving_at"),
                        })

                    slices.append({
                        "duration": flight_slice.get("duration"),
                        "segments": segments,
                    })

                results.append({
                    "offer_id": offer.get("id"),
                    "total_amount": offer.get("total_amount"),
                    "total_currency": offer.get("total_currency"),
                    "expires_at": offer.get("expires_at"),
                    "slices": slices,
                })

            return {
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
                "adults": adults,
                "cabin_class": cabin_class,
                "test_mode": not data.get("live_mode", False),
                "total_offers_returned": len(offers),
                "offers": results,
            }

    except httpx.HTTPStatusError as error:
        try:
            details = error.response.json().get("errors", [])
        except ValueError:
            details = []

        return {
            "error": "Duffel flight search failed.",
            "status_code": error.response.status_code,
            "details": [
                {
                    "code": item.get("code"),
                    "message": item.get("message"),
                }
                for item in details[:3]
            ],
        }

    except httpx.RequestError:
        return {
            "error": "Unable to connect to Duffel API."
        }
