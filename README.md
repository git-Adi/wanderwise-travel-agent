# WanderWise — AI Travel Agent

Turn a free-form travel request into (1) a structured **research template**, (2) a
**ranked list of destinations** with a ready-to-use **itinerary prompt template**, and
then (3) a full **day-by-day booked itinerary** with real flights and hotels — all via
MCP and a free, open-source-friendly LLM backend (Groq).

```
Part 1
user query
   │
   ▼  Stage 1  (LLM, no tools)
research template  ───────────►  saved to Google Drive (MCP)
   │
   ▼  Stage 2  (LLM + Exa + weather MCP tools)
ranked destinations  +  itinerary prompt template  ──►  saved to Google Drive (MCP)

Part 2 (pick a destination from Part 1's ranked list)
   │
   ▼  Stage 3  Researcher (Exa)
destination brief
   │
   ▼  Stage 4  Hotel Finder (SerpAPI Google Hotels + Exa)
hotel + dining brief
   │
   ▼  Stage 5  Planner (no tools)
full day-by-day itinerary  ──────────►  PDF + Markdown + Google Drive
```

A Streamlit app (`app.py`) wraps the whole flow end to end with a visual, step-by-step UI.

## How it works

This project is its **own MCP client/host**. It launches several MCP servers as
subprocesses over stdio, collects all of their tools, and hands them to the LLM through
an OpenAI-compatible tool-use loop (Groq). Tool calls are routed back to whichever server owns them.

Servers used (see `config/servers.json`):

| Server    | Type             | Purpose                                                      |
|-----------|------------------|---------------------------------------------------------------|
| `weather` | bundled (Python) | Open-Meteo forecast + seasonal normals — no API key           |
| `exa`     | third-party (npx)| Recent news, blogs, first-hand visitor posts, page reads      |
| `gdrive`  | bundled (Python) | Save itinerary/prompt templates to Google Drive (`drive.file`)|
| `booking` | bundled (Python) | Real flights + hotels via SerpAPI (Google Flights/Hotels)      |

> **Why not the API's `mcp_servers` connector?** That connector only attaches *remote*
> (URL) MCP servers; local stdio servers like our weather/Drive/booking servers can't use it.
> Running our own client lets every server — stdio or remote — plug in the same way and
> gives full control over the tool-use loop.

## Setup

1. **Python deps**
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Node** (for the Exa server, run via `npx`). Node 18+ recommended.

3. **Environment** — copy and fill:
   ```bash
   cp .env.example .env
   ```
   - `GROQ_API_KEY` — free at console.groq.com (used by `src/agent.py`)
   - `EXA_API_KEY` — from dashboard.exa.ai/api-keys
   - `SERPAPI_KEY` — free tier at serpapi.com (Google Flights + Hotels)
   - `TRAVEL_AGENT_MODEL` — default `llama-3.3-70b-versatile`

4. **Google Drive OAuth** (for the save step)
   - In Google Cloud Console: create an OAuth client of type **Desktop app**, enable the
     **Google Drive API**, and download the client secret JSON as `credentials.json` in the
     project root.
   - Mint a token once (opens a browser):
     ```bash
     python mcp_servers/gdrive_server.py --auth
     ```
   - Optionally set `GDRIVE_FOLDER_ID` in `.env` to drop outputs into a specific folder.

## Run

**Part 1** — research + ranked destinations:
```bash
python main.py --query "Quiet hill station near Delhi, 4 days in early October, \
mid-range budget, good for photography, avoid crowds, reachable by road within 8 hours"
```
Useful flags: `--query-file path.txt`, `--model <model>`, `--folder-id <id>`,
`--no-save` (skip Drive), `--json` (print the full structured result).

**Part 2** — interactive itinerary builder (pick a destination from Part 1's output):
```bash
python main_part2.py --part1 part1_output.json
```

**Full interactive UI** (recommended):
```bash
streamlit run app.py
```

## File map

```
config/servers.json            MCP server launch specs (env vars expanded at load)
prompts/stage1_system.md       query -> research template
prompts/stage2_system.md       research brief -> ranked destinations + itinerary template
prompts/stage3_researcher.md   destination -> deep research brief
prompts/stage4_hotel_finder.md hotels + dining via Booking/SerpAPI + Exa
prompts/stage5_planner.md      full day-by-day itinerary builder
mcp_servers/weather_server.py  bundled weather MCP server (Open-Meteo)
mcp_servers/gdrive_server.py   bundled Google Drive MCP server (upload_text_file)
mcp_servers/booking_server.py  bundled flights/hotels MCP server (SerpAPI)
src/settings.py                config loading, env expansion, JSON extraction
src/mcp_host.py                connects to N stdio servers, aggregates/namespaces tools
src/agent.py                   Groq (OpenAI-compatible) tool-use loop
src/stage1.py / stage2.py      Part 1 pipeline stages
src/stage3_researcher.py / stage4_hotel_finder.py / stage5_planner.py   Part 2 stages
src/pipeline.py / pipeline_part2.py   orchestration + Drive/PDF save
main.py / main_part2.py        CLIs
app.py                         Streamlit UI for the full flow
```

## Notes & extension points

- **Resilience:** if a server fails to start (e.g. missing API key), the pipeline
  warns and continues with whatever tools connected.
- **Free-tier rate limits:** Groq's free tier caps daily tokens per model; if you hit a
  daily limit mid-run, switch `TRAVEL_AGENT_MODEL` to another Groq model temporarily.
- **Add servers** by editing `config/servers.json`; tools are discovered dynamically.
