"""Settings, paths, and small shared helpers."""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_MODEL = os.environ.get("TRAVEL_AGENT_MODEL", "openai/gpt-oss-120b")
DRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "")
SERVERS_CONFIG = PROJECT_ROOT / "config" / "servers.json"

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def expand_env(value):
    """Replace ${VAR} references in a string with environment values."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    return value


def load_servers(only=None):
    """Load MCP server launch specs from config/servers.json.

    `only` optionally restricts to a subset of server names. Relative .py script
    paths are resolved against the project root so the pipeline can be launched
    from anywhere.
    """
    with open(SERVERS_CONFIG) as fh:
        raw = json.load(fh)
    servers = {}
    for name, spec in raw.items():
        if only is not None and name not in only:
            continue
        command = spec["command"]
        # ".venv/bin/python" is a local dev convenience; on a deployed host there's no
        # such relative path, so fall back to whatever interpreter is actually running.
        if command in (".venv/bin/python", "python", "python3"):
            command = sys.executable
        args = []
        for arg in spec.get("args", []):
            if isinstance(arg, str) and arg.endswith(".py"):
                args.append(str(PROJECT_ROOT / arg))
            else:
                args.append(arg)
        servers[name] = {"command": command, "args": args, "env": spec.get("env", {})}
    return servers


def load_prompt(name):
    """Read a system prompt from the prompts/ directory."""
    return (PROJECT_ROOT / "prompts" / name).read_text(encoding="utf-8")


def extract_json(text):
    """Best-effort extraction of a JSON object from model output.

    Strips code fences, then parses only the FIRST complete top-level JSON object
    starting at the first '{' — ignoring any trailing data (some models, especially
    smaller local ones, echo a second JSON blob or commentary after the real answer).
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if not cleaned:
        raise ValueError("Model returned an empty response — no JSON to extract.")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned).strip()
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", cleaned)

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output.")

    # parse only the first complete top-level object; ignore anything after it
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned, start)
        return obj
    except json.JSONDecodeError:
        pass

    # fall back: trim to the matching outer braces and try heuristic repairs
    end = cleaned.rfind("}")
    snippet = cleaned[start : end + 1] if end > start else cleaned[start:]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        snippet = re.sub(r",\s*([}\]])", r"\1", snippet)
        opens = snippet.count("{") - snippet.count("}")
        arr_opens = snippet.count("[") - snippet.count("]")
        snippet = snippet.rstrip(", \n\t")
        snippet += "]" * max(0, arr_opens) + "}" * max(0, opens)
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return _insert_missing_commas(snippet)


def _insert_missing_commas(s, max_attempts=30):
    """Deterministically patch 'Expecting , delimiter' errors by inserting a comma.

    Smaller local models sometimes drop a comma between fields/array items; this is
    a cheap, reliable fix that doesn't need another model call.
    """
    for _ in range(max_attempts):
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            if "Expecting ',' delimiter" in e.msg:
                s = s[: e.pos] + "," + s[e.pos :]
                continue
            if "Expecting property name enclosed in double quotes" in e.msg:
                # usually a stray trailing comma right before this position
                before = s[: e.pos].rstrip()
                if before.endswith(","):
                    s = before[:-1] + s[e.pos :]
                    continue
            raise
    raise ValueError("Could not auto-repair JSON: too many delimiter fixes needed.")


async def extract_json_safe(raw, model, on_event=None):
    """extract_json with a model-assisted repair fallback if local heuristics fail."""
    try:
        return extract_json(raw)
    except Exception as e:
        from .agent import repair_json
        if on_event:
            on_event(f"  ! JSON parse failed ({e}); asking model to repair...")
        fixed = await repair_json(raw, model, str(e), on_event=on_event)
        try:
            return extract_json(fixed)
        except Exception:
            # model repair didn't help either — last resort: patch the ORIGINAL text directly
            return _force_parse(raw)


def _force_parse(raw):
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned).strip()
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    snippet = cleaned[start : end + 1] if start != -1 and end > start else cleaned
    snippet = re.sub(r",\s*([}\]])", r"\1", snippet)
    opens = snippet.count("{") - snippet.count("}")
    arr_opens = snippet.count("[") - snippet.count("]")
    snippet = snippet.rstrip(", \n\t") + "]" * max(0, arr_opens) + "}" * max(0, opens)
    return _insert_missing_commas(snippet)
