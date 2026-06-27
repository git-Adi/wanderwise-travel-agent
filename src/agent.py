"""Tool-use agent loop backed by Groq (OpenAI-compatible API)."""

import asyncio
import json
import os
import re

from openai import OpenAI


def _client():
    return OpenAI(
        api_key=os.environ["GROQ_API_KEY"],
        base_url="https://api.groq.com/openai/v1",
    )


def _trim_history(messages, keep_last_turns=3):
    """Keep system+user plus only the most recent N (assistant + its tool results) turns.

    Groq's free tier caps tokens-per-minute fairly low for some models; long tool-use
    conversations need trimming or every later call exceeds the limit.
    """
    head = messages[:2]
    body = messages[2:]
    turns, current = [], []
    for m in body:
        if m["role"] == "assistant":
            if current:
                turns.append(current)
            current = [m]
        else:
            current.append(m)
    if current:
        turns.append(current)
    trimmed = turns[-keep_last_turns:] if len(turns) > keep_last_turns else turns
    return head + [msg for turn in trimmed for msg in turn]


def _to_openai_tools(anthropic_tools):
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in anthropic_tools
    ]


async def run_agent(
    host,
    *,
    system,
    user,
    model,
    max_tokens=4096,
    tool_servers=None,
    only_tools=None,
    max_turns=16,
    on_event=None,
):
    client = _client()
    raw_tools = host.anthropic_tools(tool_servers, only_tools=only_tools) if tool_servers else []
    openai_tools = _to_openai_tools(raw_tools) if raw_tools else []
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_text = ""

    for _ in range(max_turns):
        keep_turns = 3
        for attempt in range(4):
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": _trim_history(messages, keep_last_turns=keep_turns),
            }
            if openai_tools:
                kwargs["tools"] = openai_tools
            try:
                response = await asyncio.to_thread(
                    client.chat.completions.create, **kwargs
                )
                break
            except Exception as e:
                msg_lower = str(e).lower()
                # don't retry daily token limit exhaustion — retries just burn more quota
                if "tokens per day" in msg_lower or "tpd" in msg_lower:
                    raise
                if "request too large" in msg_lower or "413" in msg_lower:
                    # trim more aggressively and retry without a long wait
                    keep_turns = max(1, keep_turns - 1)
                    if on_event:
                        on_event(f"  ! request too large, trimming history and retrying...")
                    continue
                if "not in request.tools" in msg_lower or "tool call validation failed" in msg_lower:
                    # model called a hallucinated/unprefixed tool name — remind it of the real ones
                    valid_names = ", ".join(t["function"]["name"] for t in openai_tools)
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your last attempt called a tool name that does not exist. "
                            f"The ONLY valid tool names are: {valid_names}. "
                            "Call one of these exact names."
                        ),
                    })
                    if on_event:
                        on_event("  ! invalid tool name used; correcting and retrying...")
                    continue
                if attempt == 3:
                    raise
                wait = 10 * (attempt + 1)
                if on_event:
                    on_event(f"  ! API error ({e.__class__.__name__}), retrying in {wait}s...")
                await asyncio.sleep(wait)

        choice = response.choices[0]
        msg = choice.message
        raw_content = (msg.content or "").strip()
        # strip <think>...</think> blocks emitted by reasoning models
        last_text = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()

        assistant_turn = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_turn)

        if choice.finish_reason != "tool_calls" or not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if on_event:
                on_event(f"  -> tool {name} {arguments}")
            try:
                output = await host.call(name, arguments)
            except Exception as exc:
                output = f"ERROR: {type(exc).__name__}: {exc}"
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": str(output)[:500]}
            )

    # ran out of turns mid tool-call loop without a final text answer — force one
    if not last_text:
        messages.append({
            "role": "user",
            "content": "Stop calling tools now. Using only what you've already gathered, respond with the final answer JSON immediately.",
        })
        keep_turns = 2
        for attempt in range(4):
            try:
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=model, max_tokens=max_tokens,
                    messages=_trim_history(messages, keep_last_turns=keep_turns),
                )
                break
            except Exception as e:
                if "request too large" in str(e).lower() or "413" in str(e):
                    keep_turns = max(1, keep_turns - 1)
                    continue
                if attempt == 3:
                    raise
                await asyncio.sleep(10 * (attempt + 1))
        raw_content = (response.choices[0].message.content or "").strip()
        last_text = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()

    return last_text


async def repair_json(raw_text, model, error, on_event=None):
    """Ask the model to fix its own malformed JSON output."""
    client = _client()
    prompt = (
        "The following text was supposed to be strict JSON but failed to parse "
        f"with error: {error}\n\n"
        "Return ONLY the corrected, valid JSON. No prose, no markdown fences, "
        "no commentary — just the fixed JSON object.\n\n"
        f"{raw_text}"
    )
    if on_event:
        on_event(f"  ! JSON parse failed ({error}); asking model to repair...")
    response = None
    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except Exception as e:
            if attempt == 2:
                raise
            await asyncio.sleep(10 * (attempt + 1))
    text = (response.choices[0].message.content or "").strip()
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
