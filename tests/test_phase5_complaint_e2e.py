"""Unit, integration and offline contract tests for Phase 5 P5-D:
Complaint E2E on the Same Customer Identity (P5-K7 & P5-K8).

Verifies the complete offline journey:
1. Same synthetic customer identity across sales import and customer session
   (tenant + Google identity -> principal -> customer -> session binding).
2. Order visibility and isolation: customer reads only their own imported orders;
   cross-customer and cross-tenant access is rejected (404 order_not_found).
3. Complaint routing via supervisor:
   - Cancellation / refund -> dispute_agent (with proposal).
   - Defect / 1-1 exchange -> dispute_agent (with 1-1 proposal).
   - Extreme rage / boycott threat -> human_escalation (SOP 5 strict mode).
   - Explicit human agent request -> human_escalation (SOP 6).
4. Tenant and customer policy/context isolation:
   - Dispute agent refuses cross-customer order requests with zero data leakage.
   - Knowledge retrieval safely handles offline/tenant boundaries without inventing policies.
5. Strict pre-confirmation invariant: zero database mutations on orders or business state
   prior to explicit confirmation.
6. Confirmation owner validation: other sessions/customers cannot confirm proposals (404).
7. Confirmation idempotency:
   - First confirmation transitions order to cancelled, increments version, and logs audit.
   - Exact replay with same Idempotency-Key returns replayed=True with zero additional mutations.
   - Replay with different Idempotency-Key is rejected (409 already_confirmed).
   - Stale order version is rejected (409 stale_order).
8. Dismissal preserves order state: proposal becomes dismissed, order remains pending.
9. Reload and audit replay: all audit trails (imported_events, identity_events,
   business_events, proposals) persist across restarts and replay cleanly.
10. Failure paths: delivered orders refuse cancellation proposals.
11. Evidence checksums: all fixtures and reports have deterministic SHA256 hashes.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
import re
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

from retailops.business.application import Application
from retailops.core import ApiError
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions
from retailops.knowledge.repository import KnowledgeRepository
from retailops.knowledge.tool import KnowledgeTool
from retailops.sales.adapter import SalesImportAdapter
from retailops.sales.events import compute_signature
from retailops.sales.fixtures import (
    FIXTURE_P5D_DELIVERED_ORDER,
    FIXTURE_P5D_PENDING_ORDER,
    get_signed_fixtures,
)
from retailops.sales.simulator import DEFAULT_DEV_SECRET, SalesSimulator

DSN = os.environ.get("RETAILOPS_TEST_DATABASE_URL", "")


class MockDisputeChatGateway:
    """Deterministic offline mock LLM gateway for P5-D multi-agent complaint flow.

    Never invokes paid or remote models. Simulates supervisor triage and dispute worker responses.
    """

    def __init__(self):
        self.inputs = []

    def inspect(self):
        return {
            "name": "mock-p5d-dispute-engine",
            "digest": "sha256:p5d_mock_digest_00000000000000000000000000000000",
            "provider": "offline_mock",
            "ollama_version": "p5d-mock-0.1",
        }

    def chat(self, messages, allow_tools, timeout):
        self.inputs.append(copy.deepcopy(messages))
        last_msg = messages[-1]
        content = last_msg.get("content", "")

        # If last message was a tool callback
        if last_msg.get("role") == "tool":
            tool_name = last_msg.get("tool_name", "")
            tool_res = last_msg.get("content", "")

            # Specialized knowledge search callback synthesis
            if tool_name == "search_knowledge":
                res_data = {}
                try:
                    res_data = json.loads(tool_res) if isinstance(tool_res, str) else tool_res
                except Exception:
                    pass
                if isinstance(res_data, dict) and res_data.get("error"):
                    err_code = res_data.get("error")
                    return {
                        "message": {
                            "role": "assistant",
                            "content": f"Dạ hiện tại hệ thống tra cứu chính sách của shop đang được cập nhật ({err_code}) và chưa sẵn sàng. Để đảm bảo quyền lợi khiếu nại của anh/chị, em xin phép chuyển yêu cầu đến chuyên viên CSKH hỗ trợ trực tiếp và không tự ý áp dụng quy định chưa được xác thực nhé ạ!",
                        },
                        "done_reason": "stop",
                        "prompt_eval_count": 50,
                        "eval_count": 25,
                    }
                if isinstance(res_data, dict) and res_data.get("results"):
                    first = res_data["results"][0]
                    cid = first.get("citation_id", "")
                    excerpt = first.get("excerpt", "")
                    title = first.get("title", "Chính sách của shop")
                    return {
                        "message": {
                            "role": "assistant",
                            "content": f"Theo quy định tại {title}: {excerpt} [{cid}]. Shop đã tiếp nhận khiếu nại của anh/chị và sẽ giải quyết theo đúng chính sách này ạ!",
                        },
                        "done_reason": "stop",
                        "prompt_eval_count": 60,
                        "eval_count": 30,
                    }
                return {
                    "message": {
                        "role": "assistant",
                        "content": "Dạ hiện tại kho tri thức chính sách của shop chưa có tài liệu quy định phù hợp cho nội dung này. Để đảm bảo quyền lợi khiếu nại của anh/chị, em xin phép ghi nhận thông tin và chuyển chuyên viên CSKH hỗ trợ trực tiếp, không tự ý áp dụng quy định chưa được xác thực nhé ạ!",
                    },
                    "done_reason": "stop",
                    "prompt_eval_count": 50,
                    "eval_count": 25,
                }

            return {
                "message": {
                    "role": "assistant",
                    "content": f"Dạ em đã kiểm tra thông tin ({tool_name}): {tool_res}. Em đã chuẩn bị phương án phù hợp cho anh/chị rồi ạ!",
                },
                "done_reason": "stop",
                "prompt_eval_count": 50,
                "eval_count": 25,
            }

        lower = content.lower()

        # Cancellation tool call trigger if model is asked
        if allow_tools and any(kw in lower for kw in ("hủy đơn", "hủy hàng", "muốn hủy")):
            m = re.search(r"\b(o-\d+|o0\d{5,}|o\d{5,})\b", lower)
            target_oid = m.group(1).upper() if m else "O-90001"
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "prepare_cancellation",
                                "arguments": json.dumps({"order_id": target_oid, "reason": "ordered_by_mistake"}),
                            }
                        }
                    ],
                },
                "done_reason": "tool_calls",
                "prompt_eval_count": 60,
                "eval_count": 20,
            }

        # Knowledge search tool call trigger for complaint / policy queries
        if allow_tools and any(kw in lower for kw in ("chính sách", "quy định", "đổi trả", "bảo hành", "hoàn tiền")):
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_knowledge",
                                "arguments": json.dumps({"query": "chính sách đổi trả hàng hoàn tiền"}),
                            }
                        }
                    ],
                },
                "done_reason": "tool_calls",
                "prompt_eval_count": 60,
                "eval_count": 20,
            }

        # Default helpful assistant reply
        return {
            "message": {
                "role": "assistant",
                "content": "Dạ shop đã ghi nhận thông tin phản hồi của anh/chị và luôn sẵn sàng hỗ trợ giải quyết thỏa đáng ạ!",
            },
            "done_reason": "stop",
            "prompt_eval_count": 40,
            "eval_count": 15,
        }


class Phase5ComplaintE2ETests(unittest.TestCase):
    """Offline E2E verification of the P5-D complaint journey."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)
        self.gateway = MockDisputeChatGateway()
        self.sessions = PersistentSessions(
            self.directory,
            data_mode="persistent-demo",
            api_infer=self.gateway,
        )

        # Primary synthetic tenant
        self.tenant_id = "tenant-p5d-demo"
        self.sessions.provision_tenant(self.tenant_id, "RetailOps P5D Synthetic Shop", seed_demo=True)

        # Secondary synthetic tenant for cross-tenant testing
        self.other_tenant_id = "tenant-p5d-other"
        self.sessions.provision_tenant(self.other_tenant_id, "Other Synthetic Shop", seed_demo=True)

        # Adapters and simulators
        self.adapter = SalesImportAdapter(self.sessions, default_secret=DEFAULT_DEV_SECRET)
        self.simulator = SalesSimulator(tenant_id=self.tenant_id, secret_key=DEFAULT_DEV_SECRET)

        # Public web layer
        self.origin = "https://retailops.example.com"
        self.web = PublicWeb(self.origin, self.sessions)

        # Synthetic customer 1 (Primary owner)
        self.cust1_issuer = "https://accounts.google.com"
        self.cust1_sub = "google-sub-p5d-synthetic-001"
        self.cust1_email = "buyer.p5d.01@synthetic.retailops"
        self.cust1_name = "Synthetic Buyer One"
        self.cust1_ext_id = "ext_pos_p5d_001"

        # Log in customer 1
        self.cust1_cookie_secret = self.sessions.login_google(
            email=self.cust1_email,
            name=self.cust1_name,
            role="customer",
            sub=self.cust1_sub,
            issuer=self.cust1_issuer,
            email_verified=True,
            tenant_id=self.tenant_id,
        )
        self.cust1_cookie = f"{self.sessions.cookie_name}={self.cust1_cookie_secret}"
        resolved1 = self.sessions.control.resolve(self.sessions.cookie_id(self.cust1_cookie))
        self.cust1_id = resolved1["customer_id"]
        self.cust1_pid = resolved1["principal_id"]

        # Synthetic customer 2 (Same tenant, different identity)
        self.cust2_sub = "google-sub-p5d-synthetic-002"
        self.cust2_email = "buyer.p5d.02@synthetic.retailops"
        self.cust2_cookie_secret = self.sessions.login_google(
            email=self.cust2_email,
            name="Synthetic Buyer Two",
            role="customer",
            sub=self.cust2_sub,
            issuer="https://accounts.google.com",
            email_verified=True,
            tenant_id=self.tenant_id,
        )
        self.cust2_cookie = f"{self.sessions.cookie_name}={self.cust2_cookie_secret}"
        resolved2 = self.sessions.control.resolve(self.sessions.cookie_id(self.cust2_cookie))
        self.cust2_id = resolved2["customer_id"]

        # Synthetic customer 3 (Different tenant)
        self.cust3_sub = "google-sub-p5d-synthetic-003"
        self.cust3_cookie_secret = self.sessions.login_google(
            email="buyer.p5d.other@synthetic.retailops",
            name="Other Tenant Buyer",
            role="customer",
            sub=self.cust3_sub,
            issuer="https://accounts.google.com",
            email_verified=True,
            tenant_id=self.other_tenant_id,
        )
        self.cust3_cookie = f"{self.sessions.cookie_name}={self.cust3_cookie_secret}"

        # Link external customer to the Google customer_id in setUp
        self.adapter.link_external_customer(
            tenant_id=self.tenant_id,
            source_system="pos_online",
            external_customer_id=self.cust1_ext_id,
            customer_id=self.cust1_id,
            customer_name=self.cust1_name,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def request(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        cookie: str = "",
        headers: Optional[Dict[str, str]] = None,
        method: Optional[str] = None,
    ) -> tuple[int, Any, list[tuple[str, str]]]:
        """Helper to invoke PublicWeb.route via WSGI environ."""
        req_method = method or ("GET" if body is None else "POST")
        raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
        env = {
            "REQUEST_METHOD": req_method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_ORIGIN": self.origin,
            "HTTP_COOKIE": cookie,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(raw_body)),
            "wsgi.input": io.BytesIO(raw_body),
        }
        if headers:
            for k, v in headers.items():
                env_key = "HTTP_" + k.upper().replace("-", "_")
                env[env_key] = v

        status, data, mime, resp_headers = self.web.route(env)
        return status, data, resp_headers

    # -------------------------------------------------------------------------
    # 1. Same Customer Identity Binding & Sales Order Ingestion (P5-K7)
    # -------------------------------------------------------------------------

    def test_01_same_identity_binding_import_and_session(self):
        """P5-K7: Sales import and customer session share the identical customer_id binding."""
        # 1. Link external customer to the Google customer_id
        link_res = self.adapter.link_external_customer(
            tenant_id=self.tenant_id,
            source_system="pos_online",
            external_customer_id=self.cust1_ext_id,
            customer_id=self.cust1_id,
            customer_name=self.cust1_name,
        )
        self.assertEqual(link_res["customer_id"], self.cust1_id)

        # 2. Ingest pending sales event
        event = self.simulator.create_order_event(
            source_system="pos_online",
            event_id="evt_p5d_order_101",
            external_customer_id=self.cust1_ext_id,
            order_id="O-90001",
            status="pending",
            items=[
                {
                    "product_id": "P-601",
                    "product_title": "Áo sơ mi lụa công sở",
                    "variant_name": "Trắng / M",
                    "quantity": 1,
                    "unit_price": 450000,
                }
            ],
            total=450000,
        )
        import_res = self.adapter.ingest_event(event)
        self.imported_event = copy.deepcopy(event)
        self.assertTrue(import_res.success)
        self.assertEqual(import_res.customer_id, self.cust1_id)
        self.assertEqual(import_res.order_id, "O-90001")

        # 3. Customer 1 checks /api/session
        status, sess, _ = self.request("/api/session", cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(sess["tenant_id"], self.tenant_id)
        self.assertEqual(sess["principal_id"], self.cust1_pid)
        self.assertEqual(sess["customer_id"], self.cust1_id)
        self.assertEqual(sess["role"], "customer")

        # 4. Customer 1 checks /api/orders
        status, orders_res, _ = self.request("/api/orders", cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        order_ids = [o["id"] for o in orders_res["orders"]]
        self.assertIn("O-90001", order_ids)

        # 5. Verify email was not used as key
        self.assertNotIn("@", self.cust1_ext_id)
        self.assertNotIn("@", self.cust1_sub)

    # -------------------------------------------------------------------------
    # 2. Customer Order Visibility & Cross-Customer / Tenant Isolation (P5-K6/K7)
    # -------------------------------------------------------------------------

    def test_02_order_visibility_isolation_across_customers_and_tenants(self):
        """P5-K6/K7: Customer 1 sees O-90001; Customer 2 and other tenant receive 404."""
        self.test_01_same_identity_binding_import_and_session()

        # Customer 2 in same tenant sees ZERO orders for O-90001
        status, orders_c2, _ = self.request("/api/orders", cookie=self.cust2_cookie)
        self.assertEqual(status, 200)
        self.assertNotIn("O-90001", [o["id"] for o in orders_c2["orders"]])

        # Customer 2 direct lookup raises 404 order_not_found
        with self.assertRaises(ApiError) as ctx:
            self.request("/api/orders/O-90001", cookie=self.cust2_cookie)
        self.assertEqual(ctx.exception.code, "order_not_found")

        # Customer 3 in different tenant direct lookup raises 404 order_not_found
        with self.assertRaises(ApiError) as ctx:
            self.request("/api/orders/O-90001", cookie=self.cust3_cookie)
        self.assertEqual(ctx.exception.code, "order_not_found")

    # -------------------------------------------------------------------------
    # 3. Complaint Routing via Supervisor to Dispute Worker (P5-K7)
    # -------------------------------------------------------------------------

    def test_03_complaint_routing_cancellation_dispute_agent(self):
        """P5-K7: Supervisor routes cancellation complaint to dispute_agent and prepares proposal."""
        self.test_01_same_identity_binding_import_and_session()

        # Create conversation
        status, conv, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        cid = conv["conversation_id"]

        # Send cancellation complaint
        chat_body = {
            "conversation_id": cid,
            "text": "Tôi muốn hủy đơn hàng O-90001 vì tôi đặt nhầm sản phẩm",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res, _ = self.request("/api/chat", chat_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)

        # Verify supervisor routing & trace
        trace = chat_res["trace"]
        self.assertEqual(trace.get("orchestrator"), "multiagent_langgraph")
        self.assertEqual(trace.get("supervisor_intent"), "dispute_complaint")
        self.assertEqual(trace.get("routing_reason"), "dispute_cancellation_refund")
        sub_history = trace.get("subagent_history", [])
        self.assertIn("supervisor:routed_to_dispute_agent", sub_history)
        self.assertIn("dispute_agent:proposal_ready", sub_history)

        # Verify proposal payload (NOT mutated in DB yet)
        proposal = chat_res.get("action_proposal")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["action"], "cancel_order")
        self.assertEqual(proposal["order_id"], "O-90001")
        self.assertEqual(proposal["status"], "pending_user_confirmation")

        # Verify UI prompt asks user to review proposal
        self.assertEqual(chat_res["action"], "choose_cancel_reason")
        self.assertEqual(chat_res["order"]["id"], "O-90001")

    def test_04_complaint_routing_defect_exchange_proposal(self):
        """P5-K7: Supervisor routes defect complaint to dispute_agent, generating 1-1 exchange proposal."""
        self.test_01_same_identity_binding_import_and_session()

        status, conv, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        cid = conv["conversation_id"]

        chat_body = {
            "conversation_id": cid,
            "text": "Áo đơn O-90001 bị kẹt khóa và bung chỉ, shop đổi 1-1 cho tôi",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res, _ = self.request("/api/chat", chat_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)

        trace = chat_res["trace"]
        self.assertEqual(trace.get("supervisor_intent"), "dispute_complaint")
        self.assertEqual(trace.get("routing_reason"), "dispute_exchange_defect")
        self.assertIn("supervisor:routed_to_dispute_agent", trace.get("subagent_history", []))

        proposal = chat_res.get("action_proposal")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["action"], "exchange_1to1")
        self.assertEqual(proposal["order_id"], "O-90001")
        self.assertEqual(proposal["status"], "pending_staff_approval")

    def test_05_complaint_routing_human_escalation_on_rage_or_explicit_request(self):
        """P5-K7: Severe threats or explicit human requests escalate safely to human_escalation node."""
        status, conv, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        cid = conv["conversation_id"]

        # 1. Extreme anger / boycott threat (SOP 5 Strict Mode)
        rage_body = {
            "conversation_id": cid,
            "text": "Tôi sẽ bóc phốt và kiện cáo cửa hàng lên sàn TMĐT vì làm ăn tắc trách!",
            "request_id": str(uuid.uuid4()),
        }
        status, rage_res, _ = self.request("/api/chat", rage_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        self.assertIn("supervisor:escalate_extreme_rage", rage_res["trace"]["subagent_history"])
        self.assertIsNone(rage_res.get("action_proposal"))

        # 2. Explicit human agent request (SOP 6)
        human_body = {
            "conversation_id": cid,
            "text": "Cho tôi gặp nhân viên quản lý giải quyết ngay",
            "request_id": str(uuid.uuid4()),
        }
        status, human_res, _ = self.request("/api/chat", human_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        self.assertIn("supervisor:escalate_human", human_res["trace"]["subagent_history"])
        self.assertIsNone(human_res.get("action_proposal"))

    # -------------------------------------------------------------------------
    # 4. Tenant Policy / RAG & Cross-Customer Worker Isolation (P5-K7)
    # -------------------------------------------------------------------------

    def test_06_dispute_worker_cross_customer_refusal_no_leak(self):
        """P5-K7: Dispute worker refuses to process another customer's order and leaks no information."""
        self.test_01_same_identity_binding_import_and_session()

        # Customer 2 attempts to cancel Customer 1's order O-90001 via chat
        status, conv2, _ = self.request("/api/conversations", {}, cookie=self.cust2_cookie)
        cid2 = conv2["conversation_id"]

        chat_body = {
            "conversation_id": cid2,
            "text": "Tôi muốn hủy đơn hàng O-90001",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res, _ = self.request("/api/chat", chat_body, cookie=self.cust2_cookie)
        self.assertEqual(status, 200)

        # Worker refuses and DOES NOT generate an action proposal
        self.assertIsNone(chat_res.get("action_proposal"))
        self.assertIn("không tìm thấy đơn hàng", chat_res["message"].lower())
        self.assertNotIn("Áo sơ mi lụa", chat_res["message"])  # No leaked order details

    def test_07_tenant_policy_rag_isolation(self):
        """P5-K7 (D-R1): Boundary seam and contract verification for tenant policy retrieval:
        1. Tool trace contains search_knowledge and KnowledgeTool.search is actually called.
        2. Boundary seam with schema-isolated canned repository responses proves application-level
           trace logging, citation formatting ([KB:...]), and tenant parameter passing.
        3. Strict isolation: Tenant A receives Tenant A policy, zero leak of Tenant B marker.
        4. Safe refusal when retrieval is unavailable (knowledge_not_ready) on SQLite without inventing policy.
        NOTE: Real repository-backed pgvector retrieval on disposable database is tested in
        Phase5ComplaintPgvectorTests.test_pgvector_complaint_tenant_policy_isolation.
        """
        self.test_01_same_identity_binding_import_and_session()

        # Ensure apps are resolved and stores have schemas set for tenant isolation test
        with self.sessions.resolve(self.cust1_cookie) as b1:
            b1.application.store.schema = "tenant_alpha"
        with self.sessions.resolve(self.cust3_cookie) as b3:
            b3.application.store.schema = "tenant_beta"

        policy_a_marker = "POLICY_ALPHA_7DAYS_EXCLUSIVE"
        policy_b_marker = "POLICY_BETA_SECRET_999DAYS_RESTRICTED"

        doc_alpha = {
            "chunk": f"Chính sách đổi trả shop Alpha: Đơn hàng hợp lệ được đổi trả trong 7 ngày nếu còn nguyên tem mác. Mã quy định: {policy_a_marker}.",
            "source_key": "policies/returns_alpha.md",
            "title": "Quy định đổi trả Alpha",
            "score": 0.85,
        }
        doc_beta = {
            "chunk": f"Chính sách bảo mật shop Beta: Hàng đổi trả trong 999 ngày không giới hạn. Mã quy định: {policy_b_marker}.",
            "source_key": "policies/returns_beta.md",
            "title": "Quy định riêng Beta",
            "score": 0.95,
        }

        search_calls = []

        def fake_repo_search(repo_self, query, limit=5):
            schema = getattr(repo_self.store, "schema", None)
            search_calls.append({"schema": schema, "query": query})
            if schema == "tenant_alpha":
                return [dict(doc_alpha)]
            elif schema == "tenant_beta":
                return [dict(doc_beta)]
            return []

        # 1. Customer 1 (Tenant A) sends complaint about policy
        status, conv1, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        cid1 = conv1["conversation_id"]

        chat_body1 = {
            "conversation_id": cid1,
            "text": "Khiếu nại hoàn tiền đơn hàng O-90001 theo chính sách của shop",
            "request_id": str(uuid.uuid4()),
        }

        with patch.object(KnowledgeRepository, "search", fake_repo_search):
            status, chat_res1, _ = self.request("/api/chat", chat_body1, cookie=self.cust1_cookie)

        self.assertEqual(status, 200)
        self.assertEqual(chat_res1["trace"].get("supervisor_intent"), "dispute_complaint")

        # Assert KnowledgeTool.search was ACTUALLY called
        self.assertGreaterEqual(len(search_calls), 1)
        self.assertEqual(search_calls[0]["schema"], "tenant_alpha")
        tool_names = [t.get("name") for t in chat_res1["trace"].get("tools", [])]
        self.assertIn("search_knowledge", tool_names)
        tool_entry = next(t for t in chat_res1["trace"]["tools"] if t["name"] == "search_knowledge")
        self.assertEqual(tool_entry["status"], "ok")

        # Assert source & citation for Tenant A
        sources1 = chat_res1.get("sources", [])
        self.assertGreaterEqual(len(sources1), 1)
        self.assertTrue(sources1[0]["citation_id"].startswith("KB:"))
        self.assertEqual(sources1[0]["source_key"], "policies/returns_alpha.md")
        self.assertEqual(sources1[0]["title"], "Quy định đổi trả Alpha")

        # Assert Tenant A content is present, Tenant B marker is absent
        self.assertIn(policy_a_marker, chat_res1["message"])
        self.assertNotIn(policy_b_marker, chat_res1["message"])
        self.assertNotIn(policy_b_marker, json.dumps(sources1))

        # 2. Customer 3 (Tenant B) sends complaint in Tenant B
        status, conv3, _ = self.request("/api/conversations", {}, cookie=self.cust3_cookie)
        cid3 = conv3["conversation_id"]

        chat_body3 = {
            "conversation_id": cid3,
            "text": "Khiếu nại hoàn tiền theo chính sách của shop",
            "request_id": str(uuid.uuid4()),
        }

        with patch.object(KnowledgeRepository, "search", fake_repo_search):
            status, chat_res3, _ = self.request("/api/chat", chat_body3, cookie=self.cust3_cookie)

        self.assertEqual(status, 200)
        self.assertEqual(search_calls[-1]["schema"], "tenant_beta")
        sources3 = chat_res3.get("sources", [])
        self.assertGreaterEqual(len(sources3), 1)
        self.assertEqual(sources3[0]["source_key"], "policies/returns_beta.md")
        self.assertIn(policy_b_marker, chat_res3["message"])
        self.assertNotIn(policy_a_marker, chat_res3["message"])
        self.assertNotIn(policy_a_marker, json.dumps(sources3))

        # 3. Safe no-evidence behavior: migrated tenant schema with zero matching documents
        with self.sessions.resolve(self.cust1_cookie) as b1:
            b1.application.store.schema = "tenant_empty"
            if hasattr(b1.application, "tool_cache"):
                b1.application.tool_cache.bump_epoch(self.tenant_id, self.cust1_id)

        status, conv_empty, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        chat_body_empty = {
            "conversation_id": conv_empty["conversation_id"],
            "text": "Khiếu nại đổi trả theo chính sách của shop",
            "request_id": str(uuid.uuid4()),
        }
        with patch.object(KnowledgeRepository, "search", fake_repo_search):
            status, chat_res_empty, _ = self.request("/api/chat", chat_body_empty, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(search_calls[-1]["schema"], "tenant_empty")
        empty_tools = [t for t in chat_res_empty["trace"].get("tools", []) if t.get("name") == "search_knowledge"]
        self.assertGreaterEqual(len(empty_tools), 1)
        self.assertEqual(empty_tools[0]["status"], "ok")
        self.assertEqual(chat_res_empty.get("sources", []), [])
        self.assertNotIn("[KB:", chat_res_empty["message"])
        self.assertNotIn(policy_a_marker, chat_res_empty["message"])
        self.assertNotIn(policy_b_marker, chat_res_empty["message"])

        # 4. Safe unavailable behavior: when store has no schema (standard SQLite default)
        with self.sessions.resolve(self.cust1_cookie) as b1:
            if hasattr(b1.application.store, "schema"):
                delattr(b1.application.store, "schema")
            if hasattr(b1.application, "tool_cache"):
                b1.application.tool_cache.bump_epoch(self.tenant_id, self.cust1_id)

        status, conv_unav, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        cid_unav = conv_unav["conversation_id"]
        chat_body_unav = {
            "conversation_id": cid_unav,
            "text": "Khiếu nại hoàn tiền đơn hàng O-90001 theo chính sách của shop",
            "request_id": str(uuid.uuid4()),
        }
        with patch.object(KnowledgeRepository, "search", fake_repo_search):
            status, chat_res_unav, _ = self.request("/api/chat", chat_body_unav, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        unav_tools = [t for t in chat_res_unav["trace"].get("tools", []) if t.get("name") == "search_knowledge"]
        self.assertGreaterEqual(len(unav_tools), 1)
        self.assertEqual(unav_tools[0]["status"], "error")
        # Truthful refusal: sources is empty, does not invent policy, offers safe CSKH handoff
        self.assertEqual(chat_res_unav.get("sources", []), [])
        self.assertIn("chưa sẵn sàng", chat_res_unav["message"].lower())
        self.assertNotIn(policy_a_marker, chat_res_unav["message"])
        self.assertNotIn(policy_b_marker, chat_res_unav["message"])

    # -------------------------------------------------------------------------
    # 5. Zero Pre-Confirmation Database Mutation (P5-K7 & P5-K8)
    # -------------------------------------------------------------------------

    def test_08_no_pre_confirmation_mutation(self):
        """P5-K7/K8: Complaint chat and proposal preparation produce zero mutations on orders."""
        self.test_03_complaint_routing_cancellation_dispute_agent()

        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(order["status"], "pending")
            self.assertEqual(order["version"], 1)

            # Ensure NO order_cancelled event was emitted into business_events
            ev = db.execute("SELECT * FROM business_events WHERE order_id='O-90001' AND kind='order_cancelled'").fetchone()
            self.assertIsNone(ev)

        # Now create explicit cancellation proposal via API
        prop_body = {
            "order_id": "O-90001",
            "order_version": 1,
            "cancel_reason": "ordered_by_mistake",
        }
        status, prop_res, _ = self.request("/api/cancellation-proposals", prop_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        self.assertEqual(prop_res["workflow_status"], "awaiting_confirmation")
        pid = prop_res["proposal_id"]

        # Check database again: STILL pending and version 1!
        with bstore.connection() as db:
            order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(order["status"], "pending")
            self.assertEqual(order["version"], 1)

            p_row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
            self.assertEqual(p_row["state"], "pending")
            self.assertIsNone(p_row["confirm_key"])

    # -------------------------------------------------------------------------
    # 6. Confirmation Owner Validation & Idempotency (P5-K8)
    # -------------------------------------------------------------------------

    def test_09_confirmation_rejected_for_wrong_customer_or_session(self):
        """P5-K8: Customer 2 cannot confirm Customer 1's cancellation proposal."""
        self.test_01_same_identity_binding_import_and_session()

        # Customer 1 creates proposal
        prop_body = {"order_id": "O-90001", "order_version": 1, "cancel_reason": "ordered_by_mistake"}
        status, prop_res, _ = self.request("/api/cancellation-proposals", prop_body, cookie=self.cust1_cookie)
        pid = prop_res["proposal_id"]

        # Customer 2 attempts to confirm
        endpoint = f"/api/cancellation-proposals/{pid}/confirm"
        with self.assertRaises(ApiError) as ctx:
            self.request(
                endpoint,
                {"confirmed": True},
                cookie=self.cust2_cookie,
                headers={"Idempotency-Key": "key-intruder-000000000000001"},
            )
        self.assertEqual(ctx.exception.code, "proposal_not_found")

        # Order is still pending
        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(order["status"], "pending")

    def test_10_confirmation_rejected_for_stale_order_version(self):
        """P5-K8: Confirmation fails if order version was modified before confirmation."""
        self.test_01_same_identity_binding_import_and_session()

        prop_body = {"order_id": "O-90001", "order_version": 1, "cancel_reason": "ordered_by_mistake"}
        status, prop_res, _ = self.request("/api/cancellation-proposals", prop_body, cookie=self.cust1_cookie)
        pid = prop_res["proposal_id"]

        # Simulate concurrent order update (bump version to 2)
        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection(write=True) as db:
            db.execute("UPDATE orders SET version=2 WHERE id='O-90001'")

        # Confirm attempt must raise stale_order (409)
        endpoint = f"/api/cancellation-proposals/{pid}/confirm"
        with self.assertRaises(ApiError) as ctx:
            self.request(
                endpoint,
                {"confirmed": True},
                cookie=self.cust1_cookie,
                headers={"Idempotency-Key": "key-stale-00000000000000001"},
            )
        self.assertEqual(ctx.exception.code, "stale_order")

    def test_11_confirmation_idempotency_and_replay(self):
        """P5-K8: Confirmation succeeds once, exact replay returns replayed=True, conflicting key raises 409."""
        self.test_01_same_identity_binding_import_and_session()

        prop_body = {"order_id": "O-90001", "order_version": 1, "cancel_reason": "ordered_by_mistake"}
        status, prop_res, _ = self.request("/api/cancellation-proposals", prop_body, cookie=self.cust1_cookie)
        pid = prop_res["proposal_id"]

        endpoint = f"/api/cancellation-proposals/{pid}/confirm"
        idemp_key = "idemp_key_fixed_synth_001"

        # 1. First confirmation: success, order is cancelled
        status, res1, _ = self.request(
            endpoint,
            {"confirmed": True},
            cookie=self.cust1_cookie,
            headers={"Idempotency-Key": idemp_key},
        )
        self.assertEqual(status, 200)
        self.assertFalse(res1.get("replayed", False))
        self.assertEqual(res1["order"]["status"], "cancelled")
        self.assertEqual(res1["order"]["version"], 2)

        # Verify DB state
        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(order["status"], "cancelled")
            self.assertEqual(order["version"], 2)

            ev_cnt = db.execute(
                "SELECT count(*) as c FROM business_events WHERE order_id='O-90001' AND kind='order_cancelled'"
            ).fetchone()["c"]
            self.assertEqual(ev_cnt, 1)

        # 2. Replay with EXACT same idempotency key
        status, res2, _ = self.request(
            endpoint,
            {"confirmed": True},
            cookie=self.cust1_cookie,
            headers={"Idempotency-Key": idemp_key},
        )
        self.assertEqual(status, 200)
        self.assertTrue(res2.get("replayed", False))
        self.assertEqual(res2["order"]["status"], "cancelled")
        self.assertEqual(res2["order"]["version"], 2)

        # Verify no duplicate mutation or event
        with bstore.connection() as db:
            ev_cnt_after = db.execute(
                "SELECT count(*) as c FROM business_events WHERE order_id='O-90001' AND kind='order_cancelled'"
            ).fetchone()["c"]
            self.assertEqual(ev_cnt_after, 1)

        # 3. Replay with DIFFERENT idempotency key -> 409 already_confirmed
        with self.assertRaises(ApiError) as ctx:
            self.request(
                endpoint,
                {"confirmed": True},
                cookie=self.cust1_cookie,
                headers={"Idempotency-Key": "idemp_key_different_0002"},
            )
        self.assertEqual(ctx.exception.code, "already_confirmed")

    def test_12_proposal_dismissal_preserves_order_state(self):
        """P5-K8: Dismissing a cancellation proposal preserves pending order status and closes proposal."""
        self.test_01_same_identity_binding_import_and_session()

        prop_body = {"order_id": "O-90001", "order_version": 1, "cancel_reason": "ordered_by_mistake"}
        status, prop_res, _ = self.request("/api/cancellation-proposals", prop_body, cookie=self.cust1_cookie)
        pid = prop_res["proposal_id"]

        # Dismiss proposal
        status, dis_res, _ = self.request(f"/api/cancellation-proposals/{pid}/dismiss", {}, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)

        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(order["status"], "pending")
            p_row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
            self.assertEqual(p_row["state"], "dismissed")

        # Subsequent confirmation attempt raises 409
        with self.assertRaises(ApiError) as ctx:
            self.request(
                f"/api/cancellation-proposals/{pid}/confirm",
                {"confirmed": True},
                cookie=self.cust1_cookie,
                headers={"Idempotency-Key": "key-dismissed-0000000000001"},
            )
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn(ctx.exception.code, ("idempotency_conflict", "inactive_proposal"))

    # -------------------------------------------------------------------------
    # 7. Restart, Replay & Audit Evidence (P5-K8)
    # -------------------------------------------------------------------------

    def test_13_persistence_reload_and_audit_replay(self):
        """P5-K8: Reopen session storage, confirm persistent audit trails, and replay events cleanly."""
        self.test_11_confirmation_idempotency_and_replay()

        # Simulate service restart: instantiate fresh PersistentSessions pointing to same directory
        restarted_sessions = PersistentSessions(
            self.directory,
            data_mode="persistent-demo",
            api_infer=self.gateway,
        )
        restarted_web = PublicWeb(self.origin, restarted_sessions)

        # 1. Resolve existing session cookie
        res = restarted_sessions.control.resolve(restarted_sessions.cookie_id(self.cust1_cookie))
        self.assertEqual(res["customer_id"], self.cust1_id)

        # 2. Check /api/orders via restarted web
        env = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/orders/O-90001",
            "QUERY_STRING": "",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_ORIGIN": self.origin,
            "HTTP_COOKIE": self.cust1_cookie,
        }
        status, data, _, _ = restarted_web.route(env)
        self.assertEqual(status, 200)
        self.assertEqual(data["order"]["status"], "cancelled")
        self.assertEqual(data["order"]["version"], 2)

        # 3. Replay sales import event through adapter
        restarted_adapter = SalesImportAdapter(restarted_sessions, default_secret=DEFAULT_DEV_SECRET)
        replay_event = self.imported_event
        replay_res = restarted_adapter.ingest_event(replay_event)
        self.assertTrue(replay_res.is_replay)
        self.assertEqual(replay_res.status, "already_processed")

        # 4. Audit trail inspection
        bstore = restarted_sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            evs = [dict(r) for r in db.execute("SELECT * FROM business_events WHERE order_id='O-90001'").fetchall()]
            kinds = [e["kind"] for e in evs]
            self.assertIn("order_imported", kinds)
            self.assertIn("cancellation_proposed", kinds)
            self.assertIn("order_cancelled", kinds)

    # -------------------------------------------------------------------------
    # 8. Failure Path: Delivered Order Ineligible for Cancellation
    # -------------------------------------------------------------------------

    def test_14_failure_path_delivered_order_cannot_be_cancelled(self):
        """P5-K7/K8: Delivered orders refuse cancellation proposals via both chat and API."""
        # Ingest delivered order
        deliv_event = self.simulator.create_order_event(
            source_system="pos_online",
            event_id="evt_p5d_deliv_001",
            external_customer_id=self.cust1_ext_id,
            order_id="O-90002",
            status="delivered",
            items=[{"product_id": "P-601", "product_title": "Áo sơ mi lụa công sở", "quantity": 1, "unit_price": 450000}],
            total=450000,
        )
        self.adapter.ingest_event(deliv_event)

        # 1. Customer chats asking to cancel delivered order O-90002
        status, conv, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        cid = conv["conversation_id"]

        chat_body = {
            "conversation_id": cid,
            "text": "Tôi muốn hủy đơn hàng O-90002",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res, _ = self.request("/api/chat", chat_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        self.assertIsNone(chat_res.get("action_proposal"))
        self.assertIn("không thể hỗ trợ hủy đơn", chat_res["message"].lower())

        # 2. Direct API proposal creation raises 409 not_cancellable
        with self.assertRaises(ApiError) as ctx:
            self.request(
                "/api/cancellation-proposals",
                {"order_id": "O-90002", "order_version": 1, "cancel_reason": "ordered_by_mistake"},
                cookie=self.cust1_cookie,
            )
        self.assertEqual(ctx.exception.code, "not_cancellable")

    # -------------------------------------------------------------------------
    # 9. Evidence Checksums, Lifecycle Report & Tamper Verification (P5-K8)
    # -------------------------------------------------------------------------

    def test_15_integrated_lifecycle_raw_report_and_tamper_verification(self):
        """P5-K8 (D-R2): Full integrated lifecycle:
        1. Sales order import -> bound Google customer session.
        2. Complaint in chat -> dispute agent generates cancellation proposal.
        3. Zero pre-confirmation database mutation verified.
        4. Customer creates cancellation proposal.
        5. Wrong customer and cross-tenant confirmation denied (404).
        6. Owning customer confirms proposal -> order transitions to cancelled, version 2, 1 audit event.
        7. Process reopen / restart -> exact confirmation replay returns replayed: True with zero additional mutation.
        8. Write raw sanitized lifecycle report to disk (zero real secrets or PII).
        9. Verify SHA256 equality on round-trip read.
        10. Negative tamper assertions: tampered bytes or tampered checksums are detected and rejected.
        """
        # 1. Ingest order O-90001
        pending_event = self.simulator.create_order_event(
            source_system="pos_online",
            event_id="evt_p5d_lifecycle_001",
            external_customer_id=self.cust1_ext_id,
            order_id="O-90001",
            status="pending",
            items=[{"product_id": "P-601", "product_title": "Áo sơ mi lụa công sở", "quantity": 1, "unit_price": 450000}],
            total=450000,
        )
        self.adapter.ingest_event(pending_event)

        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection() as db:
            initial_order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(initial_order["status"], "pending")
            self.assertEqual(initial_order["version"], 1)
            initial_ev_count = db.execute(
                "SELECT count(*) as c FROM business_events WHERE order_id='O-90001' AND kind='order_cancelled'"
            ).fetchone()["c"]
            self.assertEqual(initial_ev_count, 0)

        # 2. Complaint in chat
        status, conv, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        cid = conv["conversation_id"]

        chat_body = {
            "conversation_id": cid,
            "text": "Tôi muốn hủy đơn hàng O-90001 do đổi ý",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res, _ = self.request("/api/chat", chat_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(chat_res["trace"].get("supervisor_intent"), "dispute_complaint")
        proposal_action = chat_res.get("action_proposal")
        self.assertIsNotNone(proposal_action)
        self.assertEqual(proposal_action["action"], "cancel_order")
        self.assertEqual(proposal_action["order_id"], "O-90001")

        # 3. Pre-confirmation invariant check
        with bstore.connection() as db:
            pre_order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(pre_order["status"], "pending")
            self.assertEqual(pre_order["version"], 1)
            pre_ev_count = db.execute(
                "SELECT count(*) as c FROM business_events WHERE order_id='O-90001' AND kind='order_cancelled'"
            ).fetchone()["c"]
            self.assertEqual(pre_ev_count, 0)

        # 4. Customer creates persisted proposal bound directly to complaint action_proposal
        self.assertIsNotNone(proposal_action)
        self.assertEqual(proposal_action["action"], "cancel_order")
        expected_oid = proposal_action["order_id"]
        expected_version = proposal_action.get("order_version") or chat_res.get("order", {}).get("version", 1)
        expected_reason = proposal_action.get("cancel_reason") or proposal_action.get("reason", "ordered_by_mistake")
        if expected_reason not in ("ordered_by_mistake", "no_longer_needed"):
            expected_reason = "ordered_by_mistake"

        prop_body = {
            "order_id": expected_oid,
            "order_version": expected_version,
            "cancel_reason": expected_reason,
        }
        status, prop_res, _ = self.request("/api/cancellation-proposals", prop_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        proposal_id = prop_res["proposal_id"]
        self.assertEqual(prop_res["workflow_status"], "awaiting_confirmation")

        # Assert strict 1-to-1 binding between complaint action_proposal and persisted proposal
        self.assertEqual(prop_res["order"]["id"], expected_oid)
        self.assertEqual(prop_res["order"]["version"], expected_version)
        self.assertEqual(prop_res["reason"], expected_reason)

        # 5. Security: wrong customer & cross-tenant confirmation denied
        idemp_intruder = "idem_intruder_wrong_customer_001"
        with self.assertRaises(ApiError) as ctx_wrong_cust:
            self.request(
                f"/api/cancellation-proposals/{proposal_id}/confirm",
                {"confirmed": True},
                cookie=self.cust2_cookie,
                headers={"Idempotency-Key": idemp_intruder},
            )
        self.assertEqual(ctx_wrong_cust.exception.code, "proposal_not_found")

        with self.assertRaises(ApiError) as ctx_cross_tenant:
            self.request(
                f"/api/cancellation-proposals/{proposal_id}/confirm",
                {"confirmed": True},
                cookie=self.cust3_cookie,
                headers={"Idempotency-Key": idemp_intruder},
            )
        self.assertEqual(ctx_cross_tenant.exception.code, "proposal_not_found")

        # Confirm order still untouched
        with bstore.connection() as db:
            mid_order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(mid_order["status"], "pending")
            self.assertEqual(mid_order["version"], 1)

        # 6. Owning customer confirms proposal
        idemp_valid = "idem_p5d_lifecycle_valid_0001"
        status, conf_res1, _ = self.request(
            f"/api/cancellation-proposals/{proposal_id}/confirm",
            {"confirmed": True},
            cookie=self.cust1_cookie,
            headers={"Idempotency-Key": idemp_valid},
        )
        self.assertEqual(status, 200)
        self.assertFalse(conf_res1.get("replayed", False))
        self.assertEqual(conf_res1["order"]["status"], "cancelled")
        self.assertEqual(conf_res1["order"]["version"], 2)

        # Check DB post first confirm
        with bstore.connection() as db:
            post_order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(post_order["status"], "cancelled")
            self.assertEqual(post_order["version"], 2)
            post_ev_count = db.execute(
                "SELECT count(*) as c FROM business_events WHERE order_id='O-90001' AND kind='order_cancelled'"
            ).fetchone()["c"]
            self.assertEqual(post_ev_count, 1)

        # 7. Process Reopen & Confirmation Replay
        reopened_sessions = PersistentSessions(
            self.directory,
            data_mode="persistent-demo",
            api_infer=self.gateway,
        )
        reopened_web = PublicWeb(self.origin, reopened_sessions)

        def request_reopened(path, body, cookie, headers):
            req_body = json.dumps(body).encode("utf-8")
            env = {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": path,
                "QUERY_STRING": "",
                "HTTP_HOST": "retailops.example.com",
                "HTTP_ORIGIN": self.origin,
                "HTTP_COOKIE": cookie,
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": str(len(req_body)),
                "wsgi.input": io.BytesIO(req_body),
            }
            for k, v in headers.items():
                env["HTTP_" + k.upper().replace("-", "_")] = v
            status, payload, _, _ = reopened_web.route(env)
            return status, payload

        status_replay, conf_res2 = request_reopened(
            f"/api/cancellation-proposals/{proposal_id}/confirm",
            {"confirmed": True},
            cookie=self.cust1_cookie,
            headers={"Idempotency-Key": idemp_valid},
        )
        self.assertEqual(status_replay, 200)
        self.assertTrue(conf_res2.get("replayed", False))
        self.assertEqual(conf_res2["order"]["status"], "cancelled")
        self.assertEqual(conf_res2["order"]["version"], 2)

        # Verify mutation occurred exactly once in database
        bstore_reopened = reopened_sessions.business_store(self.tenant_id)
        with bstore_reopened.connection() as db:
            reopen_order = db.execute("SELECT * FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(reopen_order["status"], "cancelled")
            self.assertEqual(reopen_order["version"], 2)
            reopen_ev_count = db.execute(
                "SELECT count(*) as c FROM business_events WHERE order_id='O-90001' AND kind='order_cancelled'"
            ).fetchone()["c"]
            self.assertEqual(reopen_ev_count, 1)

        # 8. Build raw sanitized lifecycle report with actual run timestamp
        run_timestamp = datetime.now(timezone.utc).isoformat()

        raw_report = {
            "schema_version": "retailops_p5d_lifecycle_v1",
            "generated_at_utc": run_timestamp,
            "identity_tuple": {
                "tenant_id": self.tenant_id,
                "source_system": "pos_online",
                "external_customer_id": self.cust1_ext_id,
                "customer_id": self.cust1_id,
                "principal_id": self.cust1_pid,
                "order_id": "O-90001",
                "event_id": pending_event["event_id"],
            },
            "lifecycle_ids": {
                "conversation_id": cid,
                "proposal_id": proposal_id,
                "idempotency_key": idemp_valid,
            },
            "proposal_binding": {
                "complaint_action": proposal_action["action"],
                "complaint_order_id": proposal_action["order_id"],
                "complaint_order_version": expected_version,
                "complaint_reason": expected_reason,
                "persisted_proposal_id": proposal_id,
                "persisted_order_id": prop_res["order"]["id"],
                "persisted_order_version": prop_res["order"]["version"],
                "persisted_reason": prop_res["reason"],
                "bound_to_complaint": True,
            },
            "trace": {
                "supervisor_intent": chat_res["trace"].get("supervisor_intent"),
                "tools_called": [t.get("name") for t in chat_res.get("trace", {}).get("tools", [])],
                "proposal_action": proposal_action["action"],
            },
            "before_confirmation_state": {
                "order_status": "pending",
                "order_version": 1,
                "order_cancelled_events": 0,
            },
            "after_confirmation_state": {
                "order_status": "cancelled",
                "order_version": 2,
                "replayed": False,
                "order_cancelled_events": 1,
            },
            "after_reopen_replay_state": {
                "order_status": "cancelled",
                "order_version": 2,
                "replayed": True,
                "order_cancelled_events": 1,
            },
            "security_checks": {
                "wrong_customer_confirm_denied": True,
                "cross_tenant_confirm_denied": True,
                "pre_confirmation_mutation": False,
                "contains_real_secrets": False,
                "contains_real_pii": False,
            },
        }

        # 9. Serialize and save report and checksum manifest to disk
        evidence_dir = self.directory / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        report_file = evidence_dir / "P5_D_LIFECYCLE_REPORT.json"
        manifest_file = evidence_dir / "P5_D_LIFECYCLE_MANIFEST.json"

        report_bytes = json.dumps(raw_report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        expected_hash = hashlib.sha256(report_bytes).hexdigest()
        report_file.write_bytes(report_bytes)

        manifest_data = {
            "artifact": "P5_D_LIFECYCLE_REPORT.json",
            "algorithm": "sha256",
            "sha256": expected_hash,
            "byte_count": len(report_bytes),
            "generated_at_utc": run_timestamp,
            "verified": True,
        }
        manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        manifest_file.write_bytes(manifest_bytes)

        # Round-trip read equality against file and manifest
        read_bytes = report_file.read_bytes()
        read_hash = hashlib.sha256(read_bytes).hexdigest()
        self.assertEqual(read_hash, expected_hash)
        self.assertEqual(len(expected_hash), 64)
        self.assertEqual(read_bytes, report_bytes)

        read_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(read_manifest["sha256"], expected_hash)
        self.assertEqual(read_manifest["byte_count"], len(read_bytes))

        # 10. Negative tamper assertions
        def verify_report_integrity(data: bytes, manifest_entry: dict) -> bool:
            digest = hashlib.sha256(data).hexdigest()
            expected_checksum = manifest_entry.get("sha256", "")
            if not hmac.compare_digest(digest, expected_checksum):
                raise ValueError(f"Integrity check failed: checksum mismatch ({digest} != {expected_checksum})")
            if len(data) != manifest_entry.get("byte_count", -1):
                raise ValueError("Integrity check failed: byte count mismatch")
            return True

        self.assertTrue(verify_report_integrity(read_bytes, read_manifest))

        # Tamper test 1: Modify report state
        tampered_report = copy.deepcopy(raw_report)
        tampered_report["after_confirmation_state"]["order_version"] = 99
        tampered_bytes = json.dumps(tampered_report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        tampered_hash = hashlib.sha256(tampered_bytes).hexdigest()
        self.assertNotEqual(tampered_hash, expected_hash)
        with self.assertRaises(ValueError):
            verify_report_integrity(tampered_bytes, read_manifest)

        # Tamper test 2: Check manifest tampering detection
        tampered_manifest = copy.deepcopy(read_manifest)
        tampered_manifest["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            verify_report_integrity(read_bytes, tampered_manifest)

        # Tamper test 3: Check fixture tampering detection
        orig_fix_bytes = json.dumps(pending_event, sort_keys=True, separators=(",", ":")).encode("utf-8")
        orig_fix_hash = hashlib.sha256(orig_fix_bytes).hexdigest()
        tampered_fixture = copy.deepcopy(pending_event)
        tampered_fixture["total"] = 999999
        tampered_fix_bytes = json.dumps(tampered_fixture, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertNotEqual(hashlib.sha256(tampered_fix_bytes).hexdigest(), orig_fix_hash)

        # Privacy guard: confirm zero tokens or secrets
        report_text = json.dumps(raw_report)
        self.assertNotIn("client_secret", report_text)
        self.assertNotIn("access_token", report_text)
        self.assertNotIn("refresh_token", report_text)
        self.assertNotIn("@gmail.com", report_text)

    def test_16_defect_complaint_no_policy_evidence_preserves_safe_handoff_without_exchange_proposal(self):
        """P5-K7 regression: when a defect complaint query triggers search_knowledge but
        retrieval returns no policy evidence, preserve truthful safe staff handoff and
        do NOT create an unsupported exchange proposal or assert shop warranty.
        """
        self.test_01_same_identity_binding_import_and_session()

        status, conv, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        cid = conv["conversation_id"]

        chat_body = {
            "conversation_id": cid,
            "text": "Khiếu nại đơn O-90001 bị kẹt khóa và bung chỉ, kiểm tra chính sách đổi 1-1",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res, _ = self.request("/api/chat", chat_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)

        # 1. search_knowledge tool was executed
        tool_names = [t.get("name") for t in chat_res["trace"].get("tools", [])]
        self.assertIn("search_knowledge", tool_names)
        self.assertEqual(chat_res.get("sources", []), [])

        # 2. No unsupported exchange proposal produced
        self.assertIsNone(chat_res.get("action_proposal"))
        self.assertNotIn("dispute_agent:proposal_ready", chat_res["trace"].get("subagent_history", []))
        self.assertIn("dispute_agent:listening", chat_res["trace"].get("subagent_history", []))

        # 3. Truthful safe staff handoff preserved without asserting shop warranty or exchange policy
        self.assertIn("chuyên viên CSKH", chat_res["message"])
        self.assertNotIn("Đổi mới 1-1", chat_res["message"])
        self.assertNotIn("áp dụng chính sách bảo hành", chat_res["message"])

    def test_17_defect_complaint_stale_knowledge_no_warranty_days_safe_handoff(self):
        """P5-K7 continuation regression: stale conversation-level knowledge from an earlier
        unrelated query must NOT authorize a warranty claim or exchange proposal when catalog
        product has no structured warranty days.
        """
        self.test_01_same_identity_binding_import_and_session()

        # Set product P-601 warranty_days to NULL in tenant database
        bstore = self.sessions.business_store(self.tenant_id)
        with bstore.connection(write=True) as db:
            db.execute("UPDATE products SET warranty_days = NULL WHERE id = 'P-601'")

        status, conv, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        cid = conv["conversation_id"]

        chat_body = {
            "conversation_id": cid,
            "text": "Khiếu nại đơn O-90001 bị kẹt khóa và bung chỉ, shop xử lý giúp tôi",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res, _ = self.request("/api/chat", chat_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)

        # 1. No search_knowledge executed this turn
        tool_names = [t.get("name") for t in chat_res["trace"].get("tools", [])]
        self.assertNotIn("search_knowledge", tool_names)

        # 2. No exchange proposal created
        self.assertIsNone(chat_res.get("action_proposal"))
        self.assertNotIn("dispute_agent:proposal_ready", chat_res["trace"].get("subagent_history", []))
        self.assertIn("dispute_agent:listening", chat_res["trace"].get("subagent_history", []))

        # 3. Safe handoff to CSKH without asserting warranty or 1-1 exchange
        self.assertNotIn("Đổi mới 1-1", chat_res["message"])
        self.assertNotIn("theo quy định của shop", chat_res["message"])
        self.assertIn("chưa xác định được thời hạn bảo hành", chat_res["message"])
        self.assertIn("nhân viên CSKH", chat_res["message"])

    def test_18_defect_complaint_no_order_id_safe_handoff_without_exchange_promise(self):
        """P5-K7 continuation regression: when customer submits a defect complaint without an
        order ID and without policy evidence, do not promise free 1:1 exchange or assert shop
        warranty policy; ask for order ID safely.
        """
        self.test_01_same_identity_binding_import_and_session()

        status, conv, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        cid = conv["conversation_id"]

        chat_body = {
            "conversation_id": cid,
            "text": "Khiếu nại sản phẩm áo bị kẹt khóa và bung chỉ shop ơi",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res, _ = self.request("/api/chat", chat_body, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)

        # 1. No proposal created
        self.assertIsNone(chat_res.get("action_proposal"))
        self.assertNotIn("dispute_agent:proposal_ready", chat_res["trace"].get("subagent_history", []))
        self.assertIn("dispute_agent:listening", chat_res["trace"].get("subagent_history", []))

        # 2. Asks for order ID safely without promising free exchange terms or shop warranty
        self.assertNotIn("Đổi mới 1-1", chat_res["message"])
        self.assertNotIn("miễn phí 2 chiều", chat_res["message"])
        self.assertNotIn("áp dụng chính sách", chat_res["message"])
        self.assertIn("Mã đơn hàng", chat_res["message"])

    def test_19_defect_complaint_relevant_retrieval_enforces_order_ownership_and_positive_control(self):
        """P5-K7 one-pass E2E regression: when relevant defect/warranty policy evidence is retrieved
        via search_knowledge during /api/chat:
        1. Missing explicit order (O-999) executes get_order, returns safe order-not-found clarification,
           clears unreferenced sources, emits no remedy promise, creates no proposal, and mutates no DB rows.
        2. Foreign/unowned explicit order (Customer 2 naming Customer 1's order O-90001) executes get_order,
           returns safe order-not-found/not-owned clarification, clears unreferenced sources, emits no remedy promise,
           creates no proposal, and mutates no DB rows.
        3. Positive control: Customer 1 naming owned order O-90001 with relevant KB evidence executes
           search_knowledge + get_order + get_product, preserves valid [KB:...] citation in sources/message,
           creates exchange_1to1 proposal (pending_staff_approval), and leaves O-90001 unmutated pre-confirmation.
        """
        self.test_01_same_identity_binding_import_and_session()

        with self.sessions.resolve(self.cust1_cookie) as b1:
            b1.application.store.schema = "tenant_alpha"
        with self.sessions.resolve(self.cust2_cookie) as b2:
            b2.application.store.schema = "tenant_alpha"

        defect_policy_doc = {
            "chunk": "Chính sách bảo hành sản phẩm lỗi của shop: Sản phẩm bị kẹt khóa, bung chỉ hoặc lỗi đường may được bảo hành đổi mới 1-1 trong 30 ngày.",
            "source_key": "policies/warranty_defect.md",
            "title": "Chính sách bảo hành sản phẩm lỗi",
            "score": 0.92,
        }

        def fake_defect_repo_search(repo_self, query, limit=5):
            return [dict(defect_policy_doc)]

        bstore = self.sessions.business_store(self.tenant_id)

        # 1. Missing explicit order O-999 (Customer 1)
        status, conv_miss, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        body_miss = {
            "conversation_id": conv_miss["conversation_id"],
            "text": "Khiếu nại đơn O-999 bị kẹt khóa và bung chỉ, kiểm tra chính sách đổi 1-1",
            "request_id": str(uuid.uuid4()),
        }
        with patch.object(KnowledgeRepository, "search", fake_defect_repo_search):
            status, res_miss, _ = self.request("/api/chat", body_miss, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        miss_tools = [t.get("name") for t in res_miss["trace"].get("tools", [])]
        self.assertIn("search_knowledge", miss_tools)
        self.assertIn("get_order", miss_tools)
        self.assertIsNone(res_miss.get("action_proposal"))
        self.assertEqual(res_miss.get("sources", []), [])
        self.assertIn("không tìm thấy đơn hàng O-999", res_miss["message"])
        self.assertNotIn("Đổi mới 1-1", res_miss["message"])
        self.assertNotIn("áp dụng chính sách bảo hành", res_miss["message"])

        # 2. Foreign/unowned explicit order O-90001 queried by Customer 2
        status, conv_for, _ = self.request("/api/conversations", {}, cookie=self.cust2_cookie)
        self.assertEqual(status, 201)
        body_for = {
            "conversation_id": conv_for["conversation_id"],
            "text": "Khiếu nại đơn O-90001 bị kẹt khóa và bung chỉ, kiểm tra chính sách đổi 1-1",
            "request_id": str(uuid.uuid4()),
        }
        with patch.object(KnowledgeRepository, "search", fake_defect_repo_search):
            status, res_for, _ = self.request("/api/chat", body_for, cookie=self.cust2_cookie)
        self.assertEqual(status, 200)
        for_tools = [t.get("name") for t in res_for["trace"].get("tools", [])]
        self.assertIn("search_knowledge", for_tools)
        self.assertIn("get_order", for_tools)
        self.assertIsNone(res_for.get("action_proposal"))
        self.assertEqual(res_for.get("sources", []), [])
        self.assertIn("không tìm thấy đơn hàng O-90001", res_for["message"])
        self.assertIn("không thuộc tài khoản", res_for["message"])
        self.assertNotIn("Đổi mới 1-1", res_for["message"])
        self.assertNotIn("Áo sơ mi lụa", res_for["message"])

        # 3. Positive control: Owned order O-90001 queried by Customer 1 with relevant KB evidence
        status, conv_ok, _ = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        body_ok = {
            "conversation_id": conv_ok["conversation_id"],
            "text": "Khiếu nại đơn O-90001 bị kẹt khóa và bung chỉ, kiểm tra chính sách đổi 1-1",
            "request_id": str(uuid.uuid4()),
        }
        with patch.object(KnowledgeRepository, "search", fake_defect_repo_search):
            status, res_ok, _ = self.request("/api/chat", body_ok, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)
        ok_tools = [t.get("name") for t in res_ok["trace"].get("tools", [])]
        self.assertIn("search_knowledge", ok_tools)
        self.assertIn("get_order", ok_tools)
        self.assertIn("get_product", ok_tools)
        prop_ok = res_ok.get("action_proposal")
        self.assertIsNotNone(prop_ok)
        self.assertEqual(prop_ok["action"], "exchange_1to1")
        self.assertEqual(prop_ok["order_id"], "O-90001")
        self.assertEqual(prop_ok["status"], "pending_staff_approval")
        sources_ok = res_ok.get("sources", [])
        self.assertEqual(len(sources_ok), 1)
        self.assertEqual(sources_ok[0]["source_key"], "policies/warranty_defect.md")
        self.assertIn(f"[{sources_ok[0]['citation_id']}]", res_ok["message"])

        # Confirm zero pre-confirmation DB mutation on O-90001
        with bstore.connection() as db:
            ord_row = db.execute("SELECT status, version FROM orders WHERE id='O-90001'").fetchone()
            self.assertEqual(ord_row["status"], "pending")
            self.assertEqual(ord_row["version"], 1)


@unittest.skipUnless(DSN, "RAG pgvector integration requires a disposable PostgreSQL database with pgvector.")
class Phase5ComplaintPgvectorTests(unittest.TestCase):
    """Real disposable PostgreSQL + pgvector integration tests for P5-D complaint RAG (D-R1)."""

    @classmethod
    def setUpClass(cls):
        import psycopg
        if not psycopg.conninfo.conninfo_to_dict(DSN).get("dbname", "").startswith("retailops_test"):
            raise ValueError("Refusing non-test database.")

    def clear(self):
        from psycopg import sql
        from retailops.storage.postgres import IDENTITY_SCHEMA, transaction
        with transaction(DSN, write=True) as db:
            names = db.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname=? OR nspname ~ '^tenant_[a-f0-9]{32}$'",
                (IDENTITY_SCHEMA,),
            ).fetchall()
            for row in names:
                db.raw.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(row["nspname"])))

    def setUp(self):
        from retailops.identity.postgres import PostgresSessions
        from retailops.knowledge.chunking import SourceDocument
        from retailops.knowledge.repository import KnowledgeRepository
        from retailops.storage.pg_repositories import PostgresIdentityStore
        from retailops.sales.adapter import SalesImportAdapter
        from retailops.sales.simulator import DEFAULT_DEV_SECRET, SalesSimulator

        self.clear()
        self.addCleanup(self.clear)

        PostgresIdentityStore(DSN, create=True)
        self.gateway = MockDisputeChatGateway()
        self.sessions = PostgresSessions(DSN, api_infer=self.gateway)

        # 1. Provision two distinct tenants
        self.tenant_a = "tenant-p5d-pg-a"
        self.tenant_b = "tenant-p5d-pg-b"
        self.sessions.provision_tenant(self.tenant_a, "PG Shop A", seed_demo=True)
        self.sessions.provision_tenant(self.tenant_b, "PG Shop B", seed_demo=True)

        self.bstore_a = self.sessions.business_store(self.tenant_a)
        self.bstore_b = self.sessions.business_store(self.tenant_b)

        # 2. Ingest distinct policies into real pgvector tables
        self.policy_a_marker = "POLICY_ALPHA_7DAYS_EXCLUSIVE"
        self.policy_b_marker = "POLICY_BETA_SECRET_999DAYS_RESTRICTED"

        doc_a = SourceDocument(
            source_key="policies/returns_alpha.md",
            title="Quy định đổi trả Alpha",
            source_uri="repo://policies/returns_alpha.md",
            content=f"Chính sách đổi trả shop Alpha: Đơn hàng hợp lệ được đổi trả trong 7 ngày nếu còn nguyên tem mác. Mã quy định: {self.policy_a_marker}."
        )
        doc_b = SourceDocument(
            source_key="policies/returns_beta.md",
            title="Quy định riêng Beta",
            source_uri="repo://policies/returns_beta.md",
            content=f"Chính sách bảo mật shop Beta: Hàng đổi trả trong 999 ngày không giới hạn. Mã quy định: {self.policy_b_marker}."
        )

        KnowledgeRepository(self.bstore_a).ingest([doc_a])
        KnowledgeRepository(self.bstore_b).ingest([doc_b])

        # 3. Public Web layer
        self.origin = "https://retailops.example.com"
        self.web = PublicWeb(self.origin, self.sessions)

        # 4. Set up Customer 1 in Tenant A
        self.cust1_ext_id = "ext_pos_p5d_pga_001"
        self.cust1_cookie_secret = self.sessions.login_google(
            email="buyer.pga@synthetic.retailops",
            name="Alpha PG Buyer",
            role="customer",
            sub="google-sub-pga-001",
            issuer="https://accounts.google.com",
            email_verified=True,
            tenant_id=self.tenant_a,
        )
        self.cust1_cookie = f"{self.sessions.cookie_name}={self.cust1_cookie_secret}"
        resolved1 = self.sessions.control.resolve(self.sessions.cookie_id(self.cust1_cookie))
        self.cust1_id = resolved1["customer_id"]

        # Link external customer and import order O-90001 in Tenant A
        adapter_a = SalesImportAdapter(self.sessions, default_secret=DEFAULT_DEV_SECRET)
        adapter_a.link_external_customer(
            tenant_id=self.tenant_a,
            source_system="pos_online",
            external_customer_id=self.cust1_ext_id,
            customer_id=self.cust1_id,
            customer_name="Alpha PG Buyer",
        )
        sim_a = SalesSimulator(tenant_id=self.tenant_a, secret_key=DEFAULT_DEV_SECRET)
        evt_a = sim_a.create_order_event(
            source_system="pos_online",
            event_id="evt_p5d_pga_001",
            external_customer_id=self.cust1_ext_id,
            order_id="O-90001",
            status="pending",
            items=[{"product_id": "P-601", "product_title": "Áo sơ mi lụa công sở", "quantity": 1, "unit_price": 450000}],
            total=450000,
        )
        adapter_a.ingest_event(evt_a)

        # 5. Set up Customer 3 in Tenant B
        self.cust3_cookie_secret = self.sessions.login_google(
            email="buyer.pgb@synthetic.retailops",
            name="Beta PG Buyer",
            role="customer",
            sub="google-sub-pgb-001",
            issuer="https://accounts.google.com",
            email_verified=True,
            tenant_id=self.tenant_b,
        )
        self.cust3_cookie = f"{self.sessions.cookie_name}={self.cust3_cookie_secret}"

    def request(self, path, body=None, cookie="", method=None):
        req_method = method or ("GET" if body is None else "POST")
        raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
        env = {
            "REQUEST_METHOD": req_method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "HTTP_HOST": "retailops.example.com",
            "HTTP_ORIGIN": self.origin,
            "HTTP_COOKIE": cookie,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(raw_body)),
            "wsgi.input": io.BytesIO(raw_body),
        }
        status, data, _, _ = self.web.route(env)
        return status, data

    def test_pgvector_complaint_tenant_policy_isolation(self):
        """P5-K7 (D-R1): Real PostgreSQL + pgvector complaint tenant policy isolation assertions:
        1. Ingest distinct tenant documents into real pgvector tables.
        2. Direct KnowledgeRepository search queries pgvector table knowledge_chunks with vector cosine operator.
        3. Real complaint path via /api/chat calls KnowledgeTool.search backed by pgvector.
        4. Tenant A receives exact source citation and Tenant A marker, zero leak of Tenant B marker.
        5. Tenant B receives Tenant B marker, zero leak of Tenant A marker.
        6. Safe fallback for tenant with unpopulated knowledge: returns safe response without hallucination.
        """
        from retailops.knowledge.repository import KnowledgeRepository

        # 1. Direct pgvector search assertions on disposable database
        res_a = KnowledgeRepository(self.bstore_a).search("đổi trả hàng")
        self.assertGreaterEqual(len(res_a), 1)
        self.assertEqual(res_a[0]["source_key"], "policies/returns_alpha.md")
        self.assertIn(self.policy_a_marker, res_a[0]["chunk"])
        self.assertNotIn(self.policy_b_marker, json.dumps(res_a))

        res_b = KnowledgeRepository(self.bstore_b).search("đổi trả hàng")
        self.assertGreaterEqual(len(res_b), 1)
        self.assertEqual(res_b[0]["source_key"], "policies/returns_beta.md")
        self.assertIn(self.policy_b_marker, res_b[0]["chunk"])
        self.assertNotIn(self.policy_a_marker, json.dumps(res_b))

        # 2. Complaint path via /api/chat for Customer 1 (Tenant A)
        status, conv1 = self.request("/api/conversations", {}, cookie=self.cust1_cookie)
        self.assertEqual(status, 201)
        cid1 = conv1["conversation_id"]

        chat_body1 = {
            "conversation_id": cid1,
            "text": "Khiếu nại đổi trả đơn hàng O-90001 theo chính sách của shop",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res1 = self.request("/api/chat", chat_body1, cookie=self.cust1_cookie)
        self.assertEqual(status, 200)

        # Assert KnowledgeTool was invoked with real pgvector retrieval
        tools1 = [t for t in chat_res1.get("trace", {}).get("tools", []) if t.get("name") == "search_knowledge"]
        self.assertGreaterEqual(len(tools1), 1)
        self.assertEqual(tools1[0]["status"], "ok")

        # Assert Tenant A sources and citations
        sources1 = chat_res1.get("sources", [])
        self.assertGreaterEqual(len(sources1), 1)
        self.assertEqual(sources1[0]["source_key"], "policies/returns_alpha.md")
        self.assertTrue(sources1[0]["citation_id"].startswith("KB:"))
        self.assertIn(self.policy_a_marker, chat_res1["message"])
        self.assertNotIn(self.policy_b_marker, chat_res1["message"])
        self.assertNotIn(self.policy_b_marker, json.dumps(sources1))

        # 3. Complaint path via /api/chat for Customer 3 (Tenant B)
        status, conv3 = self.request("/api/conversations", {}, cookie=self.cust3_cookie)
        self.assertEqual(status, 201)
        cid3 = conv3["conversation_id"]

        chat_body3 = {
            "conversation_id": cid3,
            "text": "Khiếu nại hoàn tiền đổi trả theo chính sách của shop",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res3 = self.request("/api/chat", chat_body3, cookie=self.cust3_cookie)
        self.assertEqual(status, 200)

        # Assert Tenant B sources and citations
        sources3 = chat_res3.get("sources", [])
        self.assertGreaterEqual(len(sources3), 1)
        self.assertEqual(sources3[0]["source_key"], "policies/returns_beta.md")
        self.assertIn(self.policy_b_marker, chat_res3["message"])
        self.assertNotIn(self.policy_a_marker, chat_res3["message"])
        self.assertNotIn(self.policy_a_marker, json.dumps(sources3))

        # 4. Safe fallback: unpopulated tenant knowledge base
        tenant_c = "tenant-p5d-pg-empty"
        self.sessions.provision_tenant(tenant_c, "Empty Shop", seed_demo=True)
        c_cookie = f"{self.sessions.cookie_name}=" + self.sessions.login_google(
            email="buyer.empty@synthetic.retailops",
            name="Empty Buyer",
            role="customer",
            sub="sub-empty-001",
            issuer="https://accounts.google.com",
            email_verified=True,
            tenant_id=tenant_c,
        )
        status, conv_empty = self.request("/api/conversations", {}, cookie=c_cookie)
        chat_body_empty = {
            "conversation_id": conv_empty["conversation_id"],
            "text": "Khiếu nại đổi trả theo chính sách của shop",
            "request_id": str(uuid.uuid4()),
        }
        status, chat_res_empty = self.request("/api/chat", chat_body_empty, cookie=c_cookie)
        self.assertEqual(status, 200)
        empty_tools = [t for t in chat_res_empty.get("trace", {}).get("tools", []) if t.get("name") == "search_knowledge"]
        self.assertGreaterEqual(len(empty_tools), 1)
        self.assertEqual(empty_tools[0]["status"], "ok")
        self.assertEqual(chat_res_empty.get("sources", []), [])
        self.assertNotIn("[KB:", chat_res_empty["message"])
        self.assertNotIn(self.policy_a_marker, chat_res_empty["message"])
        self.assertNotIn(self.policy_b_marker, chat_res_empty["message"])


if __name__ == "__main__":
    unittest.main()
