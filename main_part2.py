"""Part 2 CLI — interactive itinerary builder.

Takes Part 1 output (JSON file or inline) and guides the user through:
  - destination selection from ranked list
  - date confirmation / entry
  - budget confirmation / entry
  - transport preference (flight / train / road)
  - flight selection (if applicable)
  - hotel selection from top options
Then runs the 3-agent pipeline and saves the final itinerary to Google Drive.

Examples:
    python main_part2.py --part1 output.json
    python main_part2.py --part1 output.json --no-save
"""

import argparse
import ast
import asyncio
import json
import sys
import os

from dotenv import load_dotenv
from src.settings import DEFAULT_MODEL, DRIVE_FOLDER_ID, load_servers
from src.mcp_host import MCPHost
from src.pipeline_part2 import run_part2

load_dotenv()


# ── helpers ────────────────────────────────────────────────────────────────────────────────

def _parse_mcp(raw):
    """Parse MCP tool output.

    FastMCP serializes list results as N separate JSON text blocks joined by newlines,
    so we try to collect all top-level JSON values from the string.
    """
    if not isinstance(raw, str):
        return raw
    raw = raw.strip()
    # try as a single valid JSON value first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # collect multiple concatenated JSON objects/arrays separated by newlines
    items = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(raw):
        # skip whitespace
        while idx < len(raw) and raw[idx] in " \t\n\r":
            idx += 1
        if idx >= len(raw):
            break
        try:
            obj, end = decoder.raw_decode(raw, idx)
            items.append(obj)
            idx = end
        except json.JSONDecodeError:
            break
    if items:
        return items if len(items) > 1 else items[0]
    try:
        return ast.literal_eval(raw)
    except Exception:
        return []


def ask(prompt: str, default: str = "") -> str:
    if default:
        val = input(f"{prompt} [{default}]: ").strip()
        return val if val else default
    val = input(f"{prompt}: ").strip()
    return val


def ask_choice(prompt: str, options: list, display_fn=None) -> int:
    """Print numbered options and return 0-based index of chosen item."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        label = display_fn(opt) if display_fn else str(opt)
        print(f"  {i}. {label}")
    while True:
        raw = input("Your choice (number): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"  Please enter a number between 1 and {len(options)}.")


def parse_args():
    p = argparse.ArgumentParser(description="Part 2: interactive itinerary builder")
    p.add_argument("--part1", required=True, help="Path to Part 1 JSON output file")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--folder-id", default=DRIVE_FOLDER_ID)
    p.add_argument("--no-save", action="store_true")
    p.add_argument("--json", action="store_true", help="Print full result as JSON")
    return p.parse_args()


# ── flight search ──────────────────────────────────────────────────────────

_IATA = {
    "delhi": "DEL", "new delhi": "DEL", "mumbai": "BOM", "bangalore": "BLR",
    "bengaluru": "BLR", "chennai": "MAA", "kolkata": "CCU", "hyderabad": "HYD",
    "bali": "DPS", "denpasar": "DPS", "bangkok": "BKK", "singapore": "SIN",
    "dubai": "DXB", "london": "LHR", "new york": "JFK", "paris": "CDG",
    "tokyo": "NRT", "sydney": "SYD", "maldives": "MLE", "male": "MLE",
    "seychelles": "SEZ", "mahe": "SEZ", "phuket": "HKT", "colombo": "CMB",
    "kathmandu": "KTM", "kuala lumpur": "KUL", "hong kong": "HKG",
}

def _city_to_iata(city: str) -> str:
    key = city.split(",")[0].strip().lower()
    return _IATA.get(key, key.upper()[:3])


async def fetch_flights(host, from_city, to_city, depart_date, adults, on_event):
    """Search flights via Google Flights (SerpAPI). Returns list of flights."""
    from_code = _city_to_iata(from_city)
    to_code = _city_to_iata(to_city)
    on_event(f"  Searching Google Flights {from_code} → {to_code} on {depart_date}...")
    flights_raw = await host.call("booking__search_flights", {
        "from_airport": from_code,
        "to_airport": to_code,
        "depart_date": depart_date,
        "adults": adults,
        "currency": "INR",
    })
    flights = _parse_mcp(flights_raw)
    return flights or [], from_code, to_code


# ── hotel search ────────────────────────────────────────────────────────────

async def fetch_hotels(host, destination, checkin, checkout, adults, budget, on_event):
    city_query = destination.split(",")[0].strip()
    budget_max = {"shoestring": 3000, "mid-range": 10000, "premium": 0}.get(budget.lower(), 0)
    on_event(f"  Searching Google Hotels in {city_query}...")
    hotels_raw = await host.call("booking__search_hotels", {
        "city": city_query,
        "checkin_date": checkin,
        "checkout_date": checkout,
        "adults": adults,
        "currency": "INR",
        "budget_max": budget_max,
    })
    hotels = _parse_mcp(hotels_raw)
    return hotels or []


# ── main ────────────────────────────────────────────────────────────────────────

async def _main_async(args):
    # load Part 1 output
    with open(args.part1) as f:
        part1 = json.load(f)

    stage1 = part1.get("stage1", {})
    stage2 = part1.get("stage2", {})
    parsed = stage1.get("parsed_conditions", {})
    ranked = stage2.get("ranked_locations", [])

    print("\n" + "═" * 60)
    print("  WanderWise — Part 2: Itinerary Builder")
    print("═" * 60)

    # ── step 1: choose destination ────────────────────────
    if not ranked:
        print("No ranked destinations found in Part 1 output.")
        sys.exit(1)

    idx = ask_choice(
        "Which destination would you like to visit?",
        ranked,
        display_fn=lambda d: f"{d['name']}  ({d['match_score']}/100) — {d.get('why_it_fits', '')[:60]}..."
    )
    destination = ranked[idx]["name"]
    print(f"\n✓ Destination: {destination}")

    # ── step 2: departure city ────────────────────────────
    departure_city = parsed.get("origin", "")
    if not departure_city or departure_city == "unspecified":
        departure_city = ask("Departure city")
    else:
        departure_city = ask("Departure city", default=departure_city)
    print(f"✓ Departure: {departure_city}")

    # ── step 3: travel dates ────────────────────────────
    travel_date = ask("Start date (YYYY-MM-DD)")
    return_date = ask("Return date (YYYY-MM-DD)")
    print(f"✓ Dates: {travel_date} → {return_date}")

    # ── step 4: budget ────────────────────────────────
    budget = parsed.get("budget_band", "")
    if not budget or budget == "unspecified":
        budget = ask("Budget band", default="mid-range")
    else:
        budget = ask("Budget band", default=budget)
    print(f"✓ Budget: {budget}")

    # ── step 5: party / adults ────────────────────────
    party = parsed.get("party", "")
    if not party or party == "unspecified":
        party = ask("Party (e.g. solo, couple, family of 4)", default="couple")
    else:
        party = ask("Party", default=party)
    try:
        adults = int(ask("Number of adults", default="2"))
    except ValueError:
        adults = 2
    print(f"✓ Party: {party} ({adults} adults)")

    # ── step 6: transport preference ─────────────────────
    transport_choice = ask_choice(
        "How would you like to travel?",
        ["Flight", "Train", "Road (self-drive / bus)"],
    )
    transport_labels = ["flight", "train", "road"]
    transport_choice = transport_labels[transport_choice]
    print(f"✓ Transport: {transport_choice}")

    # ── step 7: fetch and select transport ──────────────────
    selected_transport = {}
    servers = load_servers()

    if transport_choice == "flight":
        async with MCPHost(servers, only=["booking"]) as host:
            flights, from_id, to_id = await fetch_flights(
                host, departure_city, destination, travel_date, adults,
                on_event=lambda m: print(m, file=sys.stderr)
            )

        if flights:
            def flight_label(f):
                return (
                    f"{f.get('airline', '?')} {f.get('flight_number', '')}  "
                    f"{f.get('departure', '?')} → {f.get('arrival', '?')}  "
                    f"({f.get('stops', 0)} stops)  "
                    f"₹{f.get('price', '?')}"
                )
            idx_f = ask_choice("Select your flight:", flights, display_fn=flight_label)
            selected_transport = flights[idx_f]
            print(f"✓ Flight selected: {selected_transport.get('airline')} {selected_transport.get('flight_number')}")
        else:
            print("  No flights found. Proceeding without flight selection.")

    elif transport_choice == "train":
        print("\n  Train search requires an IRCTC / erail API key (not configured).")
        train_number = ask("Enter train name or number manually (or press Enter to skip)", default="")
        if train_number:
            selected_transport = {"train": train_number, "note": "Manually entered"}
            print(f"✓ Train: {train_number}")

    else:
        selected_transport = {"mode": "road", "note": "Self-drive or bus"}
        print("✓ Road transport selected.")

    # ── step 8: fetch and select hotel ─────────────────────
    selected_hotel = {}
    async with MCPHost(servers, only=["booking"]) as host:
        hotels = await fetch_hotels(
            host, destination, travel_date, return_date, adults, budget,
            on_event=lambda m: print(m, file=sys.stderr)
        )

    if hotels:
        def hotel_label(h):
            return (
                f"{h.get('name', '?')}  "
                f"Rating: {h.get('rating', '?')} ({h.get('review_label', '')})  "
                f"₹{h.get('price_per_night', '?')}/night"
            )
        idx_h = ask_choice("Select your hotel:", hotels[:5], display_fn=hotel_label)
        selected_hotel = hotels[idx_h]
        print(f"✓ Hotel selected: {selected_hotel.get('name')}")
    else:
        print("  No hotels found via API. Proceeding without hotel pre-selection.")

    # ── step 9: run 3-agent pipeline ──────────────────────
    print("\n" + "─" * 60)
    print("Running the 3-agent pipeline...")
    print("─" * 60)

    result = await run_part2(
        destination=destination,
        travel_dates=travel_date,
        return_date=return_date,
        party=party,
        adults=adults,
        budget=budget,
        departure_city=departure_city,
        transport_choice=transport_choice,
        selected_transport=selected_transport,
        selected_hotel=selected_hotel,
        model=args.model,
        drive_folder_id=args.folder_id,
        save=not args.no_save,
        on_event=lambda m: print(m, file=sys.stderr),
    )

    # ── output ─────────────────────────────────────────────────────
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("\n" + "═" * 60)
        print("  YOUR ITINERARY")
        print("═" * 60)
        print(result["itinerary_markdown"])


def main():
    args = parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
