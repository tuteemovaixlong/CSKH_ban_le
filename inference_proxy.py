"""Loopback-only proxy for an attended model experiment; not a public app server.

ngrok forwards to this port, never directly to Ollama. Python standard library.
Only synthetic RetailOps extraction requests are supported. No admin endpoints.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import threading
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from retailops_baseline import LocalOllama, ModelConfig, SCHEMA, SYSTEM, canonical

MAX_BODY = 32768


def validate_request(payload: object, model: str) -> tuple[str, dict]:
    keys = {"model", "messages", "format", "stream", "think", "keep_alive", "options"}
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError("Unsupported request fields")
    if payload["model"] != model or payload["stream"] is not False or payload["think"] is not False:
        raise ValueError("Unsupported model or generation mode")
    if payload["format"] != SCHEMA or payload["keep_alive"] != "10m":
        raise ValueError("Schema and model retention must match this experiment")
    messages = payload["messages"]
    if (not isinstance(messages, list) or len(messages) != 2
            or messages[0] != {"role": "system", "content": SYSTEM}
            or not isinstance(messages[1], dict) or set(messages[1]) != {"role", "content"}
            or messages[1]["role"] != "user"):
        raise ValueError("Only the fixed extraction prompt is supported")
    text = messages[1]["content"]
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError("Input must contain 1–2000 characters")
    options = payload["options"]
    if not isinstance(options, dict) or set(options) != {"num_ctx", "num_predict", "temperature", "seed"}:
        raise ValueError("Unsupported generation options")
    for key, lo, hi in (("num_ctx", 1024, 4096), ("num_predict", 32, 256), ("seed", 0, 2**31 - 1)):
        if type(options[key]) is not int or not lo <= options[key] <= hi:
            raise ValueError("Generation budget out of range")
    temp = options["temperature"]
    if type(temp) not in (float, int) or not math.isfinite(temp) or not 0 <= temp <= 1:
        raise ValueError("Temperature must be between 0 and 1")
    return text, options


def create_server(config: ModelConfig, token: str, port: int = 8001) -> ThreadingHTTPServer:
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise ValueError("Provide a URL-safe 32–128 character token; secrets.token_urlsafe(32) works")
    gateway = LocalOllama(config)
    busy = threading.Lock()
    session_id = str(uuid.uuid4())
    proxy_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass  # No credentials, prompts, URLs or HTTP body logging.

        def reply(self, status: int, data: dict):
            raw = canonical(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authenticated(self) -> bool:
            supplied = self.headers.get("Authorization", "").encode("utf-8")
            if not hmac.compare_digest(supplied, ("Bearer " + token).encode("ascii")):
                self.reply(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if not self.authenticated():
                return
            if self.path not in ("/api/version", "/api/tags", "/healthz"):
                self.reply(404, {"error": "route_not_allowed"})
                return
            try:
                if self.path == "/api/tags":
                    data = gateway.request(self.path)
                    data = {"models": [m for m in data.get("models", [])
                                       if config.model in (m.get("name"), m.get("model"))]}
                elif self.path == "/api/version":
                    data = {**gateway.request(self.path), "inference_session_id": session_id,
                            "proxy_sha256": proxy_hash}
                else:
                    gateway.inspect()
                    data = {"status": "runtime_reachable_model_installed"}
                self.reply(200, data)
            except (RuntimeError, ValueError, OSError):
                self.reply(503, {"error": "inference_unavailable"})

        def do_POST(self):
            if not self.authenticated():
                return
            if self.path != "/api/chat":
                self.reply(404, {"error": "route_not_allowed"})
                return
            if self.headers.get("Transfer-Encoding"):
                self.reply(400, {"error": "transfer_encoding_not_supported"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    self.reply(413, {"error": "body_size_out_of_range"})
                    return
                if self.headers.get_content_type() != "application/json":
                    self.reply(415, {"error": "json_required"})
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("Incomplete body")
                text, options = validate_request(json.loads(raw), config.model)
            except (ValueError, UnicodeError, OSError):
                self.reply(400, {"error": "invalid_extraction_request"})
                return
            if not busy.acquire(blocking=False):
                self.reply(429, {"error": "inference_busy"})
                return
            try:
                worker = LocalOllama(replace(config, **options))
                self.reply(200, worker.generate(text))
            except (RuntimeError, ValueError, OSError):
                self.reply(503, {"error": "inference_unavailable"})
            finally:
                busy.release()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main():
    config = ModelConfig(model=os.getenv("RETAILOPS_MODEL", "qwen3.5:4b"))
    server = create_server(config, os.environ.get("RETAILOPS_INFERENCE_TOKEN", ""))
    print("RetailOps experiment proxy listening on 127.0.0.1:8001", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
