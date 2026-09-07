#!/usr/bin/env python3
"""Live E2E verification for the deployed RetailOps public service.

Runs on the EC2 host against the public HTTPS surface through Caddy while using the
server-side operator CLI only for synthetic identity/tenant setup and cleanup.
Credentials stay in private temporary files/variables and are never printed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path("/opt/retailops")
REPORT_DIR = ROOT / "e2e-reports"
COMPOSE = None


class E2EFailure(RuntimeError):
    pass


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run(args, *, cwd=ROOT, check=True, timeout=180, input_text=None):
    proc = subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        cmd = " ".join(str(part) for part in args[:6])
        raise E2EFailure(f"command failed rc={proc.returncode}: {cmd}")
    return proc


def env_value(path: Path, key: str) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def compose_base() -> list[str]:
    base = [
        "docker", "compose", "--project-name", "retailops-web",
        "--env-file", "deployed.env", "--env-file", "public.env",
        "-f", "compose.public.yaml",
    ]
    if (ROOT / "postgres-secrets").is_dir():
        base += ["-f", "compose.postgres.yaml"]
    return base


def dc(args, **kwargs):
    assert COMPOSE is not None
    return run(COMPOSE + args, **kwargs)


def cli(args):
    proc = dc(["exec", "-T", "web", "python", "-m", "retailops"] + args, timeout=180)
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise E2EFailure("operator CLI returned non-JSON output") from exc


def parse_json_file(path: Path):
    raw = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {"_raw_excerpt": raw[:300]}


class HttpClient:
    def __init__(self, host: str, temp_dir: Path):
        self.host = host
        self.origin = "https://" + host
        self.temp_dir = temp_dir
        self.sequence = 0

    def request(self, path: str, body=None, *, cookie: Path | None = None,
                headers: list[str] | None = None, timeout=60, expect_json=True):
        self.sequence += 1
        response = self.temp_dir / f"response-{self.sequence}.body"
        args = [
            "curl", "--noproxy", "*", "--silent", "--show-error",
            "--max-time", str(timeout), "--resolve", f"{self.host}:443:127.0.0.1",
            "--output", str(response), "--write-out", "%{http_code}",
        ]
        if cookie is not None:
            args += ["--cookie", str(cookie), "--cookie-jar", str(cookie)]
        payload_path = None
        if body is not None:
            payload_path = self.temp_dir / f"payload-{self.sequence}.json"
            payload_path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            os.chmod(payload_path, 0o600)
            args += [
                "-H", "Origin: " + self.origin,
                "-H", "Content-Type: application/json",
                "--data-binary", "@" + str(payload_path),
            ]
        for header in headers or []:
            args += ["-H", header]
        args.append(self.origin + path)
        proc = run(args, check=False, timeout=timeout + 10)
        if payload_path is not None:
            payload_path.unlink(missing_ok=True)
        code = proc.stdout.strip()[-3:]
        status = int(code) if code.isdigit() else 0
        if expect_json:
            data = parse_json_file(response)
        else:
            data = response.read_text(encoding="utf-8", errors="replace") if response.exists() else ""
        return status, data

    def wait_health(self, *, attempts=30, delay=2):
        last = (0, {})
        for _ in range(attempts):
            last = self.request("/healthz", timeout=15)
            if last[0] == 200 and isinstance(last[1], dict) and last[1].get("status") == "ok":
                return last
            time.sleep(delay)
        return last


def require(condition, message):
    if not condition:
        raise E2EFailure(message)


def tool_names(payload) -> list[str]:
    trace = payload.get("trace") or {}
    result = []
    for item in trace.get("tools") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result.append(item["name"])
    return result


def trace_summary(payload):
    trace = payload.get("trace") or {}
    return {
        "request_mode": trace.get("request_mode"),
        "provider": trace.get("provider"),
        "model": trace.get("model"),
        "model_calls": trace.get("model_calls"),
        "tools": tool_names(payload),
        "prompt_tokens": trace.get("prompt_tokens"),
        "generated_tokens": trace.get("generated_tokens"),
        "reported_cost_usd": trace.get("reported_cost_usd"),
        "latency_ms": trace.get("latency_ms"),
        "knowledge": trace.get("knowledge"),
    }


def configured_providers(providers_payload):
    providers = providers_payload.get("providers") if isinstance(providers_payload, dict) else None
    if not isinstance(providers, list):
        return []
    flags = {p.get("id"): bool(p.get("configured")) for p in providers if isinstance(p, dict)}
    return [provider for provider in ("custom", "api") if flags.get(provider)]


def issue_member(tenant: str, principal: str, customer: str, role: str, credential_path: str):
    created = cli([
        "identity", "create-member", "--tenant", tenant, "--principal", principal,
        "--name", principal, "--customer", customer, "--role", role,
    ])
    membership = created.get("membership_id")
    require(isinstance(membership, str) and membership, "membership was not created")
    cli(["identity", "issue-credential", "--membership", membership,
         "--credential-file", credential_path])
    credential = dc(["exec", "-T", "web", "cat", credential_path]).stdout.strip()
    require(bool(credential), "credential file was empty")
    return membership, credential


def revoke_member(membership: str | None, credential_path: str | None):
    if membership:
        try:
            cli(["identity", "revoke", "--membership", membership])
        except Exception:
            pass
    if credential_path:
        try:
            dc(["exec", "-T", "web", "rm", "-f", credential_path], check=False)
        except Exception:
            pass


def save_report(report: dict, mode: str, stamp: str, secret_values: list[str]):
    REPORT_DIR.mkdir(mode=0o700, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    for secret in secret_values:
        if secret and secret in serialized:
            raise E2EFailure("refusing to write report containing a credential")
    path = REPORT_DIR / f"LIVE_{mode.upper()}_{stamp}.json"
    path.write_text(serialized + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def common_runtime_checks(http: HttpClient, expected_image: str | None, report: dict):
    activated = env_value(ROOT / "deployed.env", "RETAILOPS_IMAGE")
    web_id = dc(["ps", "-q", "web"]).stdout.strip()
    require(bool(web_id), "web container is missing")
    web_image = run(["docker", "inspect", "--format", "{{.Config.Image}}", web_id]).stdout.strip()
    web_health = run([
        "docker", "inspect", "--format",
        "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", web_id,
    ]).stdout.strip()
    require(activated == web_image, "deployed.env and running web image differ")
    if expected_image:
        require(activated == expected_image, "live image does not match expected release image")

    status, health = http.wait_health()
    require(status == 200 and health.get("status") == "ok", "public health check failed")
    require(health.get("storage_backend") == "postgresql", "live storage is not PostgreSQL")
    require(health.get("agent_protocol") == "retailops-agent-v2", "unexpected agent protocol")

    root_status, root_html = http.request("/", expect_json=False, timeout=20)
    require(root_status == 200 and 'data-auth="cookie"' in root_html, "public login surface is unavailable")

    report["runtime"] = {
        "activated_image": activated,
        "web_image": web_image,
        "web_state": web_health,
        "health": health,
        "host": http.host,
    }
    report["checks"].update({
        "exact_live_image": True,
        "health": True,
        "public_login_surface": True,
    })


def login_and_basic_checks(http: HttpClient, tenant: str, credential: str, cookie: Path, report: dict):
    status, login = http.request("/api/login", {"token": credential}, cookie=cookie)
    require(status == 200 and login.get("scope") == "synthetic-demo", "login failed")
    status, session = http.request("/api/session", cookie=cookie)
    require(status == 200, "session lookup failed")
    require(session.get("tenant_id") == tenant, "session tenant binding is wrong")
    require(session.get("customer_id") == "C-001", "session customer binding is wrong")
    require(session.get("role") == "customer", "session role is wrong")
    require(session.get("storage_backend") == "postgresql", "session is not backed by PostgreSQL")

    status, orders = http.request("/api/orders", cookie=cookie)
    order_list = orders.get("orders") if isinstance(orders, dict) else None
    require(status == 200 and isinstance(order_list, list) and len(order_list) >= 2, "order list failed")
    pending = next((o for o in order_list if o.get("id") == "O-101"), None)
    require(pending is not None and pending.get("status") == "pending", "seeded pending order is missing")

    status, providers = http.request("/api/providers", cookie=cookie)
    require(status == 200 and isinstance(providers.get("providers"), list), "provider metadata failed")
    report["checks"].update({"login": True, "session_binding": True, "orders": True, "providers": True})
    report["session"] = {"tenant_id": tenant, "customer_id": session.get("customer_id"), "role": session.get("role")}
    return pending, providers


def run_smoke(http: HttpClient, report: dict, secret_values: list[str]):
    tenant = "e2e-live-smoke"
    principal = "e2e-smoke-" + uuid.uuid4().hex[:10]
    credential_path = "/tmp/" + principal + ".credential"
    membership = None
    try:
        cli(["identity", "init-tenant", "--tenant", tenant, "--name", "RetailOps live smoke", "--seed-demo"])
        membership, credential = issue_member(tenant, principal, "C-001", "customer", credential_path)
        secret_values.append(credential)
        cookie = http.temp_dir / "customer.cookies"
        login_and_basic_checks(http, tenant, credential, cookie, report)

        status, order = http.request("/api/orders/O-101", cookie=cookie)
        require(status == 200 and (order.get("order") or {}).get("status") == "pending", "owned order lookup failed")
        status, logout = http.request("/api/logout", {}, cookie=cookie)
        require(status == 200 and logout.get("logged_out") is True, "logout failed")
        status, _ = http.request("/api/session", cookie=cookie)
        require(status == 401, "logged-out cookie remained authorized")
        report["checks"].update({"owned_order": True, "logout_revokes_session": True})
    finally:
        revoke_member(membership, credential_path)


def chat(http: HttpClient, cookie: Path, conversation_id: str, text: str, request_id: str, timeout=130):
    return http.request("/api/chat", {
        "text": text,
        "conversation_id": conversation_id,
        "request_id": request_id,
    }, cookie=cookie, timeout=timeout)


def establish_live_conversation(http, cookie, providers_payload, report):
    attempts = []
    for provider in configured_providers(providers_payload):
        status, conversation = http.request("/api/conversations", {"provider_id": provider}, cookie=cookie)
        if status != 201:
            attempts.append({"provider": provider, "conversation_status": status})
            continue
        conversation_id = conversation.get("conversation_id")
        request_id = "e2e_general_" + uuid.uuid4().hex
        status, general = chat(http, cookie, conversation_id,
            "Giải thích ngắn gọn quicksort là gì và ý tưởng chia để trị hoạt động ra sao.", request_id)
        attempts.append({"provider": provider, "chat_status": status})
        if status == 200:
            report["provider_attempts"] = attempts
            return provider, conversation_id, general
    report["provider_attempts"] = attempts
    raise E2EFailure("no configured live model provider completed a chat")


def run_full(http: HttpClient, report: dict, secret_values: list[str]):
    tenant = "e2e-full-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    customer_principal = "e2e-customer-" + uuid.uuid4().hex[:8]
    viewer_principal = "e2e-viewer-" + uuid.uuid4().hex[:8]
    customer_cred_path = "/tmp/" + customer_principal + ".credential"
    viewer_cred_path = "/tmp/" + viewer_principal + ".credential"
    customer_membership = None
    viewer_membership = None
    report["tenant"] = tenant
    try:
        cli(["identity", "init-tenant", "--tenant", tenant, "--name", "RetailOps full live E2E", "--seed-demo"])
        ingest = cli(["knowledge", "ingest", "--tenant", tenant, "--path", "/app/data/knowledge"])
        require(ingest.get("result") == "KNOWLEDGE_INGESTED", "knowledge ingest failed")
        report["checks"]["knowledge_ingest"] = True
        report["knowledge"] = {
            "documents": ingest.get("documents"),
            "chunks": ingest.get("chunks"),
            "embedding_model": ingest.get("embedding_model"),
        }

        customer_membership, customer_credential = issue_member(
            tenant, customer_principal, "C-001", "customer", customer_cred_path,
        )
        secret_values.append(customer_credential)
        customer_cookie = http.temp_dir / "customer.cookies"
        pending, providers = login_and_basic_checks(http, tenant, customer_credential, customer_cookie, report)

        provider, conversation_id, general = establish_live_conversation(http, customer_cookie, providers, report)
        report["selected_provider"] = provider
        require(general.get("model_used") is True, "general live-model chat did not use a model")
        require((general.get("trace") or {}).get("request_mode") == "general", "general request did not use general mode")
        require(tool_names(general) == [], "general mode called RetailOps tools")
        report["checks"]["general_model"] = True
        report["traces"] = {"general": trace_summary(general)}

        order_id = "e2e_order_" + uuid.uuid4().hex
        order_text = "Đơn O-101 hiện trạng thái gì? Hãy đọc dữ liệu hệ thống và không đoán trường còn thiếu."
        status, order_chat = chat(http, customer_cookie, conversation_id, order_text, order_id)
        require(status == 200 and "get_order" in tool_names(order_chat), "order chat did not use get_order")
        require((order_chat.get("context") or {}).get("order_id") == "O-101", "order chat established wrong context")
        report["checks"]["order_model_tool"] = True
        report["traces"]["order"] = trace_summary(order_chat)

        replay_status, replay = chat(http, customer_cookie, conversation_id, order_text, order_id, timeout=30)
        require(replay_status == 200 and replay.get("replayed") is True, "chat idempotent replay failed")
        report["checks"]["chat_replay_before_restart"] = True

        product_id = "e2e_product_" + uuid.uuid4().hex
        status, product_chat = chat(http, customer_cookie, conversation_id,
            "Cho tôi thông tin sản phẩm P-001 từ catalog, chỉ nêu thuộc tính hệ thống biết.", product_id)
        require(status == 200 and set(tool_names(product_chat)) & {"get_product", "search_products", "get_context"},
                "product chat did not use a product tool")
        report["checks"]["product_model_tool"] = True
        report["traces"]["product"] = trace_summary(product_chat)

        rag_id = "e2e_rag_" + uuid.uuid4().hex
        status, rag_chat = chat(http, customer_cookie, conversation_id,
            "Theo chính sách demo của cửa hàng, điều kiện đổi trả hàng là gì? Hãy dùng knowledge base và trích dẫn nguồn.", rag_id)
        require(status == 200 and "search_knowledge" in tool_names(rag_chat), "policy chat did not search knowledge")
        require(isinstance(rag_chat.get("sources"), list) and len(rag_chat["sources"]) > 0, "policy chat returned no cited source")
        report["checks"]["rag_model_tool"] = True
        report["traces"]["rag"] = trace_summary(rag_chat)

        cancel_chat_id = "e2e_cancel_" + uuid.uuid4().hex
        status, cancel_chat = chat(http, customer_cookie, conversation_id,
            "Tôi muốn hủy đơn O-101. Hãy kiểm tra điều kiện nhưng chưa được tự hủy nếu tôi chưa xác nhận.", cancel_chat_id)
        require(status == 200 and "prepare_cancellation" in tool_names(cancel_chat), "cancel chat did not prepare cancellation")
        require(cancel_chat.get("action") == "choose_cancel_reason", "cancel chat skipped reason/confirmation UI")
        require((cancel_chat.get("order") or {}).get("status") == "pending", "cancel chat mutated the order")
        report["checks"]["model_prepares_but_does_not_mutate"] = True
        report["traces"]["cancel"] = trace_summary(cancel_chat)

        events_status, events_before = http.request("/api/events", cookie=customer_cookie)
        require(events_status == 200, "event read before proposal failed")
        before_cancelled = sum(1 for event in events_before.get("events", [])
                               if event.get("kind") == "order_cancelled" and event.get("order_id") == "O-101")

        proposal_status, proposal = http.request("/api/cancellation-proposals", {
            "order_id": "O-101",
            "order_version": pending["version"],
            "cancel_reason": "ordered_by_mistake",
        }, cookie=customer_cookie)
        proposal_id = proposal.get("proposal_id")
        require(proposal_status == 201 and isinstance(proposal_id, str), "cancellation proposal creation failed")
        require(proposal.get("workflow_status") == "awaiting_confirmation", "proposal did not pause for confirmation")
        list_status, listed = http.request("/api/cancellation-proposals", cookie=customer_cookie)
        listed_ids = [item.get("proposal_id") for item in listed.get("proposals", [])]
        require(list_status == 200 and proposal_id in listed_ids, "pending proposal was not reloadable")
        report["checks"]["proposal_created_and_reloadable"] = True

        dc(["restart", "web"], timeout=180)
        health_status, _ = http.wait_health(attempts=45, delay=2)
        require(health_status == 200, "web did not recover after restart")
        session_status, session_after = http.request("/api/session", cookie=customer_cookie)
        require(session_status == 200 and session_after.get("tenant_id") == tenant, "session did not survive web restart")
        list_status, listed_after = http.request("/api/cancellation-proposals", cookie=customer_cookie)
        listed_after_ids = [item.get("proposal_id") for item in listed_after.get("proposals", [])]
        require(list_status == 200 and proposal_id in listed_after_ids, "pending proposal did not survive restart")
        report["checks"].update({"restart_session_persistence": True, "restart_pending_persistence": True})

        replay_status, replay_after = chat(http, customer_cookie, conversation_id, order_text, order_id, timeout=30)
        require(replay_status == 200 and replay_after.get("replayed") is True, "chat replay did not survive restart")
        report["checks"]["chat_replay_after_restart"] = True

        idem = "e2e_confirm_" + uuid.uuid4().hex
        confirm_path = "/api/cancellation-proposals/" + proposal_id + "/confirm"
        first_status, first = http.request(confirm_path, {"confirmed": True}, cookie=customer_cookie,
                                          headers=["Idempotency-Key: " + idem])
        second_status, second = http.request(confirm_path, {"confirmed": True}, cookie=customer_cookie,
                                            headers=["Idempotency-Key: " + idem])
        require(first_status == 200 and first.get("replayed") is False, "first cancellation confirmation failed")
        require(second_status == 200 and second.get("replayed") is True, "duplicate confirmation was not replayed")
        order_status, order_after = http.request("/api/orders/O-101", cookie=customer_cookie)
        require(order_status == 200 and (order_after.get("order") or {}).get("status") == "cancelled",
                "backend order did not become cancelled")
        events_status, events_after = http.request("/api/events", cookie=customer_cookie)
        require(events_status == 200, "event read after confirmation failed")
        after_cancelled = sum(1 for event in events_after.get("events", [])
                              if event.get("kind") == "order_cancelled" and event.get("order_id") == "O-101")
        require(after_cancelled == before_cancelled + 1, "duplicate confirmation produced wrong audit count")
        report["checks"]["confirm_idempotency_and_backend_state"] = True

        viewer_membership, viewer_credential = issue_member(
            tenant, viewer_principal, "C-002", "viewer", viewer_cred_path,
        )
        secret_values.append(viewer_credential)
        viewer_cookie = http.temp_dir / "viewer.cookies"
        status, _ = http.request("/api/login", {"token": viewer_credential}, cookie=viewer_cookie)
        require(status == 200, "viewer login failed")
        status, viewer_orders = http.request("/api/orders", cookie=viewer_cookie)
        require(status == 200 and isinstance(viewer_orders.get("orders"), list), "viewer order read failed")
        viewer_pending = next((o for o in viewer_orders["orders"] if o.get("status") == "pending"), None)
        require(viewer_pending is not None, "viewer test has no pending order")
        deny_status, deny = http.request("/api/cancellation-proposals", {
            "order_id": viewer_pending["id"],
            "order_version": viewer_pending["version"],
            "cancel_reason": "ordered_by_mistake",
        }, cookie=viewer_cookie)
        require(deny_status == 403 and deny.get("error") == "permission_denied", "viewer was able to propose cancellation")
        report["checks"]["viewer_denied_cancel"] = True
    finally:
        revoke_member(customer_membership, customer_cred_path)
        revoke_member(viewer_membership, viewer_cred_path)
        report.setdefault("cleanup", {})["credentials_revoked"] = True
        report["cleanup"]["isolated_tenant_retained_for_audit"] = tenant


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--expected-image", default=None)
    args = parser.parse_args()

    os.umask(0o077)
    require(ROOT.is_dir(), "/opt/retailops is missing")
    require((ROOT / "public.env").is_file(), "public.env is missing")
    require((ROOT / "deployed.env").is_file(), "deployed.env is missing")

    global COMPOSE
    COMPOSE = compose_base()
    dc(["config", "--quiet"])

    host = env_value(ROOT / "public.env", "RETAILOPS_PUBLIC_HOST")
    require(bool(host), "RETAILOPS_PUBLIC_HOST is missing")
    stamp = now_stamp()
    temp_path = Path(tempfile.mkdtemp(prefix="retailops-e2e.", dir="/tmp"))
    os.chmod(temp_path, 0o700)
    report = {
        "report": "RetailOps live E2E",
        "mode": args.mode,
        "started_at_utc": stamp,
        "checks": {},
    }
    secrets = []
    try:
        http = HttpClient(host, temp_path)
        common_runtime_checks(http, args.expected_image, report)
        if args.mode == "smoke":
            run_smoke(http, report, secrets)
        else:
            run_full(http, report, secrets)
        report["pass"] = True
        report["finished_at_utc"] = now_stamp()
        path = save_report(report, args.mode, stamp, secrets)
        print(f"LIVE_E2E_{args.mode.upper()}_OK report={path}")
    except Exception as exc:
        report["pass"] = False
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        report["finished_at_utc"] = now_stamp()
        try:
            path = save_report(report, args.mode, stamp, secrets)
        except Exception:
            path = None
        suffix = f" report={path}" if path else ""
        print(f"LIVE_E2E_{args.mode.upper()}_FAILED{suffix}")
        raise
    finally:
        for child in temp_path.iterdir():
            try:
                child.unlink()
            except IsADirectoryError:
                pass
        try:
            temp_path.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    main()
