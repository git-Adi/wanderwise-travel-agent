"""Part-2 pipeline: researcher → hotel finder → planner."""

import json
import datetime as _dt
from pathlib import Path

from .mcp_host import MCPHost
from .settings import DEFAULT_MODEL, DRIVE_FOLDER_ID, load_servers
from .stage3_researcher import research_destination
from .stage4_hotel_finder import find_hotels
from .stage5_planner import build_itinerary


def _stamp():
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _render_itinerary_markdown(itinerary: dict, selected_transport: dict = None, selected_hotel: dict = None) -> str:
    lines = [f"# Itinerary: {itinerary.get('destination', '')}\n"]
    lines.append(f"**Dates:** {itinerary.get('travel_dates', '')}  ")
    lines.append(f"**Party:** {itinerary.get('party', '')}  ")
    hotel = selected_hotel or itinerary.get('selected_hotel', {})
    hotel_name = hotel.get('name', 'TBD') if isinstance(hotel, dict) else str(hotel)
    lines.append(f"**Hotel:** {hotel_name}  ")
    lines.append(f"**Transport:** {itinerary.get('transport_used', '')}  \n")

    # booking links section
    flight = selected_transport if isinstance(selected_transport, dict) else {}
    flight_link = flight.get("booking_link", "")
    hotel_link = hotel.get("booking_link", "") if isinstance(hotel, dict) else ""
    if flight_link or hotel_link:
        lines.append("## Booking Links")
        if flight_link:
            airline = flight.get("airline", "Flight")
            fn = flight.get("flight_number", "")
            price = flight.get("price", "")
            currency = flight.get("currency", "INR")
            label = f"{airline} {fn} — {currency} {price}".strip(" —")
            lines.append(f"- **Flight:** [{label}]({flight_link})")
        if hotel_link:
            lines.append(f"- **Hotel:** [{hotel_name}]({hotel_link})")
        lines.append("")

    for day in itinerary.get("days", []):
        lines.append(f"## Day {day.get('day')}: {day.get('label', '')}")
        if day.get("morning"):
            lines.append(f"**Morning:** {day['morning']}")
        if day.get("afternoon"):
            lines.append(f"**Afternoon:** {day['afternoon']}")
        if day.get("evening"):
            lines.append(f"**Evening:** {day['evening']}")
        meals = day.get("meals", {})
        if meals:
            lines.append(
                f"**Meals:** Breakfast — {meals.get('breakfast', 'TBD')} | "
                f"Lunch — {meals.get('lunch', 'TBD')} | "
                f"Dinner — {meals.get('dinner', 'TBD')}"
            )
        if day.get("estimated_cost"):
            lines.append(f"**Est. daily cost:** ₹{day['estimated_cost']}")
        lines.append("")

    breakdown = itinerary.get("total_cost_breakdown", {})
    if breakdown:
        lines.append("## Total Cost Breakdown")
        currency = breakdown.get("currency", "INR")
        for key in ("flight_or_train", "accommodation", "food", "activities", "local_transport", "miscellaneous"):
            if breakdown.get(key):
                lines.append(f"- **{key.replace('_', ' ').title()}:** {currency} {breakdown[key]}")
        lines.append(f"- **TOTAL: {currency} {breakdown.get('total', 'N/A')}**\n")

    checklist = itinerary.get("packing_checklist", [])
    if checklist:
        lines.append("## Packing Checklist")
        for item in checklist:
            lines.append(f"- {item}")
        lines.append("")

    emergency = itinerary.get("emergency_contacts", {})
    if emergency:
        lines.append("## Emergency Contacts")
        for key, val in emergency.items():
            lines.append(f"- **{key.replace('_', ' ').title()}:** {val}")

    return "\n".join(lines)


async def _save_to_drive(host, filename, content, folder_id, on_event):
    if "gdrive" not in host.sessions:
        on_event(f"  ! Drive not connected; skipped {filename}")
        return None
    result = await host.call(
        "gdrive__upload_text_file",
        {"filename": filename, "content": content, "folder_id": folder_id, "mime_type": "text/markdown"},
    )
    on_event(f"  saved: {result}")
    return result


async def run_part2(
    destination,
    travel_dates,
    return_date,
    party,
    adults,
    budget,
    departure_city,
    transport_choice,
    selected_transport,
    selected_hotel,
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

        on_event("\nStage 3: researching destination ...")
        researcher_brief = await research_destination(
            host, destination, travel_dates, return_date, party, budget, model, on_event=on_event
        )

        on_event("\nStage 4: finding hotels and dining ...")
        hotel_brief = await find_hotels(
            host, destination, travel_dates, return_date, adults, budget, model, on_event=on_event
        )

        on_event("\nStage 5: building itinerary ...")
        itinerary = await build_itinerary(
            host,
            destination=destination,
            travel_dates=travel_dates,
            return_date=return_date,
            party=party,
            budget=budget,
            transport_choice=transport_choice,
            selected_transport=selected_transport,
            selected_hotel=selected_hotel,
            researcher_brief=researcher_brief,
            hotel_brief=hotel_brief,
            model=model,
            on_event=on_event,
        )

        itinerary_md = _render_itinerary_markdown(itinerary, selected_transport, selected_hotel)
        stamp = _stamp()

        # save locally as markdown and PDF
        out_dir = Path(__file__).resolve().parent.parent / "outputs"
        out_dir.mkdir(exist_ok=True)
        safe_dest = destination.replace(" ", "_").replace(",", "")
        md_path = out_dir / f"{stamp}_itinerary_{safe_dest}.md"
        pdf_path = out_dir / f"{stamp}_itinerary_{safe_dest}.pdf"
        md_path.write_text(itinerary_md, encoding="utf-8")
        on_event(f"  saved markdown: {md_path}")
        try:
            import markdown2
            from weasyprint import HTML
            html_body = markdown2.markdown(itinerary_md, extras=["tables", "fenced-code-blocks"])
            html_full = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<style>
body{{font-family:Georgia,serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6;color:#222}}
h1{{color:#1a5276;border-bottom:2px solid #1a5276;padding-bottom:8px}}
h2{{color:#1a5276;margin-top:24px}}
strong{{color:#333}}
ul{{padding-left:20px}}
</style></head><body>{html_body}</body></html>"""
            HTML(string=html_full).write_pdf(str(pdf_path))
            on_event(f"  saved PDF:      {pdf_path}")
        except Exception as e:
            on_event(f"  ! PDF generation failed ({e}); markdown saved at {md_path}")
            pdf_path = None

        if save:
            await _save_to_drive(
                host,
                f"{stamp}_itinerary_{safe_dest}.md",
                itinerary_md,
                drive_folder_id,
                on_event,
            )

        return {
            "researcher_brief": researcher_brief,
            "hotel_brief": hotel_brief,
            "itinerary": itinerary,
            "itinerary_markdown": itinerary_md,
        }
