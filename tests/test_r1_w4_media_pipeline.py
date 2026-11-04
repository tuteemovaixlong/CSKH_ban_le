"""Phase R1 W4 media pipeline tests: Item 2 (W4-D6) chat attachment sanitization and zero-base64 history."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import secrets
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.core import ROOT
from retailops.http.public import PublicWeb
from retailops.identity.persistent import PersistentSessions
from retailops_providers import OpenRouterAgent

API_KEY = "rk_live_secret_w4_media_" + "a" * 24
TUNNEL_TOKEN = "tun_secret_w4_media_" + "b" * 28
MODEL_ID = "google/gemma-4-26b-a4b-it"


def _make_exif_jpeg_bytes(size=(64, 48), color=(210, 60, 50)) -> bytes:
    img = Image.new("RGB", size, color=color)
    exif = img.getexif()
    exif[0x010F] = "ConfidentialPhoneMaker"
    exif[0x0110] = "SecretDeviceX99"
    exif[0x9286] = "GPS:10.7769,106.7009"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, exif=exif.tobytes())
    return buf.getvalue()


def _provider_reply(content="Đã kiểm tra thông tin cho bạn.", calls=()):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [
            {
                "id": f"call_{idx}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
            for idx, (name, args) in enumerate(calls)
        ]
    return {
        "model": MODEL_ID,
        "choices": [{"message": msg, "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 110, "completion_tokens": 25},
    }


class PhaseR1W4Item2NoRawHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_root = Path(self.temp.name) / "data_root"
        self.env = patch.dict(
            os.environ,
            {
                "RETAILOPS_OUTPUT": str(self.data_root),
                "RETAILOPS_API_ENDPOINT": "https://retailops-w4.ngrok.app/v1/chat/completions",
                "RETAILOPS_API_KEY": API_KEY,
                "RETAILOPS_API_TUNNEL_TOKEN": TUNNEL_TOKEN,
                "RETAILOPS_API_VISION": "on",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_item2_chat_image_strips_exif_stores_outside_web_root_and_keeps_db_checkpoints_logs_free_of_base64(self):
        store = BusinessStore(Path(self.temp.name) / "business.sqlite3", create=True)
        store.seed()
        adapter = OpenRouterAgent(API_KEY, MODEL_ID, tunnel_token=TUNNEL_TOKEN, vision=True)
        app = Application(store, {}, api_infer=adapter, role="customer")
        cid = app.new_conversation("C-001", {"provider_id": "api"})["conversation_id"]

        raw_exif_jpg = _make_exif_jpeg_bytes((80, 60), color=(200, 30, 40))
        self.assertIn(b"ConfidentialPhoneMaker", raw_exif_jpg)
        raw_b64 = base64.b64encode(raw_exif_jpg).decode("ascii")

        log_records: list[str] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record):
                log_records.append(self.format(record))

        handler = _CaptureHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        self.addCleanup(root_logger.removeHandler, handler)

        responses = [
            _provider_reply("", calls=[("list_orders", {})]),
            _provider_reply("Mình đã kiểm tra đơn hàng và ảnh sản phẩm bạn gửi."),
        ]
        with patch.object(OpenRouterAgent, "request", side_effect=responses) as mock_req:
            res = app.chat(
                "C-001",
                {
                    "conversation_id": cid,
                    "text": "Kiểm tra giúp mình sản phẩm trong ảnh thuộc đơn nào",
                    "request_id": "req_w4_item2_" + uuid.uuid4().hex[:16],
                    "attachment": {
                        "type": "image",
                        "name": "../../secret_dir/camera_photo.jpg",
                        "mime_type": "image/jpeg",
                        "data": f"data:image/jpeg;base64,{raw_b64}",
                    },
                },
            )

        self.assertEqual(res["trace"]["model_calls"], 2)
        # Outbound model payload received sanitized EXIF-free image via image_url
        sent_payload = mock_req.call_args_list[0].args[0]
        user_msg = next(m for m in sent_payload["messages"] if m["role"] == "user")
        img_part = next(p for p in user_msg["content"] if p.get("type") == "image_url")
        sent_b64 = img_part["image_url"]["url"].split(",", 1)[1]
        sent_bytes = base64.b64decode(sent_b64)
        self.assertNotIn(b"ConfidentialPhoneMaker", sent_bytes)
        self.assertNotIn(b"SecretDeviceX99", sent_bytes)

        # Verify DB tables: agent_turns, graph_checkpoints, graph_writes, graph_runs, business_events have ZERO base64
        with store.connection() as db:
            turn_rows = db.execute("SELECT messages, result FROM agent_turns WHERE conversation_id = ?", (cid,)).fetchall()
            self.assertEqual(len(turn_rows), 1)
            messages_raw = turn_rows[0]["messages"]
            result_raw = turn_rows[0]["result"]
            self.assertNotIn("data:image/", messages_raw)
            self.assertNotIn(raw_b64[:48], messages_raw)
            self.assertNotIn(sent_b64[:48], messages_raw)
            self.assertNotIn("data:image/", result_raw)

            parsed_msgs = json.loads(messages_raw)
            stored_att = parsed_msgs[0]["attachment"]
            self.assertNotIn("data", stored_att)
            self.assertTrue(stored_att["evidence_id"].startswith("ev_"))
            self.assertEqual(stored_att["type"], "image")
            self.assertEqual(stored_att["mime_type"], "image/jpeg")
            self.assertEqual(stored_att["name"], "camera_photo.jpg")
            self.assertEqual(len(stored_att["sha256"]), 64)

            for table_name in ("graph_checkpoints", "graph_writes", "graph_runs", "business_events"):
                rows = db.execute(f'SELECT * FROM "{table_name}"').fetchall()
                serialized = json.dumps([dict(r) for r in rows], default=str)
                self.assertNotIn("data:image/", serialized, f"{table_name} leaked data URL")
                self.assertNotIn(raw_b64[:48], serialized, f"{table_name} leaked raw base64")
                self.assertNotIn(sent_b64[:48], serialized, f"{table_name} leaked re-encoded base64")

            ev_row = db.execute(
                "SELECT * FROM order_action_evidence WHERE evidence_id = ?",
                (stored_att["evidence_id"],),
            ).fetchone()
            self.assertIsNotNone(ev_row)
            self.assertIsNone(ev_row["request_id"])
            self.assertEqual(ev_row["sha256"], hashlib.sha256(sent_bytes).hexdigest())

        stored_file = store._resolve_evidence_file_path(ev_row["storage_relpath"])
        self.assertTrue(stored_file.is_file())
        self.assertFalse(stored_file.is_relative_to((ROOT / "web").resolve()))
        disk_bytes = stored_file.read_bytes()
        self.assertNotIn(b"ConfidentialPhoneMaker", disk_bytes)
        with Image.open(io.BytesIO(disk_bytes)) as reloaded:
            self.assertEqual(len(reloaded.getexif()), 0)

        joined_logs = "\n".join(log_records)
        self.assertNotIn("data:image/", joined_logs)
        self.assertNotIn(raw_b64[:48], joined_logs)

    def test_item2_history_hydrates_only_most_recent_image_when_vision_on_and_omits_pixels_when_off(self):
        store = BusinessStore(Path(self.temp.name) / "business_hist.sqlite3", create=True)
        store.seed()
        vision_adapter = OpenRouterAgent(API_KEY, MODEL_ID, tunnel_token=TUNNEL_TOKEN, vision=True)
        app = Application(store, {}, api_infer=vision_adapter, role="customer")
        cid = app.new_conversation("C-001", {"provider_id": "api"})["conversation_id"]

        img1_bytes = _make_exif_jpeg_bytes((40, 40), color=(220, 20, 20))
        img2_bytes = _make_exif_jpeg_bytes((40, 40), color=(20, 20, 220))

        # Turn 1: upload image 1
        with patch.object(OpenRouterAgent, "request", return_value=_provider_reply("Đã thấy ảnh 1.")):
            app.chat(
                "C-001",
                {
                    "conversation_id": cid,
                    "text": "Xem ảnh áo đỏ này",
                    "request_id": "req_hist_1_" + uuid.uuid4().hex[:16],
                    "attachment": {
                        "type": "image",
                        "name": "red.jpg",
                        "data": base64.b64encode(img1_bytes).decode("ascii"),
                    },
                },
            )

        # store.history() itself carries metadata only (no base64)
        hist_after_1 = store.history("C-001", cid)
        self.assertNotIn("data", hist_after_1[0]["attachment"])
        ev1_sha = hist_after_1[0]["attachment"]["sha256"]

        # Turn 2: follow-up text without attachment -> hydrates image 1 when vision=True
        with patch.object(OpenRouterAgent, "request", return_value=_provider_reply("Ảnh 1 là mẫu áo đỏ.")) as req2:
            app.chat(
                "C-001",
                {
                    "conversation_id": cid,
                    "text": "Mẫu trong ảnh vừa gửi tên gì?",
                    "request_id": "req_hist_2_" + uuid.uuid4().hex[:16],
                },
            )
        msgs_t2 = req2.call_args.args[0]["messages"]
        img_urls_t2 = [
            part["image_url"]["url"]
            for m in msgs_t2
            if isinstance(m.get("content"), list)
            for part in m["content"]
            if part.get("type") == "image_url"
        ]
        self.assertEqual(len(img_urls_t2), 1)
        self.assertEqual(hashlib.sha256(base64.b64decode(img_urls_t2[0].split(",", 1)[1])).hexdigest(), ev1_sha)

        # Turn 3: upload image 2 -> ONLY image 2 is hydrated (image 1 is NOT re-sent as pixels)
        with patch.object(OpenRouterAgent, "request", return_value=_provider_reply("Đã thấy ảnh 2.")) as req3:
            app.chat(
                "C-001",
                {
                    "conversation_id": cid,
                    "text": "Còn mẫu xanh này thì sao?",
                    "request_id": "req_hist_3_" + uuid.uuid4().hex[:16],
                    "attachment": {
                        "type": "image",
                        "name": "blue.jpg",
                        "data": base64.b64encode(img2_bytes).decode("ascii"),
                    },
                },
            )
        msgs_t3 = req3.call_args.args[0]["messages"]
        img_urls_t3 = [
            part["image_url"]["url"]
            for m in msgs_t3
            if isinstance(m.get("content"), list)
            for part in m["content"]
            if part.get("type") == "image_url"
        ]
        self.assertEqual(len(img_urls_t3), 1)
        ev2_sha = hashlib.sha256(base64.b64decode(img_urls_t3[0].split(",", 1)[1])).hexdigest()
        self.assertNotEqual(ev2_sha, ev1_sha)

        # Follow-up when vision=False -> zero image_url blocks sent
        text_only_adapter = OpenRouterAgent(API_KEY, MODEL_ID, tunnel_token=TUNNEL_TOKEN, vision=False)
        app_text_only = Application(store, {}, api_infer=text_only_adapter, role="customer")
        with patch.object(OpenRouterAgent, "request", return_value=_provider_reply("Trả lời theo văn bản.")) as req4:
            app_text_only.chat(
                "C-001",
                {
                    "conversation_id": cid,
                    "text": "Cho mình hỏi thêm về đơn hàng",
                    "request_id": "req_hist_4_" + uuid.uuid4().hex[:16],
                },
            )
        msgs_t4 = req4.call_args.args[0]["messages"]
        for m in msgs_t4:
            self.assertNotIsInstance(m.get("content"), list)

    def test_item2_chat_evidence_download_enforces_owner_staff_and_tenant_isolation(self):
        sessions = PersistentSessions(self.data_root / "persistent")
        store_a = sessions.provision_tenant("shop-a", "Shop A", seed_demo=True)
        store_a.add_customer("C-STAFFA", "Staff A")
        store_b = sessions.provision_tenant("shop-b", "Shop B", seed_demo=True)
        store_b.add_customer("C-STAFFB", "Staff B")

        def issue_cookie(tid: str, pid: str, name: str, cust_id: str, role: str) -> str:
            mid = sessions.create_member(tid, pid, name, cust_id, role)
            tok = secrets.token_urlsafe(32)
            sessions.control.register_credential(mid, tok)
            return f"{sessions.cookie_name}={sessions.login(tok)}"

        c1_cookie = issue_cookie("shop-a", "p-c1-a", "Cust 1", "C-001", "customer")
        c2_cookie = issue_cookie("shop-a", "p-c2-a", "Cust 2", "C-002", "customer")
        sa_cookie = issue_cookie("shop-a", "p-sa-a", "Staff A", "C-STAFFA", "staff")
        sb_cookie = issue_cookie("shop-b", "p-sb-b", "Staff B", "C-STAFFB", "staff")

        web = PublicWeb("https://retailops.example.com", sessions, start_timer_worker=False)

        def call(method: str, path: str, cookie: str, body: dict | None = None):
            raw = json.dumps(body).encode("utf-8") if body is not None else b""
            env = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "HTTP_HOST": "retailops.example.com",
                "QUERY_STRING": "",
                "HTTP_COOKIE": cookie,
                "CONTENT_LENGTH": str(len(raw)),
                "CONTENT_TYPE": "application/json",
                "wsgi.input": io.BytesIO(raw),
            }
            if method != "GET":
                env["HTTP_ORIGIN"] = "https://retailops.example.com"
            captured = {}

            def start_response(status, headers):
                captured["status"] = int(status.split()[0])
                captured["headers"] = dict(headers)

            chunks = b"".join(web(env, start_response))
            return captured["status"], captured["headers"], chunks

        st, _, raw_conv = call("POST", "/api/conversations", c1_cookie, {"provider_id": "custom"})
        self.assertEqual(st, 201)
        cid = json.loads(raw_conv)["conversation_id"]

        # Store chat attachment via customer_message (handoff open -> staff in shop-a can view)
        jpg = _make_exif_jpeg_bytes((32, 32), color=(40, 180, 90))
        st_msg, _, _ = call(
            "POST",
            "/api/staff/customer-message",
            c1_cookie,
            {
                "conversation_id": cid,
                "message": "Nhờ nhân viên kiểm tra ảnh sản phẩm lỗi",
                "attachment": {
                    "type": "image",
                    "name": "defect.jpg",
                    "data": "data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii"),
                },
            },
        )
        self.assertEqual(st_msg, 200)

        with store_a.connection() as db:
            ev = db.execute("SELECT evidence_id FROM order_action_evidence WHERE conversation_id = ?", (cid,)).fetchone()
            self.assertIsNotNone(ev)
            ev_id = ev["evidence_id"]

        ev_path = f"/api/conversations/{cid}/evidence/{ev_id}"
        # Owner customer -> 200
        st_own, hdr_own, body_own = call("GET", ev_path, c1_cookie)
        self.assertEqual(st_own, 200)
        self.assertEqual(hdr_own["Content-Type"], "image/jpeg")
        self.assertGreater(len(body_own), 50)

        # Other customer in same tenant -> 404
        st_c2, _, _ = call("GET", ev_path, c2_cookie)
        self.assertEqual(st_c2, 404)

        # Staff in same tenant (case has pending handoff) -> 200
        st_sa, _, _ = call("GET", ev_path, sa_cookie)
        self.assertEqual(st_sa, 200)

        # Staff in other tenant -> 404
        st_sb, _, _ = call("GET", ev_path, sb_cookie)
        self.assertEqual(st_sb, 404)


class PhaseR1W4Item3ImageProjectionAndHumanFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_root = Path(self.temp.name) / "data_root"
        self.env = patch.dict(
            os.environ,
            {
                "RETAILOPS_OUTPUT": str(self.data_root),
                "RETAILOPS_API_ENDPOINT": "https://retailops-w4.ngrok.app/v1/chat/completions",
                "RETAILOPS_API_KEY": API_KEY,
                "RETAILOPS_API_TUNNEL_TOKEN": TUNNEL_TOKEN,
                "RETAILOPS_API_VISION": "on",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_item3_projection_caps_3_images_resizes_to_1024_strips_exif_and_excludes_pii(self):
        store = BusinessStore(Path(self.temp.name) / "business_proj.sqlite3", create=True)
        store.seed()
        with store.connection(write=True) as db:
            db.execute("UPDATE customers SET name = ? WHERE id = 'C-001'", ("Trần Thị Bí Mật 0909123456 123 Nguyễn Huệ Q1",))

        adapter = OpenRouterAgent(API_KEY, MODEL_ID, tunnel_token=TUNNEL_TOKEN, vision=True)
        app = Application(store, {}, api_infer=adapter, role="customer")
        cid = app.new_conversation("C-001", {"provider_id": "api"})["conversation_id"]
        app.focus("C-001", cid, {"order_id": "O-101"})

        # Upload 2400x1600 JPEG with EXIF tags
        huge_exif_jpg = _make_exif_jpeg_bytes((2400, 1600), color=(35, 110, 210))
        responses = [
            _provider_reply("", calls=[("get_order", {"order_id": "O-101"})]),
            _provider_reply("Đơn O-101 đang ở trạng thái chờ xử lý."),
        ]
        with patch.object(OpenRouterAgent, "request", side_effect=responses) as mock_req:
            res = app.chat(
                "C-001",
                {
                    "conversation_id": cid,
                    "text": "Xem ảnh này với đơn O-101 giúp mình",
                    "request_id": "req_proj_" + uuid.uuid4().hex[:16],
                    "attachment": {
                        "type": "image",
                        "name": "highres_photo.jpg",
                        "data": base64.b64encode(huge_exif_jpg).decode("ascii"),
                    },
                },
            )
        self.assertEqual(res["trace"]["model_calls"], 2)

        # Full-res sanitized evidence remains 2400x1600 on disk, while model receives <=1024 px EXIF-free projection
        with store.connection() as db:
            ev_row = db.execute("SELECT width, height FROM order_action_evidence WHERE conversation_id = ?", (cid,)).fetchone()
            self.assertEqual((ev_row["width"], ev_row["height"]), (2400, 1600))

        step2_payload = mock_req.call_args_list[1].args[0]
        payload_json = json.dumps(step2_payload, ensure_ascii=False)
        self.assertNotIn("Trần Thị Bí Mật", payload_json)
        self.assertNotIn("0909123456", payload_json)
        self.assertNotIn("123 Nguyễn Huệ", payload_json)
        self.assertNotIn("C-001", payload_json)

        user_msg = next(m for m in step2_payload["messages"] if m["role"] == "user")
        img_parts = [p for p in user_msg["content"] if p.get("type") == "image_url"]
        self.assertEqual(len(img_parts), 1)
        proj_bytes = base64.b64decode(img_parts[0]["image_url"]["url"].split(",", 1)[1])
        self.assertNotIn(b"ConfidentialPhoneMaker", proj_bytes)
        with Image.open(io.BytesIO(proj_bytes)) as proj_img:
            self.assertLessEqual(max(proj_img.size), 1024)
            self.assertEqual(proj_img.size, (1024, 683))
            self.assertEqual(len(proj_img.getexif()), 0)

        # Verify OpenRouterAgent.translate() strictly caps total images per request to <=3
        small_b64 = base64.b64encode(_make_exif_jpeg_bytes((32, 32))).decode("ascii")
        multi_msgs = [
            {
                "role": "user",
                "content": "Lượt cũ 2 ảnh",
                "attachment": {"type": "image", "name": "old.jpg", "images": [small_b64, small_b64]},
            },
            {"role": "assistant", "content": "Đã xem."},
            {
                "role": "user",
                "content": "Lượt mới 4 ảnh",
                "attachment": {"type": "image", "name": "new.jpg", "images": [small_b64, small_b64, small_b64, small_b64]},
            },
        ]
        translated = adapter.translate(multi_msgs)
        all_emitted_imgs = [
            part
            for m in translated
            if isinstance(m.get("content"), list)
            for part in m["content"]
            if part.get("type") == "image_url"
        ]
        self.assertEqual(len(all_emitted_imgs), 3)

    def test_item3_vision_off_or_endpoint_error_falls_back_to_human_without_5xx_and_order_actions_stay_model_independent(self):
        import urllib.error

        vision_adapter = OpenRouterAgent(API_KEY, MODEL_ID, tunnel_token=TUNNEL_TOKEN, vision=True)
        sessions = PersistentSessions(self.data_root / "persistent_fallback", api_infer=vision_adapter)
        store = sessions.provision_tenant("shop-fb", "Shop Fallback", seed_demo=True)
        store.add_customer("C-STAFFFB", "Staff Fallback")
        with store.connection(write=True) as db:
            db.execute("UPDATE orders SET status = 'delivered', delivered_at = ? WHERE id = 'O-102'", (1_785_000_000.0,))

        def issue_cookie(pid: str, name: str, cust_id: str, role: str) -> str:
            mid = sessions.create_member("shop-fb", pid, name, cust_id, role)
            tok = secrets.token_urlsafe(32)
            sessions.control.register_credential(mid, tok)
            return f"{sessions.cookie_name}={sessions.login(tok)}"

        c1_cookie = issue_cookie("p-c1-fb", "Cust 1", "C-001", "customer")
        staff_cookie = issue_cookie("p-s1-fb", "Staff 1", "C-STAFFFB", "staff")

        # 1. Vision OFF -> returns 200 with "không phân tích được ảnh, chuyển nhân viên" and opens human handoff
        text_only_adapter = OpenRouterAgent(API_KEY, MODEL_ID, tunnel_token=TUNNEL_TOKEN, vision=False)
        app_off = Application(store, {}, api_infer=text_only_adapter, role="customer")
        cid1 = app_off.new_conversation("C-001", {"provider_id": "api"})["conversation_id"]
        jpg_b64 = base64.b64encode(_make_exif_jpeg_bytes((48, 48))).decode("ascii")

        res_off = app_off.chat(
            "C-001",
            {
                "conversation_id": cid1,
                "text": "Kiểm tra ảnh lỗi này cho đơn O-102",
                "request_id": "req_fb_off_" + uuid.uuid4().hex[:16],
                "attachment": {"type": "image", "name": "fault.jpg", "data": jpg_b64},
            },
        )
        self.assertIn("không phân tích được ảnh, chuyển nhân viên", res_off["message"])
        self.assertEqual(res_off["human_support"]["status"], "escalated_to_human")
        self.assertEqual(res_off["case"]["status"], "waiting")

        # 2. Vision ON, but upstream endpoint fails with HTTP 503 -> returns 200 human fallback (no 5xx!) and case continues with staff
        web = PublicWeb("https://retailops.example.com", sessions, start_timer_worker=False)

        def http_json(method: str, path: str, cookie: str, body: dict | None = None):
            raw = json.dumps(body).encode("utf-8") if body is not None else b""
            env = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "HTTP_HOST": "retailops.example.com",
                "QUERY_STRING": "",
                "HTTP_COOKIE": cookie,
                "CONTENT_LENGTH": str(len(raw)),
                "CONTENT_TYPE": "application/json",
                "wsgi.input": io.BytesIO(raw),
            }
            if method != "GET":
                env["HTTP_ORIGIN"] = "https://retailops.example.com"
            captured = {}

            def start_response(status, headers):
                captured["status"] = int(status.split()[0])

            out = b"".join(web(env, start_response))
            return captured["status"], json.loads(out)

        st_c, conv_data = http_json("POST", "/api/conversations", c1_cookie, {"provider_id": "api"})
        self.assertEqual(st_c, 201)
        cid2 = conv_data["conversation_id"]

        err_503 = urllib.error.HTTPError(
            "https://retailops-w4.ngrok.app/v1/chat/completions",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"error":"GPU worker restarting"}'),
        )
        with patch("urllib.request.OpenerDirector.open", side_effect=err_503):
            st_chat, chat_res = http_json(
                "POST",
                "/api/chat",
                c1_cookie,
                {
                    "conversation_id": cid2,
                    "text": "Nhờ xem giúp vết rách trong ảnh",
                    "request_id": "req_fb_503_" + uuid.uuid4().hex[:16],
                    "attachment": {"type": "image", "name": "tear.jpg", "data": jpg_b64},
                },
            )
        self.assertEqual(st_chat, 200)
        self.assertIn("không phân tích được ảnh, chuyển nhân viên", chat_res["message"])
        self.assertEqual(chat_res["human_support"]["status"], "escalated_to_human")
        self.assertEqual(chat_res["trace"]["model_errors"][0]["http_status"], 503)

        # Staff claims the escalated case and replies -> case continues smoothly with human!
        case_id_2 = chat_res["case"]["case_id"]
        st_claim, _ = http_json("POST", f"/api/staff/cases/{case_id_2}/claim", staff_cookie, {})
        self.assertEqual(st_claim, 200)
        st_rep, _ = http_json(
            "POST",
            "/api/staff/reply",
            staff_cookie,
            {"conversation_id": cid2, "message": "Chào bạn, mình đã xem ảnh vết rách và hỗ trợ đổi hàng ngay nhé."},
        )
        self.assertEqual(st_rep, 200)

        # 3. Order-action submission never calls or depends on any model (all gateways offline)
        sessions_no_model = PersistentSessions(self.data_root / "persistent_fallback", infer=None, api_infer=None, maintenance=False)
        web_no_model = PublicWeb("https://retailops.example.com", sessions_no_model, start_timer_worker=False)

        def http_no_model(method: str, path: str, cookie: str, body: dict):
            raw = json.dumps(body).encode("utf-8")
            env = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "HTTP_HOST": "retailops.example.com",
                "QUERY_STRING": "",
                "HTTP_COOKIE": cookie,
                "HTTP_ORIGIN": "https://retailops.example.com",
                "CONTENT_LENGTH": str(len(raw)),
                "CONTENT_TYPE": "application/json",
                "wsgi.input": io.BytesIO(raw),
            }
            captured = {}
            out = b"".join(web_no_model(env, lambda s, h: captured.setdefault("status", int(s.split()[0]))))
            return captured["status"], json.loads(out)

        st_oa, oa_res = http_no_model(
            "POST",
            "/api/order-actions",
            c1_cookie,
            {"order_id": "O-102", "type": "return", "expected_order_version": 1, "reason_code": "defective_item"},
        )
        self.assertEqual(st_oa, 201)
        self.assertTrue(oa_res["order_action_request_id"].startswith("oar_"))


def _make_text_pdf_bytes(page_texts: list[str]) -> bytes:
    """Build a valid multi-page PDF 1.4 with a Type1 Helvetica text layer."""
    objs: list[bytes] = []
    # 1: Catalog, 2: Pages, 3: Font
    page_obj_nums = [4 + i * 2 for i in range(len(page_texts))]
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode("ascii"))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for idx, txt in enumerate(page_texts):
        p_num = 4 + idx * 2
        c_num = p_num + 1
        safe_txt = txt.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_data = f"BT /F1 12 Tf 36 120 Td ({safe_txt}) Tj ET".encode("latin-1", errors="replace")
        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {c_num} 0 R >>"
        ).encode("ascii")
        content_dict = f"<< /Length {len(stream_data)} >>\nstream\n".encode("ascii") + stream_data + b"\nendstream"
        objs.append(page_dict)
        objs.append(content_dict)

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objs) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def _make_scanned_pdf_bytes(num_pages: int, *, page_size: tuple[int, int] = (1600, 1200)) -> bytes:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    try:
        for _ in range(num_pages):
            page = doc.new_page(page_size[0], page_size[1])
            page.close()
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
    finally:
        doc.close()


class _FakeClamAVScanner:
    EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.calls = 0

    def scan_bytes(self, payload: bytes) -> dict:
        from retailops.core import ApiError

        self.calls += 1
        if not self.available:
            raise ApiError(503, "malware_scanner_unavailable", "Fake scanner offline.")
        if self.EICAR_MARKER in payload:
            raise ApiError(422, "malware_detected", "Fake EICAR signature detected.")
        return {"status": "clean", "engine": "clamav-fake", "scanned_at": 1_790_000_000.0}


class PhaseR1W4Item4PdfAndClamAVTests(unittest.TestCase):
    """Item 4 acceptance tests: clamd zINSTREAM protocol, <=20MB/<=20p PDF, text excerpt vs <=3 scanned images, EICAR & scanner-down fail-closed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_root = Path(self._tmp.name) / "data_root"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._env_patch = patch.dict(
            os.environ,
            {
                "RETAILOPS_API_ENDPOINT": "https://retailops-w4.ngrok.app/v1/chat/completions",
                "RETAILOPS_API_KEY": API_KEY,
                "RETAILOPS_API_TUNNEL_TOKEN": TUNNEL_TOKEN,
                "RETAILOPS_API_VISION": "on",
            },
            clear=False,
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_item4_clamd_zinstream_protocol_clean_eicar_and_unavailable(self):
        import socket
        import struct
        import threading
        from retailops.business.clamav import ClamdScanner
        from retailops.core import ApiError

        eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        port = srv.getsockname()[1]
        stop = threading.Event()

        def handle_loop():
            srv.settimeout(0.2)
            while not stop.is_set():
                try:
                    conn, _ = srv.accept()
                except OSError:
                    continue
                with conn:
                    conn.settimeout(2.0)
                    buf = bytearray()
                    header = b""
                    while len(header) < 10:
                        part = conn.recv(10 - len(header))
                        if not part:
                            break
                        header += part
                    if header != b"zINSTREAM\x00":
                        conn.sendall(b"stream: COMMAND READ ERROR\x00")
                        continue
                    while True:
                        len_bytes = b""
                        while len(len_bytes) < 4:
                            p = conn.recv(4 - len(len_bytes))
                            if not p:
                                break
                            len_bytes += p
                        if len(len_bytes) < 4:
                            break
                        chunk_len = struct.unpack("!I", len_bytes)[0]
                        if chunk_len == 0:
                            break
                        rem = chunk_len
                        while rem > 0:
                            c = conn.recv(min(65536, rem))
                            if not c:
                                break
                            buf.extend(c)
                            rem -= len(c)
                    if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in buf:
                        conn.sendall(b"stream: Win.Test.EICAR_HDB-1 FOUND\x00")
                    else:
                        conn.sendall(b"stream: OK\x00")

        t = threading.Thread(target=handle_loop, daemon=True)
        t.start()
        try:
            scanner = ClamdScanner("127.0.0.1", port, timeout_seconds=3.0)
            clean_res = scanner.scan_bytes(b"%PDF-1.4 clean payload" * 5000)
            self.assertEqual(clean_res["status"], "clean")
            self.assertEqual(clean_res["engine"], "clamav")

            with self.assertRaises(ApiError) as eicar_ctx:
                scanner.scan_bytes(b"%PDF-1.4\n%" + eicar)
            self.assertEqual((eicar_ctx.exception.status, eicar_ctx.exception.code), (422, "malware_detected"))
        finally:
            stop.set()
            srv.close()
            t.join(timeout=2.0)

        # Closed port / unconfigured host -> fail closed (503 malware_scanner_unavailable)
        dead_scanner = ClamdScanner("127.0.0.1", port, timeout_seconds=0.5)
        with self.assertRaises(ApiError) as dead_ctx:
            dead_scanner.scan_bytes(b"%PDF-1.4 test")
        self.assertEqual((dead_ctx.exception.status, dead_ctx.exception.code), (503, "malware_scanner_unavailable"))

        unconfigured = ClamdScanner("", 3310)
        with self.assertRaises(ApiError) as uncfg_ctx:
            unconfigured.scan_bytes(b"%PDF-1.4 test")
        self.assertEqual((uncfg_ctx.exception.status, uncfg_ctx.exception.code), (503, "malware_scanner_unavailable"))

    def test_item4_text_pdf_scanned_pdf_limits_and_order_action_pdf_upload(self):
        from retailops.core import ApiError, PDF_EVIDENCE_MAX_BYTES

        vision_adapter = OpenRouterAgent(API_KEY, MODEL_ID, tunnel_token=TUNNEL_TOKEN, vision=True)
        sessions = PersistentSessions(self.data_root / "persistent_pdf", api_infer=vision_adapter)
        store = sessions.provision_tenant("shop-pdf", "Shop PDF", seed_demo=True)
        fake_scanner = _FakeClamAVScanner(available=True)
        sessions.malware_scanner = fake_scanner
        store.malware_scanner = fake_scanner
        with store.connection(write=True) as db:
            db.execute("UPDATE orders SET status = 'delivered', delivered_at = ? WHERE id = 'O-102'", (1_785_000_000.0,))

        mid = sessions.create_member("shop-pdf", "p-pdf-c1", "Cust PDF", "C-001", "customer")
        tok = secrets.token_urlsafe(32)
        sessions.control.register_credential(mid, tok)
        c1_cookie = f"{sessions.cookie_name}={sessions.login(tok)}"

        web = PublicWeb("https://retailops.example.com", sessions, start_timer_worker=False)

        # 1. Valid 2-page text PDF in chat -> stored cleanly, excerpt has [Trang 1] and [Trang 2], 0 image_url parts
        text_pdf = _make_text_pdf_bytes(["Hoa don O-102 bi rach hop", "Bien ban dong kiem buu cuc"])
        app = Application(store, {}, api_infer=vision_adapter, role="customer")
        cid_txt = app.new_conversation("C-001", {"provider_id": "api"})["conversation_id"]
        with patch.object(OpenRouterAgent, "request", return_value=_provider_reply("Đã đọc nội dung tài liệu đính kèm của bạn.")) as mock_req_txt:
            res_txt = app.chat(
                "C-001",
                {
                    "conversation_id": cid_txt,
                    "text": "Xem giúp hóa đơn PDF đính kèm",
                    "request_id": "req_pdf_txt_" + uuid.uuid4().hex[:16],
                    "attachment": {
                        "type": "document",
                        "name": "invoice_O102.pdf",
                        "data": base64.b64encode(text_pdf).decode("ascii"),
                    },
                },
            )
        self.assertIn("Đã đọc nội dung", res_txt["message"])
        sent_user_txt = [m for m in mock_req_txt.call_args.args[0]["messages"] if m.get("role") == "user"][-1]
        self.assertIsInstance(sent_user_txt["content"], str)
        self.assertIn("[Trang 1] Hoa don O-102 bi rach hop", sent_user_txt["content"])
        self.assertIn("[Trang 2] Bien ban dong kiem buu cuc", sent_user_txt["content"])

        # 2. Valid 5-page scanned PDF in chat -> renders at most 3 pages as <=1024 px images!
        scanned_pdf_5p = _make_scanned_pdf_bytes(5, page_size=(1800, 1400))
        cid_scan = app.new_conversation("C-001", {"provider_id": "api"})["conversation_id"]
        with patch.object(OpenRouterAgent, "request", return_value=_provider_reply("Đã xem 3 trang scan của bạn.")) as mock_req_scan:
            app.chat(
                "C-001",
                {
                    "conversation_id": cid_scan,
                    "text": "Biên bản viết tay scan 5 trang",
                    "request_id": "req_pdf_scan_" + uuid.uuid4().hex[:16],
                    "attachment": {
                        "type": "document",
                        "name": "scanned_5p.pdf",
                        "data": base64.b64encode(scanned_pdf_5p).decode("ascii"),
                    },
                },
            )
        sent_user_scan = [m for m in mock_req_scan.call_args.args[0]["messages"] if m.get("role") == "user"][-1]
        self.assertIsInstance(sent_user_scan["content"], list)
        scan_imgs = [p for p in sent_user_scan["content"] if p.get("type") == "image_url"]
        self.assertEqual(len(scan_imgs), 3)
        for part in scan_imgs:
            url = part["image_url"]["url"]
            raw_img = base64.b64decode(url.split(",", 1)[1])
            with Image.open(io.BytesIO(raw_img)) as im:
                self.assertLessEqual(max(im.size), 1024)
                self.assertEqual(len(im.getexif()), 0)

        # 3. Reject >20 pages (21 pages -> 400 pdf_too_many_pages), EICAR (422 malware_detected), scanner down (503)
        pdf_21p = _make_scanned_pdf_bytes(21, page_size=(200, 200))
        with self.assertRaises(ApiError) as p21_ctx:
            store.store_chat_attachment(
                "C-001",
                cid_txt,
                {"type": "document", "name": "21p.pdf", "data": base64.b64encode(pdf_21p).decode("ascii")},
            )
        self.assertEqual((p21_ctx.exception.status, p21_ctx.exception.code), (400, "pdf_too_many_pages"))

        eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        infected_pdf = text_pdf + b"\n%" + eicar + b"\n"
        with self.assertRaises(ApiError) as inf_ctx:
            store.store_chat_attachment(
                "C-001",
                cid_txt,
                {"type": "document", "name": "evil.pdf", "data": base64.b64encode(infected_pdf).decode("ascii")},
            )
        self.assertEqual((inf_ctx.exception.status, inf_ctx.exception.code), (422, "malware_detected"))

        store.malware_scanner = _FakeClamAVScanner(available=False)
        with self.assertRaises(ApiError) as down_ctx:
            store.store_chat_attachment(
                "C-001",
                cid_txt,
                {"type": "document", "name": "clean.pdf", "data": base64.b64encode(text_pdf).decode("ascii")},
            )
        self.assertEqual((down_ctx.exception.status, down_ctx.exception.code), (503, "malware_scanner_unavailable"))
        store.malware_scanner = fake_scanner

        # 4. Order-action evidence accepts application/pdf <= 20 MB (exact 20_971_520 route cap) and rejects 20_971_521!
        def raw_http(method: str, path: str, body_bytes: bytes = b"", content_type: str = "application/json", length_override: str | None = None):
            env = {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "HTTP_HOST": "retailops.example.com",
                "QUERY_STRING": "",
                "HTTP_COOKIE": c1_cookie,
                "CONTENT_LENGTH": length_override if length_override is not None else str(len(body_bytes)),
                "CONTENT_TYPE": content_type,
                "wsgi.input": io.BytesIO(body_bytes),
            }
            if method != "GET":
                env["HTTP_ORIGIN"] = "https://retailops.example.com"
            captured = {}

            def start_resp(status, headers):
                captured["status"] = int(status.split()[0])
                captured["headers"] = dict(headers)

            raw_out = b"".join(web(env, start_resp))
            return captured["status"], captured["headers"], raw_out

        st_oa, _, raw_oa = raw_http(
            "POST",
            "/api/order-actions",
            json.dumps({"order_id": "O-102", "type": "return", "expected_order_version": 1, "reason_code": "defective_item"}).encode("utf-8"),
        )
        self.assertEqual(st_oa, 201)
        req_id = json.loads(raw_oa)["order_action_request_id"]

        # > 20 MB (20_971_521 bytes) rejected with 413 evidence_too_large
        st_over20, _, raw_over20 = raw_http(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            b"%PDF-",
            content_type="application/pdf",
            length_override=str(PDF_EVIDENCE_MAX_BYTES + 1),
        )
        self.assertEqual((st_over20, json.loads(raw_over20)["error"]), (413, "evidence_too_large"))

        # Valid 11 MB PDF (>10 MB image cap, <=20 MB PDF cap) is accepted on the PDF evidence upload route!
        padded_11mb_pdf = text_pdf + (b"%" + b"A" * 1022 + b"\n") * 11_000
        self.assertGreater(len(padded_11mb_pdf), 10_485_760)
        self.assertLessEqual(len(padded_11mb_pdf), PDF_EVIDENCE_MAX_BYTES)
        st_up_pdf, _, raw_up_pdf = raw_http(
            "POST",
            f"/api/order-actions/{req_id}/evidence",
            padded_11mb_pdf,
            content_type="application/pdf",
        )
        self.assertEqual(st_up_pdf, 201, raw_up_pdf)
        ev_pdf = json.loads(raw_up_pdf)["evidence"]
        self.assertEqual(ev_pdf["mime_type"], "application/pdf")
        self.assertEqual(ev_pdf["page_count"], 2)
        self.assertEqual(ev_pdf["scan_status"], "clean")

        st_dl, hdrs_dl, bytes_dl = raw_http("GET", ev_pdf["download_url"])
        self.assertEqual(st_dl, 200)
        self.assertEqual(hdrs_dl.get("Content-Type"), "application/pdf")
        self.assertIn("attachment", hdrs_dl.get("Content-Disposition", ""))
        self.assertEqual(bytes_dl, padded_11mb_pdf)


if __name__ == "__main__":
    unittest.main()
