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


def _get_active_orders() -> Dict[str, Dict[str, Any]]:
    """Build in-memory or database orders lookup."""
    orders_map: Dict[str, Dict[str, Any]] = {
        "O-101": {
            "order_id": "O-101",
            "customer_id": "C-001",
            "product_id": "P-101",
            "product_name": "Áo thun Essential",
            "variant": "Trắng · Size M · Số lượng 1",
            "amount": 299000,
            "status": "pending",
            "order_date": "18/09/2026",
            "payment_method": "COD",
            "shipping_carrier": "Giao Hàng Tiết Kiệm (GHTK)"
        },
        "O-102": {
            "order_id": "O-102",
            "customer_id": "C-001",
            "product_id": "P-102",
            "product_name": "Áo khoác Everyday",
            "variant": "Đen · Size L · Số lượng 1",
            "amount": 799000,
            "status": "delivered",
            "order_date": "16/09/2026",
            "payment_method": "Ví MoMo",
            "shipping_carrier": "Giao Hàng Nhanh (GHN)"
        },
        "O-202": {
            "order_id": "O-202",
            "customer_id": "C-002",
            "product_id": "P-202",
            "product_name": "Áo polo",
            "variant": "Xanh · Size M · Số lượng 1",
            "amount": 399000,
            "status": "pending",
            "order_date": "18/09/2026",
            "payment_method": "VNPAY",
            "shipping_carrier": "SPX Express"
        },
        "O-301": {
            "order_id": "O-301",
            "customer_id": "C-003",
            "product_id": "P-103",
            "product_name": "Áo Sơ Mi Oxford Dài Tay",
            "variant": "Trắng · Size M · Số lượng 1",
            "amount": 350000,
            "status": "pending",
            "order_date": "18/09/2026",
            "payment_method": "COD",
            "shipping_carrier": "SPX Express"
        },
        "O-302": {
            "order_id": "O-302",
            "customer_id": "C-003",
            "product_id": "P-104",
            "product_name": "Áo Khoác Gió Bomber 2 Lớp",
            "variant": "Đen · Size L · Số lượng 1",
            "amount": 550000,
            "status": "delivered",
            "order_date": "13/09/2026",
            "payment_method": "Thẻ tín dụng",
            "shipping_carrier": "Giao Hàng Tiết Kiệm (GHTK)"
        },
        "O-303": {
            "order_id": "O-303",
            "customer_id": "C-004",
            "product_id": "P-203",
            "product_name": "Áo Polo Nam Phối Bo Cổ Co Giãn",
            "variant": "Xanh Navy · Size M · Số lượng 1",
            "amount": 399000,
            "status": "delivered",
            "order_date": "16/09/2026",
            "payment_method": "COD",
            "shipping_carrier": "Giao Hàng Nhanh (GHN)"
        },
        "O-304": {
            "order_id": "O-304",
            "customer_id": "C-004",
            "product_id": "P-301",
            "product_name": "Bộ Nồi Inox 3 Đáy Cao Cấp",
            "variant": "Bạc · Bộ 3 món · Số lượng 1",
            "amount": 1250000,
            "status": "pending",
            "order_date": "15/09/2026",
            "payment_method": "ZaloPay",
            "shipping_carrier": "Giao Hàng Nhanh (GHN)"
        }
    }
    # Merge deepseek seed data if exists
    seed_data = _load_json_file("data/deepseek_seed_data.json", {})
    for item in seed_data.get("orders", []):
        oid = item.get("id")
        if oid and oid not in orders_map:
            orders_map[oid] = {
                "order_id": oid,
                "customer_id": item.get("customer_id", "C-001"),
                "product_id": item.get("product_id", "P-101"),
                "product_name": item.get("product_name", item.get("title", "Sản phẩm RetailOps")),
                "variant": item.get("variant", "Tiêu chuẩn"),
                "amount": item.get("amount", 299000),
                "status": item.get("status", "pending"),
                "order_date": item.get("order_date", "18/09/2026"),
                "payment_method": item.get("payment_method", "COD"),
                "shipping_carrier": item.get("shipping_carrier", "GHTK")
            }
    return orders_map


def _get_shipment_data() -> Dict[str, Dict[str, Any]]:
    shipments: Dict[str, Dict[str, Any]] = {
        "O-101": {
            "carrier": "Giao Hàng Tiết Kiệm (GHTK)",
            "tracking_code": "GHTK.VN.0918231",
            "status": "in_transit",
            "status_text": "Đang trung chuyển",
            "current_location": "Bưu cục Tân Bình, TP.HCM",
            "shipper": "Nguyễn Văn Nam (0903.112.334)",
            "estimated_delivery": "Ngày mai (trước 17:00)",
            "steps": [
                {"time": "08:30 hôm nay", "event": "Đang trên xe trung chuyển liên tỉnh"},
                {"time": "20:15 hôm qua", "event": "Đã nhập kho phân loại Tân Bình"},
                {"time": "14:00 hôm qua", "event": "Shop RetailOps đã bàn giao cho shipper GHTK"}
            ]
        },
        "O-102": {
            "carrier": "Giao Hàng Nhanh (GHN)",
            "tracking_code": "GHN.VN.8839210",
            "status": "delivered",
            "status_text": "Đã giao thành công",
            "current_location": "Người nhận đã ký nhận",
            "shipper": "Trần Quốc Tuấn (0982.551.442)",
            "estimated_delivery": "Đã giao lúc 10:15 hôm qua",
            "steps": [
                {"time": "10:15 hôm qua", "event": "Giao hàng thành công - Khách hàng đã ký nhận"},
                {"time": "08:00 hôm qua", "event": "Shipper đang trên đường giao tới bạn"}
            ]
        },
        "O-301": {
            "carrier": "SPX Express",
            "tracking_code": "SPX.VN.9928110",
            "status": "delivery_failed_virtual",
            "status_text": "Bưu tá báo không liên lạc được (Ảo)",
            "current_location": "Bưu cục Cầu Giấy 2, Hà Nội",
            "shipper": "Nguyễn Văn Tuấn (0934.112.233)",
            "system_note": "Tổng đài kiểm tra bưu cục ghi nhận không có lịch sử cuộc gọi ra lúc cập nhật.",
            "can_reassign_today": True,
            "estimated_delivery": "Hôm nay trước 18:00 (khiếu nại giao lại ngay trong ca)",
            "steps": [
                {"time": "14:30 hôm nay", "event": "Bưu tá báo không liên lạc được (Hệ thống ghi nhận nghi vấn báo ảo)"},
                {"time": "08:15 hôm nay", "event": "Bưu tá Nguyễn Văn Tuấn (0934.112.233) xuất kho giao hàng"},
                {"time": "05:00 hôm nay", "event": "Nhập bưu cục Cầu Giấy 2"}
            ]
        },
        "O-302": {
            "carrier": "Giao Hàng Tiết Kiệm (GHTK)",
            "tracking_code": "GHTK.VN.4419201",
            "status": "delivered",
            "status_text": "Đã giao thành công",
            "current_location": "Khách hàng đã ký nhận",
            "shipper": "Lê Quốc Bảo (0912.883.991)",
            "delivery_date": "5 ngày trước",
            "product_id": "P-104",
            "warranty_eligible": True,
            "warranty_days_left": 85,
            "steps": [
                {"time": "11:00 5 ngày trước", "event": "Giao hàng thành công - Người nhận ký nhận"},
                {"time": "08:30 5 ngày trước", "event": "Shipper đang giao hàng"}
            ]
        },
        "O-303": {
            "carrier": "Giao Hàng Nhanh (GHN)",
            "tracking_code": "GHN.VN.7721890",
            "status": "delivered",
            "status_text": "Đã giao thành công",
            "current_location": "Khách hàng đã ký nhận",
            "shipper": "Hoàng Minh Đức (0977.441.229)",
            "delivery_date": "2 ngày trước",
            "product_id": "P-203",
            "exchange_eligible": True,
            "steps": [
                {"time": "15:20 2 ngày trước", "event": "Giao hàng thành công - Người nhận ký nhận"},
                {"time": "09:00 2 ngày trước", "event": "Shipper đang giao hàng"}
            ]
        },
        "O-304": {
            "carrier": "Giao Hàng Nhanh (GHN)",
            "tracking_code": "GHN.VN.8821990",
            "status": "sorting_delayed",
            "status_text": "Nghẽn trạm phân loại Mega Sale > 48h",
            "current_location": "Kho Tổng BN Mega SOC (Bắc Ninh)",
            "delayed_hours": 54,
            "reason": "Quá tải phân loại hàng hóa đợt Mega Sale sàn TMĐT",
            "shipper": "Chưa điều phối (Đang chờ phân tuyến trung chuyển)",
            "estimated_delivery": "Dự kiến 20/09/2026",
            "eligible_voucher": "VOUCHER_50K_COMPENSATION",
            "voucher_code": "SALE50K-BN-SOC",
            "steps": [
                {"time": "54 giờ trước", "event": "Đã nhập Kho Tổng BN Mega SOC - Đang chờ phân loại"},
                {"time": "60 giờ trước", "event": "Rời kho lấy hàng Shop RetailOps"}
            ]
        }
    }
    extra = _load_json_file("data/mock_shipments.json", {})
    shipments.update(extra)
    return shipments


# ---------------------------------------------------------------------------
# Tool 1: track_shipment
# ---------------------------------------------------------------------------
@app.tool()
def track_shipment(order_id: str) -> dict:
    """Tra cứu trạng thái vận chuyển, vị trí bưu kiện thực tế, bưu tá giao hàng và phát hiện nghẽn kho phân loại Mega SOC >48h hoặc shipper báo giao ảo."""
    oid = order_id.strip().upper()
    shipments = _get_shipment_data()
    orders = _get_active_orders()
    order = orders.get(oid, {"order_id": oid, "status": "pending"})

    shipment = shipments.get(oid)
    if not shipment:
        shipment = {
            "carrier": "Giao Hàng Tiết Kiệm (GHTK)",
            "tracking_code": f"GHTK.VN.{oid.replace('-', '')}99",
            "status": "processing",
            "status_text": "Đang chuẩn bị kiện hàng tại kho",
            "current_location": "Kho tổng RetailOps (Hà Nội)",
            "shipper": "Chưa phân công",
            "estimated_delivery": "2-3 ngày làm việc",
            "steps": [
                {"time": "Vừa xong", "event": "Đơn hàng đang được kiểm đếm và đóng gói tại kho"}
            ]
        }

    return {
        "order_id": oid,
        "order_status": order.get("status", "unknown"),
        "shipment": shipment,
        "is_delayed_mega_soc": shipment.get("delayed_hours", 0) >= 48 or shipment.get("status") in ("sorting_delayed", "congested_at_soc"),
        "is_virtual_delivery_suspected": shipment.get("status") in ("delivery_failed_virtual",),
        "compensation_voucher": shipment.get("voucher_code") or ("SALE50K-BN-SOC" if shipment.get("delayed_hours", 0) >= 48 else None)
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
    """Truy vấn cơ sở tri thức chính sách đổi trả, bảo hành 90 ngày, bồi hoàn nghẽn kho Mega SOC và khiếu nại shipper."""
    q_clean = query.strip().lower()

    docs = [
        {
            "id": "kb_warranty_90d",
            "title": "Chính sách bảo hành và đổi mới 1-1 tận nhà (90 ngày)",
            "category": "warranty",
            "content": _load_text_file("data/knowledge/policy_warranty_exchange_1to1.md", "Bảo hành 90 ngày lỗi bung chỉ, kẹt khóa YKK. Đổi mới 1-1 tận nhà miễn phí ship."),
            "keywords": ["bảo hành", "hư", "hỏng", "rách", "bung chỉ", "kẹt khóa", "khóa kéo", "lỗi", "90 ngày", "đổi mới 1-1"]
        },
        {
            "id": "kb_mega_soc_delay",
            "title": "Chính sách hỗ trợ và đền bù nghẽn kho Mega SOC >48h",
            "category": "shipping_delay",
            "content": _load_text_file("data/knowledge/policy_mega_sale_delay_voucher.md", "Nghẽn trạm Mega SOC quá 48h được tặng voucher đền bù 50.000đ (SALE50K-BN-SOC)."),
            "keywords": ["chậm", "trễ", "nghẽn", "soc", "mega soc", "48h", "voucher đền bù", "bồi thường", "bắc ninh"]
        },
        {
            "id": "kb_size_exchange",
            "title": "Chính sách đổi size 2 chiều tận nhà trong 7 ngày",
            "category": "exchange",
            "content": _load_text_file("data/knowledge/policy_size_exchange_twoway.md", "Đổi size tận nhà trong 7 ngày. Shipper giao size mới và thu hồi size cũ đồng thời."),
            "keywords": ["đổi size", "chật", "rộng", "không vừa", "đổi hàng", "7 ngày", "đổi mẫu"]
        },
        {
            "id": "kb_shipper_complaint",
            "title": "Quy trình xử lý shipper báo giao hàng ảo / không liên lạc được",
            "category": "shipper_complaint",
            "content": _load_text_file("data/knowledge/policy_shipper_complaint.md", "Shipper báo không nghe máy nhưng không có cuộc gọi: yêu cầu bưu cục điều phối giao lại ngay trong ngày."),
            "keywords": ["báo ảo", "shipper không gọi", "chưa nhận được hàng mà báo giao", "không liên lạc được", "khiếu nại shipper"]
        },
        {
            "id": "kb_cancellation",
            "title": "Chính sách hủy đơn hàng",
            "category": "cancellation",
            "content": _load_text_file("data/knowledge/cancellation.md", "Đơn hàng trạng thái pending được phép hủy trực tiếp trên giao diện."),
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
    """Tra cứu chi tiết một đơn hàng theo mã đơn (sản phẩm, phân loại, giá tiền, phương thức thanh toán, trạng thái)."""
    oid = order_id.strip().upper()
    orders = _get_active_orders()
    order = orders.get(oid)

    if not order:
        return {
            "error": "order_not_found",
            "message": f"Không tìm thấy đơn hàng {oid} trong hệ thống."
        }

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
    """Liệt kê danh sách các đơn hàng gần đây của khách hàng trong hệ thống RetailOps."""
    orders = _get_active_orders()
    orders_list = list(orders.values())

    cid = customer_id.strip().upper()
    if cid and cid != "GUEST":
        orders_list = [o for o in orders_list if o.get("customer_id") == cid]

    orders_list.sort(key=lambda x: x["order_id"], reverse=True)
    results = orders_list[:limit]

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
    oid = order_id.strip().upper()
    orders = _get_active_orders()
    order = orders.get(oid)

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
    """Tính toán giá trị giảm giá và kiểm tra điều kiện áp dụng mã voucher đền bù nghẽn kho hoặc mã khuyến mãi."""
    code = voucher_code.strip().upper()
    amount = max(0, int(order_amount))

    vouchers = {
        "SALE50K-BN-SOC": {
            "discount_type": "fixed",
            "discount_value": 50000,
            "min_order": 0,
            "description": "Voucher đền bù đơn hàng chậm trễ tại Kho BN Mega SOC >48h"
        },
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
            "- Áp dụng cho mọi lỗi đường may chỉ, kẹt khóa YKK trong vòng 90 ngày kể từ ngày nhận hàng.\n"
            "- Miễn phí đổi mới 1-1 tận nhà, bưu tá giao hàng mới và thu hồi hàng cũ đồng thời.\n"
        )
    return content


@app.resource("retailops://policies/mega-soc-delay")
def get_mega_soc_delay_resource() -> str:
    """Resource: Quy định xử lý và bồi thường voucher 50.000đ khi đơn hàng nghẽn kho phân loại Mega SOC >48h."""
    content = _load_text_file("data/knowledge/policy_mega_sale_delay_voucher.md")
    if not content:
        content = (
            "# Quy định bồi hoàn nghẽn kho Mega SOC\n\n"
            "- Kiện hàng lưu chuyển qua kho tổng SOC (Bắc Ninh, Củ Chi) vượt 48h tự động kích hoạt voucher SALE50K-BN-SOC.\n"
            "- Khách hàng nhận voucher 50.000đ cho đơn hàng tiếp theo.\n"
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
        "2. Nếu đơn bị nghẽn kho Mega SOC > 48h, thông cảm và chủ động gửi voucher bồi thường 50k (SALE50K-BN-SOC).\n"
        "3. Nếu phát hiện bưu tá báo giao ảo (không có cuộc gọi), hỗ trợ yêu cầu giao lại trong ngày qua `track_shipment`.\n"
        "4. Nếu khách hỏi đổi size hoặc bảo hành lỗi bung chỉ, cam kết đổi mới 1-1 tận nhà miễn phí ship 2 chiều qua `create_return_proposal`.\n"
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
