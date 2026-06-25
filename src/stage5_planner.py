"""Stage 5: build the full day-by-day itinerary."""

import json
from .agent import run_agent
from .settings import extract_json, load_prompt


async def build_itinerary(
    host,
    destination,
    travel_dates,
    return_date,
    party,
    budget,
    transport_choice,
    selected_transport,
    selected_hotel,
    researcher_brief,
    hotel_brief,
    model,
    on_event=None,
):
    system = load_prompt("stage5_planner.md")
    # summarise briefs to avoid context overflow
    attractions = researcher_brief.get("top_attractions", [])[:5]
    activities = researcher_brief.get("recommended_activities", [])[:6]
    day_flow = researcher_brief.get("suggested_day_flow", [])
    hotels_top = hotel_brief.get("top_hotels", [])[:3]
    dining = hotel_brief.get("dining_recommendations", [])[:5]

    user = (
        f"Destination: {destination}\n"
        f"Travel dates: {travel_dates} to {return_date}\n"
        f"Party: {party}\n"
        f"Budget band: {budget}\n"
        f"Transport chosen: {transport_choice}\n"
        f"Transport details: {json.dumps(selected_transport)}\n"
        f"Selected hotel: {json.dumps(selected_hotel)}\n\n"
        f"Climate: {researcher_brief.get('climate_summary', '')}\n"
        f"Culture tips: {researcher_brief.get('culture_and_customs', '')}\n"
        f"Safety: {researcher_brief.get('safety_tips', '')}\n"
        f"Top attractions: {json.dumps(attractions)}\n"
        f"Activities: {json.dumps(activities)}\n"
        f"Suggested day flow: {json.dumps(day_flow)}\n"
        f"Local transport: {researcher_brief.get('local_transport', '')}\n"
        f"Practical tips: {researcher_brief.get('practical_tips', '')}\n\n"
        f"Top hotels: {json.dumps(hotels_top)}\n"
        f"Dining: {json.dumps(dining)}\n\n"
        "Build the complete day-by-day itinerary and return the JSON."
    )
    raw = await run_agent(
        host,
        system=system,
        user=user,
        model=model,
        tool_servers=None,
        max_turns=1,
        max_tokens=2048,
        on_event=on_event,
    )
    return extract_json(raw)
