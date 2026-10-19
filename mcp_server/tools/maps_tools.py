

import asyncio
import math
import os
import time
from typing import Literal

import httpx
from dotenv import load_dotenv


load_dotenv()

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

USER_AGENT = os.getenv("MAPS_USER_AGENT", "").strip()

if not USER_AGENT or "@" not in USER_AGENT:
    raise ValueError(
        "Set MAPS_USER_AGENT in .env with an application "
        "name and valid contact email."
    )

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

_geocode_cache = {}
_geocode_lock = asyncio.Lock()
_last_geocode_request = 0.0


def valid_coordinates(latitude, longitude):
    try:
        latitude = float(latitude)
        longitude = float(longitude)

        return (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        )

    except (TypeError, ValueError):
        return False


def build_search_queries(location):
    location = location.strip()

    queries = [location]

    parts = [
        part.strip()
        for part in location.split(",")
        if part.strip()
    ]

    if len(parts) > 1:
        queries.append(", ".join(parts[:2]))

    if len(parts) > 2:
        queries.append(", ".join(parts[-2:]))

    lower_location = location.lower()

    if "hyderabad airport" in lower_location:
        queries.append(
            "Rajiv Gandhi International Airport, Hyderabad"
        )

    if "rajiv gandhi international airport" in lower_location:
        queries.append(
            "Shamshabad Airport, Telangana, India"
        )

    if "charminar" in lower_location:
        queries.append("Charminar, Hyderabad")

    unique_queries = []
    seen = set()

    for query in queries:
        key = query.casefold()

        if key not in seen:
            unique_queries.append(query)
            seen.add(key)

    return unique_queries[:4]


async def geocode_location(location: str) -> dict:
    global _last_geocode_request

    location = location.strip()

    if not location:
        return {
            "status": "error",
            "message": "Location cannot be empty.",
        }

    cache_key = location.casefold()

    async with _geocode_lock:
        if cache_key in _geocode_cache:
            return _geocode_cache[cache_key]

        queries = build_search_queries(location)

        try:
            async with httpx.AsyncClient(
                timeout=25.0,
                headers=HEADERS,
                follow_redirects=True,
            ) as client:
                for query in queries:
                    elapsed = (
                        time.monotonic()
                        - _last_geocode_request
                    )

                    if elapsed < 1.1:
                        await asyncio.sleep(1.1 - elapsed)

                    _last_geocode_request = time.monotonic()

                    response = await client.get(
                        NOMINATIM_URL,
                        params={
                            "q": query,
                            "format": "jsonv2",
                            "addressdetails": 1,
                            "limit": 5,
                        },
                    )

                    response.raise_for_status()
                    data = response.json()

                    if not data:
                        continue

                    place = data[0]

                    latitude = float(place["lat"])
                    longitude = float(place["lon"])

                    if not valid_coordinates(
                        latitude, longitude
                    ):
                        continue

                    result = {
                        "status": "success",
                        "requested_location": location,
                        "location": place["display_name"],
                        "latitude": latitude,
                        "longitude": longitude,
                        "provider": "OpenStreetMap Nominatim",
                        "attribution": "© OpenStreetMap contributors",
                    }

                    _geocode_cache[cache_key] = result

                    return result

            return {
                "status": "error",
                "message": (
                    f"No coordinates found for '{location}'. "
                    "Try a shorter or more specific place name."
                ),
            }

        except httpx.HTTPStatusError as error:
            return {
                "status": "error",
                "message": (
                    f"Nominatim returned HTTP "
                    f"{error.response.status_code}: "
                    f"{error.response.text[:200]}"
                ),
            }

        except httpx.TimeoutException:
            return {
                "status": "error",
                "message": "Geocoding request timed out.",
            }

        except (httpx.RequestError, ValueError, KeyError) as error:
            return {
                "status": "error",
                "message": (
                    f"Geocoding failed: "
                    f"{type(error).__name__}: {error}"
                ),
            }


async def get_directions(
    origin: str,
    destination: str,
) -> dict:
    start = await geocode_location(origin)

    if start["status"] != "success":
        return {
            "status": "error",
            "message": (
                f"Could not find origin: "
                f"{start.get('message')}"
            ),
        }

    end = await geocode_location(destination)

    if end["status"] != "success":
        return {
            "status": "error",
            "message": (
                f"Could not find destination: "
                f"{end.get('message')}"
            ),
        }

    coordinates = (
        f"{start['longitude']},{start['latitude']};"
        f"{end['longitude']},{end['latitude']}"
    )

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers=HEADERS,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                f"{OSRM_URL}/{coordinates}",
                params={
                    "overview": "false",
                    "steps": "false",
                },
            )

            response.raise_for_status()
            data = response.json()

        if (
            data.get("code") != "Ok"
            or not data.get("routes")
        ):
            return {
                "status": "error",
                "message": "No driving route found.",
            }

        route = data["routes"][0]

        return {
            "status": "success",
            "origin": start["location"],
            "destination": end["location"],
            "distance_km": round(
                route["distance"] / 1000, 2
            ),
            "estimated_duration_minutes": round(
                route["duration"] / 60, 1
            ),
            "travel_mode": "driving",
            "live_traffic_included": False,
            "provider": "OSRM / OpenStreetMap",
            "attribution": "© OpenStreetMap contributors",
        }

    except httpx.HTTPStatusError as error:
        return {
            "status": "error",
            "message": (
                f"Routing API returned HTTP "
                f"{error.response.status_code}."
            ),
        }

    except httpx.TimeoutException:
        return {
            "status": "error",
            "message": "Routing request timed out.",
        }

    except (httpx.RequestError, ValueError, KeyError) as error:
        return {
            "status": "error",
            "message": (
                f"Routing failed: "
                f"{type(error).__name__}: {error}"
            ),
        }


async def search_nearby_places(
    location: str,
    category: Literal[
        "restaurant",
        "hotel",
        "cafe",
        "hospital",
        "attraction",
    ] = "restaurant",
    radius_meters: int = 1500,
) -> dict:
    if not 100 <= radius_meters <= 5000:
        return {
            "status": "error",
            "message": (
                "Radius must be between "
                "100 and 5000 meters."
            ),
        }

    center = await geocode_location(location)

    if center["status"] != "success":
        return {
            "status": "error",
            "message": center.get(
                "message",
                "Unable to find location.",
            ),
        }

    latitude = center["latitude"]
    longitude = center["longitude"]

    category_filters = {
        "restaurant": '["amenity"="restaurant"]',
        "hotel": '["tourism"="hotel"]',
        "cafe": '["amenity"="cafe"]',
        "hospital": '["amenity"="hospital"]',
        "attraction": (
            '["tourism"~"^(attraction|museum|gallery)$"]'
        ),
    }

    osm_filter = category_filters[category]

    query = f"""
    [out:json][timeout:25];
    (
        nwr{osm_filter}(around:{radius_meters},{latitude},{longitude});
    );
    out center 30;
    """

    errors = []

    for overpass_url in OVERPASS_URLS:
        try:
            async with httpx.AsyncClient(
                timeout=40.0,
                headers=HEADERS,
                follow_redirects=True,
            ) as client:
                response = await client.post(
                    overpass_url,
                    data={"data": query},
                )

                response.raise_for_status()
                data = response.json()

            places = []

            for element in data.get("elements", []):
                tags = element.get("tags", {})
                name = tags.get("name")

                if not name:
                    continue

                center_point = element.get(
                    "center", {}
                )

                place_lat = element.get(
                    "lat",
                    center_point.get("lat"),
                )

                place_lon = element.get(
                    "lon",
                    center_point.get("lon"),
                )

                if not valid_coordinates(
                    place_lat, place_lon
                ):
                    continue

                places.append(
                    {
                        "name": name,
                        "latitude": float(place_lat),
                        "longitude": float(place_lon),
                        "address": tags.get(
                            "addr:street"
                        ),
                        "website": tags.get(
                            "website"
                        ),
                        "osm_type": element.get(
                            "type"
                        ),
                        "osm_id": element.get(
                            "id"
                        ),
                    }
                )

            return {
                "status": "success",
                "searched_location": center["location"],
                "category": category,
                "radius_meters": radius_meters,
                "total_results": len(places),
                "places": places[:15],
                "note": (
                    "Results come from OpenStreetMap. "
                    "Opening hours, availability and "
                    "prices are not verified."
                ),
                "provider": "OpenStreetMap Overpass",
                "attribution": "© OpenStreetMap contributors",
            }

        except httpx.HTTPStatusError as error:
            errors.append(
                f"{overpass_url}: "
                f"HTTP {error.response.status_code}"
            )

        except httpx.TimeoutException:
            errors.append(
                f"{overpass_url}: Request timed out"
            )

        except (
            httpx.RequestError,
            ValueError,
            KeyError,
        ) as error:
            errors.append(
                f"{overpass_url}: "
                f"{type(error).__name__}: {error}"
            )

    return {
        "status": "error",
        "message": (
            "All Overpass API endpoints failed."
        ),
        "details": errors,
    }
