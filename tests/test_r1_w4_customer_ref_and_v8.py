"""Phase R1 W4 isolated tests for Item 7 (salted HMAC-SHA-256 customer_ref) and Item 8 (Business v8 migration)."""
from __future__ import annotations

import argparse
import base64
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from retailops.business import schema as business_schema
from retailops.business.outbox import (
    compute_customer_ref,
    resolve_customer_ref_key,
    validate_outbox_envelope,
)
from retailops.business.schema import (
    BUSINESS_V7_VERSION_MAPPING,
    BUSINESS_V8_VERSION_MAPPING,
    BUSINESS_V9_VERSION_MAPPING,
    POSTGRES_BUSINESS_SCHEMA_CURRENT,
    SQLITE_BUSINESS_SCHEMA_CURRENT,
    SQLITE_BUSINESS_V7_SCHEMA_VERSION,
    SQLITE_BUSINESS_V8_SCHEMA_VERSION,
    migrate_order_action_evidence_v8,
)
from retailops.business.store import (
    BusinessStore,
    _inspect_sqlite_business_ready,
    migrate_sqlite_business_v7,
    migrate_sqlite_business_v8,
    migrate_sqlite_business_v9,
)
from retailops.config import Settings
from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.identity.store import IdentityStore
from retailops.storage import cli as database_cli
from retailops.storage import pg_schema
from retailops.storage.pg_repositories import (
    PostgresBusinessStore,
    migrate_postgres_business_v8,
    migrate_postgres_business_v9,
)
from retailops.storage.pg_schema import initialize as pg_initialize
from retailops.storage.postgres import (
    BUSINESS_SCHEMA_CURRENT,
    BUSINESS_V7_SCHEMA_VERSION,
    IDENTITY_SCHEMA,
    tenant_schema,
)
from test_r1_w3_2_business_v7 import file_sha, table_dump
from test_r1_w3_order_actions import _build_mock_pg_harness, _create_sqlite_v5_tenant_db
from test_r1_w4_media_pipeline import _make_exif_jpeg_bytes, _make_text_pdf_bytes

ROOT = Path(__file__).resolve().parents[1]
DSN = os.environ.get("RETAILOPS_TEST_DATABASE_URL", "")


class PhaseR1W4SaltedCustomerRefTests(unittest.TestCase):
    """Item 7 (W4-D8): HMAC-SHA-256 customer_ref with secret key/file and missing-key fail-safe outbox behavior."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w4-item7-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.pers = self.root / "persistent"

    def test_hmac_sha256_determinism_key_isolation_non_guessability_and_valid_envelope(self):
        key_a = "deploy-secret-key-alpha-0123456789abcdef"
        key_b = "deploy-secret-key-bravo-fedcba9876543210"

        ref_a1 = compute_customer_ref("shop-a", "C-001", key_a)
        ref_a2 = compute_customer_ref("shop-a", "C-001", key_a)
        ref_b1 = compute_customer_ref("shop-a", "C-001", key_b)
        ref_other_tenant = compute_customer_ref("shop-b", "C-001", key_a)
        ref_other_customer = compute_customer_ref("shop-a", "C-002", key_a)

        # Same tenant + same customer + same key -> identical custref_<64hex>
        self.assertEqual(ref_a1, ref_a2)
        self.assertRegex(ref_a1, r"^custref_[0-9a-f]{64}$")

        # Different key, tenant, or customer -> distinct ref
        self.assertNotEqual(ref_a1, ref_b1)
        self.assertNotEqual(ref_a1, ref_other_tenant)
        self.assertNotEqual(ref_a1, ref_other_customer)

        # Cannot be guessed from unsalted SHA-256 of customer_id or tenant:customer_id
        for candidate in ("C-001", "shop-a:C-001", "shop-a\x00C-001"):
            unsalted_full = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            self.assertNotIn(unsalted_full[:16], ref_a1)

        # End-to-end envelope creation + validation + JSONL publish via secret file
        secret_file = self.root / "secrets" / "customer_ref.key"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(f"  {key_a}\n", encoding="utf-8")

        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("RETAILOPS_CUSTOMER_REF_KEY", "RETAILOPS_CUSTOMER_REF_KEY_FILE")
        }
        clean_env["RETAILOPS_CUSTOMER_REF_KEY_FILE"] = str(secret_file)

        with patch.dict(os.environ, clean_env, clear=True):
            resolved_key, err_code, _ = resolve_customer_ref_key()
            self.assertEqual((resolved_key, err_code), (key_a, None))

            sessions = PersistentSessions(self.pers, data_mode="persistent-demo")
            store = sessions.provision_tenant("shop-a", "Shop A", seed_demo=True)
            store.create_order_action_request(
                "C-001",
                {
                    "order_id": "O-101",
                    "type": "cancel",
                    "expected_order_version": 1,
                    "reason_code": "ordered_by_mistake",
                },
                actor={"principal_id": "C-001", "role": "customer", "tenant_id": "shop-a"},
            )
            conv = store.new_conversation("C-001")
            store.record_feedback(
                "C-001",
                {
                    "conversation_id": conv["conversation_id"],
                    "feedback_type": "session_csat",
                    "rating": 5,
                    "reason_code": "fast_support",
                },
            )
            with store.connection() as db:
                rows = db.execute("SELECT payload_json FROM integration_outbox ORDER BY created_at ASC").fetchall()
            self.assertEqual(len(rows), 2)
            for row in rows:
                env = json.loads(row["payload_json"])
                validate_outbox_envelope(env)
                self.assertEqual(env["customer_ref"], ref_a1)
                self.assertNotIn("C-001", row["payload_json"])
                self.assertNotIn(key_a, row["payload_json"])
            self.assertEqual(rows[0] and json.loads(rows[0]["payload_json"])["actor"]["principal_id"], ref_a1)

            pub = store.process_outbox_batch(batch_size=10)
            self.assertEqual(pub["published"], 2)
            summary = store.outbox_status_summary()
            self.assertNotIn("error", summary)
            self.assertEqual((summary["pending"], summary["published"], summary["dead"]), (0, 2, 0))

    def test_missing_key_skips_new_outbox_writes_and_reports_clear_error_in_outbox_status(self):
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("RETAILOPS_CUSTOMER_REF_KEY", "RETAILOPS_CUSTOMER_REF_KEY_FILE")
        }
        with patch.dict(os.environ, clean_env, clear=True):
            sessions = PersistentSessions(self.pers, data_mode="persistent-demo")
            store = sessions.provision_tenant("shop-a", "Shop A", seed_demo=True)

            # Business operations succeed, but zero new rows are written to integration_outbox
            created = store.create_order_action_request(
                "C-001",
                {
                    "order_id": "O-101",
                    "type": "cancel",
                    "expected_order_version": 1,
                    "reason_code": "change_of_mind",
                },
                actor={"principal_id": "C-001", "role": "customer", "tenant_id": "shop-a"},
            )
            self.assertEqual(created["status"], "requested")

            with store.connection() as db:
                cnt = db.execute("SELECT COUNT(*) FROM integration_outbox").fetchone()[0]
            self.assertEqual(cnt, 0)

            summary = store.outbox_status_summary()
            self.assertEqual(summary["error"], "customer_ref_key_missing")
            self.assertIn("RETAILOPS_CUSTOMER_REF_KEY", summary["error_message"])

            cli_env = {
                **clean_env,
                "RETAILOPS_STORAGE_BACKEND": "sqlite",
                "RETAILOPS_OUTPUT": str(self.root),
            }
            proc = subprocess.run(
                [sys.executable, "-m", "retailops", "database", "outbox-status"],
                cwd=str(ROOT),
                env=cli_env,
                capture_output=True,
                encoding="utf-8",
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report["result"], "OUTBOX_STATUS")
            self.assertFalse(report["customer_ref_key_configured"])
            self.assertEqual(report["error"], "customer_ref_key_missing")
            self.assertIn("RETAILOPS_CUSTOMER_REF_KEY", report["message"])
            self.assertEqual(report["totals"], {"pending": 0, "published": 0, "dead": 0})
            self.assertEqual(report["tenants"][0]["error"], "customer_ref_key_missing")

    def test_settings_secret_file_conflict_and_secret_redaction(self):
        secret_val = "super-secret-customer-ref-key-9876543210"
        secret_file = self.root / "cref.secret"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(secret_val, encoding="utf-8")

        base_env = {
            "RETAILOPS_DATA_MODE": "persistent-demo",
            "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
            "RETAILOPS_CUSTOMER_REF_KEY_FILE": str(secret_file),
        }
        settings = Settings.from_environment("public", base_env)
        self.assertEqual(settings.customer_ref_key, secret_val)
        self.assertNotIn(secret_val, repr(settings))
        self.assertNotIn(secret_val, json.dumps(settings.summary()))

        with self.assertRaisesRegex(ValueError, "RETAILOPS_CUSTOMER_REF_KEY"):
            Settings.from_environment(
                "public",
                {**base_env, "RETAILOPS_CUSTOMER_REF_KEY": secret_val},
            )
        with self.assertRaisesRegex(ValueError, "at least 16"):
            Settings.from_environment(
                "public",
                {
                    "RETAILOPS_DATA_MODE": "persistent-demo",
                    "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
                    "RETAILOPS_CUSTOMER_REF_KEY": "too-short",
                },
            )


class _FakeMigrationScanner:
    def scan_bytes(self, payload: bytes) -> dict:
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in payload:
            raise ApiError(400, "malware_detected", "Phát hiện mã độc EICAR trong tệp đính kèm cũ.")
        return {"status": "clean", "engine": "fake-clamav/1.4", "scanned_at": 1700000123.0}


LEGACY_V7_EVIDENCE_DDL = """CREATE TABLE order_action_evidence (
    evidence_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES order_action_requests(request_id),
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    conversation_id TEXT NOT NULL,
    uploaded_by_principal_id TEXT NOT NULL,
    uploaded_by_role TEXT NOT NULL CHECK(uploaded_by_role IN ('customer', 'staff', 'manager')),
    mime_type TEXT NOT NULL CHECK(mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
    byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 10485760),
    width INTEGER NOT NULL CHECK(width > 0),
    height INTEGER NOT NULL CHECK(height > 0),
    sha256 TEXT NOT NULL,
    storage_relpath TEXT NOT NULL,
    created_at REAL NOT NULL,
    file_purged_at REAL
)"""


def _build_legacy_turn_messages(jpeg_b64: str, pdf_b64: str, eicar_pdf_b64: str) -> list[tuple[str, str]]:
    conv1_id = "11111111-1111-4111-8111-111111111111"
    conv2_id = "22222222-2222-4222-8222-222222222222"
    turn1_msgs = [
        {
            "role": "user",
            "content": "Áo bị bung chỉ như trong ảnh này ạ",
            "attachment": {
                "type": "image",
                "name": "../anh loi áo.jpg",
                "data": f"data:image/jpeg;base64,{jpeg_b64}",
            },
        },
        {"role": "assistant", "content": "Mình đã nhận thông tin."},
    ]
    turn2_msgs = [
        {
            "role": "user",
            "content": "Đây là hóa đơn PDF đính kèm",
            "attachment": {
                "type": "document",
                "name": "hoa_don_101.pdf",
                "data": f"data:application/pdf;base64,{pdf_b64}",
            },
        },
        {"role": "assistant", "content": "Đã ghi nhận hóa đơn."},
    ]
    turn3_msgs = [
        {
            "role": "user",
            "content": "Tệp lỗi / nhiễm mã độc",
            "attachment": {
                "type": "document",
                "name": "bad_eicar.pdf",
                "data": f"data:application/pdf;base64,{eicar_pdf_b64}",
            },
        },
        {
            "role": "user",
            "content": "Ảnh hỏng không đọc được",
            "attachment": {
                "type": "image",
                "name": "corrupt.png",
                "data": "data:image/png;base64," + base64.b64encode(b"not-a-valid-image").decode("ascii"),
            },
        },
        {"role": "assistant", "content": "Đã ghi nhận."},
    ]
    return [
        (conv1_id, json.dumps(turn1_msgs, ensure_ascii=False)),
        (conv1_id, json.dumps(turn2_msgs, ensure_ascii=False)),
        (conv2_id, json.dumps(turn3_msgs, ensure_ascii=False)),
    ]


class PhaseR1W4BusinessV8SqliteMigrationTests(unittest.TestCase):
    """Item 8 (W4-D9): SQLite Business v8 (6 -> 7) schema, fail-closed startup, attachment backfill, and idempotency."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w4-v8-sqlite-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _create_v7_workspace_with_inline_attachments(self) -> tuple[Path, Path, list[Path]]:
        ws = self.root / "ws"
        pers = ws / "persistent"
        (pers / "tenants").mkdir(parents=True)
        identity = IdentityStore(pers / "identity.sqlite3")
        raw_jpg = _make_exif_jpeg_bytes((72, 54), color=(180, 40, 60))
        self.assertIn(b"ConfidentialPhoneMaker", raw_jpg)
        raw_pdf = _make_text_pdf_bytes(["Hoa don O-101 trang 1", "Chi tiet bao hanh trang 2"])
        raw_eicar_pdf = raw_pdf + b"\nX5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*\n"

        jpg_b64 = base64.b64encode(raw_jpg).decode("ascii")
        pdf_b64 = base64.b64encode(raw_pdf).decode("ascii")
        eicar_b64 = base64.b64encode(raw_eicar_pdf).decode("ascii")

        paths: list[Path] = []
        for idx, tid in enumerate(("shop-a", "shop-b")):
            tenant = identity.ensure_tenant(tid, f"Shop {tid}")
            t_path = pers / "tenants" / f"{tenant['storage_key']}.sqlite3"
            _create_sqlite_v5_tenant_db(t_path)
            migrate_sqlite_business_v7(t_path, preflight_confirmed=True, backup_confirmed=True)

            # Downgrade order_action_evidence to exact W3/W3.2 v7 shape (NOT NULL request_id/case_id/width/height, no PDF)
            # and ensure case_assist_turns does not exist yet.
            with closing(sqlite3.connect(t_path)) as db:
                db.execute("PRAGMA foreign_keys=OFF")
                db.execute("DROP TABLE IF EXISTS case_assist_turns")
                db.execute("DROP TABLE IF EXISTS order_action_evidence")
                db.execute(LEGACY_V7_EVIDENCE_DDL)
                db.execute("UPDATE retailops_schema SET version = 6 WHERE component = 'business'")

                conv1_id = "11111111-1111-4111-8111-111111111111"
                conv2_id = "22222222-2222-4222-8222-222222222222"
                db.execute(
                    "INSERT INTO conversations(id, customer_id, order_id, expires_at, provider_id) VALUES (?, 'C-001', 'O-101', 9999999999.0, 'api')",
                    (conv1_id,),
                )
                db.execute(
                    "INSERT INTO conversations(id, customer_id, order_id, expires_at, provider_id) VALUES (?, 'C-001', 'O-102', 9999999999.0, 'api')",
                    (conv2_id,),
                )
                db.execute(
                    """INSERT INTO cases(case_id, conversation_id, customer_id, status, version, resume_count, created_at, updated_at)
                       VALUES ('case_legacy_1', ?, 'C-001', 'waiting', 1, 0, 1700000000.0, 1700000000.0)""",
                    (conv1_id,),
                )
                # Tenant 1 has 2 valid + 2 invalid attachments across 3 turns; Tenant 2 has 1 valid JPEG turn.
                turn_specs = _build_legacy_turn_messages(jpg_b64, pdf_b64, eicar_b64)
                if idx == 1:
                    turn_specs = turn_specs[:1]
                for t_idx, (cid, msgs_json) in enumerate(turn_specs, start=1):
                    db.execute(
                        """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                           VALUES (?, 'C-001', ?, ?, ?, '{}', ?)""",
                        (cid, f"req-legacy-{t_idx}", f"hash-{t_idx}", msgs_json, 1700000000.0 + t_idx),
                    )
                db.commit()
            paths.append(t_path)
        return ws, pers, paths

    def test_fresh_sqlite_db_is_v8_straight_away_and_enforces_pdf_and_scan_constraints(self):
        self.assertEqual(SQLITE_BUSINESS_V7_SCHEMA_VERSION, 6)
        self.assertEqual(SQLITE_BUSINESS_V8_SCHEMA_VERSION, 7)
        self.assertEqual(SQLITE_BUSINESS_SCHEMA_CURRENT, 8)
        self.assertEqual(POSTGRES_BUSINESS_SCHEMA_CURRENT, 9)
        self.assertEqual(BUSINESS_V7_VERSION_MAPPING, {"logical_milestone": "business_v7", "sqlite": 6, "postgresql": 7})
        self.assertEqual(BUSINESS_V8_VERSION_MAPPING, {"logical_milestone": "business_v8", "sqlite": 7, "postgresql": 8})
        self.assertEqual(BUSINESS_V9_VERSION_MAPPING, {"logical_milestone": "business_v9", "sqlite": 8, "postgresql": 9})

        fresh_path = self.root / "fresh_v8.sqlite3"
        store = BusinessStore(fresh_path)
        store.seed()
        self.assertEqual(_inspect_sqlite_business_ready(fresh_path), "v9_ready")

        with store.connection(write=True) as db:
            ver = db.execute("SELECT version FROM retailops_schema WHERE component='business'").fetchone()[0]
            self.assertEqual(ver, 8)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            self.assertIn("case_assist_turns", tables)

            # PDF up to 20 MB with clean scan_status is accepted; > 20 MB or > 10 MB image or bad scan_status is rejected
            db.execute(
                """INSERT INTO order_action_evidence(
                       evidence_id, request_id, case_id, customer_id, conversation_id, filename,
                       uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size,
                       width, height, page_count, sha256, storage_relpath,
                       scan_status, scan_engine, scanned_at, created_at, file_purged_at
                   ) VALUES ('ev_pdf_ok', NULL, NULL, 'C-001', '11111111-1111-4111-8111-111111111111', 'doc.pdf',
                             'C-001', 'customer', 'application/pdf', 20971520, NULL, NULL, 20, 'sha_ok',
                             'evidence/default/ev_pdf_ok', 'clean', 'clamav', 1.0, 1.0, NULL)"""
            )
            for bad_id, mime, bsize, pcnt, sstatus in (
                ("ev_pdf_big", "application/pdf", 20971521, 1, "clean"),
                ("ev_img_big", "image/jpeg", 10485761, None, "not_applicable"),
                ("ev_pdf_pages", "application/pdf", 1024, 21, "clean"),
                ("ev_bad_scan", "application/pdf", 1024, 1, "infected"),
            ):
                with self.subTest(bad_id=bad_id), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        """INSERT INTO order_action_evidence(
                               evidence_id, request_id, case_id, customer_id, conversation_id, filename,
                               uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size,
                               width, height, page_count, sha256, storage_relpath,
                               scan_status, scan_engine, scanned_at, created_at, file_purged_at
                           ) VALUES (?, NULL, NULL, 'C-001', '11111111-1111-4111-8111-111111111111', 'x',
                                     'C-001', 'customer', ?, ?, NULL, NULL, ?, 'sha', 'evidence/default/x',
                                     ?, 'clamav', 1.0, 1.0, NULL)""",
                        (bad_id, mime, bsize, pcnt, sstatus),
                    )

    def test_v7_fixture_with_inline_attachments_is_blocked_migrates_exact_counts_and_rerun_is_noop(self):
        ws, pers, (path_a, path_b) = self._create_v7_workspace_with_inline_attachments()
        before_hashes = (file_sha(path_a), file_sha(path_b))

        parser = argparse.ArgumentParser()
        database_cli.add_parser(parser.add_subparsers(dest="command", required=True))

        with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
            for blocked in (
                lambda: _inspect_sqlite_business_ready(path_a),
                lambda: BusinessStore(path_a, create=False),
                lambda: PersistentSessions(pers),
                lambda: database_cli.run(parser.parse_args(["database", "--output", str(ws), "check"])),
            ):
                with self.assertRaises(ApiError) as caught:
                    blocked()
                self.assertEqual((caught.exception.status, caught.exception.code), (503, "business_migration_required"))
                self.assertIn("migrate-v9", caught.exception.message)

            # Zero bytes written during fail-closed checks
            self.assertEqual((file_sha(path_a), file_sha(path_b)), before_hashes)

            # Missing confirmation flags rejected
            with self.assertRaises(ApiError) as unconf:
                database_cli.run(parser.parse_args(["database", "--output", str(ws), "migrate-v8", "--confirm-preflight"]))
            self.assertEqual((unconf.exception.status, unconf.exception.code), (400, "migration_confirmation_required"))
            self.assertEqual((file_sha(path_a), file_sha(path_b)), before_hashes)

            # Evidence table rebuild refuses foreign_keys=ON
            with closing(sqlite3.connect(path_a)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA foreign_keys=ON")
                with self.assertRaises(ValueError):
                    migrate_order_action_evidence_v8(db)

            # Simulated failure after attachment file write rolls back DB and unlinks newly written evidence files
            with patch.object(business_schema, "ensure_case_assist_tables", side_effect=RuntimeError("boom mid-v8")):
                with self.assertRaises(RuntimeError):
                    migrate_sqlite_business_v8(
                        ws,
                        preflight_confirmed=True,
                        backup_confirmed=True,
                        malware_scanner=_FakeMigrationScanner(),
                    )
            self.assertFalse((ws / "evidence").exists() and any((ws / "evidence").rglob("ev_*")))

            # Controlled migrate-v8 migrates 3 valid attachments (2 in shop-a + 1 in shop-b) and removes 2 invalid in shop-a
            scanner = _FakeMigrationScanner()
            with patch("retailops.business.store.ClamdScanner.from_environment", return_value=scanner):
                res = database_cli.run(
                    parser.parse_args(
                        ["database", "--output", str(ws), "migrate-v8", "--confirm-preflight", "--confirm-backup"]
                    )
                )
            self.assertEqual(
                res,
                {
                    "result": "BUSINESS_V8_MIGRATED",
                    "backend": "sqlite",
                    "schema_version": 7,
                    "logical_version": 8,
                    "tenants": 2,
                    "upgraded": True,
                    "attachments_migrated": 3,
                    "attachments_removed": 2,
                    "turns_updated": 4,
                },
            )

            # Re-running migrate-v8 at the v8 milestone is a 100% no-op
            dumps_after = (table_dump(path_a), table_dump(path_b))
            files_after = sorted(str(p.relative_to(ws)) for p in (ws / "evidence").rglob("ev_*"))
            again = migrate_sqlite_business_v8(
                ws,
                preflight_confirmed=True,
                backup_confirmed=True,
                malware_scanner=_FakeMigrationScanner(),
            )
            self.assertEqual(
                again,
                {
                    "result": "BUSINESS_V8_MIGRATED",
                    "backend": "sqlite",
                    "schema_version": 7,
                    "logical_version": 8,
                    "tenants": 2,
                    "upgraded": False,
                    "attachments_migrated": 0,
                    "attachments_removed": 0,
                    "turns_updated": 0,
                },
            )
            self.assertEqual((table_dump(path_a), table_dump(path_b)), dumps_after)
            self.assertEqual(sorted(str(p.relative_to(ws)) for p in (ws / "evidence").rglob("ev_*")), files_after)

            # Since W6.1b-1 moved current to Business v9, step up to v9 before `database check` / startup
            res_v9 = database_cli.run(
                parser.parse_args(
                    ["database", "--output", str(ws), "migrate-v9", "--confirm-preflight", "--confirm-backup"]
                )
            )
            self.assertEqual((res_v9["result"], res_v9["schema_version"], res_v9["upgraded"]), ("BUSINESS_V9_MIGRATED", 8, True))
            chk = database_cli.run(parser.parse_args(["database", "--output", str(ws), "check"]))
            self.assertEqual(chk, {"result": "SQLITE_SCHEMA_READY", "tenants_checked": 2})

        sessions = PersistentSessions(pers)
        store_a = sessions.business_store("shop-a")
        with store_a.connection() as db:
            turns_raw = [r["messages"] for r in db.execute("SELECT messages FROM agent_turns ORDER BY id ASC").fetchall()]
            ev_rows = [dict(r) for r in db.execute("SELECT * FROM order_action_evidence ORDER BY created_at ASC").fetchall()]
        joined_turns = "\n".join(turns_raw)
        self.assertNotIn("data:image/", joined_turns)
        self.assertNotIn("data:application/pdf", joined_turns)
        self.assertNotIn('"data":', joined_turns)
        self.assertEqual(len(ev_rows), 2)

        # Turn 1 (JPEG): EXIF stripped on disk, case_id linked, safe filename
        t1_att = json.loads(turns_raw[0])[0]["attachment"]
        self.assertEqual((t1_att["type"], t1_att["mime_type"], t1_att["name"]), ("image", "image/jpeg", "anh loi áo.jpg"))
        ev_img = store_a.get_chat_evidence_record("11111111-1111-4111-8111-111111111111", t1_att["evidence_id"])
        self.assertEqual(ev_img["case_id"], "case_legacy_1")
        self.assertEqual(ev_img["scan_status"], "not_applicable")
        disk_jpg, _ = store_a.read_order_action_evidence_bytes(ev_img)
        self.assertNotIn(b"ConfidentialPhoneMaker", disk_jpg)

        # Turn 2 (PDF): scanned clean, page_count = 2
        t2_att = json.loads(turns_raw[1])[0]["attachment"]
        self.assertEqual((t2_att["type"], t2_att["mime_type"], t2_att["page_count"]), ("document", "application/pdf", 2))
        ev_pdf = store_a.get_chat_evidence_record("11111111-1111-4111-8111-111111111111", t2_att["evidence_id"])
        self.assertEqual((ev_pdf["scan_status"], ev_pdf["scan_engine"], ev_pdf["page_count"]), ("clean", "fake-clamav/1.4", 2))

        # Turn 3 (EICAR PDF + corrupt PNG): both replaced with removed markers, zero raw bytes
        t3_msgs = json.loads(turns_raw[2])
        self.assertTrue(t3_msgs[0]["attachment"]["removed"])
        self.assertEqual(t3_msgs[0]["attachment"]["removed_reason"], "malware_detected")
        self.assertNotIn("data", t3_msgs[0]["attachment"])
        self.assertTrue(t3_msgs[1]["attachment"]["removed"])
        self.assertEqual(t3_msgs[1]["attachment"]["removed_reason"], "unsupported_evidence_type")
        self.assertNotIn("data", t3_msgs[1]["attachment"])


class PhaseR1W4BusinessV8PostgresMockTests(unittest.TestCase):
    """Item 8 (W4-D9): Mock PostgreSQL fresh v8, v7 fail-closed, attachment backfill, and idempotency."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w4-v8-pgmock-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_postgres_ddl_named_v8_constraints_match_between_fresh_and_upgrade(self):
        fresh = next(
            s for s in pg_schema.BUSINESS_V6_TABLES_DDL
            if s.lstrip().startswith("CREATE TABLE IF NOT EXISTS order_action_evidence")
        )
        upgrade = " ".join(pg_schema.BUSINESS_V8_UPGRADE_DDL)
        for cname in (
            "order_action_evidence_filename_v8_check",
            "order_action_evidence_mime_v8_check",
            "order_action_evidence_byte_size_v8_check",
            "order_action_evidence_width_v8_check",
            "order_action_evidence_height_v8_check",
            "order_action_evidence_page_count_v8_check",
            "order_action_evidence_scan_status_v8_check",
            "order_action_evidence_scan_engine_v8_check",
        ):
            self.assertIn(cname, fresh)
            self.assertIn(cname, upgrade)
        for stmt in pg_schema.BUSINESS_V8_UPGRADE_DDL:
            self.assertNotIn("%", stmt)

    def test_postgres_mock_v7_blocked_migrated_to_v8_with_attachment_backfill_and_idempotent(self):
        dsn = "postgresql://retailops:secret@127.0.0.1:5432/retailops"
        keys = ["a" * 32, "b" * 32]
        state, mock_conn_cls = _build_mock_pg_harness(keys)
        ws_out = self.root / "pg_out"

        raw_jpg = _make_exif_jpeg_bytes((64, 48), color=(90, 140, 210))
        raw_pdf = _make_text_pdf_bytes(["PG invoice page 1"])
        raw_eicar = raw_pdf + b"\nX5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*\n"
        jpg_b64 = base64.b64encode(raw_jpg).decode("ascii")
        pdf_b64 = base64.b64encode(raw_pdf).decode("ascii")
        eicar_b64 = base64.b64encode(raw_eicar).decode("ascii")

        mock_psycopg = MagicMock()
        mock_psycopg.conninfo.conninfo_to_dict.return_value = {"dbname": "retailops", "user": "retailops"}
        mock_sql = MagicMock()
        mock_sql.SQL = lambda s: SimpleNamespace(format=lambda *a: s.format(*a))
        mock_sql.Identifier = lambda s: s
        mock_psycopg.sql = mock_sql

        @contextmanager
        def fake_tx(dsn_, schema=IDENTITY_SCHEMA, *, write=False, read_only=False, lock_schema=True):
            yield mock_conn_cls(schema)

        parser = argparse.ArgumentParser()
        database_cli.add_parser(parser.add_subparsers(dest="command", required=True))
        schema_a, schema_b = (tenant_schema(k) for k in keys)

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.sql": mock_sql}), \
             patch("retailops.storage.pg_repositories.transaction", side_effect=fake_tx), \
             patch("retailops.storage.postgres.transaction", side_effect=fake_tx), \
             patch("retailops.identity.postgres.transaction", side_effect=fake_tx), \
             patch("retailops.storage.cli.os.environ", {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": dsn}), \
             patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": dsn}, clear=False):

            # Bring both mock PG schemas to v7 (Business v7) and seed inline attachments into agent_turns
            database_cli.run(parser.parse_args(["database", "migrate-v7", "--confirm-preflight", "--confirm-backup"]))
            for idx, sc in enumerate((schema_a, schema_b)):
                mem = state.schemas[sc]
                self.assertEqual(mem.execute("SELECT version FROM retailops_schema").fetchone()[0], BUSINESS_V7_SCHEMA_VERSION)
                conv1 = "11111111-1111-4111-8111-111111111111"
                conv2 = "22222222-2222-4222-8222-222222222222"
                mem.execute(
                    "INSERT INTO conversations(id, customer_id, order_id, expires_at, provider_id) VALUES (?, 'C-001', 'O-101', 9999999999.0, 'api')",
                    (conv1,),
                )
                mem.execute(
                    "INSERT INTO conversations(id, customer_id, order_id, expires_at, provider_id) VALUES (?, 'C-001', 'O-102', 9999999999.0, 'api')",
                    (conv2,),
                )
                mem.execute(
                    """INSERT INTO cases(case_id, conversation_id, customer_id, status, version, resume_count, created_at, updated_at)
                       VALUES ('case_pg_1', ?, 'C-001', 'waiting', 1, 0, 1700000000.0, 1700000000.0)""",
                    (conv1,),
                )
                specs = _build_legacy_turn_messages(jpg_b64, pdf_b64, eicar_b64)
                if idx == 1:
                    specs = specs[:1]
                for t_idx, (cid, msgs_json) in enumerate(specs, start=1):
                    mem.execute(
                        """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                           VALUES (?, 'C-001', ?, ?, ?, '{}', ?)""",
                        (cid, f"req-pg-{t_idx}", f"h-{t_idx}", msgs_json, 1700000000.0 + t_idx),
                    )
                mem.commit()

            # PG v7 schemas are blocked fail-closed on startup, store init, and `database check`
            for blocked in (
                lambda: pg_initialize(mock_conn_cls(schema_a), schema_a, "business"),
                lambda: PostgresBusinessStore(dsn, keys[0], create=False),
                lambda: PostgresSessions(dsn),
                lambda: database_cli.run(parser.parse_args(["database", "check"])),
                lambda: database_cli.run(parser.parse_args(["database", "migrate"])),
            ):
                with self.assertRaises(ApiError) as err:
                    blocked()
                self.assertEqual((err.exception.status, err.exception.code), (503, "business_migration_required"))
                self.assertIn("migrate-v9", err.exception.message)

            with self.assertRaises(ApiError) as unconf:
                database_cli.run(parser.parse_args(["database", "migrate-v8", "--confirm-backup"]))
            self.assertEqual(unconf.exception.code, "migration_confirmation_required")

            # Controlled migrate-v8 upgrades both tenants to schema v8 and backfills attachments
            with patch("retailops.business.store.ClamdScanner.from_environment", return_value=_FakeMigrationScanner()):
                mig = database_cli.run(
                    parser.parse_args(
                        ["database", "--output", str(ws_out), "migrate-v8", "--confirm-preflight", "--confirm-backup"]
                    )
                )
            self.assertEqual(
                mig,
                {
                    "result": "BUSINESS_V8_MIGRATED",
                    "backend": "postgresql",
                    "schema_version": 8,
                    "logical_version": 8,
                    "tenants": 2,
                    "upgraded": True,
                    "attachments_migrated": 3,
                    "attachments_removed": 2,
                    "turns_updated": 4,
                },
            )

            for sc in (schema_a, schema_b):
                mem = state.schemas[sc]
                self.assertEqual(mem.execute("SELECT version FROM retailops_schema").fetchone()[0], 8)
                self.assertIsNotNone(
                    mem.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_assist_turns'").fetchone()
                )
                turns_txt = "\n".join(r["messages"] for r in mem.execute("SELECT messages FROM agent_turns").fetchall())
                self.assertNotIn("data:image/", turns_txt)
                self.assertNotIn("data:application/pdf", turns_txt)

            # Second run is completely idempotent
            again = migrate_postgres_business_v8(
                dsn,
                preflight_confirmed=True,
                backup_confirmed=True,
                data_root=ws_out,
                malware_scanner=_FakeMigrationScanner(),
            )
            self.assertEqual(
                again,
                {
                    "result": "BUSINESS_V8_MIGRATED",
                    "backend": "postgresql",
                    "schema_version": 8,
                    "logical_version": 8,
                    "tenants": 2,
                    "upgraded": False,
                    "attachments_migrated": 0,
                    "attachments_removed": 0,
                    "turns_updated": 0,
                },
            )

            # Since W6.1b-1 moved current to Business v9, step up to v9 before `database check`
            mig_v9 = migrate_postgres_business_v9(dsn, preflight_confirmed=True, backup_confirmed=True)
            self.assertEqual((mig_v9["result"], mig_v9["schema_version"], mig_v9["upgraded"]), ("BUSINESS_V9_MIGRATED", 9, True))
            self.assertEqual(database_cli.run(parser.parse_args(["database", "check"]))["result"], "POSTGRES_SCHEMA_READY")

            # Fresh PG schema initializes directly to v9
            PostgresBusinessStore(dsn, "d" * 32, create=True)
            self.assertEqual(
                state.schemas[tenant_schema("d" * 32)].execute("SELECT version FROM retailops_schema").fetchone()[0],
                BUSINESS_SCHEMA_CURRENT,
            )


@unittest.skipUnless(DSN, "PostgreSQL integration runs in CI with a dedicated test database.")
class RealPostgresBusinessV8Tests(unittest.TestCase):
    """Verifies real PL/pgSQL constraint replacement and nullable column upgrade for Business v8 on PostgreSQL."""

    @classmethod
    def setUpClass(cls):
        import psycopg
        from scripts.postgres_test_guard import require_disposable_postgres_test_target
        require_disposable_postgres_test_target(DSN, psycopg.conninfo.conninfo_to_dict)

    def clear(self):
        from psycopg import sql
        from retailops.storage.postgres import transaction
        with transaction(DSN, write=True) as db:
            names = db.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname=? OR nspname ~ '^tenant_[a-f0-9]{32}$'",
                (IDENTITY_SCHEMA,),
            ).fetchall()
            for row in names:
                db.raw.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(row["nspname"])))

    def setUp(self):
        from retailops.storage.pg_repositories import PostgresIdentityStore
        self.temp = tempfile.TemporaryDirectory(prefix="r1-w4-realpg-")
        self.addCleanup(self.temp.cleanup)
        self.clear()
        self.addCleanup(self.clear)
        PostgresIdentityStore(DSN, create=True)
        self.sessions = PostgresSessions(DSN, api_daily_limit=1, data_root=Path(self.temp.name))
        self.sessions.provision_tenant("shop-a", "Cửa hàng A", seed_demo=True)
        self.key = self.sessions.control.tenant("shop-a")["storage_key"]
        self.schema = tenant_schema(self.key)

    def test_v7_postgres_schema_with_legacy_evidence_constraints_upgrades_to_v8_cleanly(self):
        from retailops.storage.postgres import transaction

        raw_jpg = _make_exif_jpeg_bytes((48, 48), color=(70, 120, 200))
        jpg_b64 = base64.b64encode(raw_jpg).decode("ascii")
        conv_id = "33333333-3333-4333-8333-333333333333"

        with transaction(DSN, self.schema, write=True) as db:
            for stmt in (
                "DROP TABLE IF EXISTS case_assist_turns",
                "DROP TABLE IF EXISTS order_action_evidence",
                """CREATE TABLE order_action_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL REFERENCES order_action_requests(request_id),
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    customer_id TEXT NOT NULL REFERENCES customers(id),
                    conversation_id TEXT NOT NULL,
                    uploaded_by_principal_id TEXT NOT NULL,
                    uploaded_by_role TEXT NOT NULL CHECK(uploaded_by_role IN ('customer', 'staff', 'manager')),
                    mime_type TEXT NOT NULL CHECK(mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
                    byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 10485760),
                    width INTEGER NOT NULL CHECK(width > 0),
                    height INTEGER NOT NULL CHECK(height > 0),
                    sha256 TEXT NOT NULL,
                    storage_relpath TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    file_purged_at DOUBLE PRECISION)""",
                "UPDATE retailops_schema SET version = 7 WHERE component = 'business'",
            ):
                db.raw.execute(stmt)
            db.execute(
                "INSERT INTO conversations(id, customer_id, order_id, expires_at, provider_id) VALUES (?, 'C-001', 'O-101', 9999999999.0, 'api')",
                (conv_id,),
            )
            msgs = json.dumps(
                [{"role": "user", "content": "Ảnh cũ", "attachment": {"type": "image", "name": "old.jpg", "data": jpg_b64}}],
                ensure_ascii=False,
            )
            db.execute(
                """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                   VALUES (?, 'C-001', 'req-realpg-1', 'h1', ?, '{}', 1700000000.0)""",
                (conv_id, msgs),
            )

        with self.assertRaises(ApiError) as blocked:
            PostgresBusinessStore(DSN, self.key)
        self.assertEqual(blocked.exception.code, "business_migration_required")

        res = migrate_postgres_business_v8(
            DSN,
            preflight_confirmed=True,
            backup_confirmed=True,
            data_root=Path(self.temp.name),
            malware_scanner=_FakeMigrationScanner(),
        )
        self.assertEqual((res["schema_version"], res["upgraded"], res["attachments_migrated"]), (8, True, 1))

        # Re-run is a no-op and PDF up to 20 MB with NULL request_id/width/height is accepted
        again = migrate_postgres_business_v8(
            DSN,
            preflight_confirmed=True,
            backup_confirmed=True,
            data_root=Path(self.temp.name),
            malware_scanner=_FakeMigrationScanner(),
        )
        self.assertEqual((again["upgraded"], again["attachments_migrated"]), (False, 0))

        with transaction(DSN, self.schema, write=True) as db:
            db.execute(
                """INSERT INTO order_action_evidence(
                       evidence_id, request_id, case_id, customer_id, conversation_id, filename,
                       uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size,
                       width, height, page_count, sha256, storage_relpath,
                       scan_status, scan_engine, scanned_at, created_at, file_purged_at
                   ) VALUES ('ev_pg_pdf_20m', NULL, NULL, 'C-001', ?, 'invoice.pdf',
                             'C-001', 'customer', 'application/pdf', 20971520, NULL, NULL, 3, 'sha_pdf',
                             'evidence/shop-a/ev_pg_pdf_20m', 'clean', 'clamav', 1.0, 1.0, NULL)""",
                (conv_id,),
            )


if __name__ == "__main__":
    unittest.main()
