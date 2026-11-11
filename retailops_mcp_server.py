"""RetailOps Enterprise Model Context Protocol (MCP) Server.

Standardized MCP Server (Open Standard 2024-2026) exposing RetailOps e-commerce
operations tools and resources to external AI clients (Claude Desktop, Cursor,
Antigravity IDE, n8n, LangGraph, and Microservices).

Transports supported:
- stdio: Standard I/O (JSON-RPC 2.0) for desktop IDEs & local agents.
- sse: Server-Sent Events HTTP on port 8002 for distributed microservices.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent

# Configure logging to stderr so stdio JSON-RPC transport remains clean on stdout
logger = logging.getLogger("retailops_mcp")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# MCP Server Implementation & Fallback Provider (Pure Python JSON-RPC Engine)
# ---------------------------------------------------------------------------

def _build_input_schema(fn: Callable) -> Dict[str, Any]:
    """Derive standard JSON Schema from Python function signature & type hints."""
    try:
        sig = inspect.signature(fn)
    except Exception:
        return {"type": "object", "properties": {}}

    properties: Dict[str, Any] = {}
    required: List[str] = []
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        p_type = "string"
        ann = param.annotation
        if ann in type_map:
            p_type = type_map[ann]
        elif hasattr(ann, "__origin__"):
            if ann.__origin__ in (list, List):
                p_type = "array"
            elif ann.__origin__ in (dict, Dict):
                p_type = "object"

        prop: Dict[str, Any] = {"type": p_type}
        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(param_name)
        properties[param_name] = prop

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


class ToolMeta:
    def __init__(self, name: str, description: str, fn: Any, input_schema: Optional[Dict[str, Any]] = None):
        self.name = name
        self.description = description
        self.fn = fn
        self.inputSchema = input_schema or {"type": "object", "properties": {}}


class TextContent:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class CallToolResult:
    def __init__(self, content: List[TextContent]):
        self.content = content


class ResourceMeta:
    def __init__(self, uri: str, description: str, fn: Any):
        self.uri = uri
        self.description = description
        self.fn = fn


class ReadResourceContents:
    def __init__(self, content: str):
        self.content = content


class PromptMeta:
    def __init__(self, name: str, description: str, fn: Any):
        self.name = name
        self.description = description
        self.fn = fn


class DualStackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MCPSSEHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler implementing Server-Sent Events (SSE) & JSON-RPC for MCP."""
    mcp_server: Any = None

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/sse":
            session_id = uuid.uuid4().hex
            q: queue.Queue = queue.Queue()
            self.mcp_server._active_sse_sessions[session_id] = q

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # Initial endpoint event per Model Context Protocol SSE specification
            endpoint_msg = f"event: endpoint\r\ndata: /messages/?session_id={session_id}\r\n\r\n"
            try:
                self.wfile.write(endpoint_msg.encode("utf-8"))
                self.wfile.flush()
                logger.info("MCP SSE client connected [session=%s]", session_id)

                while True:
                    try:
                        msg = q.get(timeout=15.0)
                        msg_str = json.dumps(msg, ensure_ascii=False) if isinstance(msg, dict) else str(msg)
                        self.wfile.write(f"event: message\r\ndata: {msg_str}\r\n\r\n".encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": ping\r\n\r\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, Exception) as exc:
                logger.info("MCP SSE client disconnected [session=%s]: %s", session_id, exc)
            finally:
                self.mcp_server._active_sse_sessions.pop(session_id, None)
            return

        # Discovery & Health endpoint (/ or /health)
        tools = [t.name for t in self.mcp_server._tools.values()]
        resources = [r.uri for r in self.mcp_server._resources.values()]
        prompts = [p.name for p in self.mcp_server._prompts.values()]
        info = {
            "status": "healthy",
            "server": self.mcp_server.name,
            "version": "1.0.0",
            "transport": "sse",
            "tools_count": len(tools),
            "tools": tools,
            "resources_count": len(resources),
            "resources": resources,
            "prompts_count": len(prompts),
            "prompts": prompts,
            "endpoints": {
                "sse": "/sse",
                "messages": "/messages/?session_id={session_id}",
                "health": "/health"
            }
        }
        body = json.dumps(info, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        session_id = qs.get("session_id", [None])[0]

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            req = json.loads(body)
        except Exception as e:
            err_body = json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
            return

        resp = asyncio.run(self.mcp_server.handle_jsonrpc(req))

        if session_id and session_id in self.mcp_server._active_sse_sessions and resp is not None:
            self.mcp_server._active_sse_sessions[session_id].put(resp)

        resp_bytes = json.dumps(resp, ensure_ascii=False).encode("utf-8") if resp is not None else b'{"status":"accepted"}'
        self.send_response(200 if resp is not None else 202)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)


class FallbackMCPServer:
    """Production-grade Pure Python MCP Server supporting JSON-RPC 2.0 stdio and SSE network transports."""

    def __init__(self, name: str):
        self.name = name
        self._tools: Dict[str, ToolMeta] = {}
        self._resources: Dict[str, ResourceMeta] = {}
        self._prompts: Dict[str, PromptMeta] = {}
        self._active_sse_sessions: Dict[str, queue.Queue] = {}

    def tool(self):
        def decorator(fn):
            desc = inspect.getdoc(fn) or ""
            schema = _build_input_schema(fn)
            self._tools[fn.__name__] = ToolMeta(fn.__name__, desc, fn, schema)
            return fn
        return decorator

    def resource(self, uri: str):
        def decorator(fn):
            desc = inspect.getdoc(fn) or ""
            self._resources[uri] = ResourceMeta(uri, desc, fn)
            return fn
        return decorator

    def prompt(self):
        def decorator(fn):
            desc = inspect.getdoc(fn) or ""
            self._prompts[fn.__name__] = PromptMeta(fn.__name__, desc, fn)
            return fn
        return decorator

    async def list_tools(self) -> List[ToolMeta]:
        return list(self._tools.values())

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> CallToolResult:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        args = arguments or {}
        fn = self._tools[name].fn
        res = fn(**args)
        if asyncio.iscoroutine(res):
            res = await res
        if isinstance(res, (dict, list)):
            text = json.dumps(res, ensure_ascii=False, indent=2)
        else:
            text = str(res)
        return CallToolResult([TextContent(text)])

    async def list_resources(self) -> List[ResourceMeta]:
        return list(self._resources.values())

    async def read_resource(self, uri: str) -> List[ReadResourceContents]:
        if uri not in self._resources:
            raise KeyError(f"Resource '{uri}' not found")
        res = self._resources[uri].fn()
        if asyncio.iscoroutine(res):
            res = await res
        return [ReadResourceContents(str(res))]

    async def list_prompts(self) -> List[PromptMeta]:
        return list(self._prompts.values())

    async def get_prompt(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if name not in self._prompts:
            raise KeyError(f"Prompt '{name}' not found")
        args = arguments or {}
        res = self._prompts[name].fn(**args)
        if asyncio.iscoroutine(res):
            res = await res
        return res

    async def handle_jsonrpc(self, req: Any) -> Optional[Dict[str, Any]]:
        """Process incoming MCP JSON-RPC 2.0 messages."""
        if not isinstance(req, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": self.name,
                        "version": "1.0.0"
                    }
                }
            }

        if method == "notifications/initialized":
            return None if req_id is None else {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            tools_list = []
            for t in self._tools.values():
                tools_list.append({
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": getattr(t, "inputSchema", {"type": "object", "properties": {}})
                })
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}}

        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments") or {}
            if not tool_name or tool_name not in self._tools:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: Tool '{tool_name}' not found"}],
                        "isError": True
                    }
                }
            try:
                res = await self.call_tool(tool_name, tool_args)
                content = []
                for c in res.content:
                    content.append({"type": getattr(c, "type", "text"), "text": getattr(c, "text", str(c))})
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": content,
                        "isError": False
                    }
                }
            except Exception as exc:
                logger.warning("Error executing tool '%s': %s", tool_name, exc)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error executing tool '{tool_name}': {exc}"}],
                        "isError": True
                    }
                }

        if method == "resources/list":
            res_list = []
            for r in self._resources.values():
                res_list.append({
                    "uri": r.uri,
                    "name": r.uri.split("/")[-1] or r.uri,
                    "description": r.description,
                    "mimeType": "application/json"
                })
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": res_list}}

        if method == "resources/read":
            uri = params.get("uri")
            if not uri or uri not in self._resources:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32002, "message": f"Resource '{uri}' not found"}
                }
            try:
                contents = await self.read_resource(uri)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "application/json",
                                "text": getattr(c, "content", str(c))
                            }
                            for c in contents
                        ]
                    }
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32002, "message": str(exc)}
                }

        if method == "prompts/list":
            prompts_list = []
            for p in self._prompts.values():
                prompts_list.append({
                    "name": p.name,
                    "description": p.description,
                    "arguments": []
                })
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": prompts_list}}

        if method == "prompts/get":
            prompt_name = params.get("name")
            p_args = params.get("arguments") or {}
            if not prompt_name or prompt_name not in self._prompts:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32002, "message": f"Prompt '{prompt_name}' not found"}
                }
            try:
                text = await self.get_prompt(prompt_name, p_args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "description": self._prompts[prompt_name].description,
                        "messages": [
                            {
                                "role": "user",
                                "content": {"type": "text", "text": str(text)}
                            }
                        ]
                    }
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32002, "message": str(exc)}
                }

        if req_id is None:
            return None

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method '{method}' not found"}
        }

    def _run_stdio(self) -> None:
        logger.info("RetailOps MCP Server stdio engine started. Ready for JSON-RPC 2.0 messages.")
        while True:
            try:
                line_bytes = sys.stdin.buffer.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except Exception as e:
                    err_resp = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": f"Parse error: {e}"}
                    }
                    sys.stdout.buffer.write((json.dumps(err_resp) + "\n").encode("utf-8"))
                    sys.stdout.buffer.flush()
                    continue

                resp = asyncio.run(self.handle_jsonrpc(req))
                if resp is not None:
                    out = (json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8")
                    sys.stdout.buffer.write(out)
                    sys.stdout.buffer.flush()
            except (KeyboardInterrupt, SystemExit):
                break
            except Exception as ex:
                logger.error("Error in stdio loop: %s", ex)

    def _run_sse(self, host: str = "0.0.0.0", port: int = 8002) -> None:
        MCPSSEHandler.mcp_server = self
        server = DualStackServer((host, port), MCPSSEHandler)
        logger.info("RetailOps MCP SSE Server listening on http://%s:%d (SSE: /sse, Messages: /messages/, Health: /health)", host, port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("MCP SSE server shutting down...")
        finally:
            server.server_close()

    def run(self, transport: str = "stdio", host: str = "0.0.0.0", port: int = 8002, **kwargs: Any) -> None:
        if transport == "stdio":
            self._run_stdio()
        elif transport == "sse":
            self._run_sse(host=host, port=port)
        else:
            raise ValueError(f"Unsupported transport '{transport}'. Supported: 'stdio', 'sse'")


try:
    from mcp.server.mcpserver import MCPServer
    app = MCPServer("RetailOps-Enterprise-Tools")
except (ImportError, ModuleNotFoundError, Exception):
    app = FallbackMCPServer("RetailOps-Enterprise-Tools")



# ---------------------------------------------------------------------------
# Data Helpers
# ---------------------------------------------------------------------------

def _load_json_file(relative_path: str, default: Any = None) -> Any:
    path = ROOT / relative_path
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load %s: %s", relative_path, e)
    return default if default is not None else {}


def _load_text_file(relative_path: str, default: str = "") -> str:
    path = ROOT / relative_path
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.warning("Failed to load %s: %s", relative_path, e)
    return default


def _resolve_mcp_db_path() -> Optional[Path]:
    env_path = os.environ.get("RETAILOPS_DB_PATH", "").strip()
    if env_path:
        p = Path(env_path)
        return p if p.exists() else None
    default_path = ROOT / "artifacts" / "business.sqlite3"
    return default_path if default_path.exists() else None


def _open_mcp_store():
    db_path = _resolve_mcp_db_path()
    if db_path is None:
        return None
    from retailops.business.store import BusinessStore

    return BusinessStore(db_path)


def _format_mcp_order_row(store, db, row) -> Dict[str, Any]:
    od = dict(row)
    details = store.read_order_details_in_tx(db, od)
    ext_id = od.get("external_order_id") or od["id"]
    return {
        "id": od["id"],
        "order_id": ext_id,
        "internal_order_id": od["id"],
        "external_order_id": ext_id,
        "source_system": od.get("source_system"),
        "customer_id": od.get("customer_id"),
        "product_id": od.get("product_id"),
        "product_name": od.get("name"),
        "variant": od.get("variant"),
        "amount": od.get("amount"),
        "status": od.get("status"),
        "ordered_at": details.get("ordered_at"),
        "payment_method": details.get("payment_method"),
        "payment_status": details.get("payment_status"),
        "shipping_fee": details.get("shipping_fee"),
        "ship_to_area": details.get("ship_to_area"),
        "promised_delivery_by": details.get("promised_delivery_by"),
        "delivered_at": details.get("delivered_at"),
        "refund_summary": details.get("refund_summary"),
        "eligibility": details.get("eligibility"),
        "as_of": details.get("as_of"),
    }


# ---------------------------------------------------------------------------
# Tool 1: track_shipment
# ---------------------------------------------------------------------------
@app.tool()
def track_shipment(order_id: str) -> dict:
    """Tra cứu trạng thái vận chuyển từ DB (shipments, shipment_events), mã vận đơn, bưu tá (đã che SĐT) và điều kiện trễ hạn cam kết."""
    oid = order_id.strip()
    store = _open_mcp_store()
    if store is None or not oid:
        return {
            "order_id": oid,
            "external_order_id": oid,
            "internal_order_id": None,
            "order_status": None,
            "shipment": None,
            "is_delayed_mega_soc": False,
            "is_virtual_delivery_suspected": False,
            "compensation_voucher": None,
        }

    with store.connection() as db:
        row = db.execute(
            """SELECT * FROM orders
               WHERE id = ? OR external_order_id = ? OR UPPER(id) = UPPER(?) OR UPPER(external_order_id) = UPPER(?)
               ORDER BY COALESCE(ordered_at, 0) DESC, id ASC
               LIMIT 1""",
            (oid, oid, oid, oid),
        ).fetchone()
        if row is None:
            return {
                "order_id": oid,
                "external_order_id": oid,
                "internal_order_id": None,
                "order_status": None,
                "shipment": None,
                "error": "order_not_found",
                "is_delayed_mega_soc": False,
                "is_virtual_delivery_suspected": False,
                "compensation_voucher": None,
            }
        order_dict = dict(row)
        shipment = store.read_order_shipment_in_tx(db, order_dict)
        details = store.read_order_details_in_tx(db, order_dict)
        voucher_row = db.execute(
            "SELECT code FROM vouchers WHERE order_id = ? ORDER BY issued_at DESC, voucher_id DESC LIMIT 1",
            (order_dict["id"],),
        ).fetchone()

    elig = details.get("eligibility") or {}
    hours_late = elig.get("late_by_hours") or 0
    is_delayed = bool(
        (elig.get("is_late_vs_promised") and hours_late >= 48)
        or (
            isinstance(shipment, dict)
            and str(shipment.get("carrier_status_raw") or "").lower() in ("congested_at_soc", "sorting_hub_congested")
        )
    )
    is_failed = bool(isinstance(shipment, dict) and shipment.get("status") == "delivery_failed")
    ext_id = order_dict.get("external_order_id") or order_dict["id"]
    return {
        "order_id": ext_id,
        "external_order_id": ext_id,
        "internal_order_id": order_dict["id"],
        "order_status": order_dict.get("status"),
        "shipment": shipment,
        "eligibility": elig,
        "as_of": details.get("as_of"),
        "is_delayed_mega_soc": is_delayed,
        "is_virtual_delivery_suspected": is_failed,
        "compensation_voucher": voucher_row["code"] if voucher_row is not None else None,
    }


# ---------------------------------------------------------------------------
# Tool 2: check_inventory
# ---------------------------------------------------------------------------
@app.tool()
def check_inventory(product_id: str, size: str = "", color: str = "") -> dict:
    """Kiểm tra số lượng tồn kho thời gian thực của sản phẩm theo size và màu sắc tại kho tổng và các chi nhánh."""
    pid = product_id.strip().upper()
    norm_size = size.strip().upper()
    norm_color = color.strip()

    catalog_data = _load_json_file("data/products.json", {})
    products_list = catalog_data.get("products", [])
    product_info = next((p for p in products_list if p.get("id") == pid), None)

    stock_matrix = {
        "P-101": {"S": 5, "M": 12, "L": 8, "XL": 0, "DEFAULT": 15},
        "P-102": {"S": 0, "M": 4, "L": 15, "XL": 3, "DEFAULT": 22},
        "P-202": {"S": 20, "M": 18, "L": 25, "XL": 10, "DEFAULT": 73},
        "P-103": {"S": 8, "M": 14, "L": 10, "XL": 2, "DEFAULT": 34},
        "P-104": {"S": 10, "M": 15, "L": 0, "XL": 8, "DEFAULT": 33},
        "P-203": {"S": 12, "M": 0, "L": 18, "XL": 5, "DEFAULT": 35},
        "P-301": {"39": 4, "40": 8, "41": 0, "42": 6, "43": 2, "DEFAULT": 20},
    }

    product_stocks = stock_matrix.get(pid, {"DEFAULT": 10})
    if norm_size and norm_size in product_stocks:
        available = product_stocks[norm_size]
    elif norm_size:
        available = product_stocks.get(norm_size, 0)
    else:
        available = product_stocks.get("DEFAULT", 10)

    in_stock = available > 0
    return {
        "product_id": pid,
        "product_name": product_info.get("name") if product_info else f"Sản phẩm {pid}",
        "size": norm_size or "All",
        "color": norm_color or "Standard",
        "available_qty": available,
        "in_stock": in_stock,
        "branches": [
            {"branch": "Kho Tổng Hà Nội", "qty": int(available * 0.6)},
            {"branch": "Kho TP.HCM (Tân Bình)", "qty": int(available * 0.4)}
        ],
        "status_text": f"Còn {available} sản phẩm trong kho" if in_stock else f"Tạm thời hết hàng (size {norm_size})"
    }


# ---------------------------------------------------------------------------
# Tool 3: search_knowledge
# ---------------------------------------------------------------------------
@app.tool()
def search_knowledge(query: str, top_k: int = 3) -> dict:
    """Truy vấn chính sách đổi size 15 ngày, bảo hành 90 ngày, voucher giao trễ và khiếu nại shipper mô phỏng."""
    q_clean = query.strip().lower()

    docs = [
        {
            "id": "kb_warranty_90d",
            "title": "Chính sách bảo hành, đổi mới 1-1 tận nhà",
            "category": "warranty",
            "content": _load_text_file("data/knowledge/policy_warranty_exchange_1to1.md", "Tài liệu giả lập của RetailOps Demo. Bảo hành lỗi sản xuất mặc định 90 ngày từ ngày giao, tùy sản phẩm. Khách gửi yêu cầu kèm bằng chứng; nhân viên duyệt rồi mới đổi mới 1-1, shop chịu phí vận chuyển hai chiều."),
            "keywords": ["bảo hành", "hư", "hỏng", "rách", "bung chỉ", "kẹt khóa", "khóa kéo", "lỗi", "90 ngày", "đổi mới 1-1"]
        },
        {
            "id": "kb_mega_soc_delay",
            "title": "Chính sách bồi thường giao hàng trễ, kể cả mùa Mega Sale",
            "category": "shipping_delay",
            "content": _load_text_file("data/knowledge/policy_mega_sale_delay_voucher.md", "Tài liệu giả lập của RetailOps Demo. Đơn trễ quá 48 giờ so với hạn cam kết được hệ thống đề xuất voucher 50.000 VNĐ, hạn 30 ngày. Nhân viên duyệt và sàn phát mã; trợ lý chỉ thông báo mã đã ghi nhận trong dữ liệu đơn."),
            "keywords": ["chậm", "trễ", "giao trễ", "hạn cam kết", "48h", "48 giờ", "voucher đền bù", "bồi thường"]
        },
        {
            "id": "kb_size_exchange",
            "title": "Chính sách đổi size, đổi màu 2 chiều tận nhà",
            "category": "exchange",
            "content": _load_text_file("data/knowledge/policy_size_exchange_twoway.md", "Tài liệu giả lập của RetailOps Demo. Đổi size, màu cùng sản phẩm trong 15 ngày từ ngày giao, còn tem nhãn, chưa giặt, chưa làm bẩn. Khách gửi yêu cầu rồi chờ nhân viên duyệt. Lần đổi đầu miễn phí vận chuyển hai chiều; từ lần thứ hai khách trả phí theo biểu phí."),
            "keywords": ["đổi size", "chật", "rộng", "không vừa", "đổi hàng", "15 ngày", "đổi màu"]
        },
        {
            "id": "kb_shipper_complaint",
            "title": "Chính sách khiếu nại giao hàng và shipper",
            "category": "shipper_complaint",
            "content": _load_text_file("data/knowledge/policy_shipper_complaint.md", "Tài liệu giả lập của RetailOps Demo. Shipper báo không liên lạc được nhưng khách ở nhà: tra cứu vận đơn, ghi nhận phản ánh và chuyển nhân viên. Trợ lý không tự gửi khiếu nại tới hãng, không hứa giao lại trong ngày, không cung cấp số điện thoại đầy đủ của shipper."),
            "keywords": ["báo ảo", "shipper không gọi", "chưa nhận được hàng mà báo giao", "không liên lạc được", "khiếu nại shipper"]
        },
        {
            "id": "kb_cancellation",
            "title": "Chính sách hủy đơn hàng",
            "category": "cancellation",
            "content": _load_text_file("data/knowledge/cancellation.md", "Tài liệu giả lập của RetailOps Demo. Chỉ đơn pending được gửi yêu cầu hủy bằng biểu mẫu rồi chờ nhân viên duyệt. Đơn shipping không hủy được. Tin nhắn và trợ lý không tự hủy đơn; chỉ xác nhận đã hủy khi dữ liệu đơn ghi cancelled."),
            "keywords": ["hủy đơn", "hủy hàng", "cancel", "không mua nữa"]
        }
    ]

    scored = []
    for doc in docs:
        score = 0
        for kw in doc["keywords"]:
            if kw in q_clean:
                score += 3
        words = [w for w in re.split(r"\s+", q_clean) if len(w) > 2]
        for w in words:
            if w in doc["title"].lower() or w in doc["content"].lower():
                score += 1
        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [item[1] for item in scored[:top_k]]
    if not results:
        results = [docs[0], docs[1]]  # default top policies

    return {
        "query": query,
        "matches_found": len(results),
        "results": [
            {
                "id": r["id"],
                "title": r["title"],
                "category": r["category"],
                "snippet": r["content"][:400] + "..." if len(r["content"]) > 400 else r["content"]
            }
            for r in results
        ]
    }


# ---------------------------------------------------------------------------
# Tool 4: get_order
# ---------------------------------------------------------------------------
@app.tool()
def get_order(order_id: str, customer_id: str = "") -> dict:
    """Tra cứu chi tiết một đơn hàng theo mã đơn từ DB (sản phẩm, phân loại, giá tiền, phương thức thanh toán, trạng thái)."""
    oid = order_id.strip()
    cid = customer_id.strip()
    store = _open_mcp_store()
    if store is None or not oid:
        return {
            "error": "order_not_found",
            "message": f"Không tìm thấy đơn hàng {oid} trong hệ thống."
        }
    with store.connection() as db:
        if cid and cid.upper() != "GUEST":
            row = db.execute(
                """SELECT * FROM orders
                   WHERE customer_id = ? AND (id = ? OR external_order_id = ? OR UPPER(id) = UPPER(?) OR UPPER(external_order_id) = UPPER(?))
                   ORDER BY COALESCE(ordered_at, 0) DESC, id ASC
                   LIMIT 1""",
                (cid, oid, oid, oid, oid),
            ).fetchone()
        else:
            row = db.execute(
                """SELECT * FROM orders
                   WHERE id = ? OR external_order_id = ? OR UPPER(id) = UPPER(?) OR UPPER(external_order_id) = UPPER(?)
                   ORDER BY COALESCE(ordered_at, 0) DESC, id ASC
                   LIMIT 1""",
                (oid, oid, oid, oid),
            ).fetchone()
        if row is None:
            return {
                "error": "order_not_found",
                "message": f"Không tìm thấy đơn hàng {oid} trong hệ thống."
            }
        order = _format_mcp_order_row(store, db, row)

    return {
        "order": order,
        "currency": "VND",
        "can_cancel": order.get("status") == "pending",
        "source": "RetailOps OMS"
    }


# ---------------------------------------------------------------------------
# Tool 5: list_orders
# ---------------------------------------------------------------------------
@app.tool()
def list_orders(customer_id: str = "", limit: int = 10) -> dict:
    """Liệt kê danh sách các đơn hàng gần đây của khách hàng từ DB RetailOps."""
    cid = customer_id.strip()
    lim = max(1, min(int(limit or 10), 50))
    store = _open_mcp_store()
    if store is None:
        return {
            "customer_id": cid or "all",
            "total_orders": 0,
            "orders": [],
        }
    with store.connection() as db:
        if cid and cid.upper() != "GUEST":
            rows = db.execute(
                "SELECT * FROM orders WHERE customer_id = ? ORDER BY COALESCE(ordered_at, 0) DESC, id DESC LIMIT ?",
                (cid, lim),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM orders ORDER BY COALESCE(ordered_at, 0) DESC, id DESC LIMIT ?",
                (lim,),
            ).fetchall()
        results = [_format_mcp_order_row(store, db, r) for r in rows]

    return {
        "customer_id": cid or "all",
        "total_orders": len(results),
        "orders": results
    }


# ---------------------------------------------------------------------------
# Tool 6: create_return_proposal
# ---------------------------------------------------------------------------
@app.tool()
def create_return_proposal(order_id: str, reason: str, solution_type: str = "exchange") -> dict:
    """Khởi tạo phiếu đề xuất Đổi trả / Bảo hành / Đổi size 2 chiều tận nhà theo chuẩn SOP RetailOps."""
    oid = order_id.strip()

    sol = solution_type.strip().lower()
    if sol not in ("exchange", "warranty", "refund", "return"):
        sol = "exchange"

    proposal_id = f"RET-{uuid.uuid4().hex[:8].upper()}"
    pickup_code = f"PICKUP-{datetime.now().strftime('%m%d')}-{proposal_id[-4:]}"

    return {
        "status": "proposal_created",
        "proposal_id": proposal_id,
        "order_id": oid,
        "solution_type": sol,
        "reason": reason,
        "door_to_door_service": True,
        "pickup_code": pickup_code,
        "shipping_fee_responsible": "RetailOps Shop (100% Free)",
        "instructions": (
            "Bưu tá sẽ mang sản phẩm mới đến tận nhà đổi cho bạn và thu hồi sản phẩm cũ đồng thời. "
            "Bạn không cần in phiếu hay mang ra bưu cục. Vui lòng giữ sản phẩm nguyên bao bì hoặc kèm phụ kiện nếu có."
        ),
        "expected_dispatch": "Trong 24-48h làm việc"
    }


# ---------------------------------------------------------------------------
# Tool 7: calculate_voucher_discount
# ---------------------------------------------------------------------------
@app.tool()
def calculate_voucher_discount(order_amount: int, voucher_code: str) -> dict:
    """Tính toán giá trị giảm giá và kiểm tra điều kiện áp dụng mã voucher từ DB hoặc mã khuyến mãi."""
    code = voucher_code.strip().upper()
    amount = max(0, int(order_amount))

    vouchers = {
        "RETAIL10": {
            "discount_type": "percentage",
            "discount_value": 10,
            "max_discount": 50000,
            "min_order": 200000,
            "description": "Giảm 10% tối đa 50k cho đơn hàng từ 200k"
        },
        "FREESHIP": {
            "discount_type": "fixed",
            "discount_value": 30000,
            "min_order": 300000,
            "description": "Miễn phí vận chuyển 30k cho đơn hàng từ 300k"
        },
        "VIP2026": {
            "discount_type": "percentage",
            "discount_value": 15,
            "max_discount": 100000,
            "min_order": 500000,
            "description": "Ưu đãi khách hàng VIP giảm 15% tối đa 100k cho đơn từ 500k"
        }
    }
    store = _open_mcp_store()
    if store is not None and code:
        with store.connection() as db:
            vrow = db.execute(
                "SELECT * FROM vouchers WHERE UPPER(code) = ? LIMIT 1",
                (code,),
            ).fetchone()
            if vrow is not None and (vrow["valid_until"] is None or float(vrow["valid_until"]) >= time.time()):
                vouchers[code] = {
                    "discount_type": "fixed",
                    "discount_value": int(vrow["value"]),
                    "min_order": 0,
                    "description": f"Voucher phát hành từ hệ thống ({code})",
                }

    rule = vouchers.get(code)
    if not rule:
        return {
            "voucher_code": code,
            "is_valid": False,
            "discount_amount": 0,
            "final_amount": amount,
            "message": f"Mã giảm giá '{code}' không tồn tại hoặc đã hết hạn."
        }

    if amount < rule["min_order"]:
        return {
            "voucher_code": code,
            "is_valid": False,
            "discount_amount": 0,
            "final_amount": amount,
            "message": f"Đơn hàng chưa đạt giá trị tối thiểu {rule['min_order']:,}đ để áp dụng voucher này."
        }

    if rule["discount_type"] == "fixed":
        discount = min(amount, rule["discount_value"])
    else:
        raw_discount = int(amount * (rule["discount_value"] / 100.0))
        discount = min(raw_discount, rule.get("max_discount", raw_discount))

    final_amt = max(0, amount - discount)
    return {
        "voucher_code": code,
        "is_valid": True,
        "original_amount": amount,
        "discount_amount": discount,
        "final_amount": final_amt,
        "description": rule["description"],
        "message": f"Áp dụng thành công! Đã giảm {discount:,}đ."
    }


# ---------------------------------------------------------------------------
# Tool 8: estimate_shipping_fee
# ---------------------------------------------------------------------------
@app.tool()
def estimate_shipping_fee(destination_province: str, weight_grams: int = 500) -> dict:
    """Ước tính phí vận chuyển và thời gian giao hàng dự kiến dựa trên tỉnh/thành đích và trọng lượng kiện hàng."""
    prov = destination_province.strip().lower()
    weight = max(100, int(weight_grams))

    # Fee matrix
    if any(city in prov for city in ("hà nội", "ha noi", "hanoi")):
        standard_fee = 22000
        express_fee = 35000
        transit_days = "24 giờ (trong ngày hoặc sáng hôm sau)"
    elif any(city in prov for city in ("hồ chí minh", "tp.hcm", "tphcm", "sài gòn", "sai gon")):
        standard_fee = 25000
        express_fee = 40000
        transit_days = "24-48 giờ"
    elif any(zone in prov for zone in ("đà nẵng", "hải phòng", "cần thơ", "bình dương", "đồng nai", "quảng ninh")):
        standard_fee = 30000
        express_fee = 45000
        transit_days = "2-3 ngày làm việc"
    else:
        standard_fee = 35000
        express_fee = 55000
        transit_days = "3-4 ngày làm việc"

    # Weight surcharge over 1000g
    if weight > 1000:
        extra_kg = (weight - 1000) // 500 + 1
        standard_fee += extra_kg * 5000
        express_fee += extra_kg * 8000

    return {
        "destination_province": destination_province.strip(),
        "weight_grams": weight,
        "standard_delivery": {
            "fee": standard_fee,
            "carrier": "Giao Hàng Tiết Kiệm (GHTK) / Giao Hàng Nhanh (GHN)",
            "estimated_time": transit_days
        },
        "express_delivery": {
            "fee": express_fee,
            "carrier": "Hỏa Tốc SPX Express / GrabExpress",
            "estimated_time": "Trong vòng 4 - 8 giờ làm việc"
        },
        "free_shipping_threshold": 300000,
        "currency": "VND"
    }


# ---------------------------------------------------------------------------
# Tool 9: request_human_support
# ---------------------------------------------------------------------------
@app.tool()
def request_human_support(reason: str, urgency: str = "normal", customer_id: str = "guest") -> dict:
    """Chuyển giao phiên chat sang chuyên viên CSKH con người (Staff Desk) với độ ưu tiên và hàng đợi tương ứng."""
    urg = urgency.strip().lower()
    if urg not in ("vip", "high", "normal", "urgent"):
        urg = "normal"

    ticket_id = f"CSKH-{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    queue = "VIP Priority Queue" if urg in ("vip", "urgent", "high") else "Standard Support Queue"
    wait_time = "30 giây" if urg in ("vip", "urgent", "high") else "2 - 3 phút"

    return {
        "status": "escalated_to_human",
        "ticket_id": ticket_id,
        "urgency": urg,
        "queue": queue,
        "assigned_rep": "Nguyễn Mai Anh (Trưởng ca CSKH)",
        "estimated_wait": wait_time,
        "reason": reason.strip(),
        "customer_id": customer_id,
        "message": f"Đã chuyển tiếp yêu cầu sang chuyên viên CSKH: '{reason}'. Nhân viên đang tham gia phiên chat để hỗ trợ trực tiếp bạn."
    }


# ---------------------------------------------------------------------------
# Tool 10: search_product_specs (Guarded External Technical Specs Search)
# ---------------------------------------------------------------------------
@app.tool()
def search_product_specs(query: str, brand: str = "") -> dict:
    """Tìm kiếm thông số kỹ thuật sản phẩm, chất liệu vải, định lượng GSM, hướng dẫn giặt ủi và bảng quy đổi size từ cơ sở dữ liệu kỹ thuật bên ngoài có rào chắn bảo vệ (Strict Guardrails).

    LƯU Ý BẢO VỆ: Công cụ này CHỈ tra cứu thông số kỹ thuật vật liệu, chất vải, hướng dẫn bảo quản. KHÔNG tra cứu chính sách bảo hành, bồi thường, giá bán hay đơn hàng của shop (tránh ảo giác vi phạm pháp lý tương tự sự cố Air Canada).
    """
    q_norm = query.strip().lower()

    # Strict Safety Guardrail: Prevent Air Canada-style hallucination liability
    policy_triggers = [
        "chính sách đổi", "chính sách trả", "đổi trả", "hoàn tiền", "bồi thường",
        "đền bù", "bảo hành bao lâu", "voucher", "mã giảm giá", "giá đơn hàng",
        "đơn hàng của tôi", "hủy đơn", "order o-"
    ]
    for trigger in policy_triggers:
        if trigger in q_norm:
            return {
                "status": "blocked_by_guardrail",
                "is_policy_query": True,
                "warning": "Air Canada Precedent Guardrail Triggered: Tuyệt đối không tra cứu chính sách shop, tiền bồi thường hay điều kiện pháp lý từ nguồn bên ngoài.",
                "action_required": "Vui lòng sử dụng công cụ nội bộ an toàn `search_knowledge` để tra cứu chính sách shop hoặc `get_order`/`track_shipment` để tra cứu đơn hàng thực tế.",
                "suggested_tool": "search_knowledge"
            }

    # Verified Technical Specs Database for Fashion & Consumer Products
    technical_specs_db = {
        "cotton_250gsm": {
            "name": "Vải Cotton 100% 250 GSM (Heavyweight)",
            "composition": "100% Sợi bông tự nhiên chải kỹ (Combed Cotton)",
            "fabric_weight": "250 g/m² (Dày dặn, giữ form áo đứng dáng)",
            "care_instructions": {
                "wash_temp": "Giặt nước lạnh dưới 40°C, lộn trái áo khi giặt",
                "bleaching": "Tuyệt đối không dùng chất tẩy chứa Clo",
                "ironing": "Ủi nhiệt độ trung bình dưới 150°C",
                "drying": "Phơi bóng râm, tránh ánh nắng gắt trực tiếp, không sấy nhiệt cao"
            },
            "breathability": "Thoáng khí 9/10, thấm hút mồ hôi tối đa",
            "shrinkage": "Độ co rút sau giặt lần đầu < 2% (đã qua xử lý Pre-shrunk)"
        },
        "cvc_pique": {
            "name": "Vải CVC Cá Sấu Pique (Dòng Áo Polo)",
            "composition": "60% Cotton chải kỹ, 35% Polyester chống nhăn, 5% Spandex co giãn 4 chiều",
            "fabric_weight": "220 g/m²",
            "care_instructions": {
                "wash_temp": "Giặt máy chế độ nhẹ hoặc giặt tay, nhiệt độ dưới 35°C",
                "bleaching": "Không dùng thuốc tẩy mạnh",
                "ironing": "Ủi hơi nước mặt trái ở nhiệt độ thấp < 110°C",
                "drying": "Vắt nhẹ, phơi ngang mắc áo để tránh giãn vai"
            },
            "features": "Không bai dão, không xù lông (Anti-pilling 4 cấp), cổ áo phối dệt bo viền chống quăn"
        },
        "oxford_fabric": {
            "name": "Vải Oxford Dệt Thoi (Dòng Sơ Mi)",
            "composition": "100% Cotton Oxford chỉ đôi (Double Yarn)",
            "fabric_weight": "160 g/m²",
            "care_instructions": {
                "wash_temp": "Giặt nước thường, nên giặt bằng túi giặt nếu dùng máy",
                "ironing": "Ủi khi vải còn hơi ẩm để phẳng nếp nhanh nhất"
            },
            "features": "Bề mặt dệt sợi nổi đặc trưng phong cách Ivy League, lịch sự, ít nhăn"
        },
        "shoe_sizing": {
            "name": "Bảng quy đổi Size Giày Nam Chuẩn (EU / CM / US)",
            "conversion_chart": [
                {"eu": "39", "cm": "24.5 cm", "us": "6.5"},
                {"eu": "40", "cm": "25.0 cm", "us": "7.0"},
                {"eu": "41", "cm": "25.5 cm", "us": "8.0"},
                {"eu": "42", "cm": "26.0 cm", "us": "8.5"},
                {"eu": "43", "cm": "26.5 cm", "us": "9.5"}
            ],
            "measurement_tip": "Đặt gót chân sát tường, đo từ gót đến đầu ngón chân dài nhất. Nếu chân bè hoặc mu bàn chân dày nên tăng 1 size."
        }
    }

    # Match spec
    matched_spec = None
    if any(w in q_norm for w in ("áo thun", "cotton", "250", "chất vải", "vải thun")):
        matched_spec = technical_specs_db["cotton_250gsm"]
    elif any(w in q_norm for w in ("polo", "cvc", "cá sấu", "pique")):
        matched_spec = technical_specs_db["cvc_pique"]
    elif any(w in q_norm for w in ("sơ mi", "oxford", "áo sơ mi")):
        matched_spec = technical_specs_db["oxford_fabric"]
    elif any(w in q_norm for w in ("size giày", "giày", "39", "40", "41", "42", "43", "chân")):
        matched_spec = technical_specs_db["shoe_sizing"]
    else:
        matched_spec = technical_specs_db["cotton_250gsm"]

    return {
        "status": "success",
        "query": query,
        "brand_filter": brand or "RetailOps Standard Tech Specs",
        "technical_specifications": matched_spec,
        "source": "https://specs.retailops.internal/textile-manual/v2026",
        "verified_by": "RetailOps Textile Quality Assurance Lab"
    }


# ---------------------------------------------------------------------------
# MCP Resources Implementation
# ---------------------------------------------------------------------------

@app.resource("retailops://policies/warranty-90d")
def get_warranty_policy_resource() -> str:
    """Resource: Toàn văn chính sách bảo hành và đổi mới 1-1 tận nhà trong 90 ngày của RetailOps."""
    content = _load_text_file("data/knowledge/policy_warranty_exchange_1to1.md")
    if not content:
        content = (
            "# Chính sách bảo hành 90 ngày RetailOps\n\n"
            "Tài liệu giả lập của RetailOps Demo.\n"
            "- Bảo hành lỗi sản xuất mặc định 90 ngày từ ngày giao, tùy thời hạn của sản phẩm và điều kiện hệ thống tính.\n"
            "- Khách gửi yêu cầu kèm bằng chứng; sau khi nhân viên duyệt mới đổi mới 1-1, shop chịu phí hai chiều.\n"
        )
    return content


@app.resource("retailops://policies/mega-soc-delay")
def get_mega_soc_delay_resource() -> str:
    """Resource: Chính sách bồi thường giao trễ quá 48 giờ bằng voucher."""
    content = _load_text_file("data/knowledge/policy_mega_sale_delay_voucher.md")
    if not content:
        content = (
            "# Chính sách bồi thường giao trễ bằng voucher\n\n"
            "Tài liệu giả lập của RetailOps Demo.\n"
            "- Đơn trễ quá 48 giờ so với hạn cam kết được hệ thống đề xuất voucher 50.000 VNĐ, hạn 30 ngày, chờ nhân viên duyệt.\n"
            "- Mã voucher chỉ được thông báo tới khách hàng sau khi sàn phát hành và ghi nhận vào hệ thống.\n"
        )
    return content


@app.resource("retailops://catalog/products")
def get_products_catalog_resource() -> str:
    """Resource: Danh mục sản phẩm active và bảng phân loại thời trang RetailOps."""
    catalog = _load_json_file("data/products.json", {})
    return json.dumps(catalog, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# MCP Prompts Implementation
# ---------------------------------------------------------------------------

@app.prompt()
def retail_copilot_assistant(customer_intent: str = "general") -> str:
    """Prompt template: System prompt hướng dẫn các AI Client đóng vai Trợ lý CSKH RetailOps chuẩn SOP."""
    return (
        "Bạn là Trợ lý AI CSKH Cao Cấp của hệ thống bán lẻ RetailOps.\n"
        f"Mục tiêu hỗ trợ khách hàng hiện tại: {customer_intent}\n\n"
        "Quy tắc nghiệp vụ cốt lõi:\n"
        "1. Luôn tra cứu thực tế vận đơn qua `track_shipment` trước khi trả lời về tình trạng đơn hàng.\n"
        "2. Nếu đơn trễ quá 48 giờ so với hạn cam kết, thông cảm và hướng dẫn chuyển nhân viên kiểm tra đề xuất voucher 50.000 VNĐ; chỉ thông báo mã khi dữ liệu đã ghi nhận voucher do sàn phát hành.\n"
        "3. Nếu phát hiện giao hàng thất bại hoặc khách phản ánh shipper chưa gọi, hỗ trợ ghi nhận và chuyển nhân viên xử lý.\n"
        "4. Nếu khách hỏi đổi size hoặc bảo hành lỗi sản xuất, kiểm tra điều kiện đơn và hướng dẫn tạo yêu cầu đổi trả.\n"
        "5. Giữ thái độ đồng cảm, trung thực, chuyên nghiệp, xoa dịu khách hàng hiệu quả."
    )


# ---------------------------------------------------------------------------
# CLI Entry Point & Transports Runner
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RetailOps Enterprise MCP Server (2026)")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport to use: 'stdio' for CLI/desktop IDEs, 'sse' for HTTP network service (default: stdio)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host address for SSE transport (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8002,
        help="HTTP port for SSE transport (default: 8002)"
    )
    args = parser.parse_args()

    logger.info("Starting RetailOps MCP Server [transport=%s, host=%s, port=%s]", args.transport, args.host, args.port)

    if args.transport == "stdio":
        try:
            app.run(transport="stdio")
        except NotImplementedError:
            if hasattr(app, "_run_stdio"):
                app._run_stdio()
            else:
                raise
        except KeyboardInterrupt:
            logger.info("MCP stdio server terminated by user.")
    elif args.transport == "sse":
        try:
            app.run(transport="sse", host=args.host, port=args.port)
        except NotImplementedError:
            if hasattr(app, "_run_sse"):
                app._run_sse(host=args.host, port=args.port)
            else:
                raise
        except KeyboardInterrupt:
            logger.info("MCP SSE server terminated by user.")


if __name__ == "__main__":
    main()
