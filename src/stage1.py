"""Stage 1: turn a free-form travel query into a structured research template.

No tools are used here - it is a pure normalize-and-template step. Returns a dict
with parsed_conditions, assumptions, and the research_template prompt string.
"""

from .agent import run_agent
from .settings import extract_json_safe, load_prompt


async def build_research_template(host, user_query, model):
    system = load_prompt("stage1_system.md")
    user = (
        "User travel conditions (free-form):\n\n"
        f"{user_query}\n\n"
        "Produce the JSON object now."
    )
    raw = await run_agent(
        host,
        system=system,
        user=user,
        model=model,
        tool_servers=None,  # generation only
        max_turns=1,
        max_tokens=4096,
    )
    return await extract_json_safe(raw, model)
