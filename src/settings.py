"""Settings, paths, and small shared helpers."""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_MODEL = os.environ.get("TRAVEL_AGENT_MODEL", "Qwen/Qwen2.5-72B-Instruct")
DRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "")
SERVERS_CONFIG = PROJECT_ROOT / "config" / "servers.json"

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def expand_env(value):
    """Replace ${VAR} references in a string with environment values."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    return value


def load_servers(only=None):
    """Load MCP server launch specs from config/servers.json."""
    with open(SERVERS_CONFIG) as fh:
        raw = json.load(fh)
    servers = {}
    for name, spec in raw.items():
        if only is not None and name not in only:
            continue
        args = []
        for arg in spec.get("args", []):
            if isinstance(arg, str) and arg.endswith(".py"):
                args.append(str(PROJECT_ROOT / arg))
            else:
                args.append(arg)
        servers[name] = {"command": spec["command"], "args": args, "env": spec.get("env", {})}
    return servers


def load_prompt(name):
    """Read a system prompt from the prompts/ directory."""
    return (PROJECT_ROOT / "prompts" / name).read_text(encoding="utf-8")


def extract_json(text):
    """Best-effort extraction of a JSON object from model output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)
