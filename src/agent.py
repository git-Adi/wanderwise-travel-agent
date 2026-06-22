"""Tool-use agent loop backed by HuggingFace InferenceClient (OpenAI-compatible)."""

import asyncio
import json
import os

from huggingface_hub import InferenceClient


def _client():
    return InferenceClient(api_key=os.environ["HF_TOKEN"])


def _to_openai_tools(anthropic_tools):
    """Convert MCP/Anthropic tool schemas to OpenAI function-calling format."""
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
    max_turns=16,
    on_event=None,
):
    client = _client()
    raw_tools = host.anthropic_tools(tool_servers) if tool_servers else []
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

        response = await asyncio.to_thread(
            client.chat.completions.create, **kwargs
        )

        choice = response.choices[0]
        msg = choice.message
        last_text = (msg.content or "").strip()

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
                {"role": "tool", "tool_call_id": tc.id, "content": output[:3000]}
            )

    return last_text
