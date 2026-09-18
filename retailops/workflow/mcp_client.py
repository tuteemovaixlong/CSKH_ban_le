"""Model Context Protocol (MCP) Client Adapter for RetailOps.

Provides client-side connection and discovery mechanisms for LangGraph and external
agents to interact with the RetailOps MCP Server (via in-process or SSE transport).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("retailops.mcp_client")


class RetailOpsMCPClient:
    """Client adapter for communicating with RetailOps Model Context Protocol Server."""

    def __init__(self, sse_url: Optional[str] = None, *, in_process_server: Any = None):
        self.sse_url = sse_url
        self._in_process_server = in_process_server
        self._cached_tools: Optional[List[Dict[str, Any]]] = None

    def _get_server(self):
        if self._in_process_server:
            return self._in_process_server
        try:
            from retailops_mcp_server import app
            return app
        except Exception as e:
            logger.warning("Could not load local retailops_mcp_server: %s", e)
            return None

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools from the MCP Server."""
        server = self._get_server()
        if not server:
            return []

        try:
            tools = await server.list_tools()
            self._cached_tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": getattr(t, "inputSchema", {}) or {}
                }
                for t in tools
            ]
            return self._cached_tools
        except Exception as e:
            logger.error("Failed to query MCP tools: %s", e)
            return []

    def _run_coroutine_sync(self, coro):
        """Helper to run a coroutine synchronously regardless of active event loops."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(lambda: asyncio.run(coro)).result()
        return asyncio.run(coro)

    def list_tools_sync(self) -> List[Dict[str, Any]]:
        """Synchronous wrapper for list_tools."""
        return self._run_coroutine_sync(self.list_tools())

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool via the MCP Server."""
        server = self._get_server()
        if not server:
            return {"error": "mcp_server_unavailable", "message": "MCP Server is not reachable"}

        try:
            res = await server.call_tool(name, arguments)
            # Unwrap TextContent
            if hasattr(res, "content") and res.content:
                text_content = res.content[0].text
                try:
                    return json.loads(text_content)
                except (ValueError, TypeError):
                    return {"result": text_content}
            return {"result": str(res)}
        except Exception as e:
            logger.error("Error executing MCP tool '%s': %s", name, e)
            return {"error": "tool_execution_failed", "message": str(e)}

    def call_tool_sync(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous wrapper for call_tool."""
        return self._run_coroutine_sync(self.call_tool(name, arguments))

    async def read_resource(self, uri: str) -> str:
        """Read an MCP resource by URI."""
        server = self._get_server()
        if not server:
            return ""
        try:
            contents = await server.read_resource(uri)
            if contents and hasattr(contents[0], "content"):
                return contents[0].content
            return ""
        except Exception as e:
            logger.error("Error reading MCP resource '%s': %s", uri, e)
            return ""

    def read_resource_sync(self, uri: str) -> str:
        """Synchronous wrapper for read_resource."""
        return self._run_coroutine_sync(self.read_resource(uri))

