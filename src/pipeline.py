"""Part-1 pipeline orchestration."""

import datetime as _dt

from .mcp_host import MCPHost
from .settings import DEFAULT_MODEL, DRIVE_FOLDER_ID, load_servers
from .stage1 import build_research_template
from .stage2 import research_and_rank


def _stamp():
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _render_ranked_markdown(stage2):
    lines = ["# Ranked Destinations\n", stage2.get("summary", ""), "\n"]
    for loc in stage2.get("ranked_locations", []):
        lines.append(f"## {loc.get('rank')}. {loc.get('name')}  (match {loc.get('match_score')}/100)")
        for key in (
            "why_it_fits",
            "weather_outlook",
            "logistics_and_traffic",
            "accommodation",
            "sightseeing_and_activities",
            "crowds_and_season",
            "safety_and_advisories",
            "standout_traveler_sentiment",
            "trade_offs_or_risks",
        ):
            if loc.get(key):
                label = key.replace("_", " ").title()
                lines.append(f"- **{label}:** {loc[key]}")
        sources = loc.get("sources") or []
        if sources:
            lines.append("- **Sources:** " + ", ".join(sources))
        lines.append("")
    lines.append("\n---\n\n# Itinerary Prompt Template (feeds Part 2)\n")
    lines.append(stage2.get("itinerary_prompt_template", ""))
    return "\n".join(lines)


async def _save_to_drive(host, filename, content, folder_id, on_event):
    if "gdrive" not in host.sessions:
        on_event(f"  ! Drive not connected ({host.failed.get('gdrive', 'unavailable')}); skipped {filename}")
        return None
    result = await host.call(
        "gdrive__upload_text_file",
        {"filename": filename, "content": content, "folder_id": folder_id, "mime_type": "text/markdown"},
    )
    on_event(f"  saved: {result}")
    return result


async def run_part1(
    user_query,
    *,
    model=DEFAULT_MODEL,
    drive_folder_id=DRIVE_FOLDER_ID,
    save=True,
    on_event=print,
):
    servers = load_servers()
    async with MCPHost(servers) as host:
        for name, err in host.failed.items():
            on_event(f"! server '{name}' failed to start: {err}")

        on_event("Stage 1: building research template ...")
        stage1 = await build_research_template(host, user_query, model)
        research_md = stage1["research_template"]
        stamp = _stamp()

        if save:
            await _save_to_drive(
                host, f"{stamp}_01_research_template.md", research_md, drive_folder_id, on_event
            )

        on_event("Stage 2: researching candidates and ranking ...")
        stage2 = await research_and_rank(host, research_md, model, on_event=on_event)
        ranked_md = _render_ranked_markdown(stage2)

        if save:
            await _save_to_drive(
                host, f"{stamp}_02_ranked_locations_template.md", ranked_md, drive_folder_id, on_event
            )

        return {"stage1": stage1, "stage2": stage2, "ranked_markdown": ranked_md}
