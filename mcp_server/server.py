
import os
import httpx
from datetime import datetime, timezone
from tavily import AsyncTavilyClient
from mcp.server.fastmcp import FastMCP
from urllib.parse import quote
from mcp_server.tools.duffel_tools import search_flights
from mcp_server.tools.currency_tools import convert_currency
from mcp_server.tools.maps_tools import (
    geocode_location,
    get_directions,
    search_nearby_places,
)
from dotenv import load_dotenv



load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

mcp = FastMCP("AI Chatbot Tools")


@mcp.tool()
def calculate(a: float, b: float, operation: str) -> float:
    """Perform addition, subtraction, multiplication or division."""

    if operation == "add":
        return a + b

    if operation == "subtract":
        return a - b

    if operation == "multiply":
        return a * b

    if operation == "divide":
        if b == 0:
            raise ValueError("Cannot divide by zero.")
        return a / b

    raise ValueError("Unsupported operation.")


@mcp.tool()
def get_current_time() -> str:
    """Get the current UTC date and time from the server."""

    return datetime.now(timezone.utc).isoformat()

@mcp.tool()
async def web_search(query: str) -> dict:
    """Search the live internet for recent information, news and facts."""

    if not TAVILY_API_KEY:
        return {"error": "TAVILY_API_KEY is not configured."}

    if not query.strip():
        return {"error": "Search query cannot be empty."}

    client = AsyncTavilyClient(api_key=TAVILY_API_KEY)

    try:
        response = await client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=False,
        )

        results = [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "content": item.get("content"),
            }
            for item in response.get("results", [])
        ]

        return {"query": query, "results": results}

    except Exception:
        return {"error": "Web search failed. Please try again."}


@mcp.tool()
async def fetch_webpage(url: str) -> dict:
    """Extract readable content from a public HTTPS webpage."""

    if not TAVILY_API_KEY:
        return {"error": "TAVILY_API_KEY is not configured."}

    if not url.startswith("https://"):
        return {"error": "Only HTTPS webpage URLs are supported."}

    client = AsyncTavilyClient(api_key=TAVILY_API_KEY)

    try:
        response = await client.extract(urls=[url])

        results = response.get("results", [])

        if not results:
            return {"error": "No readable content found."}

        page = results[0]

        return {
            "url": page.get("url"),
            "content": page.get("raw_content", "")[:12000],
        }

    except Exception:
        return {"error": "Unable to extract webpage content."}


@mcp.tool()
async def get_weather(city: str) -> dict:
    """Get current weather conditions for a city."""

    async with httpx.AsyncClient(timeout=15.0) as client:
        location_response = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": city,
                "count": 1,
                "language": "en",
                "format": "json",
            },
        )
        location_response.raise_for_status()

        locations = location_response.json().get("results", [])

        if not locations:
            return {"error": f"City not found: {city}"}

        location = locations[0]

        weather_response = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": (
                    "temperature_2m,relative_humidity_2m,"
                    "apparent_temperature,precipitation,"
                    "wind_speed_10m,weather_code"
                ),
                "timezone": "auto",
            },
        )
        weather_response.raise_for_status()

        return {
            "city": location["name"],
            "country": location.get("country"),
            "timezone": weather_response.json().get("timezone"),
            "current": weather_response.json().get("current"),
            "units": weather_response.json().get("current_units"),
        }


@mcp.tool()
async def search_wikipedia(topic: str) -> dict:
    """Search Wikipedia and retrieve an article summary with its source URL."""

    if not topic.strip():
        return {"error": "Wikipedia search topic cannot be empty."}

    headers = {
        "User-Agent": "MCPAIChatbot/1.0 (contact: your-email@example.com)"
    }

    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            headers=headers,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": topic,
                    "gsrlimit": 1,
                    "prop": "extracts|info",
                    "exintro": 1,
                    "explaintext": 1,
                    "inprop": "url",
                    "format": "json",
                    "formatversion": 2,
                },
            )

            response.raise_for_status()

            pages = response.json().get(
                "query", {}
            ).get("pages", [])

            if not pages:
                return {
                    "error": "No Wikipedia article found.",
                    "topic": topic,
                }

            page = pages[0]

            return {
                "title": page.get("title"),
                "summary": page.get("extract", ""),
                "url": page.get("fullurl"),
            }

    except httpx.HTTPStatusError as error:
        return {
            "error": "Wikipedia API request failed.",
            "status_code": error.response.status_code,
        }

    except httpx.RequestError:
        return {
            "error": "Unable to connect to Wikipedia.",
        }
#calling the search_flights function from duffel_tools.py and registering it as a tool in the MCP server
mcp.tool()(search_flights)
#calling the convert_currency function from currency_tools.py and registering it as a tool in the MCP server
mcp.tool()(convert_currency)
#calling the geocode_location, get_directions, and search_nearby_places functions from maps_tools.py and registering them as tools in the MCP server
mcp.tool()(geocode_location)
mcp.tool()(get_directions)
mcp.tool()(search_nearby_places)
if __name__ == "__main__":
    mcp.run(transport="stdio")
