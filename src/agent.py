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
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        for attempt in range(3):
            try:
                response = await asyncio.to_thread(
                    client.chat.completions.create, **kwargs
                )
                break
            except Exception as e:
                # don't retry daily token limit exhaustion — retries just burn more quota
                if "tokens per day" in str(e).lower() or "tpd" in str(e).lower():
                    raise
                if attempt == 2:
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
                {"role": "tool", "tool_call_id": tc.id, "content": str(output)[:800]}
            )

    # ran out of turns mid tool-call loop without a final text answer — force one
    if not last_text:
        messages.append({
            "role": "user",
            "content": "Stop calling tools now. Using only what you've already gathered, respond with the final answer JSON immediately.",
        })
        for attempt in range(3):
            try:
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=model, max_tokens=max_tokens, messages=messages,
                )
                break
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(10 * (attempt + 1))
        raw_content = (response.choices[0].message.content or "").strip()
        last_text = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()

    return last_text
