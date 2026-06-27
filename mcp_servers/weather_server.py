"""Weather MCP server backed by Open-Meteo (free, no API key).

Exposes three tools over stdio:
  - geocode_location: resolve a place name to coordinates
  - get_weather_forecast: near-term daily forecast (up to ~16 days out)
  - get_climate_normals: historical daily weather for the same calendar dates in prior years
"""

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_DAILY = (
    "temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "precipitation_probability_max,weather_code,wind_speed_10m_max"
)


@mcp.tool()
def geocode_location(name: str, count: int = 5) -> list[dict]:
    """Resolve a place name to candidate coordinates.

    Returns a list of matches with latitude/longitude, region, country, elevation
    and population so the caller can pick the intended place.
    """
    resp = httpx.get(
        GEOCODE_URL,
        params={"name": name, "count": count, "language": "en", "format": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    return [
        {
            "name": r.get("name"),
            "region": r.get("admin1"),
            "country": r.get("country"),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
            "elevation_m": r.get("elevation"),
            "population": r.get("population"),
        }
        for r in results
    ]


@mcp.tool()
def get_weather_forecast(
    latitude: float,
    longitude: float,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Daily weather forecast for coordinates.

    Dates are ISO YYYY-MM-DD. Forecast supports roughly the next 16 days; for travel
    further out use get_climate_normals instead. Omit dates for the default next 7 days.
    """
    params = {"latitude": latitude, "longitude": longitude, "daily": _DAILY, "timezone": "auto"}
    if start_date and end_date:
        params["start_date"] = start_date
        params["end_date"] = end_date
    resp = httpx.get(FORECAST_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("daily", {})


@mcp.tool()
def get_climate_normals(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    """Historical daily weather for the given calendar window in PRIOR years.

    Use this to estimate seasonal conditions when the trip is more than ~14 days away.
    Pass the same month/day range as the planned trip but in a past year
    (e.g. 2024-10-05 to 2024-10-09 for an early-October trip).
    """
    resp = httpx.get(
        ARCHIVE_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("daily", {})


if __name__ == "__main__":
    mcp.run()
