# WanderWise — AI Travel Research Agent

Turn a free-form travel request into (1) a structured **research template** and
(2) a **ranked list of destinations** with a ready-to-use **itinerary prompt template**,
then save both templates to **Google Drive** — all via MCP and an open-source HuggingFace model.

```
user query
   │
   ▼  Stage 1  (LLM, no tools)
research template  ──────────────►  saved to Google Drive (MCP)
   │
   ▼  Stage 2  (LLM + Exa + weather MCP tools)
ranked destinations  +  itinerary prompt template  ──►  saved to Google Drive (MCP)
```

## How it works

This project is its **own MCP client/host**. It launches several MCP servers as
subprocesses over stdio, collects all of their tools, and hands them to the model through
an OpenAI-compatible tool-use loop. Tool calls are routed back to whichever server owns them.

Servers used (see `config/servers.json`):

| Server   | Type             | Purpose                                                       |
|----------|------------------|---------------------------------------------------------------|
| `weather`| bundled (Python) | Open-Meteo forecast + seasonal normals — no API key           |
| `exa`    | third-party (npx)| Recent news, blogs, first-hand visitor posts, page reads      |
| `gdrive` | bundled (Python) | Save the two prompt templates to Google Drive (`drive.file`)  |

## Setup

1. **Python deps**
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Node** (for the Exa server, run via `npx`). Node 18+ recommended.

3. **Environment** — copy and fill:
   ```bash
   cp .env.example .env
   ```
   - `HF_TOKEN` — HuggingFace token from huggingface.co/settings/tokens
   - `EXA_API_KEY` — from dashboard.exa.ai/api-keys
   - `TRAVEL_AGENT_MODEL` — default is `Qwen/Qwen2.5-72B-Instruct`

4. **Google Drive OAuth** (for the save step)
   - In Google Cloud Console: create an OAuth client of type **Desktop app**, enable the
     **Google Drive API**, and download the client secret JSON as `credentials.json` in the
     project root.
   - Mint the token once (opens a browser):
     ```bash
     .venv/bin/python mcp_servers/gdrive_server.py --auth
     ```
   - Optionally set `GDRIVE_FOLDER_ID` in `.env` to drop outputs into a specific folder.

## Run

```bash
.venv/bin/python main.py --query "Quiet hill station near Delhi, 4 days in early October, mid-range budget, good for photography"
```

Useful flags: `--query-file path.txt`, `--model <model-id>`, `--folder-id <id>`,
`--no-save` (skip Drive), `--json` (print the full structured result).

Outputs two files to Google Drive:
- `<timestamp>_01_research_template.md`
- `<timestamp>_02_ranked_locations_template.md`

## File map

```
config/servers.json            MCP server launch specs
prompts/stage1_system.md       query -> research template
prompts/stage2_system.md       research brief -> ranked destinations + itinerary template
mcp_servers/weather_server.py  bundled weather MCP server (Open-Meteo)
mcp_servers/gdrive_server.py   bundled Google Drive MCP server
src/settings.py                config loading, env expansion, JSON extraction
src/mcp_host.py                connects to N stdio servers, aggregates/namespaces tools
src/agent.py                   HuggingFace tool-use agentic loop
src/stage1.py / stage2.py      the two pipeline stages
src/pipeline.py                orchestration + Drive save
main.py                        CLI
```
