"""Stage 2: execute the research brief with live MCP tools and rank destinations.

Uses the Exa and weather servers. Returns a dict with ranked_locations, a summary,
and the itinerary_prompt_template that feeds Part 2 of the project.
"""

from .agent import run_agent
from .settings import extract_json_safe, load_prompt


async def research_and_rank(host, research_template, model, on_event=None):
    system = load_prompt("stage2_system.md")
    user = (
        "Here is the research brief produced by the upstream Trip Conditions Planner. "
        "Use your tools to investigate the candidates, then return the JSON object.\n\n"
        f"{research_template}"
    )
    raw = await run_agent(
        host,
        system=system,
        user=user,
        model=model,
        tool_servers=["exa", "weather"],
        max_turns=24,
        max_tokens=4096,
        on_event=on_event,
    )
    return await extract_json_safe(raw, model, on_event=on_event)
