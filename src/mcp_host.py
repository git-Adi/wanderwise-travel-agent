"""MCP host that connects to several stdio MCP servers at once."""

import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .settings import expand_env


class MCPHost:
    def __init__(self, servers, only=None):
        self.servers = {k: v for k, v in servers.items() if only is None or k in only}
        self._stack = AsyncExitStack()
        self.sessions = {}
        self.tool_index = {}
        self._tools = []
        self.failed = {}

    async def __aenter__(self):
        for name, spec in self.servers.items():
            try:
                await self._connect(name, spec)
            except Exception as exc:
                self.failed[name] = f"{type(exc).__name__}: {exc}"
        return self

    async def _connect(self, name, spec):
        env = dict(os.environ)
        for key, value in (spec.get("env") or {}).items():
            env[key] = expand_env(value)
        params = StdioServerParameters(
            command=spec["command"],
            args=[expand_env(a) for a in spec.get("args", [])],
            env=env,
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session
        listed = await session.list_tools()
        for tool in listed.tools:
            anthropic_name = f"{name}__{tool.name}"[:64]
            self.tool_index[anthropic_name] = (name, tool.name)
            self._tools.append(
                {
                    "name": anthropic_name,
                    "description": (tool.description or "")[:1024],
                    "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
                }
            )

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    def anthropic_tools(self, servers=None):
        if servers is None:
            return list(self._tools)
        keep = set(servers)
        return [t for t in self._tools if self.tool_index[t["name"]][0] in keep]

    async def call(self, anthropic_name, arguments):
        if anthropic_name not in self.tool_index:
            return f"ERROR: unknown tool '{anthropic_name}'"
        server, tool = self.tool_index[anthropic_name]
        result = await self.sessions[server].call_tool(tool, arguments or {})
        parts = []
        for block in result.content:
            text = getattr(block, "text", None)
            parts.append(text if text is not None else str(block))
        return "\n".join(parts) if parts else "(no content)"
