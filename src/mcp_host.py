"""MCP host that connects to several stdio MCP servers at once.

It launches each configured server as a subprocess, lists its tools, and exposes
them to Claude as a single namespaced tool set (`<server>__<tool>`). Tool calls are
dispatched back to the owning server. This works uniformly for the bundled weather
and Google Drive servers and for third-party servers such as Exa.
"""

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
        self.tool_index = {}  # anthropic tool name -> (server name, mcp tool name)
        self._tools = []
        self.failed = {}  # server name -> error string

    async def __aenter__(self):
        for name, spec in self.servers.items():
            try:
                await self._connect(name, spec)
            except Exception as exc:  # keep the pipeline alive if one server fails
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

    def anthropic_tools(self, servers=None, only_tools=None):
        """Tool schemas for the Messages API, optionally limited to some servers/tools.

        only_tools: optional set of exact anthropic tool names to whitelist.
        """
        if servers is None:
            tools = list(self._tools)
        else:
            keep = set(servers)
            tools = [t for t in self._tools if self.tool_index[t["name"]][0] in keep]
        if only_tools is not None:
            tools = [t for t in tools if t["name"] in only_tools]
        return tools

    async def call(self, anthropic_name, arguments):
        """Dispatch a namespaced tool call to its owning server; return text output."""
        if anthropic_name not in self.tool_index:
            return f"ERROR: unknown tool '{anthropic_name}'"
        server, tool = self.tool_index[anthropic_name]
        result = await self.sessions[server].call_tool(tool, arguments or {})
        parts = []
        for block in result.content:
            text = getattr(block, "text", None)
            parts.append(text if text is not None else str(block))
        return "\n".join(parts) if parts else "(no content)"
