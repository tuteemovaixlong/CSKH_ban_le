"""Isolated unit tests for Phase R1 W2: operational hygiene, Business v5 migration, case lifecycle, timers, resume, and feedback."""
import argparse
import ast
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import urllib.parse

from retailops.bootstrap import build_public_app
from retailops.business.application import Application
from retailops.business.schema import (
    BUSINESS_V5_VERSION_MAPPING,
    POSTGRES_BUSINESS_SCHEMA_CURRENT,
    SQLITE_BUSINESS_SCHEMA_CURRENT,
)
from retailops.business.store import BusinessStore
from retailops.config import Settings
from retailops.core import ApiError, ROOT
from retailops.identity.persistent import PersistentSessions
from retailops.identity.postgres import PostgresSessions
from retailops.identity.store import IdentityStore
from retailops.storage import cli as database_cli
from retailops.storage.pg_repositories import (
    PostgresBusinessStore,
    PostgresIdentityStore,
    migrate_postgres_business_v5,
)
from retailops.storage.pg_schema import initialize as pg_initialize
from retailops.storage.postgres import BUSINESS_SCHEMA_CURRENT, IDENTITY_SCHEMA, tenant_schema


def _load_colab_ngrok_helper(rel_path: str):
    source = (ROOT / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel_path)
    fn_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "open_colab_ngrok_tunnel"
    )
    mod = ast.Module(body=[fn_node], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {"urllib": SimpleNamespace(parse=urllib.parse)}
    exec(compile(mod, rel_path, "exec"), ns)
    return ns["open_colab_ngrok_tunnel"], source


class PhaseR1W2Item0HygieneTests(unittest.TestCase):
    def test_update_ec2_refuses_execution_writes_nothing_and_has_no_patch_or_constraint_mutations(self):
        script_path = ROOT / "scripts" / "update_ec2.py"
        script_src = script_path.read_text(encoding="utf-8")
        self.assertNotIn("/opt/retailops/patches", script_src)
        self.assertNotIn("ALTER TABLE", script_src)
        self.assertNotIn("memberships_role_check", script_src)
        self.assertNotIn("subprocess", script_src)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for extra_args in ([], ["--auto-ip"], ["--api-endpoint", "https://example.ngrok-free.app/v1/chat/completions"]):
                proc = subprocess.run(
                    [sys.executable, str(script_path), *extra_args],
                    cwd=tmp_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=10,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(list(tmp_dir.iterdir()), [])
                combined = proc.stdout + proc.stderr
                self.assertIn("RETAILOPS_API_ENDPOINT", combined)
                self.assertIn("api.env", combined)
                self.assertIn("--force-recreate web", combined)
                self.assertIn("migrate-v5", combined)

    def test_colab_launchers_remove_update_ec2_and_enforce_static_ngrok_domain_rules(self):
        for rel_path in ("notebooks/colab_vllm_l4.py", "notebooks/colab_llama_server_gguf.py"):
            with self.subTest(notebook=rel_path):
                helper, src = _load_colab_ngrok_helper(rel_path)
                self.assertNotIn("update_ec2.py", src)
                self.assertIn("RETAILOPS_API_ENDPOINT", src)
                self.assertIn("--force-recreate web", src)
                self.assertIn("NGROK_DOMAIN", src)

                class _FakeNgrok:
                    def __init__(self, behavior):
                        self.behavior = behavior
                        self.auth_tokens_seen = []
                        self.connect_calls = []
                        self.disconnected = []

                    def get_tunnels(self):
                        return [SimpleNamespace(public_url="https://old.ngrok-free.app")]

                    def disconnect(self, url):
                        self.disconnected.append(url)

                    def set_auth_token(self, tok):
                        self.auth_tokens_seen.append(tok)

                    def connect(self, port, proto="http", **kwargs):
                        self.connect_calls.append((port, proto, kwargs))
                        return self.behavior(self.auth_tokens_seen[-1], port, proto, kwargs)

                # 1. Static NGROK_DOMAIN: uses ONLY first token and validates matching hostname
                ok_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: SimpleNamespace(public_url="https://shop-static.ngrok-free.app")
                )
                url = helper(
                    ok_ngrok,
                    8001,
                    ["tok-primary", "tok-secondary"],
                    ngrok_domain="shop-static.ngrok-free.app",
                )
                self.assertEqual(url, "https://shop-static.ngrok-free.app")
                self.assertEqual(ok_ngrok.auth_tokens_seen, ["tok-primary"])
                self.assertEqual(ok_ngrok.connect_calls, [(8001, "http", {"domain": "shop-static.ngrok-free.app"})])
                self.assertIn("https://old.ngrok-free.app", ok_ngrok.disconnected)

                # 2. Static NGROK_DOMAIN: when first token fails, must NOT try second token
                fail_domain_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: (_ for _ in ()).throw(RuntimeError("domain not owned"))
                )
                with self.assertRaises(RuntimeError) as dom_fail:
                    helper(
                        fail_domain_ngrok,
                        8001,
                        ["tok-primary", "tok-secondary"],
                        ngrok_domain="shop-static.ngrok-free.app",
                    )
                self.assertEqual(fail_domain_ngrok.auth_tokens_seen, ["tok-primary"])
                self.assertIn("shop-static.ngrok-free.app", str(dom_fail.exception))

                # 3. Static NGROK_DOMAIN: mismatched returned URL disconnects and raises RuntimeError
                mismatch_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: SimpleNamespace(public_url="https://random-other.ngrok-free.app")
                )
                with self.assertRaises(RuntimeError) as mis_err:
                    helper(
                        mismatch_ngrok,
                        8001,
                        ["tok-primary"],
                        ngrok_domain="shop-static.ngrok-free.app",
                    )
                self.assertIn("không khớp", str(mis_err.exception))
                self.assertIn("https://random-other.ngrok-free.app", mismatch_ngrok.disconnected)

                # 4. Dynamic tunnel (no NGROK_DOMAIN): falls back to second token, and errors clearly when all fail
                fallback_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: (
                        (_ for _ in ()).throw(RuntimeError("quota exceeded"))
                        if tok == "tok-1"
                        else SimpleNamespace(public_url="https://dynamic-ok.ngrok-free.app")
                    )
                )
                dyn_url = helper(fallback_ngrok, 8001, ["tok-1", "tok-2"], ngrok_domain="")
                self.assertEqual(dyn_url, "https://dynamic-ok.ngrok-free.app")
                self.assertEqual(fallback_ngrok.auth_tokens_seen, ["tok-1", "tok-2"])

                all_fail_ngrok = _FakeNgrok(
                    lambda tok, port, proto, kw: (_ for _ in ()).throw(RuntimeError(f"bad {tok}"))
                )
                with self.assertRaises(RuntimeError) as all_fail_err:
                    helper(all_fail_ngrok, 8001, ["tok-1", "tok-2"], ngrok_domain="")
                self.assertIn("tok-1", str(all_fail_err.exception))
                self.assertIn("tok-2", str(all_fail_err.exception))

                with self.assertRaises(RuntimeError):
                    helper(all_fail_ngrok, 8001, ["  ", ""], ngrok_domain="")


class PhaseR1W2BusinessV5MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_item1_fresh_db_v5_tables_version_mapping_and_no_cascade_on_conversation_cleanup(self):
        self.assertEqual(SQLITE_BUSINESS_SCHEMA_CURRENT, 4)
        self.assertEqual(POSTGRES_BUSINESS_SCHEMA_CURRENT, 5)
        self.assertEqual(BUSINESS_SCHEMA_CURRENT, 5)
        self.assertEqual(
            BUSINESS_V5_VERSION_MAPPING,
            {"logical_milestone": "business_v5", "sqlite": 4, "postgresql": 5},
        )

        # 1. Fresh SQLite BusinessStore creates SQLite v4 (logical Business v5) directly; no W3 v6 tables
        fresh_sqlite = self.root / "fresh_business.sqlite3"
        store = BusinessStore(fresh_sqlite)
        store.seed()
        with store.connection() as db:
            ver_row = db.execute("SELECT component, version FROM retailops_schema").fetchone()
            self.assertEqual((ver_row["component"], ver_row["version"]), ("business", 4))
            tables = {
                r[0]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
        self.assertTrue({"cases", "handoff_episodes", "case_feedback_events"}.issubset(tables))
        self.assertFalse(tables & {"order_action_requests", "order_action_decisions", "integration_outbox"})

        # Expired conversation cleanup MUST NOT cascade-delete cases, handoff_episodes, or case_feedback_events
        now = time.time()
        with store.connection(write=True) as db:
            db.execute(
                "INSERT INTO conversations(id, customer_id, expires_at, provider_id) VALUES ('exp-conv-1', 'C-001', ?, 'custom')",
                (now - 60,),
            )
            db.execute(
                "INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at) "
                "VALUES ('exp-conv-1', 'C-001', 'req-exp-1', 'h1', '[]', '{}', ?)",
                (now - 120,),
            )
            turn_id = db.execute("SELECT id FROM agent_turns WHERE conversation_id='exp-conv-1'").fetchone()[0]
            db.execute(
                """INSERT INTO cases(
                       case_id, conversation_id, customer_id, status, version,
                       resolved_reason, resolved_at, created_at, updated_at
                   ) VALUES ('case_exp_1', 'exp-conv-1', 'C-001', 'resolved', 2, 'staff_resolved', ?, ?, ?)""",
                (now - 80, now - 200, now - 80),
            )
            db.execute(
                """INSERT INTO handoff_episodes(
                       handoff_id, case_id, conversation_id, customer_id, status, reason_code, created_at, closed_at
                   ) VALUES ('hoff_exp_1', 'case_exp_1', 'exp-conv-1', 'C-001', 'resolved', 'need_human', ?, ?)""",
                (now - 150, now - 80),
            )
            db.execute(
                """INSERT INTO case_feedback_events(
                       feedback_event_id, case_id, conversation_id, turn_id, customer_id,
                       feedback_type, raw_value, rating, sentiment_flag, preference_label, created_at
                   ) VALUES ('cfbk_exp_1', 'case_exp_1', 'exp-conv-1', ?, 'C-001', 'session_csat', '5', 5, 'positive', 'chosen', ?)""",
                (turn_id, now - 90),
            )
        # Trigger expired conversation cleanup via new_conversation
        store.new_conversation("C-001")
        with store.connection() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM conversations WHERE id='exp-conv-1'").fetchone())
            self.assertIsNotNone(db.execute("SELECT 1 FROM cases WHERE case_id='case_exp_1'").fetchone())
            self.assertIsNotNone(db.execute("SELECT 1 FROM handoff_episodes WHERE handoff_id='hoff_exp_1'").fetchone())
            self.assertIsNotNone(
                db.execute("SELECT 1 FROM case_feedback_events WHERE feedback_event_id='cfbk_exp_1'").fetchone()
            )

    def test_item2_sqlite_multi_tenant_v4_to_v5_controlled_migration_and_backfill(self):
        legacy_root = self.root / "legacy_biz_v4_sqlite"
        pers = legacy_root / "persistent"
        tenants_dir = pers / "tenants"
        tenants_dir.mkdir(parents=True, exist_ok=True)
        id_store = IdentityStore(pers / "identity.sqlite3")
        t1 = id_store.ensure_tenant("shop-alpha", "Shop Alpha")
        t2 = id_store.ensure_tenant("shop-beta", "Shop Beta")
        t1_path = tenants_dir / f"{t1['storage_key']}.sqlite3"
        t2_path = tenants_dir / f"{t2['storage_key']}.sqlite3"

        def _seed_pre_v5_sqlite(p: Path, *, with_open_handoff: bool):
            b = BusinessStore(p)
            b.seed()
            with closing(sqlite3.connect(p)) as db, db:
                db.execute("DROP TABLE case_feedback_events")
                db.execute("DROP TABLE handoff_episodes")
                db.execute("DROP TABLE cases")
                db.execute("UPDATE retailops_schema SET version=3 WHERE component='business'")
                db.execute(
                    "INSERT INTO conversations(id, customer_id, expires_at, provider_id) VALUES ('conv-open', 'C-001', 1999999999.0, 'custom')"
                )
                db.execute(
                    "INSERT INTO conversations(id, customer_id, expires_at, provider_id) VALUES ('conv-closed-handoff', 'C-002', 1999999999.0, 'custom')"
                )
                db.execute(
                    "INSERT INTO conversations(id, customer_id, expires_at, provider_id) VALUES ('conv-bot-only', 'C-003', 1999999999.0, 'custom')"
                )
                if with_open_handoff:
                    db.execute(
                        "INSERT INTO conversation_feedback(conversation_id, customer_id, feedback_type, reason_code, comment, created_at) "
                        "VALUES ('conv-open', 'C-001', 'human_handoff', 'customer_requested_human', 'Cần hỗ trợ gấp', 1700000100.0)"
                    )
                db.execute(
                    "INSERT INTO conversation_feedback(conversation_id, customer_id, feedback_type, reason_code, comment, created_at) "
                    "VALUES ('conv-closed-handoff', 'C-002', 'human_handoff', 'resolved', 'Đã xong', 1700000200.0)"
                )
                db.execute(
                    "INSERT INTO conversation_feedback(conversation_id, customer_id, feedback_type, rating, sentiment_flag, created_at) "
                    "VALUES ('conv-bot-only', 'C-003', 'session_csat', 5, 'positive', 1700000300.0)"
                )

        _seed_pre_v5_sqlite(t1_path, with_open_handoff=True)
        _seed_pre_v5_sqlite(t2_path, with_open_handoff=False)

        def _snap(p: Path):
            uri = p.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as rdb:
                ver = rdb.execute("SELECT version FROM retailops_schema WHERE component='business'").fetchone()[0]
                tbls = sorted(
                    r[0]
                    for r in rdb.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                )
                fbs = rdb.execute(
                    "SELECT conversation_id, feedback_type, reason_code, rating FROM conversation_feedback ORDER BY id"
                ).fetchall()
                return ver, tbls, fbs

        snap1_before = _snap(t1_path)
        snap2_before = _snap(t2_path)
        self.assertEqual(snap1_before[0], 3)
        self.assertNotIn("cases", snap1_before[1])

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", required=True)
        database_cli.add_parser(sub)

        # 1. Store init, PersistentSessions, build_public_app, and ordinary CLI check fail closed with 503 and ZERO writes
        with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
            for blocked_call in (
                lambda: BusinessStore(t1_path),
                lambda: BusinessStore(t1_path, create=False, initialize_db=False, read_only=False),
                lambda: PersistentSessions(pers),
                lambda: build_public_app(
                    Settings(
                        interface="public",
                        bind="127.0.0.1",
                        port=8000,
                        origin="https://retailops.example.com",
                        access_token="unused-token-" + "z" * 32,
                        output=legacy_root,
                        data_mode="persistent-demo",
                    )
                ),
                lambda: database_cli.run(parser.parse_args(["database", "--output", str(legacy_root), "check"])),
            ):
                with self.assertRaises(ApiError) as err:
                    blocked_call()
                self.assertEqual((err.exception.status, err.exception.code), (503, "business_migration_required"))

            # Missing confirmation flags rejected with 400 and ZERO writes
            for unconf in (
                ["database", "--output", str(legacy_root), "migrate-v5"],
                ["database", "--output", str(legacy_root), "migrate-v5", "--confirm-preflight"],
                ["database", "--output", str(legacy_root), "migrate-v5", "--confirm-backup"],
            ):
                with self.assertRaises(ApiError) as cerr:
                    database_cli.run(parser.parse_args(unconf))
                self.assertEqual((cerr.exception.status, cerr.exception.code), (400, "migration_confirmation_required"))

        self.assertEqual(_snap(t1_path), snap1_before)
        self.assertEqual(_snap(t2_path), snap2_before)

        # 2. Explicit operator migrate-v5 upgrades ALL tenants, backfills exact cases/episodes, preserves conversation_feedback
        with patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "sqlite"}, clear=False):
            res1 = database_cli.run(
                parser.parse_args(
                    ["database", "--output", str(legacy_root), "migrate-v5", "--confirm-preflight", "--confirm-backup"]
                )
            )
            self.assertEqual(
                res1,
                {
                    "result": "BUSINESS_V5_MIGRATED",
                    "backend": "sqlite",
                    "schema_version": 4,
                    "logical_version": 5,
                    "tenants": 2,
                    "upgraded": True,
                    "cases_created": 6,
                    "episodes_created": 1,
                },
            )
            # Re-running is 100% idempotent
            res2 = database_cli.run(
                parser.parse_args(
                    ["database", "--output", str(legacy_root), "migrate-v5", "--confirm-preflight", "--confirm-backup"]
                )
            )
            self.assertEqual(res2["upgraded"], False)
            self.assertEqual(res2["cases_created"], 0)
            self.assertEqual(res2["episodes_created"], 0)
            chk = database_cli.run(parser.parse_args(["database", "--output", str(legacy_root), "check"]))
            self.assertEqual(chk, {"result": "SQLITE_SCHEMA_READY", "tenants_checked": 2})

        # Inspect backfilled rows in tenant 1 & tenant 2 and verify conversation_feedback was untouched
        b1 = BusinessStore(t1_path)
        b2 = BusinessStore(t2_path)
        with b1.connection() as db:
            cases_t1 = {
                r["conversation_id"]: dict(r) for r in db.execute("SELECT * FROM cases").fetchall()
            }
            eps_t1 = [dict(r) for r in db.execute("SELECT * FROM handoff_episodes").fetchall()]
            fbs_t1 = db.execute(
                "SELECT conversation_id, feedback_type, reason_code, rating FROM conversation_feedback ORDER BY id"
            ).fetchall()
        self.assertEqual(cases_t1["conv-open"]["status"], "waiting")
        self.assertIsNone(cases_t1["conv-open"]["resolved_reason"])
        self.assertEqual(cases_t1["conv-closed-handoff"]["status"], "resolved")
        self.assertEqual(cases_t1["conv-closed-handoff"]["resolved_reason"], "migrated_v5")
        self.assertEqual(cases_t1["conv-bot-only"]["status"], "resolved")
        self.assertEqual(cases_t1["conv-bot-only"]["resolved_reason"], "migrated_v5")
        self.assertEqual(len(eps_t1), 1)
        self.assertEqual(eps_t1[0]["case_id"], cases_t1["conv-open"]["case_id"])
        self.assertEqual(eps_t1[0]["status"], "pending")
        self.assertEqual(eps_t1[0]["comment"], "Cần hỗ trợ gấp")
        self.assertEqual([tuple(r) for r in fbs_t1], [tuple(r) for r in snap1_before[2]])

        with b2.connection() as db:
            cases_t2 = {r["conversation_id"]: dict(r) for r in db.execute("SELECT * FROM cases").fetchall()}
            eps_t2 = db.execute("SELECT * FROM handoff_episodes").fetchall()
        self.assertEqual({c["status"] for c in cases_t2.values()}, {"resolved"})
        self.assertEqual({c["resolved_reason"] for c in cases_t2.values()}, {"migrated_v5"})
        self.assertEqual(eps_t2, [])

    def test_item1_and_item2_postgres_mock_fresh_and_v4_to_v5_multi_tenant_migration(self):
        pg_dsn = "postgresql://retailops:secret@127.0.0.1:5432/retailops"
        key_a = "a" * 32
        key_b = "b" * 32
        schema_a = tenant_schema(key_a)
        schema_b = tenant_schema(key_b)

        # Back each mocked PostgreSQL tenant schema by an in-memory SQLite engine for exact SQL/backfill fidelity
        class _PgState:
            def __init__(self):
                self.identity_version = 5
                self.tenants = [
                    {"id": "shop-a", "storage_key": key_a},
                    {"id": "shop-b", "storage_key": key_b},
                ]
                self.schemas = {}
                self.sql_log = []

            def add_v4_tenant(self, schema_name: str, *, with_open_handoff: bool):
                mem = sqlite3.connect(":memory:")
                mem.row_factory = sqlite3.Row
                mem.executescript(
                    """
                    CREATE TABLE retailops_schema(component TEXT PRIMARY KEY, version INTEGER NOT NULL);
                    INSERT INTO retailops_schema VALUES ('business', 4);
                    CREATE TABLE customers(id TEXT PRIMARY KEY, name TEXT NOT NULL);
                    INSERT INTO customers VALUES ('C-001', 'A'), ('C-002', 'B');
                    CREATE TABLE conversations(id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_id TEXT, product_id TEXT, revision INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL, provider_id TEXT NOT NULL DEFAULT 'custom');
                    CREATE TABLE agent_turns(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, customer_id TEXT NOT NULL, request_id TEXT NOT NULL, input_hash TEXT NOT NULL, messages TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL);
                    CREATE TABLE conversation_feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, turn_id INTEGER, customer_id TEXT NOT NULL, feedback_type TEXT NOT NULL, rating INTEGER, sentiment_flag TEXT, reason_code TEXT, comment TEXT, created_at REAL NOT NULL);
                    """
                )
                mem.execute("INSERT INTO conversations VALUES ('pg-conv-1', 'C-001', NULL, NULL, 0, 1999999999.0, 'custom')")
                mem.execute("INSERT INTO conversations VALUES ('pg-conv-2', 'C-002', NULL, NULL, 0, 1999999999.0, 'custom')")
                if with_open_handoff:
                    mem.execute(
                        "INSERT INTO conversation_feedback(conversation_id, customer_id, feedback_type, reason_code, comment, created_at) "
                        "VALUES ('pg-conv-1', 'C-001', 'human_handoff', 'need_human', 'PG handoff', 1700000500.0)"
                    )
                mem.execute(
                    "INSERT INTO conversation_feedback(conversation_id, customer_id, feedback_type, reason_code, comment, created_at) "
                    "VALUES ('pg-conv-2', 'C-002', 'human_handoff', 'resolved', 'PG done', 1700000600.0)"
                )
                mem.commit()
                self.schemas[schema_name] = mem

        state = _PgState()
        state.add_v4_tenant(schema_a, with_open_handoff=True)
        state.add_v4_tenant(schema_b, with_open_handoff=False)

        class _CursorAdapter:
            def __init__(self, rows):
                self._rows = rows

            def fetchone(self):
                return self._rows[0] if self._rows else None

            def fetchall(self):
                return list(self._rows)

        class _MockPgConn:
            def __init__(self, active_schema: str):
                self.active_schema = active_schema
                self.raw = self

            def execute(self, query, params=()):
                q = str(query).strip()
                norm_params = tuple(params) if params else ()
                state.sql_log.append((self.active_schema, q))
                q_qmark = q.replace("%s", "?")

                if "pg_extension" in q:
                    return _CursorAdapter([{"schema": "retailops_extensions", "version": "0.8.6"}])
                if "pg_namespace" in q:
                    target_ns = norm_params[0]
                    exists = target_ns == IDENTITY_SCHEMA or target_ns in state.schemas
                    return _CursorAdapter([{"exists": 1}] if exists else [])
                if q.startswith("SET LOCAL search_path TO "):
                    target = q.split("SET LOCAL search_path TO ", 1)[1].split(",", 1)[0].strip().strip('"')
                    self.active_schema = target
                    return _CursorAdapter([])
                if q.startswith("CREATE SCHEMA "):
                    new_s = q.split("CREATE SCHEMA ", 1)[1].strip().strip('"')
                    mem = sqlite3.connect(":memory:")
                    mem.row_factory = sqlite3.Row
                    mem.create_function("to_tsvector", 2, lambda cfg, txt: txt or "", deterministic=True)
                    state.schemas[new_s] = mem
                    self.active_schema = new_s
                    return _CursorAdapter([])
                if q.startswith("REVOKE ALL ON SCHEMA ") or "USING gin" in q or "USING hnsw" in q:
                    return _CursorAdapter([])
                if "information_schema.tables" in q:
                    t_schema = norm_params[0]
                    mem = state.schemas.get(t_schema)
                    has_cases = bool(
                        mem and mem.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'").fetchone()
                    )
                    return _CursorAdapter([{"exists": 1}] if has_cases else [])
                if ".retailops_schema" in q:
                    prefix = q.split("FROM ", 1)[1].split(".retailops_schema", 1)[0].strip().strip('"')
                    if prefix == IDENTITY_SCHEMA:
                        return _CursorAdapter([{"component": "identity", "version": state.identity_version}])
                    mem = state.schemas[prefix]
                    rows = [dict(r) for r in mem.execute("SELECT component, version FROM retailops_schema").fetchall()]
                    return _CursorAdapter(rows)

                if self.active_schema == IDENTITY_SCHEMA:
                    if "SELECT version FROM retailops_schema" in q:
                        return _CursorAdapter([{"version": state.identity_version}])
                    if "FROM tenants" in q:
                        return _CursorAdapter(list(state.tenants))
                    return _CursorAdapter([])

                mem = state.schemas[self.active_schema]
                sql_sqlite = (
                    q_qmark.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                    .replace("DOUBLE PRECISION", "REAL")
                    .replace("retailops_extensions.vector(384)", "TEXT")
                    .replace("tsvector GENERATED", "TEXT GENERATED")
                    .replace("char_length(", "length(")
                )
                cur = mem.execute(sql_sqlite, norm_params)
                mem.commit()
                if cur.description:
                    return _CursorAdapter([dict(r) for r in cur.fetchall()])
                return _CursorAdapter([])

        mock_psycopg = MagicMock()
        mock_psycopg.conninfo.conninfo_to_dict.return_value = {"dbname": "retailops", "user": "retailops"}
        mock_sql = MagicMock()
        mock_sql.SQL = lambda s: SimpleNamespace(format=lambda *a: s.format(*a))
        mock_sql.Identifier = lambda s: s
        mock_psycopg.sql = mock_sql

        @contextmanager
        def _fake_tx(dsn, schema=IDENTITY_SCHEMA, *, write=False, read_only=False):
            yield _MockPgConn(schema)

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", required=True)
        database_cli.add_parser(sub)

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.sql": mock_sql}), \
             patch("retailops.storage.pg_repositories.transaction", side_effect=_fake_tx), \
             patch("retailops.storage.postgres.transaction", side_effect=_fake_tx), \
             patch("retailops.identity.postgres.transaction", side_effect=_fake_tx), \
             patch("retailops.storage.cli.os.environ", {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": pg_dsn}), \
             patch.dict(os.environ, {"RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": pg_dsn}, clear=False):

            # 1. Startup, store init, direct pg_initialize, and ordinary CLI fail closed on PG v4 with ZERO schema/data changes
            for pg_blocked in (
                lambda: pg_initialize(_MockPgConn(schema_a), schema_a, "business"),
                lambda: PostgresBusinessStore(pg_dsn, key_a, create=False),
                lambda: PostgresSessions(pg_dsn),
                lambda: database_cli.run(parser.parse_args(["database", "check"])),
                lambda: database_cli.run(parser.parse_args(["database", "migrate"])),
            ):
                with self.assertRaises(ApiError) as b_err:
                    pg_blocked()
                self.assertEqual((b_err.exception.status, b_err.exception.code), (503, "business_migration_required"))

            with self.assertRaises(ApiError) as unconf_pg:
                database_cli.run(parser.parse_args(["database", "migrate-v5", "--confirm-preflight"]))
            self.assertEqual((unconf_pg.exception.status, unconf_pg.exception.code), (400, "migration_confirmation_required"))

            for sc in (schema_a, schema_b):
                ver = state.schemas[sc].execute("SELECT version FROM retailops_schema").fetchone()[0]
                self.assertEqual(ver, 4)
                self.assertIsNone(
                    state.schemas[sc].execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'").fetchone()
                )

            # 2. Explicit operator migrate-v5 upgrades BOTH PG tenant schemas to v5 and backfills accurately
            mig_pg_1 = database_cli.run(
                parser.parse_args(["database", "migrate-v5", "--confirm-preflight", "--confirm-backup"])
            )
            self.assertEqual(
                mig_pg_1,
                {
                    "result": "BUSINESS_V5_MIGRATED",
                    "backend": "postgresql",
                    "schema_version": 5,
                    "logical_version": 5,
                    "tenants": 2,
                    "upgraded": True,
                    "cases_created": 4,
                    "episodes_created": 1,
                },
            )
            mig_pg_2 = migrate_postgres_business_v5(pg_dsn, preflight_confirmed=True, backup_confirmed=True)
            self.assertEqual(mig_pg_2["upgraded"], False)
            self.assertEqual(mig_pg_2["cases_created"], 0)
            self.assertEqual(mig_pg_2["episodes_created"], 0)

            for sc in (schema_a, schema_b):
                ver = state.schemas[sc].execute("SELECT version FROM retailops_schema").fetchone()[0]
                self.assertEqual(ver, 5)
                fb_cnt = state.schemas[sc].execute("SELECT COUNT(*) FROM conversation_feedback").fetchone()[0]
                self.assertGreaterEqual(fb_cnt, 1)

            cases_a = {
                r["conversation_id"]: dict(r)
                for r in state.schemas[schema_a].execute("SELECT * FROM cases").fetchall()
            }
            self.assertEqual(cases_a["pg-conv-1"]["status"], "waiting")
            self.assertEqual(cases_a["pg-conv-2"]["status"], "resolved")
            self.assertEqual(cases_a["pg-conv-2"]["resolved_reason"], "migrated_v5")

            # 3. Fresh PostgreSQL tenant schema initializes directly to v5
            key_c = "c" * 32
            PostgresBusinessStore(pg_dsn, key_c, create=True)
            schema_c = tenant_schema(key_c)
            self.assertEqual(
                state.schemas[schema_c].execute("SELECT version FROM retailops_schema").fetchone()[0],
                5,
            )
            self.assertIsNotNone(
                state.schemas[schema_c].execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'").fetchone()
            )


class _SimpleAgent:
    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.seen_messages = []

    def inspect(self):
        return {"name": "fixture", "digest": "fix-1", "provider": "custom", "agent_protocol": "retailops-agent-v2"}

    def chat(self, messages, allow_tools, timeout):
        self.seen_messages.append(list(messages))
        if self.replies:
            nxt = self.replies.pop(0)
        else:
            nxt = {"message": {"role": "assistant", "content": "Phản hồi tự động từ bot."}}
        return {
            "prompt_eval_count": 20,
            "eval_count": 10,
            "reported_cost_usd": 0.0,
            **nxt,
        }


class PhaseR1W2CaseHandoffResumeFeedbackTests(unittest.TestCase):
    """Items 3, 4, 9, and 10: Case creation, durable handoff episodes, resume/retention, and feedback mapping."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1_762_100_000.0
        self.store = BusinessStore(Path(self.tmp.name) / "biz.sqlite3")
        self.store.clock = lambda: self.now
        self.store.seed()
        self.agent = _SimpleAgent()
        from retailops.business.application import Application

        self.app = Application(self.store, {}, self.agent)

    def test_item3_new_conversation_creates_waiting_case_and_bot_only_stays_off_staff_desk(self):
        from retailops.http.routes import api_result

        status, created = api_result(self.app, "C-001", "POST", "/api/conversations", {"provider_id": "custom"})
        self.assertEqual(status, 201)
        cid = created["conversation_id"]
        case_id = created["case_id"]
        self.assertTrue(case_id.startswith("case_"))

        with self.store.connection() as db:
            row = dict(db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone())
            ep_cnt = db.execute("SELECT COUNT(*) FROM handoff_episodes WHERE case_id = ?", (case_id,)).fetchone()[0]
        self.assertEqual(row["conversation_id"], cid)
        self.assertEqual(row["customer_id"], "C-001")
        self.assertEqual(row["status"], "waiting")
        self.assertIsNone(row["holder"])
        self.assertEqual(row["version"], 1)
        self.assertEqual(ep_cnt, 0)

        # Pure bot chat turn never puts the case on Staff Desk
        self.app.chat("C-001", {"conversation_id": cid, "text": "Xin chào shop", "request_id": "r" * 24})
        self.assertEqual(self.store.escalations(), [])

    def test_item4_all_three_handoff_paths_durable_fail_closed_and_single_open_episode(self):
        from retailops.http.routes import api_result
        from retailops_tools import BoundTools

        # Path 1: POST /api/feedback (human_handoff) + idempotent second call
        c1 = self.app.new_conversation("C-001", {})
        cid1, case1 = c1["conversation_id"], c1["case_id"]
        st1, fb1 = api_result(
            self.app,
            "C-001",
            "POST",
            "/api/feedback",
            {"conversation_id": cid1, "feedback_type": "human_handoff", "comment": "Cần gặp nhân viên"},
        )
        self.assertEqual(st1, 200)
        self.assertEqual(fb1["case_id"], case1)
        self.assertTrue(fb1["handoff_id"].startswith("hoff_"))

        _, fb1_dup = api_result(
            self.app,
            "C-001",
            "POST",
            "/api/feedback",
            {"conversation_id": cid1, "feedback_type": "human_handoff", "comment": "Nhắc lại lần 2"},
        )
        self.assertEqual(fb1_dup["handoff_id"], fb1["handoff_id"])
        with self.store.connection() as db:
            open_eps = db.execute(
                "SELECT * FROM handoff_episodes WHERE case_id = ? AND status = 'pending'", (case1,)
            ).fetchall()
        self.assertEqual(len(open_eps), 1)
        self.assertEqual(open_eps[0]["comment"], "Nhắc lại lần 2")

        # Path 2: POST /api/staff/customer-message writes customer turn + handoff atomically
        c2 = self.app.new_conversation("C-001", {})
        cid2, case2 = c2["conversation_id"], c2["case_id"]
        st2, cm2 = api_result(
            self.app,
            "C-001",
            "POST",
            "/api/staff/customer-message",
            {"conversation_id": cid2, "message": "Shop kiểm tra đơn gấp giúp em"},
        )
        self.assertEqual(st2, 200)
        self.assertEqual(cm2["case_id"], case2)
        self.assertTrue(cm2["handoff_id"].startswith("hoff_"))

        # Verify atomic rollback on DB failure inside customer_message
        c2_fail = self.app.new_conversation("C-001", {})
        cid2_fail = c2_fail["conversation_id"]
        with patch.object(self.store, "_request_human_handoff_in_tx", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(ApiError):
                self.store.customer_message("C-001", cid2_fail, "Tin nhắn lỗi DB")
        with self.store.connection() as db:
            turns_fail = db.execute("SELECT COUNT(*) FROM agent_turns WHERE conversation_id = ?", (cid2_fail,)).fetchone()[0]
            eps_fail = db.execute("SELECT COUNT(*) FROM handoff_episodes WHERE conversation_id = ?", (cid2_fail,)).fetchone()[0]
        self.assertEqual((turns_fail, eps_fail), (0, 0))

        # Path 3: request_human_support tool — no Mai Anh, fails closed on DB error
        c3 = self.app.new_conversation("C-001", {})
        cid3, case3 = c3["conversation_id"], c3["case_id"]
        snap3 = self.store.conversation("C-001", cid3)
        ro_store = BusinessStore(Path(self.tmp.name) / "biz.sqlite3", create=False, initialize_db=False, read_only=True)
        bound_fail = BoundTools(ro_store, self.app.catalog, "C-001", snap3, self.agent.inspect())
        with self.assertRaises(ApiError):
            bound_fail("request_human_support", {"reason": "Cần hỗ trợ trên kho chỉ đọc"})
        self.assertIsNone(bound_fail.human_support)
        with self.store.connection() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM handoff_episodes WHERE case_id = ?", (case3,)).fetchone()[0], 0
            )

        bound_ok = BoundTools(self.store, self.app.catalog, "C-001", snap3, self.agent.inspect())
        tool_res = bound_ok("request_human_support", {"reason": "Cần nhân viên tư vấn đổi mẫu"})
        self.assertEqual(tool_res["status"], "escalated_to_human")
        self.assertEqual(tool_res["case_id"], case3)
        self.assertTrue(tool_res["handoff_id"].startswith("hoff_"))
        self.assertNotIn("support_rep", tool_res)
        self.assertNotIn("Mai Anh", json.dumps(tool_res, ensure_ascii=False))

    def test_item9_resume_within_and_past_retention_and_concurrency_safety(self):
        import threading
        from retailops.http.routes import api_result

        created = self.app.new_conversation("C-001", {})
        cid, case_id_1 = created["conversation_id"], created["case_id"]
        self.agent.replies = [{"message": {"role": "assistant", "content": "Đơn O-101 đang chờ xử lý."}}]
        self.app.chat("C-001", {"conversation_id": cid, "text": "Kiểm tra đơn O-101", "request_id": "a" * 24})

        # Close case at self.now
        with self.store.connection(write=True) as db:
            db.execute(
                "UPDATE cases SET status = 'resolved', resolved_reason = 'inactivity', resolved_at = ?, version = version + 1 WHERE case_id = ?",
                (self.now, case_id_1),
            )

        # 1. Concurrent resume WITHIN retention -> reopens SAME case_id, increments resume_count ONCE
        self.now += 3600.0
        barrier = threading.Barrier(4)
        results_within = []
        errors_within = []

        def _worker_within():
            try:
                barrier.wait(timeout=5)
                results_within.append(self.store.resume_case("C-001", cid))
            except Exception as exc:  # pragma: no cover
                errors_within.append(exc)

        threads = [threading.Thread(target=_worker_within) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(errors_within, [])
        self.assertEqual({r["case_id"] for r in results_within}, {case_id_1})

        with self.store.connection() as db:
            row_reopened = dict(db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id_1,)).fetchone())
            total_cases = db.execute("SELECT COUNT(*) FROM cases WHERE conversation_id = ?", (cid,)).fetchone()[0]
        self.assertEqual(total_cases, 1)
        self.assertEqual(row_reopened["status"], "waiting")
        self.assertEqual(row_reopened["resume_count"], 1)
        self.assertEqual(row_reopened["resumed_at"], self.now)

        # Next chat turn within retention loads prior DB history cleanly
        self.agent.seen_messages.clear()
        self.agent.replies = [{"message": {"role": "assistant", "content": "Em tiếp tục hỗ trợ đơn O-101 ạ."}}]
        self.app.chat("C-001", {"conversation_id": cid, "text": "Hỏi tiếp về đơn vừa rồi", "request_id": "b" * 24})
        prompt_text = json.dumps(self.agent.seen_messages[-1], ensure_ascii=False)
        self.assertIn("Kiểm tra đơn O-101", prompt_text)

        # 2. Close case again, advance clock PAST 7-day retention AND trigger conversation TTL cleanup
        with self.store.connection(write=True) as db:
            db.execute(
                "UPDATE cases SET status = 'resolved', resolved_reason = 'completed', resolved_at = ?, version = version + 1 WHERE case_id = ?",
                (self.now, case_id_1),
            )
        self.now += self.store.CONVERSATION_TTL + 120.0
        # Trigger expired conversations cleanup via another new_conversation
        self.store.new_conversation("C-002")

        # Concurrent resume PAST retention -> creates ONE new case_id with previous_case_id = case_id_1
        barrier2 = threading.Barrier(4)
        results_past = []
        errors_past = []

        def _worker_past():
            try:
                barrier2.wait(timeout=5)
                _, resp = api_result(self.app, "C-001", "POST", f"/api/conversations/{cid}/resume", {})
                results_past.append(resp)
            except Exception as exc:  # pragma: no cover
                errors_past.append(exc)

        threads2 = [threading.Thread(target=_worker_past) for _ in range(4)]
        for t in threads2:
            t.start()
        for t in threads2:
            t.join(timeout=5)
        self.assertEqual(errors_past, [])
        new_case_ids = {r["case_id"] for r in results_past}
        self.assertEqual(len(new_case_ids), 1)
        case_id_2 = next(iter(new_case_ids))
        self.assertNotEqual(case_id_2, case_id_1)

        with self.store.connection() as db:
            open_cases = db.execute(
                "SELECT * FROM cases WHERE conversation_id = ? AND status <> 'resolved'", (cid,)
            ).fetchall()
        self.assertEqual(len(open_cases), 1)
        self.assertEqual(open_cases[0]["case_id"], case_id_2)
        self.assertEqual(open_cases[0]["previous_case_id"], case_id_1)
        self.assertEqual(open_cases[0]["resume_count"], 0)

        # Expired case turns must NOT leak into the new case's LLM prompt
        self.agent.seen_messages.clear()
        self.agent.replies = [{"message": {"role": "assistant", "content": "Chào mừng anh/chị quay lại ở ca mới!"}}]
        self.app.chat("C-001", {"conversation_id": cid, "text": "Mở câu hỏi mới", "request_id": "c" * 24})
        new_prompt_text = json.dumps(self.agent.seen_messages[-1], ensure_ascii=False)
        self.assertNotIn("Kiểm tra đơn O-101", new_prompt_text)

    def test_item10_case_feedback_events_mapping_and_never_mutates_case_or_timers(self):
        created = self.app.new_conversation("C-001", {})
        cid, case_id = created["conversation_id"], created["case_id"]
        r = self.app.chat("C-001", {"conversation_id": cid, "text": "Tư vấn áo thun", "request_id": "d" * 24})
        turn_id = r["turn_id"]

        # Seed active timer deadlines on the case to verify feedback never touches them or closes the case
        rem_dl = self.now + 300.0
        comp_dl = self.now + 250.0
        with self.store.connection(write=True) as db:
            db.execute(
                """UPDATE cases
                   SET reminder_deadline = ?, completion_deadline = ?, feedback_prompted_at = ?
                   WHERE case_id = ?""",
                (rem_dl, comp_dl, self.now, case_id),
            )
            before_case = dict(db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone())

        # Turn rating: like -> chosen, dislike -> rejected, neutral -> no case_feedback_events row
        like_res = self.store.record_feedback(
            "C-001", {"conversation_id": cid, "turn_id": turn_id, "feedback_type": "turn_rating", "vote": "like"}
        )
        dislike_res = self.store.record_feedback(
            "C-001", {"conversation_id": cid, "turn_id": turn_id, "feedback_type": "turn_rating", "vote": "dislike"}
        )
        neutral_res = self.store.record_feedback(
            "C-001", {"conversation_id": cid, "turn_id": turn_id, "feedback_type": "turn_rating", "sentiment_flag": "neutral"}
        )
        self.assertEqual((like_res["preference_label"], like_res["raw_value"]), ("chosen", "like"))
        self.assertEqual((dislike_res["preference_label"], dislike_res["raw_value"]), ("rejected", "dislike"))
        self.assertNotIn("feedback_event_id", neutral_res)

        # Session CSAT: 1..3 -> rejected, 4..5 -> chosen
        expected_csat = {1: "rejected", 2: "rejected", 3: "rejected", 4: "chosen", 5: "chosen"}
        for stars, expected_lbl in expected_csat.items():
            csat_res = self.store.record_feedback(
                "C-001", {"conversation_id": cid, "feedback_type": "session_csat", "rating": stars}
            )
            self.assertEqual(csat_res["preference_label"], expected_lbl)
            self.assertEqual(csat_res["raw_value"], str(stars))

        with self.store.connection() as db:
            ev_rows = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM case_feedback_events WHERE case_id = ? ORDER BY created_at ASC", (case_id,)
                ).fetchall()
            ]
            after_case = dict(db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone())

        self.assertEqual(len(ev_rows), 7)  # 2 turn_rating + 5 session_csat (neutral skipped)
        self.assertEqual(after_case["status"], "waiting")
        self.assertEqual(after_case["version"], before_case["version"])
        self.assertEqual(after_case["reminder_deadline"], rem_dl)
        self.assertEqual(after_case["completion_deadline"], comp_dl)


class PhaseR1W2StaffDeskClaimResolveReadOnlyTests(unittest.TestCase):
    """Items 5, 6, and 7: Concurrent claim/release/resolve, 3-bucket Staff Desk, and audited read-only resolved view."""

    def setUp(self):
        import secrets
        from retailops.http.public import PublicWeb
        from tests.test_r1_w1_identity_rbac import ORIGIN, _FixtureGateway, _wsgi

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = time.time()
        self.sessions = PersistentSessions(
            self.root / "persistent",
            infer=_FixtureGateway(),
            api_infer=_FixtureGateway(),
            api_daily_limit=10,
            default_tenant_id="store-alpha",
        )
        orig_bstore = self.sessions.business_store

        def _clocked_bstore(tid):
            st = orig_bstore(tid)
            st.clock = lambda: self.now
            return st

        self.sessions.business_store = _clocked_bstore
        self.store_a = self.sessions.provision_tenant("store-alpha", "Alpha", seed_demo=True)
        self.store_b = self.sessions.provision_tenant("store-beta", "Beta", seed_demo=True)
        self.store_a.clock = lambda: self.now
        self.store_b.clock = lambda: self.now
        self.web = PublicWeb(ORIGIN, self.sessions)
        self._wsgi = _wsgi

        def _mk(tid: str, pid: str, name: str, cid: str, role: str):
            mid = self.sessions.create_member(tid, pid, name, cid, role=role)
            tok = secrets.token_urlsafe(32)
            self.sessions.control.register_credential(mid, tok)
            st, _, hdrs = _wsgi(self.web, "POST", "/api/login", {"token": tok})
            self.assertEqual(st, 200)
            return {"principal_id": pid, "membership_id": mid}, hdrs["Set-Cookie"].split(";")[0]

        self.cust_a, self.ck_cust_a = _mk("store-alpha", "prin_cust_a", "Khách Alpha", "C-001", "customer")
        self.staff1_a, self.ck_staff1_a = _mk("store-alpha", "prin_staff_1", "Nhân viên 1", "C-001", "staff")
        self.staff2_a, self.ck_staff2_a = _mk("store-alpha", "prin_staff_2", "Nhân viên 2", "C-002", "staff")
        self.mgr_a, self.ck_mgr_a = _mk("store-alpha", "prin_mgr_a", "Quản lý Alpha", "C-001", "manager")
        self.staff_b, self.ck_staff_b = _mk("store-beta", "prin_staff_b", "Nhân viên Beta", "C-001", "staff")

    def test_item5_concurrent_claim_release_lease_release_and_stale_handoff_guard(self):
        import threading

        _, conv_res, _ = self._wsgi(self.web, "POST", "/api/conversations", {}, cookie=self.ck_cust_a)
        cid, case_id = conv_res["conversation_id"], conv_res["case_id"]
        _, fb_res, _ = self._wsgi(
            self.web,
            "POST",
            "/api/feedback",
            {"conversation_id": cid, "feedback_type": "human_handoff", "comment": "Cần hỗ trợ gấp"},
            cookie=self.ck_cust_a,
        )
        handoff_1 = fb_res["handoff_id"]

        # Seed an active workflow lease on this conversation to prove resolve releases it
        with self.store_a.connection(write=True) as db:
            db.execute(
                "INSERT INTO graph_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("run-lease-1", "C-001", "fp-1", json.dumps({"id": cid}), self.now + 1800, "owner-1", self.now + 180),
            )

        # 1. Two Staff concurrently claim the same case -> exactly 1 wins (200), 1 gets 409 case_claim_conflict
        barrier = threading.Barrier(2)
        claim_outcomes = []

        def _claim(ck):
            barrier.wait(timeout=5)
            st, body, _ = self._wsgi(self.web, "POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=ck)
            claim_outcomes.append((st, body))

        t1 = threading.Thread(target=_claim, args=(self.ck_staff1_a,))
        t2 = threading.Thread(target=_claim, args=(self.ck_staff2_a,))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        statuses = sorted(st for st, _ in claim_outcomes)
        self.assertEqual(statuses, [200, 409])
        loser_body = [b for st, b in claim_outcomes if st == 409][0]
        self.assertEqual(loser_body["error"], "case_claim_conflict")

        winner_body = [b for st, b in claim_outcomes if st == 200][0]
        winner_holder = winner_body["case"]["holder"]
        winner_ck = self.ck_staff1_a if winner_holder == self.staff1_a["principal_id"] else self.ck_staff2_a
        other_ck = self.ck_staff2_a if winner_ck == self.ck_staff1_a else self.ck_staff1_a

        # Non-holder staff cannot reply, release, or resolve while held
        self.assertEqual(
            self._wsgi(self.web, "POST", "/api/staff/reply", {"case_id": case_id, "message": "Chen ngang"}, cookie=other_ck)[0],
            409,
        )
        self.assertEqual(
            self._wsgi(self.web, "POST", f"/api/staff/cases/{case_id}/release", {}, cookie=other_ck)[0],
            403,
        )

        # Winner releases -> back to waiting (holder = NULL), then re-claims and resolves
        st_rel, b_rel, _ = self._wsgi(self.web, "POST", f"/api/staff/cases/{case_id}/release", {}, cookie=winner_ck)
        self.assertEqual(st_rel, 200)
        self.assertEqual((b_rel["case"]["status"], b_rel["case"]["holder"]), ("waiting", None))

        self.assertEqual(self._wsgi(self.web, "POST", f"/api/staff/cases/{case_id}/claim", {}, cookie=winner_ck)[0], 200)
        st_rep, _, _ = self._wsgi(
            self.web, "POST", "/api/staff/reply", {"case_id": case_id, "message": "Em đã xử lý đơn cho mình ạ."}, cookie=winner_ck
        )
        self.assertEqual(st_rep, 200)

        st_res, b_res, _ = self._wsgi(
            self.web,
            "POST",
            "/api/staff/resolve",
            {"case_id": case_id, "handoff_id": handoff_1},
            cookie=winner_ck,
        )
        self.assertEqual(st_res, 200)
        self.assertEqual(b_res["case"]["status"], "resolved")
        self.assertEqual(b_res["case"]["resolved_reason"], "staff_resolved")
        self.assertIsNone(b_res["case"]["holder"])
        self.assertEqual(b_res["leases_released"], 1)

        with self.store_a.connection() as db:
            gr_row = db.execute("SELECT lease_owner, lease_until FROM graph_runs WHERE id = 'run-lease-1'").fetchone()
        self.assertEqual((gr_row["lease_owner"], gr_row["lease_until"]), (None, 0))

        # Replying to resolved case is denied (403)
        st_rep_closed, b_rep_closed, _ = self._wsgi(
            self.web, "POST", "/api/staff/reply", {"case_id": case_id, "message": "Trả lời sau khi đóng"}, cookie=winner_ck
        )
        self.assertEqual((st_rep_closed, b_rep_closed["error"]), (403, "case_not_escalated"))

        # 2. Customer reopens case and creates a NEW handoff episode -> resolving with STALE handoff_1 is rejected!
        _, fb_res2, _ = self._wsgi(
            self.web,
            "POST",
            "/api/feedback",
            {"conversation_id": cid, "feedback_type": "human_handoff", "comment": "Hỏi thêm câu nữa"},
            cookie=self.ck_cust_a,
        )
        handoff_2 = fb_res2["handoff_id"]
        self.assertNotEqual(handoff_2, handoff_1)

        st_stale, b_stale, _ = self._wsgi(
            self.web,
            "POST",
            "/api/staff/resolve",
            {"case_id": case_id, "handoff_id": handoff_1},
            cookie=winner_ck,
        )
        self.assertEqual((st_stale, b_stale["error"]), (409, "stale_handoff_episode"))
        with self.store_a.connection() as db:
            ep2 = db.execute("SELECT status FROM handoff_episodes WHERE handoff_id = ?", (handoff_2,)).fetchone()
            k_row = db.execute("SELECT status FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        self.assertEqual(ep2["status"], "pending")
        self.assertEqual(k_row["status"], "waiting")

    def test_item6_and_item7_three_bucket_staff_desk_and_audited_readonly_resolved_view(self):
        # 1. Pure bot-only open case + pure bot-only closed case -> NEVER appear on Staff Desk
        _, bot_open, _ = self._wsgi(self.web, "POST", "/api/conversations", {}, cookie=self.ck_cust_a)
        _, bot_closed, _ = self._wsgi(self.web, "POST", "/api/conversations", {}, cookie=self.ck_cust_a)
        with self.store_a.connection(write=True) as db:
            db.execute(
                "UPDATE cases SET status = 'resolved', resolved_reason = 'inactivity', resolved_at = ? WHERE case_id = ?",
                (self.now, bot_closed["case_id"]),
            )

        # 2. Case W (Waiting), Case P (In Progress), Case R (Resolved handoff)
        _, cw, _ = self._wsgi(self.web, "POST", "/api/conversations", {}, cookie=self.ck_cust_a)
        _, cp, _ = self._wsgi(self.web, "POST", "/api/conversations", {}, cookie=self.ck_cust_a)
        _, cr, _ = self._wsgi(self.web, "POST", "/api/conversations", {}, cookie=self.ck_cust_a)
        for cobj in (cw, cp, cr):
            self._wsgi(
                self.web,
                "POST",
                "/api/feedback",
                {"conversation_id": cobj["conversation_id"], "feedback_type": "human_handoff", "comment": "Hỗ trợ"},
                cookie=self.ck_cust_a,
            )
        self._wsgi(self.web, "POST", f"/api/staff/cases/{cp['case_id']}/claim", {}, cookie=self.ck_staff1_a)
        self._wsgi(self.web, "POST", "/api/staff/resolve", {"case_id": cr["case_id"]}, cookie=self.ck_staff1_a)

        st_desk, desk, _ = self._wsgi(self.web, "GET", "/api/staff/cases", cookie=self.ck_staff1_a)
        self.assertEqual(st_desk, 200)
        self.assertEqual([x["case_id"] for x in desk["waiting"]], [cw["case_id"]])
        self.assertEqual([x["case_id"] for x in desk["in_progress"]], [cp["case_id"]])
        self.assertEqual([x["case_id"] for x in desk["resolved"]], [cr["case_id"]])
        # Open count ONLY counts open cases (waiting + in_progress = 2); resolved & bot-only excluded!
        self.assertEqual(desk["open_count"], 2)
        all_desk_ids = {
            x["case_id"]
            for bucket in ("waiting", "in_progress", "resolved")
            for x in desk[bucket]
        }
        self.assertNotIn(bot_open["case_id"], all_desk_ids)
        self.assertNotIn(bot_closed["case_id"], all_desk_ids)

        # 3. Item 7: Read-only viewing of resolved case by Staff & Manager records an audit row EVERY time
        with self.store_a.connection() as db:
            views_before = db.execute(
                "SELECT COUNT(*) FROM business_events WHERE kind = 'resolved_case_viewed'"
            ).fetchone()[0]
        self.assertEqual(views_before, 0)

        st_v1, b_v1, _ = self._wsgi(
            self.web, "GET", f"/api/staff/cases/{cr['case_id']}/messages", cookie=self.ck_staff1_a
        )
        st_v2, b_v2, _ = self._wsgi(
            self.web, "GET", f"/api/staff/cases/{cr['case_id']}/messages", cookie=self.ck_mgr_a
        )
        self.assertEqual((st_v1, b_v1["read_only"]), (200, True))
        self.assertEqual((st_v2, b_v2["read_only"]), (200, True))

        with self.store_a.connection() as db:
            view_events = [
                json.loads(r["payload"])
                for r in db.execute(
                    "SELECT payload FROM business_events WHERE kind = 'resolved_case_viewed' ORDER BY id ASC"
                ).fetchall()
            ]
        self.assertEqual(len(view_events), 2)
        self.assertEqual(view_events[0]["actor"]["principal_id"], self.staff1_a["principal_id"])
        self.assertEqual(view_events[1]["actor"]["principal_id"], self.mgr_a["principal_id"])

        # Foreign tenant staff gets 404 on resolved case; bot-only open case gets 403 case_not_escalated
        st_other, b_other, _ = self._wsgi(
            self.web, "GET", f"/api/staff/cases/{cr['case_id']}/messages", cookie=self.ck_staff_b
        )
        self.assertEqual((st_other, b_other["error"]), (404, "case_not_found"))
        st_bot, b_bot, _ = self._wsgi(
            self.web, "GET", f"/api/staff/cases/{bot_open['case_id']}/messages", cookie=self.ck_staff1_a
        )
        self.assertEqual((st_bot, b_bot["error"]), (403, "case_not_escalated"))

        # Advance clock past 7-day retention -> viewing resolved case is denied (403 case_retention_expired)
        self.now += self.store_a.CONVERSATION_TTL + 60.0
        st_exp, b_exp, _ = self._wsgi(
            self.web, "GET", f"/api/staff/cases/{cr['case_id']}/messages", cookie=self.ck_staff1_a
        )
        self.assertEqual((st_exp, b_exp["error"]), (403, "case_retention_expired"))


if __name__ == "__main__":
    unittest.main()
