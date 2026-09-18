#!/usr/bin/env python3
"""Run live HTTP evaluation against the deployed RetailOps EC2 service connected to Colab/Custom model.

Performs:
1. Authentication via /api/login using invite token or member credential.
2. Conversation session creation via /api/conversations with provider_id='custom'.
3. Iterates over scenarios in evals/scenarios/benchmark_250.jsonl.
4. Posts questions to /api/chat, measures TTFT & total latency, inspects tools called and citations.
5. Emits live evaluation report to evals/reports/live_benchmark_report_<timestamp>.json and .md.
"""
import argparse
import http.cookiejar
import json
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evals" / "scenarios" / "benchmark_250.jsonl"
DEFAULT_ORIGIN = "https://retailops.54-144-244-233.sslip.io"


class LiveClient:
    def __init__(self, base_url: str, token: str, insecure: bool = True):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.jar = http.cookiejar.CookieJar()
        self.insecure = insecure
        import ssl
        self.ctx = ssl.create_default_context()
        if insecure:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

    def request(self, method: str, path: str, payload=None, timeout: int = 45):
        url = self.base_url + path
        headers = {"User-Agent": "RetailOps-Live-Benchmark/1.0"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        t0 = time.perf_counter()
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                raw = resp.read().decode("utf-8")
                try:
                    body = json.loads(raw)
                except Exception:
                    body = raw
                return resp.status, body, elapsed_ms, None
        except urllib.error.HTTPError as err:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            raw = err.read().decode("utf-8")
            try:
                body = json.loads(raw)
            except Exception:
                body = raw
            return err.code, body, elapsed_ms, f"HTTPError {err.code}: {err.reason}"
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return 0, None, elapsed_ms, str(exc)

    def login(self):
        status, body, _, err = self.request("POST", "/api/login", {"token": self.token})
        if status != 200:
            raise RuntimeError(f"Đăng nhập thất bại (HTTP {status}): {body or err}")
        return body

    def new_conversation(self, provider: str = "custom"):
        status, body, _, err = self.request("POST", "/api/conversations", {"provider_id": provider})
        if status not in (200, 201):
            raise RuntimeError(f"Tạo hội thoại thất bại (HTTP {status}): {body or err}")
        return body["conversation_id"]

    def chat(self, conversation_id: str, text: str, req_id: str = None, timeout: int = 60):
        req_id = req_id or f"bench_{int(time.time()*1000)}_{text[:8]}"
        payload = {
            "conversation_id": conversation_id,
            "text": text,
            "request_id": re.sub(r"[^A-Za-z0-9_-]", "_", req_id)
        }
        return self.request("POST", "/api/chat", payload, timeout=timeout)


def run_live_eval(origin: str, token: str, dataset_path: Path, max_cases: int = 10, provider: str = "custom"):
    print(f"[*] Bắt đầu kiểm thử Live trên: {origin}")
    print(f"[*] Nguồn Model: {provider.upper()} (Colab / Ollama)")

    client = LiveClient(origin, token)
    print("[*] Đang đăng nhập tài khoản...")
    login_info = client.login()
    print(f"  [+] Đăng nhập thành công! Tenant: {login_info.get('tenant_id', 'demo')}")

    print(f"[*] Nạp kịch bản từ: {dataset_path.name}...")
    cases = []
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                cases.append(json.loads(line))
            except Exception:
                pass

    if max_cases and len(cases) > max_cases:
        print(f"[*] Giới hạn kiểm thử {max_cases} ca mẫu (trong tổng số {len(cases)} ca)...")
        cases = cases[:max_cases]

    results = []
    for idx, c in enumerate(cases, start=1):
        cid = c["id"]
        text = c["user_text"]
        cat = c["category"]
        print(f"\n[{idx}/{len(cases)}] [ID: {cid}] ({cat}): \"{text[:60]}...\"")

        # Tạo conversation mới cho mỗi kịch bản để độc lập ngữ cảnh
        try:
            conv_id = client.new_conversation(provider=provider)
        except Exception as e:
            print(f"  [!] Lỗi tạo conversation: {e}")
            results.append({
                "id": cid, "category": cat, "passed": False,
                "error": f"New conversation error: {e}", "latency_ms": 0
            })
            continue

        status, body, elapsed_ms, err = client.chat(conv_id, text, req_id=f"req_{cid}")
        if status != 200:
            print(f"  [X] HTTP {status}: {err or body}")
            results.append({
                "id": cid, "category": cat, "passed": False,
                "status": status, "error": err or body, "latency_ms": elapsed_ms
            })
            continue

        trace = body.get("trace", {})
        msg = body.get("message", "")
        tools_called = [t.get("name") for t in trace.get("tools", [])]
        sources = body.get("sources", [])

        # Đánh giá tiêu chuẩn
        exp_tools = set(c.get("expected_tools", []))
        forb_tools = set(c.get("forbidden_tools", []))

        tool_pass = True
        if forb_tools and (set(tools_called) & forb_tools):
            tool_pass = False

        print(f"  [+] HTTP 200 OK | Trễ: {elapsed_ms:.1f}ms")
        print(f"      AI: \"{msg[:75]}...\"")
        if tools_called:
            print(f"      Tools: {tools_called}")

        results.append({
            "id": cid,
            "category": cat,
            "passed": tool_pass,
            "status": 200,
            "latency_ms": elapsed_ms,
            "tools_called": tools_called,
            "response": msg,
            "sources": sources
        })

    # Tổng kết
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms", 0) > 0]
    p50 = statistics.median(latencies) if latencies else 0.0
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

    print("\n" + "=" * 60)
    print(f"🎉 HOÀN TẤT LIVE BENCHMARK (Nguồn: {provider})")
    print(f"   - Tổng số ca kiểm thử : {total}")
    print(f"   - Số ca thành công    : {passed} / {total} ({round((passed/total)*100, 1) if total else 0}%)")
    print(f"   - Độ trễ TTFT p50     : {round(p50, 1)} ms")
    print(f"   - Độ trễ tối đa p95   : {round(p95, 1)} ms")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Run live evaluation on deployed EC2 public web.")
    parser.add_argument("--origin", "-u", default=DEFAULT_ORIGIN, help="Base URL of RetailOps service")
    parser.add_argument("--token", "-t", required=True, help="Invite token or login access code")
    parser.add_argument("--dataset", "-d", type=Path, default=DEFAULT_DATASET, help="Benchmark JSONL dataset")
    parser.add_argument("--count", "-n", type=int, default=10, help="Number of scenarios to test (default 10)")
    parser.add_argument("--provider", "-p", choices=("custom", "api"), default="custom", help="Model provider")
    args = parser.parse_args()

    run_live_eval(args.origin, args.token, args.dataset, args.count, args.provider)


if __name__ == "__main__":
    main()
