"""WanderWise — interactive Streamlit UI for the full Part 1 + Part 2 pipeline.

Run with:
    .venv/bin/streamlit run app.py
"""

import asyncio
import json
import ast
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Streamlit Cloud injects secrets via st.secrets, not the OS environment. Our MCP
# subprocesses inherit os.environ, so copy any matching secrets there before importing
# anything that reads env vars at import time (e.g. src.settings.DEFAULT_MODEL).
try:
    _secrets = dict(st.secrets)
except Exception:
    _secrets = {}
for _key in (
    "GROQ_API_KEY", "EXA_API_KEY", "SERPAPI_KEY", "TRAVEL_AGENT_MODEL",
    "GDRIVE_FOLDER_ID", "GDRIVE_CREDENTIALS_JSON", "GDRIVE_TOKEN_JSON",
):
    if _key in _secrets and _key not in os.environ:
        os.environ[_key] = str(_secrets[_key])

from src.settings import DEFAULT_MODEL, DRIVE_FOLDER_ID, load_servers
from src.mcp_host import MCPHost
from src.pipeline import run_part1
from src.pipeline_part2 import run_part2

st.set_page_config(page_title="WanderWise", page_icon="🌍", layout="wide")

# ── global styles ──────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    .stApp { background: linear-gradient(160deg, #0f2027 0%, #203a43 50%, #2c5364 100%); }
    h1, h2, h3 { color: #f4f9ff !important; }
    p, label, span, div[data-testid="stMarkdownContainer"] { color: #e8f1f8; }
    .dest-card {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 16px;
        padding: 18px 20px;
        margin-bottom: 14px;
        transition: all 0.2s ease;
    }
    .dest-card:hover { border-color: #5dd9c1; transform: translateY(-2px); }
    .score-badge {
        display: inline-block;
        background: linear-gradient(135deg, #5dd9c1, #2c8a78);
        color: #06231d;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 999px;
        font-size: 0.85rem;
    }
    .flight-card, .hotel-card {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 12px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    .day-card {
        background: rgba(255,255,255,0.05);
        border-left: 4px solid #5dd9c1;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 12px;
    }
    .cost-pill {
        background: rgba(93,217,193,0.15);
        color: #5dd9c1;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .stButton>button {
        background: linear-gradient(135deg, #5dd9c1, #2c8a78);
        color: #06231d;
        font-weight: 700;
        border: none;
        border-radius: 10px;
        padding: 0.5rem 1.4rem;
    }
    .stButton>button:hover { opacity: 0.9; }
    </style>
    """,
    unsafe_allow_html=True,
)


def run_async(coro):
    return asyncio.run(coro)


def _parse_mcp(raw):
    if not isinstance(raw, str):
        return raw
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    items, decoder, idx = [], json.JSONDecoder(), 0
    while idx < len(raw):
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


async def fetch_flights_async(from_city, to_city, depart_date, adults):
    servers = load_servers()
    async with MCPHost(servers, only=["booking"]) as host:
        from_code, to_code = _city_to_iata(from_city), _city_to_iata(to_city)
        raw = await host.call("booking__search_flights", {
            "from_airport": from_code, "to_airport": to_code,
            "depart_date": depart_date, "adults": adults, "currency": "INR",
        })
        return _parse_mcp(raw) or []


async def fetch_hotels_async(destination, checkin, checkout, adults, budget):
    servers = load_servers()
    async with MCPHost(servers, only=["booking"]) as host:
        city_query = destination.split(",")[0].strip()
        budget_max = {"shoestring": 3000, "mid-range": 10000, "premium": 0}.get(budget.lower(), 0)
        raw = await host.call("booking__search_hotels", {
            "city": city_query, "checkin_date": checkin, "checkout_date": checkout,
            "adults": adults, "currency": "INR", "budget_max": budget_max,
        })
        return _parse_mcp(raw) or []


# ── session state ───────────────────────────────────────────────────────────────────────────────────────────
stdefaults = {
    "step": 0, "part1_result": None, "destination": None, "ranked": [],
    "flights": [], "hotels": [], "selected_flight": None, "selected_hotel": None,
    "itinerary_result": None, "log_lines": [],
}
defaults = stdefaults
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


def log(msg):
    st.session_state.log_lines.append(str(msg))


def goto(step):
    st.session_state.step = step


# ── header ───────────────────────────────────────────────────────────────────────────────────────
st.title("🌍 WanderWise")
st.caption("AI travel planner — from a single sentence to a full booked itinerary")

steps = ["Describe trip", "Pick destination", "Trip details", "Flight", "Hotel", "Itinerary"]
cols = st.columns(len(steps))
for i, (col, label) in enumerate(zip(cols, steps)):
    marker = "🟢" if i < st.session_state.step else ("🔵" if i == st.session_state.step else "⚪")
    col.markdown(f"<div style='text-align:center;font-size:0.85rem'>{marker}<br>{label}</div>", unsafe_allow_html=True)
st.divider()

# ── STEP 0: query ─────────────────────────────────────────────────────────────
if st.session_state.step == 0:
    st.subheader("Where would you like to go?")
    query = st.text_area(
        "Describe your trip in plain English",
        placeholder="e.g. Beach destination outside India in October with pleasant weather, 7 days, couple trip, mid-range budget",
        height=100,
    )
    if st.button("✨ Find destinations", type="primary"):
        if not query.strip():
            st.warning("Please describe your trip first.")
        else:
            with st.status("Running research pipeline...", expanded=True) as status:
                def on_event(m):
                    status.write(str(m))
                result = run_async(run_part1(query, on_event=on_event))
                st.session_state.part1_result = result
                st.session_state.ranked = result["stage2"].get("ranked_locations", [])
                status.update(label="Done!", state="complete")
            goto(1)
            st.rerun()

# ── STEP 1: pick destination ────────────────────────────────────
elif st.session_state.step == 1:
    st.subheader("Top destinations for you")
    ranked = st.session_state.ranked
    if not ranked:
        st.error("No destinations found. Go back and try a different query.")
        if st.button("⬅ Back"):
            goto(0); st.rerun()
    else:
        for i, d in enumerate(ranked):
            with st.container():
                st.markdown(
                    f"""<div class="dest-card">
                    <h3>{d.get('rank', i+1)}. {d.get('name')} <span class="score-badge">{d.get('match_score')}/100</span></h3>
                    <p>{d.get('why_it_fits', '')}</p>
                    <p>🌤️ {d.get('weather_outlook', '')}</p>
                    </div>""",
                    unsafe_allow_html=True,
                )
                if st.button(f"Choose {d.get('name')}", key=f"dest_{i}"):
                    st.session_state.destination = d.get("name")
                    goto(2)
                    st.rerun()
        if st.button("⬅ Back"):
            goto(0); st.rerun()

# ── STEP 2: trip details ───────────────────────────────────────────────────────
elif st.session_state.step == 2:
    st.subheader(f"Plan details for {st.session_state.destination}")
    parsed = st.session_state.part1_result["stage1"].get("parsed_conditions", {})
    with st.form("trip_details"):
        c1, c2 = st.columns(2)
        departure_city = c1.text_input("Departure city", value=parsed.get("origin") or "Delhi")
        budget = c2.selectbox("Budget band", ["shoestring", "mid-range", "premium"], index=1)
        c3, c4 = st.columns(2)
        start_date = c3.date_input("Start date")
        end_date = c4.date_input("End date")
        c5, c6 = st.columns(2)
        party = c5.text_input("Party", value=parsed.get("party") or "couple")
        adults = c6.number_input("Adults", min_value=1, max_value=10, value=2)
        transport = st.radio("How will you travel?", ["Flight", "Train", "Road"], horizontal=True)
        submitted = st.form_submit_button("Continue →", type="primary")

    if submitted:
        st.session_state.trip = dict(
            departure_city=departure_city, budget=budget,
            start_date=str(start_date), end_date=str(end_date),
            party=party, adults=int(adults), transport=transport.lower(),
        )
        if transport.lower() == "flight":
            with st.spinner("Searching real flights via Google Flights..."):
                flights = run_async(fetch_flights_async(
                    departure_city, st.session_state.destination, str(start_date), int(adults)
                ))
                st.session_state.flights = flights
            goto(3)
        else:
            st.session_state.selected_flight = {"mode": transport.lower()}
            goto(4)
        st.rerun()
    if st.button("⬅ Back"):
        goto(1); st.rerun()

# ── STEP 3: pick flight ─────────────────────────────────────────────────────
elif st.session_state.step == 3:
    st.subheader("✈️ Choose your flight")
    flights = st.session_state.flights
    if not flights:
        st.warning("No flights found via API. You can skip and continue.")
        if st.button("Skip flight selection →", type="primary"):
            st.session_state.selected_flight = {}
            goto(4); st.rerun()
    else:
        for i, f in enumerate(flights):
            st.markdown(
                f"""<div class="flight-card">
                <b>{f.get('airline')}</b> {f.get('flight_number', '')}
                &nbsp;|&nbsp; {f.get('departure')} → {f.get('arrival')}
                &nbsp;|&nbsp; {f.get('stops', 0)} stop(s)
                &nbsp;|&nbsp; <span class="cost-pill">₹{f.get('price')}</span>
                &nbsp;|&nbsp; <a href="{f.get('booking_link','')}" target="_blank" style="color:#5dd9c1;">Book on Google Flights ↗</a>
                </div>""",
                unsafe_allow_html=True,
            )
            if st.button(f"Select this flight", key=f"flight_{i}"):
                st.session_state.selected_flight = f
                goto(4); st.rerun()
    if st.button("⬅ Back"):
        goto(2); st.rerun()

# ── STEP 4: pick hotel ─────────────────────────────────────────────────────────────────────────────
elif st.session_state.step == 4:
    st.subheader("🏨 Choose your hotel")
    if not st.session_state.hotels:
        with st.spinner("Searching real hotels via Google Hotels..."):
            trip = st.session_state.trip
            hotels = run_async(fetch_hotels_async(
                st.session_state.destination, trip["start_date"], trip["end_date"],
                trip["adults"], trip["budget"],
            ))
            st.session_state.hotels = hotels

    hotels = st.session_state.hotels
    if not hotels:
        st.warning("No hotels found via API. You can skip and continue.")
        if st.button("Skip hotel selection →", type="primary"):
            st.session_state.selected_hotel = {}
            goto(5); st.rerun()
    else:
        for i, h in enumerate(hotels[:8]):
            st.markdown(
                f"""<div class="hotel-card">
                <b>{h.get('name')}</b> &nbsp;⭐ {h.get('rating')} ({h.get('review_count', 0)} reviews)
                &nbsp;|&nbsp; <span class="cost-pill">₹{h.get('price_per_night')}/night</span>
                &nbsp;|&nbsp; <a href="{h.get('booking_link','')}" target="_blank" style="color:#5dd9c1;">View hotel ↗</a>
                </div>""",
                unsafe_allow_html=True,
            )
            if st.button("Select this hotel", key=f"hotel_{i}"):
                st.session_state.selected_hotel = h
                goto(5); st.rerun()
    if st.button("⬅ Back"):
        goto(3); st.rerun()

# ── STEP 5: build + show itinerary ─────────────────────────────────────────────────────────
elif st.session_state.step == 5:
    st.subheader("🗺️ Your itinerary")

    if st.session_state.itinerary_result is None:
        trip = st.session_state.trip
        with st.status("Running researcher → hotel finder → planner...", expanded=True) as status:
            def on_event(m):
                status.write(str(m))
            result = run_async(run_part2(
                destination=st.session_state.destination,
                travel_dates=trip["start_date"],
                return_date=trip["end_date"],
                party=trip["party"],
                adults=trip["adults"],
                budget=trip["budget"],
                departure_city=trip["departure_city"],
                transport_choice=trip["transport"],
                selected_transport=st.session_state.selected_flight or {},
                selected_hotel=st.session_state.selected_hotel or {},
                on_event=on_event,
            ))
            st.session_state.itinerary_result = result
            status.update(label="Itinerary ready!", state="complete")

    result = st.session_state.itinerary_result
    itinerary = result["itinerary"]

    h1, h2, h3 = st.columns(3)
    h1.metric("Destination", itinerary.get("destination", st.session_state.destination))
    h2.metric("Dates", itinerary.get("travel_dates", ""))
    breakdown = itinerary.get("total_cost_breakdown", {})
    h3.metric("Total cost", f"₹{breakdown.get('total', 'N/A')}")

    flight = st.session_state.selected_flight or {}
    hotel = st.session_state.selected_hotel or {}
    bl1, bl2 = st.columns(2)
    if flight.get("booking_link"):
        bl1.link_button("✈️ Book flight", flight["booking_link"])
    if hotel.get("booking_link"):
        bl2.link_button("🏨 Book hotel", hotel["booking_link"])

    st.divider()
    for day in itinerary.get("days", []):
        with st.container():
            st.markdown(
                f"""<div class="day-card">
                <h4>Day {day.get('day')}: {day.get('label', '')}</h4>
                <p>☀️ <b>Morning:</b> {day.get('morning', '')}</p>
                <p>🌤️ <b>Afternoon:</b> {day.get('afternoon', '')}</p>
                <p>🌙 <b>Evening:</b> {day.get('evening', '')}</p>
                <span class="cost-pill">Est. ₹{day.get('estimated_cost', 'N/A')}/day</span>
                </div>""",
                unsafe_allow_html=True,
            )

    with st.expander("💰 Full cost breakdown"):
        for k, v in breakdown.items():
            if k != "total":
                st.write(f"**{k.replace('_', ' ').title()}:** {breakdown.get('currency', 'INR')} {v}")
        st.write(f"**TOTAL: {breakdown.get('currency', 'INR')} {breakdown.get('total', 'N/A')}**")

    with st.expander("🎒 Packing checklist & emergency contacts"):
        for item in itinerary.get("packing_checklist", []):
            st.write(f"- {item}")
        st.write("**Emergency contacts:**")
        for k, v in itinerary.get("emergency_contacts", {}).items():
            st.write(f"- {k.replace('_', ' ').title()}: {v}")

    st.divider()
    pdf_files = sorted(Path("outputs").glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if pdf_files:
        with open(pdf_files[0], "rb") as f:
            st.download_button("📄 Download itinerary PDF", f, file_name=pdf_files[0].name, mime="application/pdf", type="primary")

    if st.button("🔄 Plan a new trip"):
        for k in defaults:
            st.session_state[k] = defaults[k]
        st.rerun()
