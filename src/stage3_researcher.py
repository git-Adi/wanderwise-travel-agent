"""Stage 3: deep destination research for the chosen destination."""

from .agent import run_agent
from .settings import extract_json, load_prompt


async def research_destination(host, destination, travel_dates, return_date, party, budget, model, on_event=None):
    system = load_prompt("stage3_researcher.md")
    user = (
        f"Destination: {destination}\n"
        f"Travel dates: {travel_dates} to {return_date}\n"
        f"Party: {party}\n"
        f"Budget band: {budget}\n\n"
        "Research this destination thoroughly and return the JSON brief."
    )
    raw = await run_agent(
        host,
        system=system,
        user=user,
        model=model,
        tool_servers=["exa"],
        only_tools={"exa__web_search_exa"},
        max_turns=8,
        max_tokens=2048,
        on_event=on_event,
    )
    return extract_json(raw)
