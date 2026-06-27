"""Flights + Hotels MCP server via SerpAPI (Google Flights & Google Hotels).

Exposes tools over stdio:
  - search_flights: search one-way flights using Google Flights
  - search_hotels: search hotels using Google Hotels
"""

import os
from mcp.server.fastmcp import FastMCP
from serpapi import GoogleSearch

mcp = FastMCP("booking")

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")


@mcp.tool()
def search_flights(
    from_airport: str,
    to_airport: str,
    depart_date: str,
    adults: int = 2,
    currency: str = "INR",
) -> list[dict]:
    """Search one-way flights using Google Flights.

    Args:
        from_airport: Origin IATA code e.g. 'DEL'
        to_airport:   Destination IATA code e.g. 'DPS'
        depart_date:  Departure date in YYYY-MM-DD format
        adults:       Number of adult passengers (default 2)
        currency:     Currency code e.g. INR, USD (default INR)

    Returns list of flights with airline, times, price, stops, duration, and booking link.
    """
    params = {
        "engine": "google_flights",
        "departure_id": from_airport,
        "arrival_id": to_airport,
        "outbound_date": depart_date,
        "adults": adults,
        "currency": currency,
        "type": "2",  # 2 = one-way
        "api_key": SERPAPI_KEY,
    }
    results = GoogleSearch(params).get_dict()
    flights = []
    for f in (results.get("best_flights") or []) + (results.get("other_flights") or []):
        legs = f.get("flights", [{}])
        first = legs[0] if legs else {}
        last = legs[-1] if legs else {}
        booking_link = f.get("booking_token", "")
        if booking_link:
            booking_link = f"https://www.google.com/flights?hl=en#flt={from_airport}.{to_airport}.{depart_date};c:{currency};e:1;s:0*0;sd:1;t:f;tt:o;bk:{booking_link}"
        else:
            booking_link = (
                f"https://www.google.com/flights?hl=en#flt={from_airport}.{to_airport}"
                f".{depart_date};c:{currency};e:1;s:0*0;sd:1;t:f;tt:o"
            )
        flights.append({
            "airline": first.get("airline", "Unknown"),
            "flight_number": first.get("flight_number", ""),
            "departure": first.get("departure_airport", {}).get("time", ""),
            "arrival": last.get("arrival_airport", {}).get("time", ""),
            "duration_minutes": f.get("total_duration", 0),
            "stops": len(legs) - 1,
            "price": f.get("price", "N/A"),
            "currency": currency,
            "airline_logo": first.get("airline_logo", ""),
            "booking_link": booking_link,
        })
        if len(flights) >= 8:
            break
    return flights


@mcp.tool()
def search_hotels(
    city: str,
    checkin_date: str,
    checkout_date: str,
    adults: int = 2,
    currency: str = "INR",
    budget_max: int = 0,
) -> list[dict]:
    """Search hotels using Google Hotels.

    Args:
        city:          Destination city name e.g. 'Bali'
        checkin_date:  Check-in date in YYYY-MM-DD format
        checkout_date: Check-out date in YYYY-MM-DD format
        adults:        Number of adults (default 2)
        currency:      Currency code e.g. INR, USD (default INR)
        budget_max:    Max price per night (0 = no limit)

    Returns list of hotels with name, rating, price, amenities, and booking link.
    """
    params = {
        "engine": "google_hotels",
        "q": f"hotels in {city}",
        "check_in_date": checkin_date,
        "check_out_date": checkout_date,
        "adults": adults,
        "currency": currency,
        "api_key": SERPAPI_KEY,
        "gl": "in",
        "hl": "en",
    }
    if budget_max:
        params["max_price"] = budget_max

    results = GoogleSearch(params).get_dict()
    hotels = []
    for h in (results.get("properties") or [])[:10]:
        hotels.append({
            "name": h.get("name", "Unknown"),
            "rating": h.get("overall_rating", "N/A"),
            "review_count": h.get("reviews", 0),
            "price_per_night": h.get("rate_per_night", {}).get("lowest", "N/A"),
            "currency": currency,
            "amenities": h.get("amenities", [])[:6],
            "description": h.get("description", ""),
            "address": h.get("neighborhood", h.get("location", "")),
            "booking_link": h.get("link") or "",
            "thumbnail": h.get("thumbnail", ""),
        })
    return hotels


if __name__ == "__main__":
    mcp.run()
