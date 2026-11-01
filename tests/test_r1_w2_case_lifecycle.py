"""Isolated unit tests for Phase R1 W2: operational hygiene, Business v5 migration, case lifecycle, timers, resume, and feedback."""
import argparse
import ast
from contextlib import closing, contextmanager
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


if __name__ == "__main__":
    unittest.main()
