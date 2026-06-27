"""Stage 4: find hotels and dining options using Booking.com + Exa."""

from .agent import run_agent
from .settings import extract_json_safe, load_prompt


async def find_hotels(host, destination, checkin, checkout, adults, budget, model, on_event=None):
    system = load_prompt("stage4_hotel_finder.md")
    user = (
        f"Destination: {destination}\n"
        f"Check-in: {checkin}\n"
        f"Check-out: {checkout}\n"
        f"Adults: {adults}\n"
        f"Budget band: {budget}\n\n"
        "Find the best hotels and dining options. Return the JSON."
    )
    raw = await run_agent(
        host,
        system=system,
        user=user,
        model=model,
        tool_servers=["booking", "exa"],
        max_turns=6,
        max_tokens=3000,
        on_event=on_event,
    )
    return await extract_json_safe(raw, model, on_event=on_event)
