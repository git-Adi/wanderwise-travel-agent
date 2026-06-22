"""Stage 1: turn a free-form travel query into a structured research template."""

from .agent import run_agent
from .settings import extract_json, load_prompt


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
        tool_servers=None,
        max_turns=1,
        max_tokens=4096,
    )
    return extract_json(raw)
