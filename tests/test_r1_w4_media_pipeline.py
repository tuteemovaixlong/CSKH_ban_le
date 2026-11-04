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


if __name__ == "__main__":
    unittest.main()
