"""SQLite business repository and atomic cancellation rules.

No HTTP, session or model dependency. This module never deletes a database or
seeds demo data implicitly; its owner explicitly chooses those lifecycle actions.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from retailops.core import (
    ApiError,
    EVIDENCE_MAX_COUNT,
    EVIDENCE_RETENTION_SECONDS,
    ORDER_ACTION_REASONS,
    REASONS,
    fields,
    require,
)
from retailops.business.evidence import (
    atomic_write_bytes,
    inspect_and_reencode_evidence,
    resolve_protected_subdir,
)
from retailops.business.outbox import (
    OUTBOX_MAX_ATTEMPTS,
    append_outbox_jsonl_line,
    compute_next_backoff_seconds,
    seal_closed_integration_days,
    validate_outbox_envelope,
)
from retailops.guardrails.topic_filter import (
    SAFE_REFUSAL_MESSAGE,
    contains_canary_or_secret,
    sanitize_structured_payload,
)
from retailops.schema import migrate
from retailops.business.schema import (
    BUSINESS_V5_VERSION_MAPPING,
    BUSINESS_V6_VERSION_MAPPING,
    SQLITE_BUSINESS_SCHEMA_CURRENT,
    SQLITE_BUSINESS_V5_SCHEMA_VERSION,
    backfill_business_v5_cases,
    ensure_case_tables,
    ensure_import_tables,
    ensure_order_action_tables,
    initialize as initialize_schema,
)

ROOT = Path(__file__).resolve().parents[2]

def _parse_variant_string(v_str):
    delimiter = "·" if "·" in str(v_str) else ("/" if "/" in str(v_str) else None)
    color = None
    size = None
    if delimiter:
        parts = [pt.strip() for pt in str(v_str).split(delimiter)]
        if len(parts) >= 2:
            color = parts[0]
            size = parts[1].replace("Size ", "").strip()
        elif len(parts) == 1:
            size = parts[0].replace("Size ", "").strip()
    else:
        parts = [str(v_str).strip()]
        if "Size " in parts[0]:
            size = parts[0].replace("Size ", "").strip()
        else:
            size = parts[0]
    return size, color


class VariantStockResult(int):
    """Backwards-compatible integer stock that also carries variant status and stock."""
    def __new__(cls, stock, status='ok'):
        val = int(stock) if stock is not None and not isinstance(stock, bool) else 0
        obj = super().__new__(cls, val)
        obj.stock = stock
        obj.status = status
        return obj

    def __iter__(self):
        yield self.stock
        yield self.status


def _inspect_sqlite_business_ready(path, *, target_version=SQLITE_BUSINESS_SCHEMA_CURRENT):
    """Read-only inspection of a business SQLite file without modifying a single byte.

    Returns 'empty' for a missing, zero-byte, or zero-table file; 'v6_ready' when already at
    SQLite business schema v5 (logical Business v6) with all Business v5 and v6 tables plus
    orders.delivered_at; raises ValueError for wrong component / unsupported future version;
    and raises ApiError(503, 'business_migration_required', ...) when an existing pre-v6
    business DB is found.
    """
    db_path = Path(path)
    if not db_path.exists() or db_path.stat().st_size == 0:
        return 'empty'
    uri = db_path.resolve().as_uri() + '?mode=ro'
    ro_db = None
    try:
        ro_db = sqlite3.connect(uri, uri=True, timeout=5)
        ro_db.row_factory = sqlite3.Row
        tables = {
            r[0]
            for r in ro_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if not tables:
            return 'empty'
        if 'retailops_schema' in tables:
            rows = ro_db.execute('SELECT component, version FROM retailops_schema').fetchall()
            if rows and (len(rows) != 1 or rows[0]['component'] != 'business'):
                raise ValueError('Database belongs to another RetailOps component.')
            if not rows:
                raise ApiError(
                    503,
                    'business_migration_required',
                    'Kho dữ liệu cửa hàng thiếu dấu vết schema Business v6; khởi động bị chặn fail-closed. '
                    'Hãy chạy lệnh operator database migrate-v6 với --confirm-preflight --confirm-backup.',
                )
            ver = rows[0]['version']
            if ver not in range(1, SQLITE_BUSINESS_SCHEMA_CURRENT + 1):
                raise ValueError('Unsupported database schema version; use the matching application version.')
            if ver < target_version:
                raise ApiError(
                    503,
                    'business_migration_required',
                    f'Kho dữ liệu cửa hàng đang ở SQLite schema v{ver} (trước Business v6); khởi động bị chặn fail-closed. '
                    'Hãy chạy lệnh operator database migrate-v6 với --confirm-preflight --confirm-backup.',
                )
            required_v5_tables = {'cases', 'handoff_episodes', 'case_feedback_events'}
            if not required_v5_tables.issubset(tables):
                raise ApiError(
                    503,
                    'business_migration_required',
                    'Kho dữ liệu cửa hàng chưa đầy đủ các bảng Business v5; khởi động bị chặn fail-closed. '
                    'Hãy chạy lệnh operator database migrate-v6 với --confirm-preflight --confirm-backup.',
                )
            if target_version >= SQLITE_BUSINESS_SCHEMA_CURRENT:
                required_v6_tables = {
                    'order_action_requests',
                    'order_action_decisions',
                    'order_action_evidence',
                    'integration_outbox',
                }
                order_cols = {
                    row['name'] for row in ro_db.execute('PRAGMA table_info(orders)')
                } if 'orders' in tables else set()
                if not required_v6_tables.issubset(tables) or 'delivered_at' not in order_cols:
                    raise ApiError(
                        503,
                        'business_migration_required',
                        'Kho dữ liệu cửa hàng chưa đầy đủ các bảng/cột Business v6; khởi động bị chặn fail-closed. '
                        'Hãy chạy lệnh operator database migrate-v6 với --confirm-preflight --confirm-backup.',
                    )
                return 'v6_ready'
            return 'v5_ready'
        if 'memberships' in tables or 'tenants' in tables:
            raise ValueError('Database belongs to another RetailOps component.')
        if tables & {'orders', 'conversations', 'proposals', 'business_events', 'products'}:
            raise ApiError(
                503,
                'business_migration_required',
                'Kho dữ liệu cửa hàng legacy chưa nâng cấp lên Business v6; khởi động bị chặn fail-closed. '
                'Hãy chạy lệnh operator database migrate-v6 với --confirm-preflight --confirm-backup.',
            )
        raise ValueError('Database belongs to another RetailOps component.')
    except sqlite3.Error as exc:
        raise ApiError(
            503,
            'database_unavailable',
            'Cơ sở dữ liệu tạm thời gián đoạn. Vui lòng thử lại sau ít phút.',
        ) from exc
    finally:
        if ro_db is not None:
            ro_db.close()


def _migrate_single_sqlite_business_file(db_path: Path, *, target_version: int = SQLITE_BUSINESS_SCHEMA_CURRENT):
    if not db_path.is_file():
        raise ApiError(404, 'database_not_found', f'Không tìm thấy kho dữ liệu cửa hàng SQLite: {db_path.name}')
    try:
        state = _inspect_sqlite_business_ready(db_path, target_version=target_version)
    except ApiError as exc:
        if exc.code != 'business_migration_required':
            raise
        state = 'needs_migration'
    if state == 'empty':
        raise ApiError(404, 'database_not_found', f'Kho dữ liệu cửa hàng SQLite đang rỗng: {db_path.name}')

    uri = db_path.resolve().as_uri() + '?mode=rw'
    db = sqlite3.connect(uri, uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        ver_before_row = (
            db.execute("SELECT version FROM retailops_schema WHERE component='business'").fetchone()
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retailops_schema'").fetchone()
            else None
        )
        ver_before = int(ver_before_row['version']) if ver_before_row else 0
        cases_before = (
            db.execute('SELECT COUNT(*) FROM cases').fetchone()[0]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'").fetchone()
            else 0
        )
        episodes_before = (
            db.execute('SELECT COUNT(*) FROM handoff_episodes').fetchone()[0]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='handoff_episodes'").fetchone()
            else 0
        )
        if ver_before < target_version or state == 'needs_migration':
            migrate(db, 'business', initialize_schema, target_version=target_version)
            ensure_import_tables(db)
            ensure_case_tables(db)
            backfill_res = backfill_business_v5_cases(db)
            if target_version >= SQLITE_BUSINESS_SCHEMA_CURRENT:
                ensure_order_action_tables(db)
        else:
            backfill_res = {'cases_created': 0, 'episodes_created': 0}
        cases_after = (
            db.execute('SELECT COUNT(*) FROM cases').fetchone()[0]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'").fetchone()
            else 0
        )
        episodes_after = (
            db.execute('SELECT COUNT(*) FROM handoff_episodes').fetchone()[0]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='handoff_episodes'").fetchone()
            else 0
        )
        fk_errors = db.execute('PRAGMA foreign_key_check').fetchall()
        if fk_errors:
            raise sqlite3.IntegrityError(f'Foreign key check failed during Business migration: {[tuple(r) for r in fk_errors]}')
        db.commit()
        return {
            'upgraded': bool(ver_before < target_version or state == 'needs_migration' or backfill_res['cases_created'] > 0),
            'cases_created': int(cases_after - cases_before),
            'episodes_created': int(episodes_after - episodes_before),
        }
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise
    finally:
        db.close()


def _resolve_sqlite_tenant_files(target: Path, *, milestone_label: str) -> list[Path]:
    pers_dir = target / 'persistent' if (target / 'persistent').is_dir() else target
    id_file = pers_dir / 'identity.sqlite3'
    tenants_dir = pers_dir / 'tenants'
    require(
        id_file.is_file() or tenants_dir.is_dir(),
        404,
        'database_not_found',
        f'Không tìm thấy thư mục dữ liệu persistent SQLite hiện hữu để nâng cấp {milestone_label}.',
    )
    if id_file.is_file():
        from retailops.identity.store import _inspect_sqlite_identity_ready
        id_state = _inspect_sqlite_identity_ready(id_file)
        require(
            id_state == 'v5_ready',
            503,
            'identity_migration_required',
            f'Kho identity SQLite chưa ở schema v5; hãy chạy identity migrate-v5 trước khi nâng cấp {milestone_label}.',
        )

    tenant_files = []
    seen = set()
    if id_file.is_file():
        ro_uri = id_file.resolve().as_uri() + '?mode=ro'
        ro_id = sqlite3.connect(ro_uri, uri=True, timeout=5)
        ro_id.row_factory = sqlite3.Row
        try:
            for row in ro_id.execute('SELECT storage_key FROM tenants ORDER BY id').fetchall():
                cand = tenants_dir / f"{row['storage_key']}.sqlite3"
                if cand.is_file() and cand.resolve() not in seen:
                    seen.add(cand.resolve())
                    tenant_files.append(cand)
        finally:
            ro_id.close()
    if tenants_dir.is_dir():
        for cand in sorted(tenants_dir.glob('*.sqlite3')):
            if cand.is_file() and cand.resolve() not in seen:
                seen.add(cand.resolve())
                tenant_files.append(cand)
    return tenant_files


def migrate_sqlite_business_v5(path, *, preflight_confirmed=False, backup_confirmed=False):
    """Explicit operator migration command for SQLite Business v5 (W2-D3, §11.5).

    Accepts either a single SQLite business database file OR a workspace/persistent
    directory (upgrading every tenant business database under persistent/tenants/).
    Never invoked automatically at web startup, store construction, or ordinary CLI commands.
    """
    require(
        preflight_confirmed is True and backup_confirmed is True,
        400,
        'migration_confirmation_required',
        'Lệnh nâng cấp Business v5 yêu cầu xác nhận tường minh --confirm-preflight và --confirm-backup theo runbook §11.5.',
    )
    target = Path(path)
    if target.is_file():
        single = _migrate_single_sqlite_business_file(target, target_version=SQLITE_BUSINESS_V5_SCHEMA_VERSION)
        return {
            'result': 'BUSINESS_V5_MIGRATED',
            'backend': 'sqlite',
            'schema_version': SQLITE_BUSINESS_V5_SCHEMA_VERSION,
            'logical_version': BUSINESS_V5_VERSION_MAPPING['postgresql'],
            'tenants': 1,
            'upgraded': single['upgraded'],
            'cases_created': single['cases_created'],
            'episodes_created': single['episodes_created'],
        }

    tenant_files = _resolve_sqlite_tenant_files(target, milestone_label='Business v5')
    any_upgraded = False
    total_cases = 0
    total_episodes = 0
    for tf in tenant_files:
        res = _migrate_single_sqlite_business_file(tf, target_version=SQLITE_BUSINESS_V5_SCHEMA_VERSION)
        any_upgraded = any_upgraded or res['upgraded']
        total_cases += res['cases_created']
        total_episodes += res['episodes_created']

    return {
        'result': 'BUSINESS_V5_MIGRATED',
        'backend': 'sqlite',
        'schema_version': SQLITE_BUSINESS_V5_SCHEMA_VERSION,
        'logical_version': BUSINESS_V5_VERSION_MAPPING['postgresql'],
        'tenants': len(tenant_files),
        'upgraded': any_upgraded,
        'cases_created': total_cases,
        'episodes_created': total_episodes,
    }


def migrate_sqlite_business_v6(path, *, preflight_confirmed=False, backup_confirmed=False):
    """Explicit operator migration command for SQLite Business v6 (W3-D1..W3-D4, W3-D6, W3-D9).

    Upgrades pre-v6 business databases to SQLite v5 (logical Business v6), adding nullable
    orders.delivered_at (left NULL on existing orders), order_action_requests, append-only
    order_action_decisions, order_action_evidence, and integration_outbox. Does not backfill
    pending proposals (W3-D9). Never invoked automatically.
    """
    require(
        preflight_confirmed is True and backup_confirmed is True,
        400,
        'migration_confirmation_required',
        'Lệnh nâng cấp Business v6 yêu cầu xác nhận tường minh --confirm-preflight và --confirm-backup theo runbook §11.5.',
    )
    target = Path(path)
    if target.is_file():
        single = _migrate_single_sqlite_business_file(target, target_version=SQLITE_BUSINESS_SCHEMA_CURRENT)
        return {
            'result': 'BUSINESS_V6_MIGRATED',
            'backend': 'sqlite',
            'schema_version': SQLITE_BUSINESS_SCHEMA_CURRENT,
            'logical_version': BUSINESS_V6_VERSION_MAPPING['postgresql'],
            'tenants': 1,
            'upgraded': single['upgraded'],
        }

    tenant_files = _resolve_sqlite_tenant_files(target, milestone_label='Business v6')
    any_upgraded = False
    for tf in tenant_files:
        res = _migrate_single_sqlite_business_file(tf, target_version=SQLITE_BUSINESS_SCHEMA_CURRENT)
        any_upgraded = any_upgraded or res['upgraded']

    return {
        'result': 'BUSINESS_V6_MIGRATED',
        'backend': 'sqlite',
        'schema_version': SQLITE_BUSINESS_SCHEMA_CURRENT,
        'logical_version': BUSINESS_V6_VERSION_MAPPING['postgresql'],
        'tenants': len(tenant_files),
        'upgraded': any_upgraded,
    }


CASE_INACTIVITY_REMINDER_MESSAGE = (
    'Bạn còn cần mình hỗ trợ thêm thông tin gì không ạ? '
    'Nếu chưa nhận được phản hồi sau ít phút nữa, hệ thống sẽ tạm đóng ca hỗ trợ này '
    '(bạn vẫn có thể nhắn lại bất kỳ lúc nào để tiếp tục).'
)


class BusinessStore:
    CONVERSATION_TTL = 7 * 86400  # 7 days persistent chat history
    _supports_skip_locked = False

    def _now(self) -> float:
        clk = getattr(self, 'clock', None)
        return float(clk() if callable(clk) else time.time())

    def _timer_config(self):
        from retailops.config import (
            CaseTimerConfig,
            DEFAULT_CASE_HELD_SILENCE_SECONDS,
            positive_float,
        )
        cfg = getattr(self, 'case_timer_config', None)
        data_mode = str(getattr(self, 'data_mode', '') or os.environ.get('RETAILOPS_DATA_MODE', '')).strip()
        is_prod_env = str(os.environ.get('RETAILOPS_ENV', '')).strip().lower() in ('production', 'prod', 'live')
        if isinstance(cfg, CaseTimerConfig):
            if data_mode in ('production', 'live') or is_prod_env:
                return CaseTimerConfig(
                    reminder_seconds=cfg.reminder_seconds,
                    post_reminder_close_seconds=cfg.post_reminder_close_seconds,
                    completion_seconds=cfg.completion_seconds,
                    held_silence_seconds=cfg.held_silence_seconds,
                    scan_seconds=cfg.scan_seconds,
                    data_mode=data_mode or cfg.data_mode,
                    production_env=is_prod_env or cfg.production_env,
                )
            return cfg
        return CaseTimerConfig(
            held_silence_seconds=positive_float(
                os.environ,
                'RETAILOPS_CASE_HELD_SILENCE_SECONDS',
                DEFAULT_CASE_HELD_SILENCE_SECONDS,
            ),
            data_mode=data_mode or 'synthetic-demo',
            production_env=is_prod_env,
        )

    @staticmethod
    def _ensure_customer_in_tx(db, customer_id: str) -> None:
        if not customer_id:
            return
        db.execute(
            "INSERT INTO customers(id, name) VALUES (?, 'Khách hàng') "
            "ON CONFLICT(id) DO NOTHING",
            (customer_id,),
        )

    @staticmethod
    def _case_public_dict(row, *, customer_silent_seconds: int | None = None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        has_timer = any(
            d.get(col) is not None
            for col in ('reminder_deadline', 'inactivity_deadline', 'completion_deadline')
        )
        return {
            'case_id': d['case_id'],
            'conversation_id': d['conversation_id'],
            'customer_id': d['customer_id'],
            'status': d['status'],
            'holder': d.get('holder'),
            'holder_name': d.get('holder_name'),
            'version': int(d['version']),
            'resolved_reason': d.get('resolved_reason'),
            'resolved_at': d.get('resolved_at'),
            'resumed_at': d.get('resumed_at'),
            'resume_count': int(d.get('resume_count') or 0),
            'previous_case_id': d.get('previous_case_id'),
            'has_active_timer': bool(has_timer and d['status'] != 'resolved' and d.get('holder') is None),
            'customer_silent_seconds': customer_silent_seconds,
            'created_at': d['created_at'],
            'updated_at': d['updated_at'],
        }

    def _compute_customer_silent_seconds_in_tx(
        self,
        db,
        case_row,
        *,
        now: float | None = None,
        threshold_seconds: float | None = None,
    ) -> int | None:
        if case_row is None:
            return None
        d = dict(case_row)
        status = d.get('status') or d.get('case_status')
        holder = d.get('holder')
        cid = d.get('conversation_id')
        if status != 'in_progress' or not holder or not cid:
            return None
        now_ts = self._now() if now is None else float(now)
        threshold = (
            float(self._timer_config().held_silence_seconds)
            if threshold_seconds is None
            else float(threshold_seconds)
        )
        resumed_at = d.get('resumed_at')
        base_created = d.get('case_created_at') if 'case_created_at' in d else d.get('created_at')
        open_since = float(resumed_at if resumed_at is not None else (base_created or 0.0))
        last_resolve = db.execute(
            "SELECT MAX(id) AS max_id FROM agent_turns WHERE conversation_id = ? AND request_id LIKE ?",
            (cid, 'sys-notice-resolve-%'),
        ).fetchone()
        min_turn_id = int(last_resolve['max_id'] or 0) if last_resolve is not None else 0
        last_turn = db.execute(
            """SELECT id, request_id, result, created_at
               FROM agent_turns
               WHERE conversation_id = ?
                 AND created_at >= ?
                 AND id > ?
                 AND request_id NOT LIKE ?
                 AND request_id NOT LIKE ?
                 AND request_id NOT LIKE ?
               ORDER BY id DESC LIMIT 1""",
            (cid, open_since - 1e-6, min_turn_id, 'sys-notice-%', 'sys-reminder-%', 'sys-oar-%'),
        ).fetchone()
        if last_turn is None:
            return None
        res_raw = last_turn['result']
        try:
            res_obj = json.loads(res_raw) if isinstance(res_raw, str) else (res_raw or {})
        except Exception:
            res_obj = {}
        if not isinstance(res_obj, dict) or res_obj.get('author') != 'staff':
            return None
        elapsed = now_ts - float(last_turn['created_at'])
        if elapsed < threshold:
            return None
        return int(elapsed)

    @staticmethod
    def _latest_case_in_tx(db, cid: str):
        return db.execute(
            'SELECT * FROM cases WHERE conversation_id = ? '
            'ORDER BY created_at DESC, updated_at DESC, case_id DESC LIMIT 1',
            (cid,),
        ).fetchone()

    def _ensure_active_case_in_tx(self, db, cid: str, customer_id: str, now: float) -> dict:
        row = self._latest_case_in_tx(db, cid)
        if row is not None:
            return dict(row)
        self._ensure_customer_in_tx(db, customer_id)
        case_id = f'case_{uuid.uuid4().hex}'
        db.execute(
            """INSERT INTO cases(
                   case_id, conversation_id, customer_id, status, holder, holder_name,
                   version, resume_count, created_at, updated_at
               ) VALUES (?, ?, ?, 'waiting', NULL, NULL, 1, 0, ?, ?)""",
            (case_id, cid, customer_id, now, now),
        )
        return dict(self._latest_case_in_tx(db, cid))

    def __init__(self, path, *, create=True, initialize_db=True, read_only=False):
        if initialize_db and read_only:
            raise ValueError('Read-only business stores cannot initialize or migrate a database.')
        self.path = Path(path)
        self.initialize = bool(initialize_db)
        self.read_only = bool(read_only)
        if self.initialize:
            state = _inspect_sqlite_business_ready(self.path)
            if state == 'empty' and not create and not self.path.is_file():
                raise ApiError(503, 'database_unavailable', 'Kho dữ liệu cửa hàng chưa tồn tại.')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connection(create=create) as db:
                db.execute('PRAGMA journal_mode=WAL')
            with self.connection(write=True) as db:
                if state == 'empty':
                    migrate(db, 'business', initialize_schema)
                ensure_import_tables(db)
        else:
            if not self.path.is_file():
                raise ApiError(503, 'database_unavailable', 'Kho dữ liệu cửa hàng chưa tồn tại; không tự khởi tạo khi chạy purge.')
            if not self.read_only:
                state = _inspect_sqlite_business_ready(self.path)
                if state == 'empty':
                    raise ApiError(503, 'database_unavailable', 'Kho dữ liệu cửa hàng đang rỗng.')

    @contextmanager
    def connection(self, write=False, *, create=False):
        if self.read_only and (write or create):
            raise ApiError(409, 'read_only_store', 'Kho cửa hàng đang ở chế độ chỉ đọc.')
        # Only explicit construction may create a database. A lost mount must not
        # silently create a blank database while a cached repository is in use.
        mode = 'ro' if self.read_only else ('rwc' if create else 'rw')
        uri = self.path.resolve().as_uri() + f'?mode={mode}'
        db = None
        try:
            db = sqlite3.connect(uri, uri=True, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except (sqlite3.IntegrityError, sqlite3.ProgrammingError):
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            raise
        except sqlite3.Error as exc:
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            if self.read_only and 'readonly' in str(exc).lower():
                raise ApiError(409, 'read_only_store', 'Kho cửa hàng đang ở chế độ chỉ đọc.') from exc
            raise ApiError(503, 'database_unavailable', 'Cơ sở dữ liệu tạm thời gián đoạn. Vui lòng thử lại sau ít phút.') from exc
        except Exception:
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            raise
        finally:
            if db is not None:
                db.close()

    def seed(self):
        # Conflict handling preserves cancelled orders across process/container restarts.
        with self.connection(write=True) as db:
            customers = [
                ('C-001', 'Mai Anh'),
                ('C-002', 'Khách mẫu'),
                ('C-003', 'Trần Thị Mai'),
                ('C-004', 'Lê Hoàng Nam'),
                ('manager', 'Quản lý cửa hàng'),
                ('system', 'Hệ thống')
            ]
            orders = [
                ("O-101", "C-001", "Áo thun Essential", "Trắng · Size M · Số lượng 1", 299000, "pending", "P-101"),
                ("O-102", "C-001", "Áo khoác Everyday", "Đen · Size L · Số lượng 1", 799000, "delivered", "P-102"),
                ("O-202", "C-002", "Áo polo", "Xanh · Size M · Số lượng 1", 399000, "pending", "P-202"),
                ("O-301", "C-003", "Áo Sơ Mi Oxford Dài Tay", "Trắng · Size M · Số lượng 1", 350000, "pending", "P-103"),
                ("O-302", "C-003", "Áo Khoác Gió Bomber 2 Lớp", "Đen · Size L · Số lượng 1", 550000, "delivered", "P-104"),
                ("O-303", "C-004", "Áo Polo Nam Phối Bo Cổ Co Giãn", "Xanh Navy · Size M · Số lượng 1", 399000, "delivered", "P-203"),
                ("O-304", "C-004", "Bộ Nồi Inox 3 Đáy Cao Cấp", "Bạc · Bộ 3 món · Số lượng 1", 1250000, "pending", "P-401"),
            ]
            seed_file = ROOT / "data" / "deepseek_seed_data.json"
            if seed_file.exists():
                try:
                    with open(seed_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    known_cids = {x[0] for x in customers}
                    for c in data.get("customers", []):
                        if c["id"] not in known_cids:
                            customers.append((c["id"], c["name"]))
                            known_cids.add(c["id"])
                    known_oids = {x[0] for x in orders}
                    for o in data.get("orders", []):
                        if o["id"] not in known_oids:
                            orders.append((o["id"], o["customer_id"], o["name"], o["variant"], o["amount"], o["status"], o.get("product_id")))
                            known_oids.add(o["id"])
                except Exception:
                    pass
            db.executemany("INSERT INTO customers VALUES (?,?) ON CONFLICT DO NOTHING", customers)
            self.seed_catalog(db)
            self._ensure_purge_tombstone_table(db)
            tombstoned_oids = {
                str(r["order_id"]) for r in db.execute("SELECT order_id FROM order_purge_tombstones").fetchall()
            }
            orders_to_seed = [o for o in orders if o[0] not in tombstoned_oids]
            db.executemany("INSERT INTO orders(id, customer_id, name, variant, amount, status, product_id) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", orders_to_seed)
            order_to_product = {
                'O-101': 'P-101', 'O-102': 'P-102', 'O-202': 'P-202',
                'O-301': 'P-103', 'O-302': 'P-104', 'O-303': 'P-203', 'O-304': 'P-401',
                'O-305': 'P-501', 'O-306': 'P-503', 'O-307': 'P-506', 'O-308': 'P-502',
                'O-309': 'P-504', 'O-310': 'P-507', 'O-311': 'P-505', 'O-312': 'P-508',
            }
            for oid, pid in order_to_product.items():
                db.execute("UPDATE orders SET product_id=? WHERE id=? AND product_id IS NULL", (pid, oid))
            db.execute("""
                UPDATE orders 
                SET product_id = (SELECT p.id FROM products p WHERE p.name = orders.name LIMIT 1)
                WHERE product_id IS NULL AND EXISTS (SELECT 1 FROM products p WHERE p.name = orders.name)
            """)

    def seed_catalog(self, db=None):
        def _do_seed(conn):
            catalog_file = ROOT / "data" / "products.json"
            if not catalog_file.exists():
                return
            try:
                with open(catalog_file, "r", encoding="utf-8") as f:
                    catalog_data = json.load(f)
            except Exception:
                return

            STOCK_MAP = {
                'P-101': {'S': 5, 'M': 12, 'L': 8, 'XL': 0},
                'P-102': {'S': 0, 'M': 4, 'L': 15, 'XL': 3},
                'P-202': {'S': 20, 'M': 18, 'L': 25, 'XL': 10},
                'P-103': {'S': 8, 'M': 14, 'L': 10, 'XL': 2},
                'P-104': {'S': 10, 'M': 15, 'L': 0, 'XL': 8},
                'P-203': {'S': 12, 'M': 0, 'L': 18, 'XL': 5},
                'P-301': {'39': 4, '40': 8, '41': 0, '42': 6, '43': 2},
                'P-601': {'S': 10, 'M': 15, 'L': 10},
                'P-602': {'S': 12, 'M': 18, 'L': 10},
                'P-603': {'40': 6, '41': 10, '42': 9},
            }

            now = time.time()
            products = catalog_data.get("products", [])
            for p in products:
                pid = p["id"]
                name = p.get("name", "")
                aliases = json.dumps(p.get("aliases", []), ensure_ascii=False)
                category = p.get("category")
                price = p.get("price")
                stock = p.get("stock") if "stock" in p else 0
                warranty_days = p.get("warranty_days") if "warranty_days" in p else 90
                description = p.get("description", "")
                raw_variants = p.get("variants", [])
                variants_json = json.dumps(raw_variants, ensure_ascii=False)
                material = p.get("material")
                care = p.get("care")
                is_sys = 1 if pid in ('P-101', 'P-102', 'P-202') or p.get("is_system_immutable") else 0

                extra = {}
                for k, v in p.items():
                    if k not in {'id', 'name', 'aliases', 'category', 'price', 'stock',
                                'warranty_days', 'description', 'variants', 'material',
                                'care', 'is_system_immutable'}:
                        extra[k] = v
                extra_json = json.dumps(extra, ensure_ascii=False)

                conn.execute("""
                    INSERT INTO products(id, name, aliases, category, price, stock, warranty_days,
                                         description, variants, material, care, is_system_immutable,
                                         extra_data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                """, (pid, name, aliases, category, price, stock, warranty_days,
                      description, variants_json, material, care, is_sys,
                      extra_json, now, now))

                for v_str in raw_variants:
                    size, color = _parse_variant_string(v_str)
                    if pid in STOCK_MAP and size in STOCK_MAP[pid]:
                        var_stock = STOCK_MAP[pid][size]
                    elif stock is None:
                        var_stock = None
                    elif stock <= 0:
                        var_stock = 0
                    else:
                        var_stock = max(1, stock // len(raw_variants)) if raw_variants else stock

                    var_id = f"{pid}-{size or 'STD'}-{color or 'STD'}".replace(" ", "_")
                    conn.execute("""
                        INSERT INTO product_variants(id, product_id, variant_name, size, color, stock, price)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                    """, (var_id, pid, v_str, size, color, var_stock, price))

        if db is not None:
            _do_seed(db)
        else:
            with self.connection(write=True) as conn:
                _do_seed(conn)

    _DEMO_SAMPLE_FIXTURE_SPEC = {
        "P-601": {
            "offset": 1,
            "name": "Áo sơ mi lụa công sở",
            "variant": "Trắng / M",
            "amount": 450000,
            "status": "pending",
            "version": 1,
            "cancel_reason": None,
        },
        "P-602": {
            "offset": 2,
            "name": "Quần tây đen hàn quốc",
            "variant": "Đen / L",
            "amount": 520000,
            "status": "delivered",
            "version": 1,
            "cancel_reason": None,
        },
        "P-603": {
            "offset": 3,
            "name": "Giày lười da bò cao cấp",
            "variant": "Nâu / 41",
            "amount": 890000,
            "status": "delivered",
            "version": 1,
            "cancel_reason": None,
        },
    }

    @staticmethod
    def _ensure_purge_tombstone_table(conn):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS order_purge_tombstones (
                order_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                status TEXT NOT NULL,
                amount BIGINT NOT NULL,
                snapshot_name TEXT NOT NULL,
                variant TEXT,
                reason TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                purged_at DOUBLE PRECISION NOT NULL,
                pre_counts_json TEXT NOT NULL,
                post_counts_json TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_purge_tombstones_customer "
            "ON order_purge_tombstones(customer_id, product_id)"
        )

    @staticmethod
    def _tombstone_table_exists(conn) -> bool:
        try:
            if hasattr(conn, "raw"):
                row = conn.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name = 'order_purge_tombstones'"
                ).fetchone()
                return row is not None
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_purge_tombstones'"
            ).fetchone()
            return row is not None
        except Exception:
            return False

    def is_order_purged(self, order_id: str, db=None) -> bool:
        if not isinstance(order_id, str) or not order_id.strip():
            return False
        oid = order_id.strip()

        def _check(conn):
            if not self._tombstone_table_exists(conn):
                return False
            row = conn.execute(
                "SELECT 1 FROM order_purge_tombstones WHERE order_id=? LIMIT 1",
                (oid,),
            ).fetchone()
            return row is not None

        if db is not None:
            return _check(db)
        with self.connection() as conn:
            return _check(conn)

    def get_purge_tombstone(self, order_id: str, db=None):
        if not isinstance(order_id, str) or not order_id.strip():
            return None
        oid = order_id.strip()

        def _fetch(conn):
            if not self._tombstone_table_exists(conn):
                return None
            row = conn.execute(
                "SELECT * FROM order_purge_tombstones WHERE order_id=? LIMIT 1",
                (oid,),
            ).fetchone()
            return dict(row) if row is not None else None

        if db is not None:
            return _fetch(db)
        with self.connection() as conn:
            return _fetch(conn)

    @classmethod
    def _row_matches_demo_fixture_spec(cls, row: dict, pid: str) -> bool:
        spec = cls._DEMO_SAMPLE_FIXTURE_SPEC.get(pid)
        if not spec or not isinstance(row, dict):
            return False
        try:
            amt = int(row.get("amount")) if row.get("amount") is not None else -1
            ver = int(row.get("version")) if row.get("version") is not None else -1
        except (TypeError, ValueError):
            return False
        return (
            str(row.get("product_id")) == pid
            and row.get("name") == spec["name"]
            and row.get("variant") == spec["variant"]
            and amt == spec["amount"]
            and row.get("status") == spec["status"]
            and ver == spec["version"]
            and row.get("cancel_reason") is None
        )

    @staticmethod
    def _has_import_or_item_provenance(conn, customer_id: str, order_ids: tuple[str, str, str]) -> bool:
        oid1, oid2, oid3 = order_ids
        imp = conn.execute(
            "SELECT 1 FROM imported_events WHERE customer_id=? OR order_id IN (?, ?, ?) LIMIT 1",
            (customer_id, oid1, oid2, oid3),
        ).fetchone()
        if imp is not None:
            return True
        items = conn.execute(
            "SELECT 1 FROM order_items WHERE order_id IN (?, ?, ?) LIMIT 1",
            (oid1, oid2, oid3),
        ).fetchone()
        if items is not None:
            return True
        sales_ev = conn.execute(
            "SELECT 1 FROM business_events WHERE (customer_id=? OR order_id IN (?, ?, ?)) AND kind='sales_event_imported' LIMIT 1",
            (customer_id, oid1, oid2, oid3),
        ).fetchone()
        return sales_ev is not None

    def seed_demo_sample_orders(self, customer_id, db=None):
        def _do_seed_orders(conn):
            self._ensure_purge_tombstone_table(conn)
            cust_tombstones = conn.execute(
                "SELECT order_id, product_id FROM order_purge_tombstones WHERE customer_id=?",
                (customer_id,),
            ).fetchall()
            if cust_tombstones:
                return []
            existing_rows = conn.execute(
                "SELECT id, customer_id, name, variant, amount, status, version, cancel_reason, product_id "
                "FROM orders WHERE customer_id=? ORDER BY id ASC",
                (customer_id,),
            ).fetchall()
            if existing_rows:
                if len(existing_rows) == 3:
                    by_pid = {str(r["product_id"]): dict(r) for r in existing_rows}
                    p601 = by_pid.get("P-601")
                    p602 = by_pid.get("P-602")
                    p603 = by_pid.get("P-603")
                    if (
                        p601
                        and p602
                        and p603
                        and re.fullmatch(r"O-[78]\d{5}", str(p601["id"]))
                        and re.fullmatch(r"O-[78]\d{5}", str(p602["id"]))
                        and re.fullmatch(r"O-[78]\d{5}", str(p603["id"]))
                    ):
                        n1 = int(str(p601["id"])[2:])
                        n2 = int(str(p602["id"])[2:])
                        n3 = int(str(p603["id"])[2:])
                        if (
                            700001 <= n1 <= 899990
                            and n2 == n1 + 1
                            and n3 == n1 + 2
                            and self._row_matches_demo_fixture_spec(p601, "P-601")
                            and self._row_matches_demo_fixture_spec(p602, "P-602")
                            and self._row_matches_demo_fixture_spec(p603, "P-603")
                        ):
                            oid_triplet = (str(p601["id"]), str(p602["id"]), str(p603["id"]))
                            p602_oid = oid_triplet[1]
                            has_prov = conn.execute(
                                "SELECT 1 FROM business_events WHERE customer_id=? AND order_id=? AND kind='demo_sample_fixture_seeded' LIMIT 1",
                                (customer_id, p602_oid),
                            ).fetchone()
                            if has_prov is None and not self._has_import_or_item_provenance(conn, customer_id, oid_triplet):
                                self.log(
                                    conn,
                                    customer_id,
                                    "demo_sample_fixture_seeded",
                                    p602_oid,
                                    fixture="google_demo_sample_v1",
                                    product_id="P-602",
                                    canonical_name="Quần tây đen hàn quốc",
                                    display_name="Bộ xếp hình gỗ cho bé",
                                )
                return []
            seed_base = 700000 + (abs(hash(customer_id)) % 199990)
            p602_oid = f"O-{seed_base + 2}"
            sample_orders = [
                (f"O-{seed_base + 1}", customer_id, "Áo sơ mi lụa công sở", "Trắng / M", 450000, "pending", 1, None, "P-601"),
                (p602_oid, customer_id, "Quần tây đen hàn quốc", "Đen / L", 520000, "delivered", 1, None, "P-602"),
                (f"O-{seed_base + 3}", customer_id, "Giày lười da bò cao cấp", "Nâu / 41", 890000, "delivered", 1, None, "P-603"),
            ]
            tombstoned_oids = {
                str(r["order_id"])
                for r in conn.execute(
                    "SELECT order_id FROM order_purge_tombstones WHERE order_id IN (?, ?, ?)",
                    (sample_orders[0][0], sample_orders[1][0], sample_orders[2][0]),
                ).fetchall()
            }
            inserted_oids = []
            for ord_row in sample_orders:
                if ord_row[0] in tombstoned_oids:
                    continue
                conn.execute(
                    """INSERT INTO orders(id, customer_id, name, variant, amount, status, version, cancel_reason, product_id)
                       VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                    ord_row,
                )
                inserted_oids.append(ord_row[0])
            if p602_oid in inserted_oids:
                self.log(
                    conn,
                    customer_id,
                    "demo_sample_fixture_seeded",
                    p602_oid,
                    fixture="google_demo_sample_v1",
                    product_id="P-602",
                    canonical_name="Quần tây đen hàn quốc",
                    display_name="Bộ xếp hình gỗ cho bé",
                )
            return inserted_oids

        if db is not None:
            return _do_seed_orders(db)
        with self.connection(write=True) as conn:
            return _do_seed_orders(conn)

    def _collect_purge_reference_counts(
        self, conn, *, order_id: str, customer_id: str, product_id: str
    ) -> dict:
        orders_target = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM orders WHERE id=?", (order_id,)).fetchone()["cnt"]
        )
        orders_total = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM orders").fetchone()["cnt"]
        )
        customer_orders_total = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM orders WHERE customer_id=?", (customer_id,)).fetchone()["cnt"]
        )
        sibling_order_ids = [
            str(r["id"])
            for r in conn.execute(
                "SELECT id FROM orders WHERE customer_id=? AND id<>? ORDER BY id ASC",
                (customer_id, order_id),
            ).fetchall()
        ]
        order_items_target = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM order_items WHERE order_id=?", (order_id,)).fetchone()["cnt"]
        )
        proposals_target = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM proposals WHERE order_id=?", (order_id,)).fetchone()["cnt"]
        )
        confirmed_proposals_target = int(
            conn.execute(
                "SELECT COUNT(*) AS cnt FROM proposals WHERE order_id=? AND state='confirmed'",
                (order_id,),
            ).fetchone()["cnt"]
        )
        conversations_linked = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM conversations WHERE order_id=?", (order_id,)).fetchone()["cnt"]
        )
        conversations_total = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM conversations WHERE customer_id=?", (customer_id,)).fetchone()["cnt"]
        )
        business_events_target = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM business_events WHERE order_id=?", (order_id,)).fetchone()["cnt"]
        )
        imported_events_target = int(
            conn.execute("SELECT COUNT(*) AS cnt FROM imported_events WHERE order_id=?", (order_id,)).fetchone()["cnt"]
        )
        tombstones_target = 0
        if self._tombstone_table_exists(conn):
            tombstones_target = int(
                conn.execute(
                    "SELECT COUNT(*) AS cnt FROM order_purge_tombstones WHERE order_id=?",
                    (order_id,),
                ).fetchone()["cnt"]
            )
        prod_row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        cust_row = conn.execute("SELECT id, name FROM customers WHERE id=?", (customer_id,)).fetchone()
        product_snapshot = self._row_to_product(prod_row) if prod_row is not None else None
        if isinstance(product_snapshot, dict):
            product_snapshot = {
                "id": product_snapshot.get("id"),
                "name": product_snapshot.get("name"),
                "price": product_snapshot.get("price"),
                "stock": product_snapshot.get("stock"),
                "warranty_days": product_snapshot.get("warranty_days"),
                "variants": product_snapshot.get("variants"),
            }
        return {
            "orders_target": orders_target,
            "orders_total": orders_total,
            "customer_orders_total": customer_orders_total,
            "sibling_order_ids": sibling_order_ids,
            "order_items_target": order_items_target,
            "proposals_target": proposals_target,
            "confirmed_proposals_target": confirmed_proposals_target,
            "conversations_linked": conversations_linked,
            "conversations_total": conversations_total,
            "business_events_target": business_events_target,
            "imported_events_target": imported_events_target,
            "tombstones_target": tombstones_target,
            "product_exists": 1 if prod_row is not None else 0,
            "product_snapshot": product_snapshot,
            "customer_exists": 1 if cust_row is not None else 0,
        }

    def purge_demo_order(
        self,
        *,
        tenant_id: str,
        order_id: str,
        customer_id: str,
        product_id: str,
        status: str,
        amount: int,
        snapshot_name: str,
        execute: bool = False,
        reason: str = "",
        operator_id: str | None = None,
    ) -> dict:
        require(
            isinstance(tenant_id, str) and tenant_id.strip()
            and isinstance(order_id, str) and order_id.strip()
            and isinstance(customer_id, str) and customer_id.strip()
            and isinstance(product_id, str) and product_id.strip()
            and isinstance(status, str) and status.strip()
            and type(amount) is int and amount >= 0
            and isinstance(snapshot_name, str) and snapshot_name.strip(),
            400,
            "invalid_purge_parameters",
            "Cần cung cấp đầy đủ tenant_id và toàn bộ tuple kỳ vọng (order_id, customer_id, product_id, status, amount, snapshot_name).",
        )
        tenant_clean = tenant_id.strip()
        oid = order_id.strip()
        cid = customer_id.strip()
        pid = product_id.strip()
        st = status.strip()
        sname = snapshot_name.strip()
        if execute:
            require(
                isinstance(reason, str) and reason.strip() and isinstance(operator_id, str) and operator_id.strip(),
                400,
                "purge_reason_required",
                "Chế độ thực thi (--execute) bắt buộc phải có reason và operator_id để lưu kiểm toán.",
            )

        with self.connection(write=bool(execute)) as conn:
            if execute:
                self._ensure_purge_tombstone_table(conn)
            existing_tombstone = None
            if self._tombstone_table_exists(conn):
                t_row = conn.execute(
                    "SELECT * FROM order_purge_tombstones WHERE order_id=? LIMIT 1",
                    (oid,),
                ).fetchone()
                if t_row is not None:
                    existing_tombstone = dict(t_row)

            by_id_rows = conn.execute(
                "SELECT id, customer_id, name, variant, amount, status, version, cancel_reason, product_id "
                "FROM orders WHERE id=?",
                (oid,),
            ).fetchall()

            if existing_tombstone is not None and len(by_id_rows) == 0:
                require(
                    existing_tombstone.get("tenant_id") == tenant_clean
                    and existing_tombstone.get("customer_id") == cid
                    and existing_tombstone.get("product_id") == pid
                    and existing_tombstone.get("status") == st
                    and int(existing_tombstone.get("amount", -1)) == int(amount)
                    and existing_tombstone.get("snapshot_name") == sname,
                    409,
                    "purge_tombstone_mismatch",
                    "Tombstone hiện có của đơn hàng không khớp với tuple yêu cầu.",
                )
                post_counts = self._collect_purge_reference_counts(
                    conn, order_id=oid, customer_id=cid, product_id=pid
                )
                return {
                    "status": "already_purged",
                    "mode": "execute" if execute else "dry_run",
                    "executed": False,
                    "idempotent_replay": True,
                    "tenant_id": tenant_clean,
                    "order_id": oid,
                    "tombstone": existing_tombstone,
                    "post_counts": post_counts,
                    "catalog_product": post_counts["product_snapshot"],
                }

            by_tuple_rows = conn.execute(
                "SELECT id, customer_id, name, variant, amount, status, version, cancel_reason, product_id "
                "FROM orders WHERE customer_id=? AND product_id=? AND status=? AND amount=? AND name=?",
                (cid, pid, st, int(amount), sname),
            ).fetchall()

            require(
                len(by_id_rows) > 0,
                404,
                "purge_target_not_found",
                f"Không tìm thấy đơn hàng {oid} trong tenant {tenant_clean}.",
            )
            require(
                len(by_id_rows) == 1 and len(by_tuple_rows) <= 1,
                409,
                "purge_target_ambiguous",
                f"Phát hiện nhiều bản ghi trùng lặp cho tuple của đơn {oid}; hủy thao tác fail-closed.",
            )

            target = dict(by_id_rows[0])
            mismatches = []
            if str(target.get("customer_id")) != cid:
                mismatches.append("customer_id")
            if str(target.get("product_id")) != pid:
                mismatches.append("product_id")
            if str(target.get("status")) != st:
                mismatches.append("status")
            try:
                target_amt = int(target.get("amount")) if target.get("amount") is not None else -1
            except (TypeError, ValueError):
                target_amt = -1
            if target_amt != int(amount):
                mismatches.append("amount")
            if str(target.get("name")) != sname:
                mismatches.append("name")
            if len(by_tuple_rows) == 1 and str(by_tuple_rows[0]["id"]) != oid:
                mismatches.append("order_id")
            require(
                not mismatches,
                409,
                "purge_tuple_mismatch",
                f"Đơn hàng {oid} không khớp toàn bộ tuple kỳ vọng ({', '.join(mismatches)}); hủy thao tác fail-closed.",
            )

            pre_counts = self._collect_purge_reference_counts(
                conn, order_id=oid, customer_id=cid, product_id=pid
            )
            require(
                pre_counts["confirmed_proposals_target"] == 0,
                409,
                "purge_unclassified_reference",
                f"Đơn hàng {oid} có proposal đã confirmed ({pre_counts['confirmed_proposals_target']}); hủy thao tác fail-closed.",
            )
            require(
                pre_counts["product_exists"] == 1 and pre_counts["customer_exists"] == 1,
                409,
                "purge_context_missing",
                f"Không tìm thấy sản phẩm {pid} hoặc khách hàng {cid} trong tenant {tenant_clean}.",
            )

            if not execute:
                return {
                    "status": "dry_run_verified",
                    "mode": "dry_run",
                    "executed": False,
                    "idempotent_replay": False,
                    "tenant_id": tenant_clean,
                    "matched_order": target,
                    "pre_counts": pre_counts,
                    "planned_mutations": {
                        "delete_orders": 1,
                        "delete_order_items": pre_counts["order_items_target"],
                        "delete_proposals": pre_counts["proposals_target"],
                        "unlink_conversations": pre_counts["conversations_linked"],
                        "insert_tombstone": 1,
                        "insert_audit_event": 1,
                    },
                    "preserved_history": {
                        "business_events_retained": pre_counts["business_events_target"],
                        "imported_events_retained": pre_counts["imported_events_target"],
                    },
                    "catalog_product": pre_counts["product_snapshot"],
                }

            unlinked_convs = conn.execute(
                "UPDATE conversations SET order_id=NULL WHERE order_id=?",
                (oid,),
            ).rowcount
            deleted_proposals = conn.execute(
                "DELETE FROM proposals WHERE order_id=?",
                (oid,),
            ).rowcount
            deleted_items = conn.execute(
                "DELETE FROM order_items WHERE order_id=?",
                (oid,),
            ).rowcount
            deleted_orders = conn.execute(
                "DELETE FROM orders WHERE id=? AND customer_id=? AND product_id=? AND status=? AND amount=? AND name=?",
                (oid, cid, pid, st, int(amount), sname),
            ).rowcount
            require(
                deleted_orders == 1,
                409,
                "purge_delete_count_mismatch",
                f"Số dòng xóa khỏi bảng orders là {deleted_orders} (kỳ vọng 1); rollback.",
            )

            now = time.time()
            self.log(
                conn,
                cid,
                "demo_order_purged_by_operator",
                oid,
                tenant_id=tenant_clean,
                product_id=pid,
                snapshot_name=sname,
                variant=target.get("variant"),
                amount=int(amount),
                status=st,
                operator_id=operator_id.strip(),
                reason=reason.strip(),
            )
            conn.execute(
                """INSERT INTO order_purge_tombstones(
                    order_id, tenant_id, customer_id, product_id, status, amount,
                    snapshot_name, variant, reason, operator_id, purged_at,
                    pre_counts_json, post_counts_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    oid,
                    tenant_clean,
                    cid,
                    pid,
                    st,
                    int(amount),
                    sname,
                    target.get("variant"),
                    reason.strip(),
                    operator_id.strip(),
                    now,
                    json.dumps(pre_counts, ensure_ascii=False),
                    "{}",
                ),
            )
            post_counts = self._collect_purge_reference_counts(
                conn, order_id=oid, customer_id=cid, product_id=pid
            )
            conn.execute(
                "UPDATE order_purge_tombstones SET post_counts_json=? WHERE order_id=?",
                (json.dumps(post_counts, ensure_ascii=False), oid),
            )

            require(
                post_counts["orders_target"] == 0
                and post_counts["orders_total"] == pre_counts["orders_total"] - 1
                and post_counts["customer_orders_total"] == pre_counts["customer_orders_total"] - 1
                and post_counts["sibling_order_ids"] == pre_counts["sibling_order_ids"]
                and post_counts["product_exists"] == 1
                and post_counts["product_snapshot"] == pre_counts["product_snapshot"]
                and post_counts["customer_exists"] == 1
                and post_counts["conversations_total"] == pre_counts["conversations_total"]
                and post_counts["imported_events_target"] == pre_counts["imported_events_target"]
                and post_counts["business_events_target"] == pre_counts["business_events_target"] + 1
                and post_counts["tombstones_target"] == 1,
                500,
                "purge_postcondition_failed",
                "Kiểm tra hậu điều kiện sau khi xóa đơn không khớp kỳ vọng; rollback toàn bộ giao dịch.",
            )

            return {
                "status": "purged",
                "mode": "execute",
                "executed": True,
                "idempotent_replay": False,
                "tenant_id": tenant_clean,
                "purged_order": target,
                "pre_counts": pre_counts,
                "post_counts": post_counts,
                "deleted_counts": {
                    "orders": deleted_orders,
                    "order_items": deleted_items,
                    "proposals": deleted_proposals,
                    "conversations_unlinked": unlinked_convs,
                },
                "preserved_history": {
                    "business_events_before": pre_counts["business_events_target"],
                    "business_events_after": post_counts["business_events_target"],
                    "imported_events_retained": post_counts["imported_events_target"],
                },
                "catalog_product": post_counts["product_snapshot"],
            }

    def is_demo_sample_order(self, customer_id, order_id) -> bool:
        if not isinstance(customer_id, str) or not customer_id or not isinstance(order_id, str) or not order_id:
            return False
        if not re.fullmatch(r"O-[78]\d{5}", order_id):
            return False
        n2 = int(order_id[2:])
        if not (700002 <= n2 <= 899991):
            return False
        oid_triplet = (f"O-{n2 - 1}", order_id, f"O-{n2 + 1}")
        with self.connection() as db:
            p602_row = db.execute(
                "SELECT id, customer_id, name, variant, amount, status, version, cancel_reason, product_id "
                "FROM orders WHERE id=? AND customer_id=? LIMIT 1",
                (order_id, customer_id),
            ).fetchone()
            if p602_row is None or not self._row_matches_demo_fixture_spec(dict(p602_row), "P-602"):
                return False
            if self._has_import_or_item_provenance(db, customer_id, oid_triplet):
                return False
            prov = db.execute(
                "SELECT payload FROM business_events WHERE customer_id=? AND order_id=? AND kind='demo_sample_fixture_seeded' ORDER BY id ASC LIMIT 1",
                (customer_id, order_id),
            ).fetchone()
            if prov is None:
                return False
            try:
                payload = json.loads(prov["payload"]) if isinstance(prov["payload"], str) else (prov["payload"] or {})
            except Exception:
                payload = {}
            return (
                payload.get("fixture") == "google_demo_sample_v1"
                and payload.get("product_id") == "P-602"
                and payload.get("display_name") == "Bộ xếp hình gỗ cho bé"
            )

    @staticmethod
    def _row_to_product(row):
        d = dict(row)
        raw_aliases = json.loads(d['aliases']) if isinstance(d['aliases'], str) else d['aliases']
        if isinstance(raw_aliases, (list, tuple)):
            aliases = [str(a) for a in raw_aliases if a is not None]
        elif isinstance(raw_aliases, str):
            aliases = [raw_aliases]
        else:
            aliases = []
        raw_variants = json.loads(d['variants']) if isinstance(d['variants'], str) else d['variants']
        variants = raw_variants if isinstance(raw_variants, list) else []
        extra = json.loads(d.get('extra_data') or '{}') if isinstance(d.get('extra_data'), str) else (d.get('extra_data') or {})
        return {
            'id': d['id'],
            'name': d['name'],
            'aliases': aliases,
            'category': d['category'],
            'price': d['price'],
            'stock': d['stock'],
            'warranty_days': d['warranty_days'],
            'description': d['description'],
            'variants': variants,
            'material': d['material'],
            'care': d['care'],
            'is_system_immutable': bool(d['is_system_immutable']),
            **extra,
            'created_at': d['created_at'],
            'updated_at': d['updated_at']
        }

    def get_product(self, pid):
        if not isinstance(pid, str) or not pid.isascii() or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', pid):
            return None
        with self.connection() as db:
            row = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not row:
                return None
            return self._row_to_product(row)

    def list_products(self):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM products ORDER BY id").fetchall()
            return [self._row_to_product(r) for r in rows]

    def add_product(self, p, actor=None):
        require(isinstance(p, dict), 400, "invalid_product", "Dữ liệu sản phẩm không hợp lệ.")
        pid = str(p.get("id", "")).strip().upper()
        name = str(p.get("name", "")).strip()
        require(pid and re.fullmatch(r"P-[0-9]{3,6}", pid), 400, "invalid_product_id", "Mã sản phẩm phải có dạng P-xxx (ví dụ: P-509).")
        require(name, 400, "invalid_product_name", "Tên sản phẩm không được để trống.")

        now = time.time()
        raw_aliases = p.get("aliases")
        if not isinstance(raw_aliases, (list, tuple)):
            raw_aliases = [name.lower(), pid.lower()]
        aliases = json.dumps([str(a) for a in raw_aliases if a is not None], ensure_ascii=False)
        category = p.get("category")
        price = p.get("price")
        stock = p.get("stock")
        warranty_days = p.get("warranty_days")
        description = p.get("description")
        raw_variants = p.get("variants", [])
        variants_json = json.dumps(raw_variants, ensure_ascii=False)
        material = p.get("material")
        care = p.get("care")
        is_sys = 1 if pid in ('P-101', 'P-102', 'P-202') or p.get("is_system_immutable") else 0

        extra = {}
        for k, v in p.items():
            if k not in {'id', 'name', 'aliases', 'category', 'price', 'stock',
                        'warranty_days', 'description', 'variants', 'material',
                        'care', 'is_system_immutable'}:
                extra[k] = v
        extra_json = json.dumps(extra, ensure_ascii=False)

        with self.connection(write=True) as db:
            existing = db.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone()
            require(existing is None, 409, "product_exists", f"Sản phẩm {pid} đã tồn tại trong danh mục.")

            db.execute("""
                INSERT INTO products(id, name, aliases, category, price, stock, warranty_days,
                                     description, variants, material, care, is_system_immutable,
                                     extra_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (pid, name, aliases, category, price, stock, warranty_days,
                  description, variants_json, material, care, is_sys,
                  extra_json, now, now))

            for v_str in raw_variants:
                size, color = _parse_variant_string(v_str)
                if stock is None:
                    var_stock = None
                elif stock <= 0:
                    var_stock = 0
                else:
                    var_stock = max(0, stock // len(raw_variants)) if raw_variants else stock
                var_id = f"{pid}-{size or 'STD'}-{color or 'STD'}".replace(" ", "_")
                db.execute("""
                    INSERT INTO product_variants(id, product_id, variant_name, size, color, stock, price)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                """, (var_id, pid, v_str, size, color, var_stock, price))

            actor_ctx = actor or {"principal_id": "manager", "role": "manager", "actor_type": "principal"}
            cid = actor_ctx.get("principal_id") or "manager"
            self.log(db, cid, "product_created", None, product_id=pid, product=p, actor=actor_ctx)

        return self.get_product(pid)

    def update_product(self, pid, updates, actor=None):
        require(isinstance(updates, dict), 400, "invalid_updates", "Dữ liệu cập nhật không hợp lệ.")
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if row is None:
                raise KeyError(f"Không tìm thấy sản phẩm {pid}.")

            now = time.time()
            cols = []
            params = []
            allowed_fields = {"name", "price", "warranty_days", "category", "description", "material", "care"}
            for f in allowed_fields:
                if f in updates:
                    cols.append(f"{f}=?")
                    params.append(updates[f])

            if "aliases" in updates:
                cols.append("aliases=?")
                raw_al = updates["aliases"] if isinstance(updates["aliases"], (list, tuple)) else []
                params.append(json.dumps([str(a) for a in raw_al if a is not None], ensure_ascii=False))

            existing_vars = db.execute("SELECT * FROM product_variants WHERE product_id=?", (pid,)).fetchall()
            existing_map = {r["variant_name"]: dict(r) for r in existing_vars}
            price_val = updates.get("price", row["price"])
            explicit_variant_stocks = updates.get("variant_stocks", {})

            if "variants" in updates:
                cols.append("variants=?")
                raw_vars = updates["variants"]
                params.append(json.dumps(raw_vars, ensure_ascii=False))
                db.execute("DELETE FROM product_variants WHERE product_id=?", (pid,))

                new_var_records = []
                for v_str in raw_vars:
                    size, color = _parse_variant_string(v_str)
                    if v_str in explicit_variant_stocks:
                        var_stock = max(0, int(explicit_variant_stocks[v_str]))
                    elif v_str in existing_map:
                        # PRESERVE existing variant stock across metadata updates
                        var_stock = existing_map[v_str]["stock"]
                    else:
                        var_stock = 0
                    var_id = f"{pid}-{size or 'STD'}-{color or 'STD'}".replace(" ", "_")
                    new_var_records.append((var_id, pid, v_str, size, color, var_stock, price_val))

                for rec in new_var_records:
                    db.execute("""
                        INSERT INTO product_variants(id, product_id, variant_name, size, color, stock, price)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, rec)

                # Total product stock is the sum of all variant stocks if variants exist
                if new_var_records:
                    total_variant_stock = sum(r[5] for r in new_var_records)
                    cols.append("stock=?")
                    params.append(total_variant_stock)
                else:
                    if "stock" in updates:
                        cols.append("stock=?")
                        params.append(updates["stock"])
            else:
                if explicit_variant_stocks and existing_map:
                    for v_str, new_s in explicit_variant_stocks.items():
                        if v_str in existing_map:
                            db.execute("UPDATE product_variants SET stock=?, price=? WHERE product_id=? AND variant_name=?",
                                       (max(0, int(new_s)), price_val, pid, v_str))
                    v_sum_row = db.execute("SELECT COALESCE(SUM(stock), 0) AS total_stock FROM product_variants WHERE product_id=?", (pid,)).fetchone()
                    if v_sum_row:
                        try:
                            v_sum = v_sum_row["total_stock"] if "total_stock" in v_sum_row else v_sum_row[0]
                        except (TypeError, KeyError, IndexError):
                            v_sum = v_sum_row[0] if v_sum_row else 0
                    else:
                        v_sum = 0
                    cols.append("stock=?")
                    params.append(int(v_sum or 0))
                elif "stock" in updates:
                    new_stock = updates["stock"]
                    cols.append("stock=?")
                    params.append(new_stock)
                    if existing_vars and "price" in updates:
                        db.execute("UPDATE product_variants SET price=? WHERE product_id=?", (price_val, pid))
                elif "price" in updates and existing_vars:
                    db.execute("UPDATE product_variants SET price=? WHERE product_id=?", (price_val, pid))

            cols.append("updated_at=?")
            params.append(now)
            params.append(pid)

            db.execute(f"UPDATE products SET {', '.join(cols)} WHERE id=?", tuple(params))

            actor_ctx = actor or {"principal_id": "manager", "role": "manager", "actor_type": "principal"}
            cid = actor_ctx.get("customer_id") or actor_ctx.get("principal_id") or "manager"
            self.log(db, cid, "product_updated", None, product_id=pid, updates=updates, actor=actor_ctx)

        return self.get_product(pid)

    def delete_product(self, pid, actor=None):
        if pid in ('P-101', 'P-102', 'P-202'):
            raise ValueError(f"Sản phẩm {pid} là sản phẩm cơ sở hệ thống phục vụ kiểm thử, không được phép xóa.")
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if row is None:
                raise KeyError(f"Không tìm thấy sản phẩm {pid}.")
            if row["is_system_immutable"]:
                raise ValueError(f"Sản phẩm {pid} là sản phẩm cơ sở hệ thống, không được phép xóa.")

            # Check if any orders reference this product
            ref_orders = [r["id"] for r in db.execute("SELECT id FROM orders WHERE product_id=?", (pid,)).fetchall()]
            if ref_orders:
                raise ValueError(f"product_has_existing_orders: Sản phẩm {pid} đã phát sinh {len(ref_orders)} đơn hàng trong hệ thống ({', '.join(ref_orders[:3])}{'...' if len(ref_orders) > 3 else ''}). Không thể xóa để bảo toàn dữ liệu lịch sử đơn hàng và bảo hành.")

            product_dict = self._row_to_product(row)
            db.execute("DELETE FROM product_variants WHERE product_id=?", (pid,))
            db.execute("DELETE FROM products WHERE id=?", (pid,))

            actor_ctx = actor or {"principal_id": "manager", "role": "manager", "actor_type": "principal"}
            cid = actor_ctx.get("customer_id") or actor_ctx.get("principal_id") or "manager"
            self.log(db, cid, "product_deleted", None, product_id=pid, actor=actor_ctx)

        return product_dict

    def get_variant_stock(self, pid, size, color=None):
        size_clean = (size or "").strip().upper()
        color_clean = (color or "").strip().lower()
        if color_clean in ("tiêu chuẩn", "standard", "default", ""):
            color_clean = None

        with self.connection() as db:
            p_row = db.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()
            if not p_row:
                return VariantStockResult(None, "product_not_found")

            rows = db.execute("SELECT * FROM product_variants WHERE product_id=?", (pid,)).fetchall()
            if not rows:
                st = p_row["stock"]
                if st is None:
                    return VariantStockResult(None, "stock_unknown")
                if size_clean and size_clean not in ("FREE SIZE", "FREESIZE", "TIÊU CHUẨN", "STANDARD", "DEFAULT"):
                    return VariantStockResult(None, "variant_not_found")
                if color_clean:
                    return VariantStockResult(None, "variant_not_found")
                return VariantStockResult(st, "ok")

            if color_clean:
                matched = [r for r in rows if (r["size"] or "").strip().upper() == size_clean and (r["color"] or "").strip().lower() == color_clean]
                if matched:
                    st = matched[0]["stock"]
                    if st is None:
                        return VariantStockResult(None, "stock_unknown")
                    return VariantStockResult(st, "ok")
                return VariantStockResult(None, "variant_not_found")

            matched_by_size = [r for r in rows if (r["size"] or "").strip().upper() == size_clean]
            if matched_by_size:
                if any(r["stock"] is None for r in matched_by_size):
                    return VariantStockResult(None, "stock_unknown")
                total_size_stock = sum(r["stock"] for r in matched_by_size)
                return VariantStockResult(total_size_stock, "ok")

            return VariantStockResult(None, "variant_not_found")

    def get_catalog_revision(self):
        with self.connection() as db:
            p_row = db.execute("SELECT MAX(updated_at) AS max_val FROM products").fetchone()
            p_max = 0.0
            if p_row:
                try:
                    val = p_row["max_val"] if "max_val" in p_row else p_row[0]
                except (TypeError, KeyError, IndexError):
                    val = p_row[0] if p_row else None
                if val is not None:
                    p_max = float(val)

            ev_row = db.execute("SELECT MAX(created_at) AS max_val FROM business_events WHERE kind LIKE ?", ('product_%',)).fetchone()
            ev_max = 0.0
            if ev_row:
                try:
                    val = ev_row["max_val"] if "max_val" in ev_row else ev_row[0]
                except (TypeError, KeyError, IndexError):
                    val = ev_row[0] if ev_row else None
                if val is not None:
                    ev_max = float(val)

            return max(p_max, ev_max)


    def manager_events(self, limit=100):
        with self.connection() as db:
            rows = db.execute(
                "SELECT id, customer_id, created_at, kind, order_id, payload FROM business_events WHERE kind != 'demo_sample_fixture_seeded' ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d['payload'] = json.loads(d['payload']) if isinstance(d['payload'], str) else d['payload']
                _, d['payload'] = sanitize_structured_payload(d['payload'], preserve_reasoning=True)
            except Exception:
                pass
            result.append(d)
        return result


    def add_customer(self, customer_id, name):
        require(isinstance(customer_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', customer_id)
                and isinstance(name, str) and 0 < len(name.strip()) <= 100,
                400, 'invalid_customer', 'Thông tin khách hàng không hợp lệ.')
        with self.connection(write=True) as db:
            require(db.execute('SELECT 1 FROM customers WHERE id=?', (customer_id,)).fetchone() is None,
                    409, 'customer_exists', 'Khách hàng đã tồn tại.')
            db.execute('INSERT INTO customers VALUES (?,?)', (customer_id, name))

    def customer(self, customer_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM customers WHERE id=?', (customer_id,)).fetchone()
        require(row is not None, 404, 'customer_not_found', 'Không tìm thấy khách hàng.')
        return dict(row)

    @staticmethod
    def owned(db, customer, oid):
        if not isinstance(oid, str) or not oid.isascii() or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', oid):
            require(False, 404, "order_not_found", "Không tìm thấy đơn hàng của bạn.")
        row = db.execute("SELECT * FROM orders WHERE id=? AND customer_id=?", (oid, customer)).fetchone()
        require(row is not None, 404, "order_not_found", "Không tìm thấy đơn hàng của bạn.")
        return dict(row)

    @staticmethod
    def log(db, customer, kind, oid=None, **payload):
        db.execute("INSERT INTO business_events(customer_id,created_at,kind,order_id,payload) VALUES (?,?,?,?,?)",
                   (customer, time.time(), kind, oid, json.dumps(payload, ensure_ascii=False)))

    def event(self, customer, kind, oid=None, **payload):
        with self.connection(write=True) as db:
            self.log(db, customer, kind, oid, **payload)

    def orders(self, customer):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM orders WHERE customer_id=? ORDER BY id", (customer,))]

    def lookup(self, customer, oid):
        with self.connection(write=True) as db:
            order = self.owned(db, customer, oid)
            self.log(db, customer, "order_viewed", oid)
            return order

    def order_items(self, order_id):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order_id,))]

    def imported_event(self, source_system, event_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM imported_events WHERE source_system=? AND event_id=?", (source_system, event_id)).fetchone()
            return dict(row) if row else None

    def events(self, customer):
        with self.connection() as db:
            result = [dict(r) for r in db.execute(
                "SELECT id,created_at,kind,order_id,payload FROM business_events WHERE customer_id=? AND kind != 'demo_sample_fixture_seeded' ORDER BY id DESC LIMIT 30", (customer,))]
        for row in result:
            row["payload"] = json.loads(row["payload"])
            _, row["payload"] = sanitize_structured_payload(row["payload"], preserve_reasoning=True)
        return result

    def new_conversation(self, customer, provider_id='custom'):
        cid = str(uuid.uuid4())
        case_id = f'case_{uuid.uuid4().hex}'
        now = self._now()
        with self.connection(write=True) as db:
            db.execute('DELETE FROM conversations WHERE expires_at < ?', (now,))
            self._ensure_customer_in_tx(db, customer)
            db.execute('INSERT INTO conversations(id,customer_id,expires_at,provider_id) VALUES (?,?,?,?)',
                       (cid, customer, now + self.CONVERSATION_TTL, provider_id))
            db.execute(
                """INSERT INTO cases(
                       case_id, conversation_id, customer_id, status, holder, holder_name,
                       version, resume_count, created_at, updated_at
                   ) VALUES (?, ?, ?, 'waiting', NULL, NULL, 1, 0, ?, ?)""",
                (case_id, cid, customer, now, now),
            )
            case_row = self._latest_case_in_tx(db, cid)
        return {
            'conversation_id': cid,
            'case_id': case_id,
            'provider_id': provider_id,
            'context': {'order_id': None, 'product_id': None},
            'case': self._case_public_dict(case_row),
        }

    def reserve_api_attempt(self, limit):
        # Reserve before network I/O; even failed/timed-out calls can be billable.
        day = time.strftime('%Y-%m-%d', time.gmtime())
        with self.connection(write=True) as db:
            row = db.execute("SELECT attempts FROM provider_daily_usage WHERE day=? AND provider_id='api'", (day,)).fetchone()
            require(row is None or row['attempts'] < limit, 429, 'api_daily_limit',
                    'Demo đã hết lượt chat API hôm nay (UTC). Bạn có thể chọn custom model đang được cấu hình.')
            db.execute("""INSERT INTO provider_daily_usage(day,provider_id,attempts) VALUES (?,'api',1)
                ON CONFLICT(day,provider_id) DO UPDATE SET attempts=provider_daily_usage.attempts+1""", (day,))
            cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).date().isoformat()
            db.execute("DELETE FROM provider_daily_usage WHERE day < ?", (cutoff,))

    def conversation(self, customer, cid):
        require(isinstance(cid, str) and re.fullmatch(r'[a-f0-9-]{36}', cid),
                400, 'invalid_conversation', 'Mã cuộc trò chuyện không hợp lệ.')
        now = self._now()
        with self.connection() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=? AND customer_id=?', (cid, customer)).fetchone()
        require(row is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn. Hãy mở cuộc trò chuyện mới.')
        require(row['expires_at'] > now, 409, 'conversation_expired', 'Cuộc trò chuyện đã hết hạn. Hãy bấm Cuộc trò chuyện mới.')
        return dict(row)

    def peek_conversation_for_chat(self, customer, cid):
        require(isinstance(cid, str) and re.fullmatch(r'[a-f0-9-]{36}', cid),
                400, 'invalid_conversation', 'Mã cuộc trò chuyện không hợp lệ.')
        now = self._now()
        with self.connection() as db:
            conv = db.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone()
            latest_case = self._latest_case_in_tx(db, cid)
        if conv is not None and conv['customer_id'] != customer:
            raise ApiError(404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn. Hãy mở cuộc trò chuyện mới.')
        if conv is None and (latest_case is None or latest_case['customer_id'] != customer):
            raise ApiError(404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn. Hãy mở cuộc trò chuyện mới.')
        if latest_case is not None and latest_case['status'] == 'resolved':
            if conv is not None:
                return dict(conv)
            return {
                'id': cid,
                'customer_id': customer,
                'order_id': None,
                'product_id': None,
                'revision': 0,
                'provider_id': 'custom',
                'expires_at': now + self.CONVERSATION_TTL,
            }
        require(conv is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn. Hãy mở cuộc trò chuyện mới.')
        require(conv['expires_at'] > now, 409, 'conversation_expired', 'Cuộc trò chuyện đã hết hạn. Hãy bấm Cuộc trò chuyện mới.')
        return dict(conv)

    def _prepare_customer_activity_in_tx(self, db, customer, cid, now, *, forbidden_on_mismatch=False):
        conv = db.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone()
        latest_case = self._latest_case_in_tx(db, cid)
        if conv is None and latest_case is None:
            raise ApiError(404, 'conversation_not_found', 'Cuộc trò chuyện không tồn tại hoặc đã bị xóa.')
        owner_id = conv['customer_id'] if conv is not None else latest_case['customer_id']
        if owner_id != customer:
            if forbidden_on_mismatch:
                raise ApiError(403, 'forbidden', 'Không có quyền gửi tin nhắn trong cuộc trò chuyện này.')
            raise ApiError(404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn. Hãy mở cuộc trò chuyện mới.')

        if latest_case is None:
            latest_case = self._ensure_active_case_in_tx(db, cid, customer, now)
        else:
            latest_case = dict(latest_case)

        if latest_case['status'] == 'resolved':
            resolved_at = latest_case.get('resolved_at')
            within_retention = (
                conv is not None
                and float(conv['expires_at']) > now
                and (resolved_at is None or (now - float(resolved_at)) <= self.CONVERSATION_TTL)
            )
            if within_retention:
                won = db.execute(
                    """UPDATE cases
                       SET status = 'waiting',
                           holder = NULL,
                           holder_name = NULL,
                           resolved_reason = NULL,
                           resolved_at = NULL,
                           resumed_at = ?,
                           resume_count = resume_count + 1,
                           awaiting_customer_since = NULL,
                           reminder_deadline = NULL,
                           reminded_at = NULL,
                           inactivity_deadline = NULL,
                           feedback_prompted_at = NULL,
                           completion_deadline = NULL,
                           version = version + 1,
                           updated_at = ?
                       WHERE case_id = ? AND version = ? AND status = 'resolved'""",
                    (now, now, latest_case['case_id'], latest_case['version']),
                ).rowcount
                if won == 1:
                    db.execute(
                        'UPDATE conversations SET expires_at = ? WHERE id = ?',
                        (now + self.CONVERSATION_TTL, cid),
                    )
                    self.log(
                        db,
                        customer,
                        'customer_resumed',
                        conv['order_id'] if conv is not None else None,
                        case_id=latest_case['case_id'],
                        conversation_id=cid,
                        resume_count=int(latest_case.get('resume_count') or 0) + 1,
                    )
            else:
                self._ensure_customer_in_tx(db, customer)
                if conv is None:
                    db.execute(
                        """INSERT INTO conversations(id, customer_id, order_id, product_id, revision, expires_at, provider_id)
                           VALUES (?, ?, NULL, NULL, 0, ?, 'custom')""",
                        (cid, customer, now + self.CONVERSATION_TTL),
                    )
                else:
                    db.execute(
                        'UPDATE conversations SET order_id = NULL, product_id = NULL, revision = revision + 1, expires_at = ? WHERE id = ?',
                        (now + self.CONVERSATION_TTL, cid),
                    )
                new_case_id = f'case_{uuid.uuid4().hex}'
                inserted = db.execute(
                    """INSERT INTO cases(
                           case_id, conversation_id, customer_id, status, holder, holder_name,
                           version, resume_count, previous_case_id, created_at, updated_at
                       ) VALUES (?, ?, ?, 'waiting', NULL, NULL, 1, 0, ?, ?, ?)
                       ON CONFLICT (conversation_id) WHERE status <> 'resolved' DO NOTHING""",
                    (new_case_id, cid, customer, latest_case['case_id'], now, now),
                ).rowcount
                if inserted == 1:
                    self.log(
                        db,
                        customer,
                        'case_opened_from_expired_case',
                        None,
                        case_id=new_case_id,
                        previous_case_id=latest_case['case_id'],
                        conversation_id=cid,
                    )
            conv_after = db.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone()
            case_after = self._latest_case_in_tx(db, cid)
            return dict(conv_after), dict(case_after)

        require(conv is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn. Hãy mở cuộc trò chuyện mới.')
        require(float(conv['expires_at']) > now, 409, 'conversation_expired', 'Cuộc trò chuyện đã hết hạn. Hãy bấm Cuộc trò chuyện mới.')
        db.execute(
            """UPDATE cases
               SET awaiting_customer_since = NULL,
                   reminder_deadline = NULL,
                   reminded_at = NULL,
                   inactivity_deadline = NULL,
                   feedback_prompted_at = NULL,
                   completion_deadline = NULL,
                   version = version + 1,
                   updated_at = ?
               WHERE case_id = ? AND status <> 'resolved'""",
            (now, latest_case['case_id']),
        )
        case_after = self._latest_case_in_tx(db, cid)
        return dict(conv), dict(case_after)

    def prepare_customer_chat(self, customer, cid):
        require(isinstance(cid, str) and re.fullmatch(r'[a-f0-9-]{36}', cid),
                400, 'invalid_conversation', 'Mã cuộc trò chuyện không hợp lệ.')
        now = self._now()
        with self.connection(write=True) as db:
            conv, active_case = self._prepare_customer_activity_in_tx(db, customer, cid, now)
        return conv, self._case_public_dict(active_case)

    def resume_case(self, customer, cid):
        require(isinstance(cid, str) and re.fullmatch(r'[a-f0-9-]{36}', cid),
                400, 'invalid_conversation', 'Mã cuộc trò chuyện không hợp lệ.')
        now = self._now()
        with self.connection(write=True) as db:
            conv, active_case = self._prepare_customer_activity_in_tx(db, customer, cid, now)
        pub = self._case_public_dict(active_case)
        return {
            'status': 'ok',
            'conversation_id': conv['id'],
            'case_id': pub['case_id'],
            'previous_case_id': pub['previous_case_id'],
            'reopened_same_case': pub['previous_case_id'] is None or pub['resume_count'] > 0,
            'case': pub,
        }

    def has_turns(self, customer, cid) -> bool:
        require(isinstance(cid, str) and re.fullmatch(r'[a-f0-9-]{36}', cid),
                400, 'invalid_conversation', 'Mã cuộc trò chuyện không hợp lệ.')
        with self.connection() as db:
            active_case = self._latest_case_in_tx(db, cid)
            if active_case is not None and active_case['previous_case_id'] is not None:
                row = db.execute(
                    'SELECT 1 FROM agent_turns WHERE conversation_id=? AND customer_id=? '
                    'AND created_at >= ? AND request_id NOT LIKE ? AND request_id NOT LIKE ? '
                    'AND request_id NOT LIKE ? LIMIT 1',
                    (cid, customer, float(active_case['created_at']) - 1e-6, 'sys-reminder-%', 'sys-oar-%', 'sys-notice-%'),
                ).fetchone()
            else:
                row = db.execute(
                    'SELECT 1 FROM agent_turns WHERE conversation_id=? AND customer_id=? '
                    'AND request_id NOT LIKE ? AND request_id NOT LIKE ? AND request_id NOT LIKE ? LIMIT 1',
                    (cid, customer, 'sys-reminder-%', 'sys-oar-%', 'sys-notice-%'),
                ).fetchone()
            return row is not None

    def remember(self, customer, snapshot, oid, pid):
        if snapshot is None:
            return
        now = self._now()
        with self.connection(write=True) as db:
            if oid is not None:
                self.owned(db, customer, oid)
            updated = db.execute('''UPDATE conversations SET order_id=?,product_id=?,revision=revision+1,expires_at=?
                WHERE id=? AND customer_id=? AND revision=? AND expires_at>?''',
                (oid, pid, now + self.CONVERSATION_TTL, snapshot['id'], customer, snapshot['revision'], now)).rowcount
            require(updated == 1, 409, 'conversation_changed', 'Ngữ cảnh đã thay đổi hoặc hết hạn. Hãy gửi lại yêu cầu trong cuộc trò chuyện hiện tại.')

    def replay(self, customer, cid, request_id, digest):
        with self.connection() as db:
            row = db.execute('''SELECT id,input_hash,result FROM agent_turns
                WHERE conversation_id=? AND customer_id=? AND request_id=?''',
                (cid, customer, request_id)).fetchone()
        if row:
            require(row['input_hash'] == digest, 409, 'request_conflict', 'Mã yêu cầu đã dùng cho nội dung khác.')
            result = json.loads(row['result'])
            if isinstance(result, dict):
                if isinstance(result.get('message'), str) and contains_canary_or_secret(result['message']):
                    result['message'] = SAFE_REFUSAL_MESSAGE
                _, result = sanitize_structured_payload(result, preserve_reasoning=True)
            result['turn_id'] = row['id'] if 'id' in row else row[0]
            # The answer is explicitly an old result. Never reopen a stale cancel card.
            return {**result, 'replayed': True, 'action': 'reply'}
        return None

    def get_graph_run(self, run_id):
        with self.connection() as db:
            row = db.execute('''SELECT id,customer_id,fingerprint,seed,expires_at,lease_owner,lease_until
                FROM graph_runs WHERE id=?''', (run_id,)).fetchone()
            return dict(row) if row else None

    def history(self, customer, cid, limit=6):
        with self.connection() as db:
            active_case = self._latest_case_in_tx(db, cid)
            if active_case is not None and active_case['previous_case_id'] is not None:
                rows = db.execute(
                    '''SELECT messages FROM agent_turns
                       WHERE conversation_id=? AND customer_id=?
                         AND created_at >= ? AND request_id NOT LIKE ? AND request_id NOT LIKE ? AND request_id NOT LIKE ?
                       ORDER BY id DESC LIMIT ?''',
                    (cid, customer, float(active_case['created_at']) - 1e-6, 'sys-reminder-%', 'sys-oar-%', 'sys-notice-%', limit),
                ).fetchall()
            else:
                rows = db.execute(
                    '''SELECT messages FROM agent_turns
                       WHERE conversation_id=? AND customer_id=?
                         AND request_id NOT LIKE ? AND request_id NOT LIKE ? AND request_id NOT LIKE ?
                       ORDER BY id DESC LIMIT ?''',
                    (cid, customer, 'sys-reminder-%', 'sys-oar-%', 'sys-notice-%', limit),
                ).fetchall()
        turns, characters, count = [], 0, 0
        preserved_recent_image = False
        for row in rows:
            _, raw = sanitize_structured_payload(json.loads(row['messages']), preserve_reasoning=True)
            clean_turn = []
            for m in raw:
                role = m.get('role')
                content = m.get('content', '')
                if not isinstance(content, str):
                    content = str(content)
                if role == 'user':
                    user_entry = {'role': 'user', 'content': content}
                    att = m.get('attachment')
                    if isinstance(att, dict) and att.get('type') in ('image', 'document'):
                        if att.get('type') == 'image' and att.get('data') and not preserved_recent_image:
                            user_entry['attachment'] = att
                            preserved_recent_image = True
                        else:
                            user_entry['attachment'] = {'type': att.get('type'), 'name': att.get('name', '')}
                    clean_turn.append(user_entry)
                elif role == 'assistant':
                    entry = {'role': 'assistant', 'content': content}
                    if 'tool_calls' in m and m['tool_calls']:
                        entry['tool_calls'] = m['tool_calls']
                    clean_turn.append(entry)
                elif role == 'tool':
                    clean_turn.append({'role': 'tool', 'tool_name': m.get('tool_name', ''), 'content': content})
            if not clean_turn:
                continue
            size = sum(len(m.get('content', '')) + len(json.dumps(m.get('tool_calls', []), ensure_ascii=False)) for m in clean_turn)
            if characters + size > 4500 or count + len(clean_turn) > 16:
                break  # Keep whole contiguous turns, never orphan tool calls/results.
            characters += size; count += len(clean_turn); turns.append(clean_turn)

        flat = [m for turn in reversed(turns) for m in turn]
        if not flat:
            return []

        # Normalize message sequence for LLM agent protocol:
        # Merge adjacent turns of the same role so user->assistant alternation is strictly preserved
        normalized = []
        for m in flat:
            if not normalized:
                if m['role'] == 'user':
                    normalized.append(dict(m))
                continue
            prev = normalized[-1]
            if m['role'] == 'user' and prev['role'] == 'user':
                prev['content'] = (prev['content'] + '\n' + m['content'])[:2000]
            elif m['role'] == 'assistant' and prev['role'] == 'assistant' and 'tool_calls' not in m and 'tool_calls' not in prev:
                prev['content'] = (prev['content'] + '\n' + m['content'])
            else:
                normalized.append(dict(m))

        # Because `run_agent()` will append `+ [user]`, history MUST end with an assistant turn.
        # If the last turn was user (e.g. from an unreplied human message), drop it so the new question takes its place.
        while normalized and normalized[-1]['role'] != 'assistant':
            normalized.pop()

        if not normalized or normalized[0]['role'] != 'user':
            return []

        return normalized

    def finish_turn(self, customer, snapshot, request_id, digest, messages, result, versions):
        now = self._now()
        tcfg = self._timer_config()
        with self.connection(write=True) as db:
            for oid, version in versions.items():
                require(self.owned(db, customer, oid)['version'] == version, 409, 'order_changed_during_chat',
                        'Đơn đã thay đổi trong lúc model trả lời. Hãy gửi lại để đọc trạng thái mới.')
            context = result['context']
            updated = db.execute('''UPDATE conversations SET order_id=?,product_id=?,revision=revision+1,expires_at=?
                WHERE id=? AND customer_id=? AND revision=? AND expires_at>?''',
                (context['order_id'], context['product_id'], now + self.CONVERSATION_TTL, snapshot['id'], customer,
                 snapshot['revision'], now)).rowcount
            require(updated == 1, 409, 'conversation_changed', 'Ngữ cảnh đã thay đổi hoặc hết hạn. Hãy gửi lại trong cuộc trò chuyện hiện tại.')
            case_row = self._ensure_active_case_in_tx(db, snapshot['id'], customer, now)
            open_ep = db.execute(
                "SELECT 1 FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                (case_row['case_id'],),
            ).fetchone()
            if (
                not result.get('human_support')
                and open_ep is None
                and case_row['status'] == 'waiting'
                and case_row.get('holder') is None
                and case_row.get('feedback_prompted_at') is None
            ):
                db.execute(
                    """UPDATE cases
                       SET awaiting_customer_since = ?,
                           reminder_deadline = ?,
                           reminded_at = NULL,
                           inactivity_deadline = NULL,
                           version = version + 1,
                           updated_at = ?
                       WHERE case_id = ? AND status = 'waiting' AND holder IS NULL AND feedback_prompted_at IS NULL""",
                    (now, now + tcfg.reminder_seconds, now, case_row['case_id']),
                )
            else:
                db.execute(
                    'UPDATE cases SET updated_at = ? WHERE case_id = ?',
                    (now, case_row['case_id']),
                )
            case_after = self._latest_case_in_tx(db, snapshot['id'])
            result['case'] = self._case_public_dict(case_after)
            cursor = db.execute('''INSERT INTO agent_turns(conversation_id,customer_id,request_id,input_hash,messages,result,created_at)
                VALUES (?,?,?,?,?,?,?) RETURNING id''', (snapshot['id'], customer, request_id, digest,
                json.dumps(messages, ensure_ascii=False), json.dumps(result, ensure_ascii=False), now))
            row = cursor.fetchone()
            turn_id = row['id'] if row and 'id' in row else (row[0] if row else getattr(cursor, 'lastrowid', None))
            result['turn_id'] = turn_id
            self.log(db, customer, 'agent_replied', context['order_id'], trace=result['trace'])
            return turn_id

    def prompt_case_feedback(self, customer: str, cid: str) -> dict:
        require(isinstance(cid, str) and re.fullmatch(r'[a-f0-9-]{36}', cid),
                400, 'invalid_conversation', 'Mã cuộc trò chuyện không hợp lệ.')
        now = self._now()
        tcfg = self._timer_config()
        with self.connection(write=True) as db:
            conv = db.execute(
                'SELECT id, customer_id, order_id, expires_at FROM conversations WHERE id = ? AND customer_id = ?',
                (cid, customer),
            ).fetchone()
            require(conv is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn.')
            require(float(conv['expires_at']) > now, 409, 'conversation_expired', 'Cuộc trò chuyện đã hết hạn.')
            case_row = self._latest_case_in_tx(db, cid)
            if case_row is None:
                case_row = self._ensure_active_case_in_tx(db, cid, customer, now)
            else:
                case_row = dict(case_row)
            require(case_row['status'] != 'resolved', 409, 'case_already_resolved', 'Ca hỗ trợ đã đóng.')
            open_ep = db.execute(
                "SELECT 1 FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                (case_row['case_id'],),
            ).fetchone()
            require(
                case_row.get('holder') is None and open_ep is None,
                409,
                'case_in_human_handoff',
                'Ca hỗ trợ đang chờ hoặc do nhân viên phụ trách; không đặt timer kết thúc tự động.',
            )
            won = db.execute(
                """UPDATE cases
                   SET feedback_prompted_at = ?,
                       completion_deadline = ?,
                       awaiting_customer_since = NULL,
                       reminder_deadline = NULL,
                       reminded_at = NULL,
                       inactivity_deadline = NULL,
                       version = version + 1,
                       updated_at = ?
                   WHERE case_id = ? AND version = ? AND status <> 'resolved' AND holder IS NULL""",
                (now, now + tcfg.completion_seconds, now, case_row['case_id'], case_row['version']),
            ).rowcount
            require(won == 1, 409, 'case_version_conflict', 'Trạng thái ca hỗ trợ vừa thay đổi; hãy thử lại.')
            self.log(
                db,
                customer,
                'case_feedback_prompted',
                conv['order_id'],
                case_id=case_row['case_id'],
                conversation_id=cid,
                completion_deadline=now + tcfg.completion_seconds,
            )
            updated_case = self._latest_case_in_tx(db, cid)
        return {
            'status': 'ok',
            'conversation_id': cid,
            'case_id': case_row['case_id'],
            'case': self._case_public_dict(updated_case),
        }

    def process_due_case_timers(self, now: float | None = None) -> dict:
        now_ts = float(self._now() if now is None else now)
        tcfg = self._timer_config()
        reminded = 0
        resolved_inactivity = 0
        resolved_completed = 0

        with self.connection() as db:
            due_reminders = [
                dict(r)
                for r in db.execute(
                    """SELECT case_id, conversation_id, customer_id, version
                       FROM cases
                       WHERE status = 'waiting'
                         AND holder IS NULL
                         AND reminded_at IS NULL
                         AND feedback_prompted_at IS NULL
                         AND reminder_deadline IS NOT NULL
                         AND reminder_deadline <= ?
                         AND NOT EXISTS (
                             SELECT 1 FROM handoff_episodes he
                             WHERE he.case_id = cases.case_id AND he.status = 'pending'
                         )
                       ORDER BY reminder_deadline ASC, case_id ASC""",
                    (now_ts,),
                ).fetchall()
            ]

        for cand in due_reminders:
            with self.connection(write=True) as db:
                won = db.execute(
                    """UPDATE cases
                       SET reminded_at = ?,
                           reminder_deadline = NULL,
                           inactivity_deadline = ?,
                           version = version + 1,
                           updated_at = ?
                       WHERE case_id = ? AND version = ?
                         AND status = 'waiting' AND holder IS NULL
                         AND reminded_at IS NULL AND feedback_prompted_at IS NULL
                         AND reminder_deadline IS NOT NULL AND reminder_deadline <= ?
                         AND NOT EXISTS (
                             SELECT 1 FROM handoff_episodes he
                             WHERE he.case_id = cases.case_id AND he.status = 'pending'
                         )""",
                    (
                        now_ts,
                        now_ts + tcfg.post_reminder_close_seconds,
                        now_ts,
                        cand['case_id'],
                        cand['version'],
                        now_ts,
                    ),
                ).rowcount
                if won == 1:
                    reminded += 1
                    conv = db.execute(
                        'SELECT id, order_id, product_id FROM conversations WHERE id = ?',
                        (cand['conversation_id'],),
                    ).fetchone()
                    if conv is not None:
                        turn_messages = [{'role': 'assistant', 'content': CASE_INACTIVITY_REMINDER_MESSAGE}]
                        turn_result = {
                            'message': CASE_INACTIVITY_REMINDER_MESSAGE,
                            'author': 'system_reminder',
                            'source': 'case_timer',
                            'case_id': cand['case_id'],
                            'context': {'order_id': conv['order_id'], 'product_id': conv['product_id']},
                            'trace': {'case_timer': 'inactivity_reminder', 'case_version': int(cand['version']) + 1},
                        }
                        db.execute(
                            """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                               VALUES (?, ?, ?, 'system-reminder', ?, ?, ?)
                               ON CONFLICT(conversation_id, request_id) DO NOTHING""",
                            (
                                cand['conversation_id'],
                                cand['customer_id'],
                                f"sys-reminder-{cand['case_id']}-v{cand['version']}",
                                json.dumps(turn_messages, ensure_ascii=False),
                                json.dumps(turn_result, ensure_ascii=False),
                                now_ts,
                            ),
                        )
                    self.log(
                        db,
                        cand['customer_id'],
                        'case_inactivity_reminded',
                        conv['order_id'] if conv else None,
                        case_id=cand['case_id'],
                        conversation_id=cand['conversation_id'],
                    )

        with self.connection() as db:
            due_inactivity = [
                dict(r)
                for r in db.execute(
                    """SELECT case_id, conversation_id, customer_id, version
                       FROM cases
                       WHERE status = 'waiting'
                         AND holder IS NULL
                         AND reminded_at IS NOT NULL
                         AND feedback_prompted_at IS NULL
                         AND inactivity_deadline IS NOT NULL
                         AND inactivity_deadline <= ?
                         AND NOT EXISTS (
                             SELECT 1 FROM handoff_episodes he
                             WHERE he.case_id = cases.case_id AND he.status = 'pending'
                         )
                       ORDER BY inactivity_deadline ASC, case_id ASC""",
                    (now_ts,),
                ).fetchall()
            ]

        for cand in due_inactivity:
            with self.connection(write=True) as db:
                won = db.execute(
                    """UPDATE cases
                       SET status = 'resolved',
                           resolved_reason = 'inactivity',
                           resolved_at = ?,
                           awaiting_customer_since = NULL,
                           reminder_deadline = NULL,
                           inactivity_deadline = NULL,
                           completion_deadline = NULL,
                           version = version + 1,
                           updated_at = ?
                       WHERE case_id = ? AND version = ?
                         AND status = 'waiting' AND holder IS NULL
                         AND reminded_at IS NOT NULL AND feedback_prompted_at IS NULL
                         AND inactivity_deadline IS NOT NULL AND inactivity_deadline <= ?
                         AND NOT EXISTS (
                             SELECT 1 FROM handoff_episodes he
                             WHERE he.case_id = cases.case_id AND he.status = 'pending'
                         )""",
                    (now_ts, now_ts, cand['case_id'], cand['version'], now_ts),
                ).rowcount
                if won == 1:
                    resolved_inactivity += 1
                    conv = db.execute(
                        'SELECT order_id FROM conversations WHERE id = ?',
                        (cand['conversation_id'],),
                    ).fetchone()
                    leases = self._release_conversation_leases_in_tx(
                        db, cand['customer_id'], cand['conversation_id']
                    )
                    self.log(
                        db,
                        cand['customer_id'],
                        'case_resolved_inactivity',
                        conv['order_id'] if conv else None,
                        case_id=cand['case_id'],
                        conversation_id=cand['conversation_id'],
                        leases_released=leases,
                    )

        with self.connection() as db:
            due_completion = [
                dict(r)
                for r in db.execute(
                    """SELECT case_id, conversation_id, customer_id, version
                       FROM cases
                       WHERE status <> 'resolved'
                         AND holder IS NULL
                         AND feedback_prompted_at IS NOT NULL
                         AND completion_deadline IS NOT NULL
                         AND completion_deadline <= ?
                         AND NOT EXISTS (
                             SELECT 1 FROM handoff_episodes he
                             WHERE he.case_id = cases.case_id AND he.status = 'pending'
                         )
                       ORDER BY completion_deadline ASC, case_id ASC""",
                    (now_ts,),
                ).fetchall()
            ]

        for cand in due_completion:
            with self.connection(write=True) as db:
                won = db.execute(
                    """UPDATE cases
                       SET status = 'resolved',
                           resolved_reason = 'completed',
                           resolved_at = ?,
                           awaiting_customer_since = NULL,
                           reminder_deadline = NULL,
                           inactivity_deadline = NULL,
                           completion_deadline = NULL,
                           version = version + 1,
                           updated_at = ?
                       WHERE case_id = ? AND version = ?
                         AND status <> 'resolved' AND holder IS NULL
                         AND feedback_prompted_at IS NOT NULL
                         AND completion_deadline IS NOT NULL AND completion_deadline <= ?
                         AND NOT EXISTS (
                             SELECT 1 FROM handoff_episodes he
                             WHERE he.case_id = cases.case_id AND he.status = 'pending'
                         )""",
                    (now_ts, now_ts, cand['case_id'], cand['version'], now_ts),
                ).rowcount
                if won == 1:
                    resolved_completed += 1
                    conv = db.execute(
                        'SELECT order_id FROM conversations WHERE id = ?',
                        (cand['conversation_id'],),
                    ).fetchone()
                    leases = self._release_conversation_leases_in_tx(
                        db, cand['customer_id'], cand['conversation_id']
                    )
                    self.log(
                        db,
                        cand['customer_id'],
                        'case_resolved_completed',
                        conv['order_id'] if conv else None,
                        case_id=cand['case_id'],
                        conversation_id=cand['conversation_id'],
                        leases_released=leases,
                    )

        return {
            'reminded': reminded,
            'resolved_inactivity': resolved_inactivity,
            'resolved_completed': resolved_completed,
        }

    def _append_case_system_notice_in_tx(
        self,
        db,
        *,
        conversation_id: str | None,
        customer_id: str,
        case_id: str,
        request_id: str,
        milestone: str,
        notice_text: str,
        staff_name: str | None = None,
        handoff_id: str | None = None,
        now: float | None = None,
    ) -> tuple[int | None, str]:
        if not request_id.startswith('sys-notice-'):
            raise ValueError(f'Case notice request_id must start with sys-notice-: {request_id!r}')
        now_ts = self._now() if now is None else float(now)
        if not conversation_id:
            return None, notice_text
        conv = db.execute(
            'SELECT id, order_id, product_id, expires_at FROM conversations WHERE id = ?',
            (conversation_id,),
        ).fetchone()
        if conv is None:
            return None, notice_text
        turn_messages = [{'role': 'assistant', 'content': notice_text}]
        trace_info: dict[str, object] = {
            'case_milestone': milestone,
            'case_id': case_id,
        }
        turn_result: dict[str, object] = {
            'message': notice_text,
            'author': 'system_case_notice',
            'source': 'interface',
            'milestone': milestone,
            'case_id': case_id,
            'context': {
                'order_id': conv['order_id'],
                'product_id': conv['product_id'],
            },
            'trace': trace_info,
        }
        if handoff_id:
            turn_result['handoff_id'] = handoff_id
            trace_info['handoff_id'] = handoff_id
        if staff_name:
            turn_result['staff_name'] = staff_name
            trace_info['staff_name'] = staff_name
        db.execute(
            """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
               VALUES (?, ?, ?, 'system-case-notice', ?, ?, ?)
               ON CONFLICT(conversation_id, request_id) DO NOTHING""",
            (
                conversation_id,
                customer_id,
                request_id,
                json.dumps(turn_messages, ensure_ascii=False),
                json.dumps(turn_result, ensure_ascii=False),
                now_ts,
            ),
        )
        new_exp = max(float(conv['expires_at']), now_ts + self.CONVERSATION_TTL)
        db.execute('UPDATE conversations SET expires_at = ? WHERE id = ?', (new_exp, conversation_id))
        turn_row = db.execute(
            'SELECT id FROM agent_turns WHERE conversation_id = ? AND request_id = ?',
            (conversation_id, request_id),
        ).fetchone()
        turn_id = turn_row['id'] if turn_row and 'id' in turn_row else (turn_row[0] if turn_row else None)
        return turn_id, notice_text

    def _request_human_handoff_in_tx(
        self,
        db,
        customer: str,
        cid: str,
        *,
        reason_code: str | None,
        comment: str | None,
        turn_id: int | None = None,
        sentiment: str | None = None,
        update_existing_feedback_only: bool = False,
        now: float | None = None,
        forbidden_on_mismatch: bool = False,
    ) -> dict:
        now_ts = self._now() if now is None else float(now)
        conv, active_case = self._prepare_customer_activity_in_tx(
            db, customer, cid, now_ts, forbidden_on_mismatch=forbidden_on_mismatch
        )
        case_id = active_case['case_id']
        open_ep = db.execute(
            "SELECT * FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
            (case_id,),
        ).fetchone()
        handoff_notice_msg = 'Đã gửi yêu cầu gặp nhân viên. Nhân viên CSKH sẽ phản hồi trong cuộc trò chuyện này.'
        notice_turn_id = None
        if open_ep is not None:
            handoff_id = open_ep['handoff_id']
            if comment is not None:
                db.execute(
                    'UPDATE handoff_episodes SET comment = ? WHERE handoff_id = ?',
                    (comment, handoff_id),
                )
            existing_notice = db.execute(
                'SELECT id FROM agent_turns WHERE conversation_id = ? AND request_id = ?',
                (cid, f'sys-notice-handoff-{handoff_id}'),
            ).fetchone()
            if existing_notice is not None:
                notice_turn_id = existing_notice['id'] if 'id' in existing_notice else existing_notice[0]
        else:
            handoff_id = f'hoff_{uuid.uuid4().hex}'
            db.execute(
                """INSERT INTO handoff_episodes(
                       handoff_id, case_id, conversation_id, customer_id,
                       status, reason_code, comment, created_at
                   ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (handoff_id, case_id, cid, customer, reason_code, comment, now_ts),
            )
            notice_turn_id, handoff_notice_msg = self._append_case_system_notice_in_tx(
                db,
                conversation_id=cid,
                customer_id=customer,
                case_id=case_id,
                request_id=f'sys-notice-handoff-{handoff_id}',
                milestone='handoff_requested',
                notice_text=handoff_notice_msg,
                handoff_id=handoff_id,
                now=now_ts,
            )

        next_status = 'in_progress' if active_case.get('holder') else 'waiting'
        db.execute(
            """UPDATE cases
               SET status = ?,
                   awaiting_customer_since = NULL,
                   reminder_deadline = NULL,
                   reminded_at = NULL,
                   inactivity_deadline = NULL,
                   feedback_prompted_at = NULL,
                   completion_deadline = NULL,
                   version = version + 1,
                   updated_at = ?
               WHERE case_id = ?""",
            (next_status, now_ts, case_id),
        )

        existing_fb = db.execute(
            """SELECT id FROM conversation_feedback
               WHERE conversation_id = ? AND feedback_type = 'human_handoff' AND COALESCE(reason_code, '') <> 'resolved'
               ORDER BY id DESC LIMIT 1""",
            (cid,),
        ).fetchone()
        if update_existing_feedback_only and existing_fb is not None:
            feedback_id = existing_fb['id']
            if comment is not None:
                db.execute('UPDATE conversation_feedback SET comment = ? WHERE id = ?', (comment, feedback_id))
        else:
            cursor = db.execute(
                """INSERT INTO conversation_feedback
                   (conversation_id, turn_id, customer_id, feedback_type, rating, sentiment_flag, reason_code, comment, created_at)
                   VALUES (?, ?, ?, 'human_handoff', NULL, ?, ?, ?, ?) RETURNING id""",
                (cid, turn_id, customer, sentiment, reason_code, comment, now_ts),
            )
            fb_row = cursor.fetchone()
            feedback_id = fb_row['id'] if fb_row and 'id' in fb_row else (fb_row[0] if fb_row else getattr(cursor, 'lastrowid', None))

        refreshed_case = self._latest_case_in_tx(db, cid)
        return {
            'case_id': case_id,
            'handoff_id': handoff_id,
            'feedback_id': feedback_id,
            'conversation': conv,
            'case': self._case_public_dict(refreshed_case),
            'notice_turn_id': notice_turn_id,
            'notice_message': handoff_notice_msg,
        }

    def request_human_handoff(
        self,
        customer: str,
        cid: str,
        *,
        reason_code: str = 'customer_requested_human',
        comment: str | None = None,
        turn_id: int | None = None,
    ) -> dict:
        require(isinstance(cid, str) and len(cid) <= 64 and bool(cid.strip()), 400, 'invalid_conversation', 'Thiếu hoặc sai conversation_id.')
        if comment is not None:
            require(isinstance(comment, str) and len(comment) <= 1000, 400, 'comment_too_long', 'Nhận xét tối đa 1000 ký tự.')
            if contains_canary_or_secret(comment):
                _, comment = sanitize_structured_payload(comment, preserve_reasoning=False)
        now = self._now()
        with self.connection(write=True) as db:
            handoff = self._request_human_handoff_in_tx(
                db,
                customer,
                cid,
                reason_code=reason_code,
                comment=comment,
                turn_id=turn_id,
                sentiment='neutral',
                now=now,
            )
            self.log(
                db,
                customer,
                'human_handoff_requested',
                handoff['conversation'].get('order_id'),
                case_id=handoff['case_id'],
                handoff_id=handoff['handoff_id'],
                reason_code=reason_code,
            )
        return {
            'status': 'ok',
            'case_id': handoff['case_id'],
            'handoff_id': handoff['handoff_id'],
            'feedback_id': handoff['feedback_id'],
            'case': handoff['case'],
            'notice_turn_id': handoff.get('notice_turn_id'),
            'notice_message': handoff.get('notice_message'),
            'created_at': now,
        }

    def record_feedback(self, customer, body):
        require(isinstance(body, dict), 400, 'invalid_payload', 'Dữ liệu phản hồi không hợp lệ.')
        cid = body.get('conversation_id')
        require(isinstance(cid, str) and len(cid) <= 64, 400, 'invalid_conversation', 'Thiếu hoặc sai conversation_id.')
        fb_type = body.get('feedback_type')
        require(fb_type in ('turn_rating', 'session_csat', 'human_handoff'), 400, 'invalid_feedback_type', 'Loại phản hồi không hợp lệ.')

        turn_id = body.get('turn_id')
        if turn_id is not None:
            require(type(turn_id) is int and turn_id > 0, 400, 'invalid_turn_id', 'Mã lượt thoại không hợp lệ.')

        rating = body.get('rating')
        if rating is not None:
            require(type(rating) is int and 1 <= rating <= 5, 400, 'invalid_rating', 'Đánh giá phải từ 1 đến 5 sao.')

        sentiment = body.get('sentiment_flag')
        if sentiment is not None:
            require(sentiment in ('positive', 'negative', 'neutral'), 400, 'invalid_sentiment', 'Cờ cảm xúc không hợp lệ.')

        vote = body.get('vote')
        if vote is not None:
            require(vote in ('like', 'dislike'), 400, 'invalid_vote', 'Đánh giá lượt thoại phải là like hoặc dislike.')
            if sentiment is None:
                sentiment = 'positive' if vote == 'like' else 'negative'

        reason_code = body.get('reason_code')
        if reason_code is not None:
            require(isinstance(reason_code, str) and len(reason_code) <= 64, 400, 'invalid_reason_code', 'Mã lý do không hợp lệ.')

        comment = body.get('comment')
        if comment is not None:
            require(isinstance(comment, str) and len(comment) <= 1000, 400, 'comment_too_long', 'Nhận xét tối đa 1000 ký tự.')
            if contains_canary_or_secret(comment):
                _, comment = sanitize_structured_payload(comment, preserve_reasoning=False)

        now = self._now()
        if fb_type == 'human_handoff':
            with self.connection(write=True) as db:
                handoff = self._request_human_handoff_in_tx(
                    db,
                    customer,
                    cid,
                    reason_code=reason_code or 'customer_requested_human',
                    comment=comment,
                    turn_id=turn_id,
                    sentiment=sentiment,
                    now=now,
                )
                self.log(
                    db,
                    customer,
                    'feedback_received',
                    None,
                    feedback_id=handoff['feedback_id'],
                    feedback_type=fb_type,
                    case_id=handoff['case_id'],
                    handoff_id=handoff['handoff_id'],
                    sentiment_flag=sentiment,
                )
            return {
                'status': 'ok',
                'feedback_id': handoff['feedback_id'],
                'feedback_type': fb_type,
                'case_id': handoff['case_id'],
                'handoff_id': handoff['handoff_id'],
                'case': handoff['case'],
                'notice_turn_id': handoff.get('notice_turn_id'),
                'notice_message': handoff.get('notice_message'),
                'created_at': now,
            }

        raw_value = None
        preference_label = None
        if vote in ('like', 'dislike'):
            raw_value = vote
            preference_label = 'chosen' if vote == 'like' else 'rejected'
        elif rating is not None:
            raw_value = str(rating)
            preference_label = 'chosen' if rating in (4, 5) else 'rejected'
        elif sentiment in ('positive', 'negative'):
            raw_value = 'like' if sentiment == 'positive' else 'dislike'
            preference_label = 'chosen' if sentiment == 'positive' else 'rejected'

        feedback_event_id = None
        with self.connection(write=True) as db:
            conv = db.execute('SELECT id FROM conversations WHERE id=? AND customer_id=?', (cid, customer)).fetchone()
            latest_case = self._latest_case_in_tx(db, cid)
            if conv is None and (latest_case is None or latest_case['customer_id'] != customer):
                raise ApiError(404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của khách hàng.')
            if latest_case is None:
                latest_case = self._ensure_active_case_in_tx(db, cid, customer, now)
            else:
                latest_case = dict(latest_case)

            cursor = db.execute('''INSERT INTO conversation_feedback
                (conversation_id, turn_id, customer_id, feedback_type, rating, sentiment_flag, reason_code, comment, created_at)
                VALUES (?,?,?,?,?,?,?,?,?) RETURNING id''',
                (cid, turn_id, customer, fb_type, rating, sentiment, reason_code, comment, now))
            row = cursor.fetchone()
            feedback_id = row['id'] if row and 'id' in row else (row[0] if row else getattr(cursor, 'lastrowid', None))

            if preference_label is not None and raw_value is not None:
                self._ensure_customer_in_tx(db, customer)
                feedback_event_id = f'fbev_{uuid.uuid4().hex}'
                db.execute(
                    """INSERT INTO case_feedback_events(
                           feedback_event_id, case_id, conversation_id, turn_id, customer_id,
                           feedback_type, raw_value, rating, sentiment_flag, preference_label,
                           reason_code, comment, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        feedback_event_id,
                        latest_case['case_id'],
                        cid,
                        turn_id,
                        customer,
                        fb_type,
                        raw_value,
                        rating,
                        sentiment,
                        preference_label,
                        reason_code,
                        comment,
                        now,
                    ),
                )
                fb_extra = {
                    'feedback_event_id': feedback_event_id,
                    'feedback_type': fb_type,
                    'preference_label': preference_label,
                }
                if rating is not None:
                    fb_extra['rating'] = rating
                if sentiment is not None:
                    fb_extra['sentiment_flag'] = sentiment
                if turn_id is not None:
                    fb_extra['turn_id'] = turn_id
                self._enqueue_outbox_in_tx(
                    db,
                    event_type='case_feedback_recorded',
                    actor={'principal_id': customer, 'role': 'customer'},
                    customer_id=customer,
                    case_id=latest_case['case_id'],
                    reason_code=reason_code,
                    correlation_id=feedback_event_id,
                    idempotency_key=feedback_event_id,
                    source='app',
                    now=now,
                    extra_fields=fb_extra,
                )
            self.log(db, customer, 'feedback_received', None,
                     feedback_id=feedback_id, feedback_event_id=feedback_event_id,
                     case_id=latest_case['case_id'], feedback_type=fb_type,
                     rating=rating, sentiment_flag=sentiment, preference_label=preference_label)
        out = {
            'status': 'ok',
            'feedback_id': feedback_id,
            'feedback_type': fb_type,
            'case_id': latest_case['case_id'],
            'created_at': now,
        }
        if feedback_event_id is not None:
            out['feedback_event_id'] = feedback_event_id
            out['preference_label'] = preference_label
            out['raw_value'] = raw_value
        return out

    def feedbacks(self, customer=None, conversation_id=None):
        with self.connection() as db:
            query = 'SELECT * FROM conversation_feedback'
            params = []
            clauses = []
            if customer:
                clauses.append('customer_id=?')
                params.append(customer)
            if conversation_id:
                clauses.append('conversation_id=?')
                params.append(conversation_id)
            if clauses:
                query += ' WHERE ' + ' AND '.join(clauses)
            query += ' ORDER BY id DESC'
            out = []
            for r in db.execute(query, tuple(params)):
                d = dict(r)
                if isinstance(d.get('comment'), str) and contains_canary_or_secret(d['comment']):
                    _, d['comment'] = sanitize_structured_payload(d['comment'], preserve_reasoning=False)
                out.append(d)
            return out

    def escalations(self, limit=20):
        now = self._now()
        held_threshold = float(self._timer_config().held_silence_seconds)
        with self.connection() as db:
            rows = db.execute('''
                SELECT he.handoff_id, he.case_id, k.conversation_id, k.customer_id,
                       k.status AS case_status, k.holder, k.holder_name, k.version AS case_version,
                       k.resumed_at, k.created_at AS case_created_at,
                       he.reason_code, he.comment, NULL AS sentiment_flag,
                       he.created_at, k.updated_at, c.name AS customer_name, conv.order_id
                FROM cases k
                JOIN handoff_episodes he
                  ON he.case_id = k.case_id AND he.status = 'pending'
                JOIN customers c ON k.customer_id = c.id
                LEFT JOIN conversations conv ON k.conversation_id = conv.id
                WHERE k.status IN ('waiting', 'in_progress')
                ORDER BY k.updated_at DESC, he.created_at DESC
                LIMIT ?
            ''', (limit,)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d['customer_silent_seconds'] = self._compute_customer_silent_seconds_in_tx(
                    db, d, now=now, threshold_seconds=held_threshold
                )
                d.pop('case_created_at', None)
                d['id'] = d['handoff_id']
                if isinstance(d.get('comment'), str) and contains_canary_or_secret(d['comment']):
                    _, d['comment'] = sanitize_structured_payload(d['comment'], preserve_reasoning=False)
                out.append(d)
        return out

    def list_conversations(self, customer, limit=20):
        now = self._now()
        with self.connection() as db:
            rows = db.execute('''
                SELECT c.id, c.customer_id, c.order_id, c.product_id, c.provider_id, c.expires_at,
                       SUM(CASE WHEN t.id IS NOT NULL
                                 AND t.request_id NOT LIKE ?
                                 AND t.request_id NOT LIKE ?
                                 AND t.request_id NOT LIKE ?
                           THEN 1 ELSE 0 END) as turns_count,
                       COUNT(t.id) as raw_turns_count,
                       MAX(t.created_at) as last_activity,
                       MIN(t.created_at) as first_activity
                FROM conversations c
                LEFT JOIN agent_turns t ON c.id = t.conversation_id
                WHERE c.customer_id = ? AND c.expires_at > ?
                GROUP BY c.id, c.customer_id, c.order_id, c.product_id, c.provider_id, c.expires_at
                ORDER BY COALESCE(MAX(t.created_at), c.expires_at) DESC
                LIMIT ?
            ''', ('sys-reminder-%', 'sys-oar-%', 'sys-notice-%', customer, now, limit)).fetchall()

            conversations = []
            for r in rows:
                item = dict(r)
                item['turns_count'] = int(item.get('turns_count') or 0)
                raw_cnt = int(item.pop('raw_turns_count', 0) or 0)
                item['has_case_notices'] = raw_cnt > item['turns_count']
                cid = item['id']
                first_turn = db.execute('''
                    SELECT messages, result FROM agent_turns
                    WHERE conversation_id=?
                      AND request_id NOT LIKE ?
                      AND request_id NOT LIKE ?
                      AND request_id NOT LIKE ?
                    ORDER BY id ASC LIMIT 1
                ''', (cid, 'sys-reminder-%', 'sys-oar-%', 'sys-notice-%')).fetchone()
                if first_turn is None and raw_cnt > 0:
                    first_turn = db.execute('''
                        SELECT messages, result FROM agent_turns
                        WHERE conversation_id=?
                        ORDER BY id ASC LIMIT 1
                    ''', (cid,)).fetchone()

                snippet = ""
                if first_turn:
                    try:
                        msgs = json.loads(first_turn['messages'])
                        for m in msgs:
                            if m.get('role') == 'user' and m.get('content'):
                                snippet = m['content'].strip()[:80]
                                break
                    except Exception:
                        pass
                    if not snippet:
                        try:
                            res = json.loads(first_turn['result'])
                            if res.get('message'):
                                snippet = res['message'].strip()[:80]
                        except Exception:
                            pass
                if snippet and contains_canary_or_secret(snippet):
                    snippet = SAFE_REFUSAL_MESSAGE[:80]

                latest_case = self._latest_case_in_tx(db, cid)
                open_ep = None
                if latest_case is not None:
                    open_ep = db.execute(
                        "SELECT handoff_id FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                        (latest_case['case_id'],),
                    ).fetchone()

                item['snippet'] = snippet or f"Cuộc trò chuyện {cid[:8]}"
                item['has_human_handoff'] = bool(
                    latest_case is not None
                    and latest_case['status'] in ('waiting', 'in_progress')
                    and open_ep is not None
                )
                if latest_case is not None:
                    item['case_id'] = latest_case['case_id']
                    item['case_status'] = latest_case['status']
                conversations.append(item)
            return conversations

    @staticmethod
    def _release_conversation_leases_in_tx(db, customer_id: str, cid: str) -> int:
        released = 0
        for gr in db.execute(
            'SELECT id, seed FROM graph_runs WHERE customer_id = ? AND lease_until > 0',
            (customer_id,),
        ).fetchall():
            try:
                seed_obj = json.loads(gr['seed']) if isinstance(gr['seed'], str) else gr['seed']
            except Exception:
                seed_obj = None
            if isinstance(seed_obj, dict) and seed_obj.get('id') == cid:
                released += db.execute(
                    'UPDATE graph_runs SET lease_owner = NULL, lease_until = 0 WHERE id = ?',
                    (gr['id'],),
                ).rowcount
        return released

    def staff_desk_cases(self, limit=50):
        now = self._now()
        held_threshold = float(self._timer_config().held_silence_seconds)
        with self.connection() as db:
            waiting_rows = db.execute(
                '''SELECT he.handoff_id, k.case_id, k.conversation_id, k.customer_id,
                          k.status, k.holder, k.holder_name, k.version,
                          k.resolved_reason, k.resolved_at, k.resume_count,
                          he.reason_code, he.comment, he.created_at, k.updated_at,
                          c.name AS customer_name, conv.order_id
                   FROM cases k
                   JOIN handoff_episodes he
                     ON he.case_id = k.case_id AND he.status = 'pending'
                   JOIN customers c ON k.customer_id = c.id
                   LEFT JOIN conversations conv ON k.conversation_id = conv.id
                   WHERE k.status = 'waiting' AND k.holder IS NULL
                   ORDER BY k.updated_at DESC, he.created_at DESC
                   LIMIT ?''',
                (limit,),
            ).fetchall()

            in_progress_rows = db.execute(
                '''SELECT he.handoff_id, k.case_id, k.conversation_id, k.customer_id,
                          k.status, k.holder, k.holder_name, k.version,
                          k.resolved_reason, k.resolved_at, k.resume_count,
                          k.resumed_at, k.created_at AS case_created_at,
                          he.reason_code, he.comment,
                          COALESCE(he.created_at, k.created_at) AS created_at, k.updated_at,
                          c.name AS customer_name, conv.order_id
                   FROM cases k
                   LEFT JOIN handoff_episodes he
                     ON he.case_id = k.case_id AND he.status = 'pending'
                   JOIN customers c ON k.customer_id = c.id
                   LEFT JOIN conversations conv ON k.conversation_id = conv.id
                   WHERE k.status = 'in_progress' AND k.holder IS NOT NULL
                   ORDER BY k.updated_at DESC
                   LIMIT ?''',
                (limit,),
            ).fetchall()

            resolved_rows = db.execute(
                '''SELECT (
                              SELECT he2.handoff_id FROM handoff_episodes he2
                              WHERE he2.case_id = k.case_id
                              ORDER BY he2.created_at DESC LIMIT 1
                          ) AS handoff_id,
                          k.case_id, k.conversation_id, k.customer_id,
                          k.status, k.holder, k.holder_name, k.version,
                          k.resolved_reason, k.resolved_at, k.resume_count,
                          (
                              SELECT he3.reason_code FROM handoff_episodes he3
                              WHERE he3.case_id = k.case_id
                              ORDER BY he3.created_at DESC LIMIT 1
                          ) AS reason_code,
                          (
                              SELECT he4.comment FROM handoff_episodes he4
                              WHERE he4.case_id = k.case_id
                              ORDER BY he4.created_at DESC LIMIT 1
                          ) AS comment,
                          k.created_at, k.updated_at,
                          c.name AS customer_name, conv.order_id
                   FROM cases k
                   JOIN customers c ON k.customer_id = c.id
                   JOIN conversations conv ON k.conversation_id = conv.id
                   WHERE k.status = 'resolved'
                     AND conv.expires_at > ?
                     AND (k.resolved_at IS NULL OR k.resolved_at >= ?)
                     AND EXISTS (SELECT 1 FROM handoff_episodes hex WHERE hex.case_id = k.case_id)
                   ORDER BY COALESCE(k.resolved_at, k.updated_at) DESC
                   LIMIT ?''',
                (now, now - self.CONVERSATION_TTL, limit),
            ).fetchall()
            open_action_cases = {
                r['case_id']
                for r in db.execute(
                    'SELECT DISTINCT case_id FROM order_action_requests WHERE closed_at IS NULL'
                ).fetchall()
            }

            def _clean(rows, *, compute_silence: bool = False):
                items = []
                for r in rows:
                    d = dict(r)
                    d['customer_silent_seconds'] = (
                        self._compute_customer_silent_seconds_in_tx(
                            db, d, now=now, threshold_seconds=held_threshold
                        )
                        if compute_silence
                        else None
                    )
                    d.pop('case_created_at', None)
                    d['id'] = d.get('handoff_id') or d['case_id']
                    d['sentiment_flag'] = None
                    d['has_open_order_action'] = d['case_id'] in open_action_cases
                    if isinstance(d.get('comment'), str) and contains_canary_or_secret(d['comment']):
                        _, d['comment'] = sanitize_structured_payload(d['comment'], preserve_reasoning=False)
                    items.append(d)
                return items

            waiting = _clean(waiting_rows, compute_silence=False)
            in_progress = _clean(in_progress_rows, compute_silence=True)
            resolved = _clean(resolved_rows, compute_silence=False)
        open_count = len(waiting) + len(in_progress)
        return {
            'waiting': waiting,
            'in_progress': in_progress,
            'resolved': resolved,
            'open_count': open_count,
            'counts': {
                'open': open_count,
                'waiting': len(waiting),
                'in_progress': len(in_progress),
                'resolved': len(resolved),
            },
        }

    def conversation_transcript(self, cid, *, case_id=None, read_only=False):
        now = self._now()
        with self.connection() as db:
            if case_id is not None:
                case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
                if case_row is not None and cid is None:
                    cid = case_row['conversation_id']
            else:
                case_row = self._latest_case_in_tx(db, cid) if cid else None
            open_ep = None
            silent_secs = None
            if case_row is not None:
                open_ep = db.execute(
                    "SELECT * FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                    (case_row['case_id'],),
                ).fetchone()
                silent_secs = self._compute_customer_silent_seconds_in_tx(db, case_row, now=now)
            conv = db.execute('''
                SELECT conv.*, c.name as customer_name
                FROM conversations conv
                JOIN customers c ON conv.customer_id = c.id
                WHERE conv.id=?
            ''', (cid,)).fetchone() if cid else None
            turns = db.execute('''
                SELECT id, customer_id, request_id, messages, result, created_at
                FROM agent_turns WHERE conversation_id=?
                ORDER BY id ASC
            ''', (cid,)).fetchall() if cid else []
            feedbacks = db.execute('''
                SELECT * FROM conversation_feedback WHERE conversation_id=?
                ORDER BY id ASC
            ''', (cid,)).fetchall() if cid else []
        clean_turns = []
        for t in turns:
            td = dict(t)
            if isinstance(td.get('messages'), str):
                try:
                    parsed_msgs = json.loads(td['messages'])
                    _, cleaned_msgs = sanitize_structured_payload(parsed_msgs, preserve_reasoning=True)
                    td['messages'] = json.dumps(cleaned_msgs, ensure_ascii=False)
                except Exception:
                    _, td['messages'] = sanitize_structured_payload(td['messages'], preserve_reasoning=True)
            elif isinstance(td.get('messages'), (list, dict)):
                _, td['messages'] = sanitize_structured_payload(td['messages'], preserve_reasoning=True)
            if isinstance(td.get('result'), str):
                try:
                    parsed_res = json.loads(td['result'])
                    if isinstance(parsed_res, dict) and isinstance(parsed_res.get('message'), str) and contains_canary_or_secret(parsed_res['message']):
                        parsed_res['message'] = SAFE_REFUSAL_MESSAGE
                    _, cleaned_res = sanitize_structured_payload(parsed_res, preserve_reasoning=True)
                    td['result'] = json.dumps(cleaned_res, ensure_ascii=False)
                except Exception:
                    _, td['result'] = sanitize_structured_payload(td['result'], preserve_reasoning=True)
            elif isinstance(td.get('result'), dict):
                parsed_res = dict(td['result'])
                if isinstance(parsed_res.get('message'), str) and contains_canary_or_secret(parsed_res['message']):
                    parsed_res['message'] = SAFE_REFUSAL_MESSAGE
                _, td['result'] = sanitize_structured_payload(parsed_res, preserve_reasoning=True)
            clean_turns.append(td)
        clean_feedbacks = []
        for f in feedbacks:
            fd = dict(f)
            if isinstance(fd.get('comment'), str) and contains_canary_or_secret(fd['comment']):
                _, fd['comment'] = sanitize_structured_payload(fd['comment'], preserve_reasoning=False)
            clean_feedbacks.append(fd)
        ep_dict = dict(open_ep) if open_ep is not None else None
        if ep_dict and isinstance(ep_dict.get('comment'), str) and contains_canary_or_secret(ep_dict['comment']):
            _, ep_dict['comment'] = sanitize_structured_payload(ep_dict['comment'], preserve_reasoning=False)
        return {
            'conversation': dict(conv) if conv else None,
            'case': self._case_public_dict(case_row, customer_silent_seconds=silent_secs),
            'active_handoff': ep_dict,
            'read_only': bool(read_only or (case_row is not None and case_row['status'] == 'resolved')),
            'turns': clean_turns,
            'feedbacks': clean_feedbacks,
        }

    def claim_case(self, case_id: str, *, staff_name=None, actor=None, expected_version=None):
        require(isinstance(case_id, str) and bool(case_id.strip()), 400, 'invalid_case_id', 'Mã ca hỗ trợ không hợp lệ.')
        staff_label = staff_name.strip() if (staff_name and isinstance(staff_name, str) and staff_name.strip()) else 'Nhân viên hỗ trợ'
        actor_meta = None
        if isinstance(actor, dict):
            actor_meta = {
                'principal_id': actor.get('principal_id'),
                'role': actor.get('role'),
                'tenant_id': actor.get('tenant_id'),
                'membership_id': actor.get('membership_id'),
                'display_name': actor.get('display_name'),
                'actor_type': actor.get('actor_type', 'principal'),
            }
        holder_id = (actor_meta.get('principal_id') if actor_meta else None) or staff_label
        now = self._now()
        with self.connection(write=True) as db:
            case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
            require(case_row is not None, 404, 'case_not_found', 'Không tìm thấy ca hỗ trợ.')
            require(case_row['status'] != 'resolved', 409, 'case_already_resolved', 'Ca hỗ trợ đã đóng, không thể nhận ca.')
            open_ep = db.execute(
                "SELECT * FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                (case_id,),
            ).fetchone()
            require(open_ep is not None, 409, 'case_not_escalated', 'Ca hỗ trợ chưa có yêu cầu chuyển tiếp nhân viên đang mở.')
            require(
                case_row['status'] == 'waiting' and case_row['holder'] is None,
                409,
                'case_claim_conflict',
                'Ca hỗ trợ đã được nhân viên khác nhận xử lý.',
            )
            if expected_version is not None:
                require(int(case_row['version']) == int(expected_version), 409, 'case_claim_conflict', 'Phiên bản ca hỗ trợ đã thay đổi.')
            won = db.execute(
                """UPDATE cases
                   SET holder = ?,
                       holder_name = ?,
                       status = 'in_progress',
                       awaiting_customer_since = NULL,
                       reminder_deadline = NULL,
                       reminded_at = NULL,
                       inactivity_deadline = NULL,
                       feedback_prompted_at = NULL,
                       completion_deadline = NULL,
                       version = version + 1,
                       updated_at = ?
                   WHERE case_id = ? AND version = ? AND status = 'waiting' AND holder IS NULL""",
                (holder_id, staff_label, now, case_id, case_row['version']),
            ).rowcount
            require(won == 1, 409, 'case_claim_conflict', 'Ca hỗ trợ vừa được nhân viên khác nhận trước đó.')
            conv = db.execute('SELECT order_id FROM conversations WHERE id = ?', (case_row['conversation_id'],)).fetchone()
            log_kwargs = {
                'case_id': case_id,
                'handoff_id': open_ep['handoff_id'],
                'holder': holder_id,
                'staff_name': staff_label,
            }
            if actor_meta is not None:
                log_kwargs['actor'] = actor_meta
            self.log(db, case_row['customer_id'], 'case_claimed', conv['order_id'] if conv else None, **log_kwargs)
            claim_ver = int(case_row['version']) + 1
            notice_turn_id, notice_message = self._append_case_system_notice_in_tx(
                db,
                conversation_id=case_row['conversation_id'],
                customer_id=case_row['customer_id'],
                case_id=case_id,
                request_id=f'sys-notice-claim-{case_id}-v{claim_ver}',
                milestone='case_claimed',
                notice_text=f'Nhân viên {staff_label} đã nhận ca hỗ trợ.',
                staff_name=staff_label,
                handoff_id=open_ep['handoff_id'],
                now=now,
            )
            caller_role = (actor_meta.get('role') if actor_meta else None) or 'staff'
            norm_claim_actor = self._normalize_actor(actor, holder_id, caller_role)
            pending_oars = db.execute(
                """SELECT * FROM order_action_requests
                   WHERE case_id = ? AND status = 'requested' AND closed_at IS NULL
                   ORDER BY created_at ASC, request_id ASC""",
                (case_id,),
            ).fetchall()
            for oar in pending_oars:
                old_ver = int(oar['version'])
                new_ver = old_ver + 1
                oar_won = db.execute(
                    """UPDATE order_action_requests
                       SET status = 'under_review',
                           reviewed_at = COALESCE(reviewed_at, ?),
                           version = ?,
                           updated_at = ?
                       WHERE request_id = ? AND version = ? AND status = 'requested'""",
                    (now, new_ver, now, oar['request_id'], old_ver),
                ).rowcount
                if oar_won == 1:
                    db.execute(
                        """INSERT INTO order_action_decisions(
                               decision_id, request_id, case_id, order_id, conversation_id,
                               action, from_status, to_status, from_refund_status, to_refund_status,
                               refund_decision, inspection_outcome, actor_principal_id, actor_role,
                               note, created_at
                           ) VALUES (?, ?, ?, ?, ?, 'start_review', 'requested', 'under_review', ?, ?,
                                     ?, ?, ?, ?, ?, ?)""",
                        (
                            f"oad_{uuid.uuid4().hex}",
                            oar['request_id'],
                            case_id,
                            oar['order_id'],
                            oar['conversation_id'],
                            oar['refund_status'],
                            oar['refund_status'],
                            oar['refund_decision'],
                            oar['inspection_outcome'],
                            norm_claim_actor['principal_id'],
                            norm_claim_actor['role'],
                            f"Nhận ca xử lý bởi {staff_label}"[:500],
                            now,
                        ),
                    )
                    self.log(
                        db,
                        oar['customer_id'],
                        'order_action_status_changed',
                        oar['order_id'],
                        request_id=oar['request_id'],
                        case_id=case_id,
                        action='start_review',
                        from_status='requested',
                        to_status='under_review',
                        version=new_ver,
                        actor=norm_claim_actor,
                    )
                    self._enqueue_outbox_in_tx(
                        db,
                        event_type='request_status_changed',
                        actor=norm_claim_actor,
                        customer_id=oar['customer_id'],
                        case_id=case_id,
                        order_action_request_id=oar['request_id'],
                        order_id=oar['order_id'],
                        before={'status': 'requested', 'version': old_ver},
                        after={'status': 'under_review', 'version': new_ver},
                        reason_code=oar['reason_code'],
                        correlation_id=f"claim:{case_id}:{oar['request_id']}",
                        idempotency_key=f"claim:{case_id}:{oar['request_id']}:v{new_ver}",
                        source='app',
                        now=now,
                    )
                    self._append_order_action_notice_in_tx(
                        db,
                        req_row=oar,
                        new_status='under_review',
                        new_version=new_ver,
                        now=now,
                    )
            updated = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
            silent_secs = self._compute_customer_silent_seconds_in_tx(db, updated, now=now)
        return {
            'status': 'ok',
            'claimed': True,
            'case_id': case_id,
            'handoff_id': open_ep['handoff_id'],
            'case': self._case_public_dict(updated, customer_silent_seconds=silent_secs),
            'notice_turn_id': notice_turn_id,
            'notice_message': notice_message,
        }

    def release_case(self, case_id: str, *, staff_name=None, actor=None, expected_version=None):
        require(isinstance(case_id, str) and bool(case_id.strip()), 400, 'invalid_case_id', 'Mã ca hỗ trợ không hợp lệ.')
        staff_label = staff_name.strip() if (staff_name and isinstance(staff_name, str) and staff_name.strip()) else 'Nhân viên hỗ trợ'
        actor_meta = None
        if isinstance(actor, dict):
            actor_meta = {
                'principal_id': actor.get('principal_id'),
                'role': actor.get('role'),
                'tenant_id': actor.get('tenant_id'),
                'membership_id': actor.get('membership_id'),
                'display_name': actor.get('display_name'),
                'actor_type': actor.get('actor_type', 'principal'),
            }
        caller_id = (actor_meta.get('principal_id') if actor_meta else None) or staff_label
        caller_role = actor_meta.get('role') if actor_meta else 'staff'
        now = self._now()
        with self.connection(write=True) as db:
            case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
            require(case_row is not None, 404, 'case_not_found', 'Không tìm thấy ca hỗ trợ.')
            require(
                case_row['status'] == 'in_progress' and case_row['holder'] is not None,
                409,
                'case_not_claimed',
                'Ca hỗ trợ hiện không ở trạng thái đang được giữ.',
            )
            require(
                case_row['holder'] == caller_id or caller_role == 'manager',
                403,
                'case_held_by_other',
                'Chỉ nhân viên đang giữ ca hoặc quản lý mới được trả ca về hàng chờ.',
            )
            if expected_version is not None:
                require(int(case_row['version']) == int(expected_version), 409, 'case_version_conflict', 'Phiên bản ca hỗ trợ đã thay đổi.')
            won = db.execute(
                """UPDATE cases
                   SET holder = NULL,
                       holder_name = NULL,
                       status = 'waiting',
                       version = version + 1,
                       updated_at = ?
                   WHERE case_id = ? AND version = ? AND status = 'in_progress'""",
                (now, case_id, case_row['version']),
            ).rowcount
            require(won == 1, 409, 'case_version_conflict', 'Trạng thái ca hỗ trợ vừa thay đổi; hãy tải lại.')
            conv = db.execute('SELECT order_id FROM conversations WHERE id = ?', (case_row['conversation_id'],)).fetchone()
            log_kwargs = {'case_id': case_id, 'previous_holder': case_row['holder'], 'staff_name': staff_label}
            if actor_meta is not None:
                log_kwargs['actor'] = actor_meta
            self.log(db, case_row['customer_id'], 'case_released', conv['order_id'] if conv else None, **log_kwargs)
            release_ver = int(case_row['version']) + 1
            notice_turn_id, notice_message = self._append_case_system_notice_in_tx(
                db,
                conversation_id=case_row['conversation_id'],
                customer_id=case_row['customer_id'],
                case_id=case_id,
                request_id=f'sys-notice-release-{case_id}-v{release_ver}',
                milestone='case_released',
                notice_text=f'Nhân viên {staff_label} đã trả ca hỗ trợ về hàng chờ.',
                staff_name=staff_label,
                now=now,
            )
            updated = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
        return {
            'status': 'ok',
            'released': True,
            'case_id': case_id,
            'case': self._case_public_dict(updated),
            'notice_turn_id': notice_turn_id,
            'notice_message': notice_message,
        }

    def staff_reply(self, customer_id, cid, staff_name, message, *, actor=None, case_id=None):
        require(isinstance(message, str) and message.strip(), 400, 'invalid_message', 'Tin nhắn không được để trống.')
        staff_name = staff_name.strip() if (staff_name and isinstance(staff_name, str) and staff_name.strip()) else "Nhân viên hỗ trợ"
        actor_meta = None
        if isinstance(actor, dict):
            actor_meta = {
                "principal_id": actor.get("principal_id"),
                "role": actor.get("role"),
                "tenant_id": actor.get("tenant_id"),
                "membership_id": actor.get("membership_id"),
                "display_name": actor.get("display_name"),
                "actor_type": actor.get("actor_type", "principal"),
            }
        now = self._now()
        req_id = f"staff-{uuid.uuid4().hex[:12]}"
        with self.connection(write=True) as db:
            if case_id is not None:
                case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
                require(case_row is not None, 404, 'case_not_found', 'Không tìm thấy ca hỗ trợ.')
                if cid is not None:
                    require(case_row['conversation_id'] == cid, 409, 'case_conversation_mismatch', 'Mã ca không khớp với cuộc trò chuyện.')
                cid = case_row['conversation_id']
            else:
                case_row = self._latest_case_in_tx(db, cid)
            conv = db.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone()
            require(conv is not None, 404, 'conversation_not_found', 'Cuộc trò chuyện không tồn tại hoặc đã bị xóa.')
            if customer_id is None:
                customer_id = conv['customer_id']
            require(
                case_row is not None and case_row['status'] in ('waiting', 'in_progress'),
                403,
                'case_not_escalated',
                'Cuộc trò chuyện hiện không có phiên hỗ trợ chuyển tiếp đang mở.',
            )
            open_ep = db.execute(
                "SELECT * FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                (case_row['case_id'],),
            ).fetchone()
            require(
                open_ep is not None,
                403,
                'case_not_escalated',
                'Cuộc trò chuyện hiện không có phiên hỗ trợ chuyển tiếp đang mở.',
            )
            if case_row['holder'] is not None and actor_meta is not None and actor_meta.get('principal_id'):
                require(
                    actor_meta['principal_id'] == case_row['holder'] or actor_meta.get('role') == 'manager',
                    409,
                    'case_held_by_other',
                    'Ca hỗ trợ đang do nhân viên khác phụ trách.',
                )

            turn_messages = [
                {"role": "assistant", "content": message}
            ]
            trace_payload = {"staff": True, "staff_name": staff_name, "case_id": case_row["case_id"], "handoff_id": open_ep["handoff_id"]}
            if actor_meta is not None:
                trace_payload.update({
                    "actor_principal_id": actor_meta["principal_id"],
                    "actor_role": actor_meta["role"],
                    "actor_membership_id": actor_meta["membership_id"],
                    "tenant_id": actor_meta["tenant_id"],
                })
            turn_result = {
                "message": message,
                "author": "staff",
                "staff_name": staff_name,
                "case_id": case_row["case_id"],
                "handoff_id": open_ep["handoff_id"],
                "context": {"order_id": conv["order_id"], "product_id": conv["product_id"]},
                "trace": trace_payload
            }
            if actor_meta is not None:
                turn_result["actor_role"] = actor_meta["role"]

            cursor = db.execute('''
                INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
            ''', (cid, customer_id, req_id, "staff-reply",
                  json.dumps(turn_messages, ensure_ascii=False),
                  json.dumps(turn_result, ensure_ascii=False), now))
            row = cursor.fetchone()
            turn_id = row['id'] if row and 'id' in row else (row[0] if row else getattr(cursor, 'lastrowid', None))

            db.execute('UPDATE conversations SET revision=revision+1, expires_at=? WHERE id=?', (now + self.CONVERSATION_TTL, cid))
            db.execute(
                """UPDATE cases
                   SET awaiting_customer_since = NULL,
                       reminder_deadline = NULL,
                       reminded_at = NULL,
                       inactivity_deadline = NULL,
                       feedback_prompted_at = NULL,
                       completion_deadline = NULL,
                       version = version + 1,
                       updated_at = ?
                   WHERE case_id = ?""",
                (now, case_row['case_id']),
            )
            db.execute('''
                UPDATE conversation_feedback
                SET comment=?
                WHERE conversation_id=? AND feedback_type='human_handoff' AND COALESCE(reason_code, '')!='resolved'
            ''', (f"Đang xử lý bởi {staff_name}: {message[:120]}", cid))

            log_kwargs = {
                "staff_name": staff_name,
                "message": message,
                "case_id": case_row["case_id"],
                "handoff_id": open_ep["handoff_id"],
            }
            if actor_meta is not None:
                log_kwargs["actor"] = actor_meta
            self.log(db, customer_id, 'staff_replied', conv['order_id'], **log_kwargs)
            updated_case = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_row['case_id'],)).fetchone()

        out = {
            'status': 'ok',
            'turn_id': turn_id,
            'request_id': req_id,
            'case_id': case_row['case_id'],
            'handoff_id': open_ep['handoff_id'],
            'case': self._case_public_dict(updated_case),
            'staff_name': staff_name,
            'message': message,
            'created_at': now
        }
        if actor_meta is not None:
            out['actor_role'] = actor_meta['role']
            out['actor_principal_id'] = actor_meta['principal_id']
        return out

    def customer_message(self, customer_id, cid, message):
        require(isinstance(message, str) and message.strip(), 400, 'invalid_message', 'Tin nhắn không được để trống.')
        clean_comment = message[:200]
        if contains_canary_or_secret(clean_comment):
            _, clean_comment = sanitize_structured_payload(clean_comment, preserve_reasoning=False)
        now = self._now()
        req_id = f"cust-{uuid.uuid4().hex[:12]}"
        with self.connection(write=True) as db:
            conv, _ = self._prepare_customer_activity_in_tx(
                db, customer_id, cid, now, forbidden_on_mismatch=True
            )
            turn_messages = [
                {"role": "user", "content": message}
            ]
            turn_result = {
                "message": "",
                "author": "customer",
                "status": "waiting_staff",
                "context": {"order_id": conv["order_id"], "product_id": conv["product_id"]},
                "trace": {"waiting_staff": True}
            }

            cursor = db.execute('''
                INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
            ''', (cid, customer_id, req_id, "customer-msg",
                  json.dumps(turn_messages, ensure_ascii=False),
                  json.dumps(turn_result, ensure_ascii=False), now))
            row = cursor.fetchone()
            turn_id = row['id'] if row and 'id' in row else (row[0] if row else getattr(cursor, 'lastrowid', None))

            db.execute('UPDATE conversations SET revision=revision+1, expires_at=? WHERE id=?', (now + self.CONVERSATION_TTL, cid))

            handoff = self._request_human_handoff_in_tx(
                db,
                customer_id,
                cid,
                reason_code='customer_message',
                comment=clean_comment,
                turn_id=turn_id,
                update_existing_feedback_only=True,
                now=now,
                forbidden_on_mismatch=True,
            )

            self.log(
                db,
                customer_id,
                'customer_messaged_staff',
                conv['order_id'],
                message=message,
                case_id=handoff['case_id'],
                handoff_id=handoff['handoff_id'],
            )

        return {
            'status': 'ok',
            'turn_id': turn_id,
            'request_id': req_id,
            'case_id': handoff['case_id'],
            'handoff_id': handoff['handoff_id'],
            'case': handoff['case'],
            'message': message,
            'created_at': now
        }

    def resolve_escalation(self, cid=None, staff_name=None, *, actor=None, case_id=None, handoff_id=None):
        staff_name = staff_name.strip() if (staff_name and isinstance(staff_name, str) and staff_name.strip()) else "Nhân viên hỗ trợ"
        actor_meta = None
        if isinstance(actor, dict):
            actor_meta = {
                "principal_id": actor.get("principal_id"),
                "role": actor.get("role"),
                "tenant_id": actor.get("tenant_id"),
                "membership_id": actor.get("membership_id"),
                "display_name": actor.get("display_name"),
                "actor_type": actor.get("actor_type", "principal"),
            }
        closed_by = (actor_meta.get("principal_id") if actor_meta else None) or staff_name
        now = self._now()
        with self.connection(write=True) as db:
            if case_id is not None:
                case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
                require(case_row is not None, 404, 'case_not_found', 'Không tìm thấy ca hỗ trợ.')
                if cid is not None:
                    require(case_row['conversation_id'] == cid, 409, 'case_conversation_mismatch', 'Mã ca không khớp với cuộc trò chuyện.')
                cid = case_row['conversation_id']
            elif handoff_id is not None and cid is None:
                ep_lookup = db.execute('SELECT * FROM handoff_episodes WHERE handoff_id = ?', (handoff_id,)).fetchone()
                require(ep_lookup is not None, 409, 'stale_handoff_episode', 'Phiên chuyển tiếp không tồn tại hoặc đã cũ.')
                case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (ep_lookup['case_id'],)).fetchone()
                require(case_row is not None, 404, 'case_not_found', 'Không tìm thấy ca hỗ trợ.')
                cid = case_row['conversation_id']
            else:
                case_row = self._latest_case_in_tx(db, cid) if cid else None

            conv = db.execute('SELECT customer_id, order_id FROM conversations WHERE id=?', (cid,)).fetchone() if cid else None
            require(
                conv is not None or case_row is not None,
                404,
                'conversation_not_found',
                'Cuộc trò chuyện không tồn tại hoặc đã bị xóa.',
            )
            require(
                case_row is not None,
                409,
                'case_not_escalated',
                'Cuộc trò chuyện không có phiên hỗ trợ đang mở để hoàn tất.',
            )

            if handoff_id is not None:
                ep_target = db.execute('SELECT * FROM handoff_episodes WHERE handoff_id = ?', (handoff_id,)).fetchone()
                require(
                    ep_target is not None
                    and ep_target['case_id'] == case_row['case_id']
                    and ep_target['status'] == 'pending',
                    409,
                    'stale_handoff_episode',
                    'Phiên chuyển tiếp đã cũ hoặc đã được đóng; không đóng phiên mới.',
                )

            require(
                case_row['status'] in ('waiting', 'in_progress'),
                409,
                'case_not_escalated',
                'Cuộc trò chuyện không có phiên hỗ trợ đang mở để hoàn tất.',
            )
            open_ep = db.execute(
                "SELECT * FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                (case_row['case_id'],),
            ).fetchone()
            require(
                open_ep is not None,
                409,
                'case_not_escalated',
                'Cuộc trò chuyện không có phiên hỗ trợ đang mở để hoàn tất.',
            )
            if handoff_id is not None:
                require(
                    open_ep['handoff_id'] == handoff_id,
                    409,
                    'stale_handoff_episode',
                    'Mã phiên chuyển tiếp không khớp với phiên đang mở của ca này.',
                )
            if case_row['holder'] is not None and actor_meta is not None and actor_meta.get('principal_id'):
                require(
                    actor_meta['principal_id'] == case_row['holder'] or actor_meta.get('role') == 'manager',
                    409,
                    'case_held_by_other',
                    'Ca hỗ trợ đang do nhân viên khác phụ trách.',
                )

            ep_updated = db.execute(
                """UPDATE handoff_episodes
                   SET status = 'resolved', closed_at = ?, closed_by = ?
                   WHERE handoff_id = ? AND status = 'pending'""",
                (now, closed_by, open_ep['handoff_id']),
            ).rowcount
            require(ep_updated == 1, 409, 'stale_handoff_episode', 'Phiên chuyển tiếp vừa thay đổi trạng thái.')

            case_updated = db.execute(
                """UPDATE cases
                   SET status = 'resolved',
                       resolved_reason = 'staff_resolved',
                       resolved_at = ?,
                       holder = NULL,
                       holder_name = NULL,
                       awaiting_customer_since = NULL,
                       reminder_deadline = NULL,
                       reminded_at = NULL,
                       inactivity_deadline = NULL,
                       feedback_prompted_at = NULL,
                       completion_deadline = NULL,
                       version = version + 1,
                       updated_at = ?
                   WHERE case_id = ? AND version = ? AND status <> 'resolved'""",
                (now, now, case_row['case_id'], case_row['version']),
            ).rowcount
            require(case_updated == 1, 409, 'case_version_conflict', 'Trạng thái ca hỗ trợ vừa thay đổi; hãy tải lại.')

            cust_id = conv['customer_id'] if conv is not None else case_row['customer_id']
            ord_id = conv['order_id'] if conv is not None else None
            leases_released = self._release_conversation_leases_in_tx(db, cust_id, cid)

            db.execute('''
                UPDATE conversation_feedback
                SET reason_code='resolved'
                WHERE conversation_id=? AND feedback_type='human_handoff' AND COALESCE(reason_code, '')!='resolved'
            ''', (cid,))
            log_kwargs = {
                "staff_name": staff_name,
                "case_id": case_row["case_id"],
                "handoff_id": open_ep["handoff_id"],
                "leases_released": leases_released,
            }
            if actor_meta is not None:
                log_kwargs["actor"] = actor_meta
            self.log(db, cust_id, 'escalation_resolved', ord_id, **log_kwargs)
            resolve_ver = int(case_row['version']) + 1
            notice_turn_id, notice_message = self._append_case_system_notice_in_tx(
                db,
                conversation_id=cid,
                customer_id=cust_id,
                case_id=case_row['case_id'],
                request_id=f"sys-notice-resolve-{case_row['case_id']}-v{resolve_ver}",
                milestone='case_resolved',
                notice_text=f'Nhân viên {staff_name} đã hoàn tất và đóng ca hỗ trợ. Hệ thống chuyển lại Trợ lý AI.',
                staff_name=staff_name,
                handoff_id=open_ep['handoff_id'],
                now=now,
            )
            updated_case = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_row['case_id'],)).fetchone()

        out = {
            'status': 'ok',
            'resolved': True,
            'case_id': case_row['case_id'],
            'handoff_id': open_ep['handoff_id'],
            'leases_released': leases_released,
            'case': self._case_public_dict(updated_case),
            'staff_name': staff_name,
            'notice_turn_id': notice_turn_id,
            'notice_message': notice_message,
        }
        if actor_meta is not None:
            out['actor_role'] = actor_meta['role']
            out['actor_principal_id'] = actor_meta['principal_id']
        return out


    @staticmethod
    def _is_db_integrity_error(exc: Exception) -> bool:
        if isinstance(exc, sqlite3.IntegrityError):
            return True
        if getattr(exc, "sqlstate", None) in ("23505", "23514", "23503"):
            return True
        return exc.__class__.__name__ in ("UniqueViolation", "IntegrityError", "CheckViolation", "ForeignKeyViolation")

    @staticmethod
    def _opaque_customer_ref(tenant_id: str, customer_id: str) -> str:
        digest = hashlib.sha256(f"{tenant_id}:{customer_id}".encode("utf-8")).hexdigest()[:24]
        return f"custref_{digest}"

    @staticmethod
    def _iso_utc(ts: float) -> str:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _effective_tenant_id(self, actor: dict | None = None) -> str:
        if isinstance(actor, dict):
            tid = str(actor.get("tenant_id") or "").strip()
            if tid:
                return tid
        tid = str(getattr(self, "tenant_id", "") or "").strip()
        return tid or "default"

    @staticmethod
    def _normalize_actor(actor: dict | None, fallback_principal: str, fallback_role: str) -> dict:
        if isinstance(actor, dict):
            pid = str(actor.get("principal_id") or "").strip() or fallback_principal
            role = str(actor.get("role") or "").strip() or fallback_role
            return {
                "principal_id": pid,
                "role": role,
                "tenant_id": actor.get("tenant_id"),
                "membership_id": actor.get("membership_id"),
                "display_name": actor.get("display_name"),
                "actor_type": actor.get("actor_type", "principal"),
            }
        return {
            "principal_id": fallback_principal,
            "role": fallback_role,
            "tenant_id": None,
            "membership_id": None,
            "display_name": None,
            "actor_type": "system" if fallback_role == "system" else "principal",
        }

    @staticmethod
    def _sanitize_reason_text(text: str | None) -> str | None:
        if text is None:
            return None
        require(isinstance(text, str), 400, "invalid_reason_text", "Ghi chú lý do phải là chuỗi ký tự.")
        cleaned = text.strip()
        require(len(cleaned) <= 500, 400, "reason_text_too_long", "Ghi chú lý do tối đa 500 ký tự.")
        if not cleaned:
            return None
        if contains_canary_or_secret(cleaned):
            _, cleaned = sanitize_structured_payload(cleaned, preserve_reasoning=False)
            cleaned = str(cleaned)[:500]
        return cleaned

    def _enqueue_outbox_in_tx(
        self,
        db,
        *,
        event_type: str,
        actor: dict | None,
        tenant_id: str | None = None,
        customer_id: str | None = None,
        case_id: str | None = None,
        order_action_request_id: str | None = None,
        order_id: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        reason_code: str | None = None,
        reason_text: str | None = None,
        evidence_refs: list[dict] | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        source: str = "app",
        now: float | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        require(source in ("app", "worker", "import"), 400, "invalid_outbox_source", "Nguồn outbox không hợp lệ.")
        now_ts = self._now() if now is None else float(now)
        resolved_tid = str(tenant_id or self._effective_tenant_id(actor)).strip() or "default"
        norm_actor = self._normalize_actor(actor, "system", "system")
        actor_principal = norm_actor["principal_id"]
        if norm_actor["role"] == "customer":
            actor_principal = self._opaque_customer_ref(resolved_tid, str(customer_id or actor_principal))
        event_id = str(uuid.uuid4())
        envelope: dict = {
            "schema": "retailops.order_action",
            "schema_version": 1,
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": self._iso_utc(now_ts),
            "tenant_id": resolved_tid,
            "actor": {
                "principal_id": actor_principal,
                "role": norm_actor["role"],
            },
        }
        if customer_id:
            envelope["customer_ref"] = self._opaque_customer_ref(resolved_tid, str(customer_id))
        if case_id is not None:
            envelope["case_id"] = case_id
        if order_action_request_id is not None:
            envelope["order_action_request_id"] = order_action_request_id
        if order_id is not None:
            envelope["order_id"] = order_id
        allowed_state_keys = ("status", "version", "refund_status", "refund_decision", "inspection_outcome")
        if isinstance(before, dict):
            envelope["before"] = {k: v for k, v in before.items() if k in allowed_state_keys}
        if isinstance(after, dict):
            envelope["after"] = {k: v for k, v in after.items() if k in allowed_state_keys}
        if reason_code is not None:
            envelope["reason_code"] = str(reason_code)[:64]
        clean_rt = self._sanitize_reason_text(reason_text) if reason_text is not None else None
        if clean_rt is not None:
            envelope["reason_text"] = clean_rt
        if evidence_refs is None and order_action_request_id is not None:
            ev_rows = db.execute(
                """SELECT evidence_id, sha256 FROM order_action_evidence
                   WHERE request_id = ?
                   ORDER BY created_at ASC, evidence_id ASC""",
                (order_action_request_id,),
            ).fetchall()
            if ev_rows:
                evidence_refs = [
                    {"evidence_id": r["evidence_id"], "sha256": r["sha256"]}
                    for r in ev_rows
                ]
        if evidence_refs:
            envelope["evidence_refs"] = [
                {"evidence_id": str(ref["evidence_id"]), "sha256": str(ref["sha256"])}
                for ref in evidence_refs
                if isinstance(ref, dict) and ref.get("evidence_id") and ref.get("sha256")
            ]
        if isinstance(extra_fields, dict):
            for k, v in extra_fields.items():
                if k not in envelope and k not in ("customer_id", "customer_name", "phone", "address", "comment", "message"):
                    envelope[k] = v
        envelope["correlation_id"] = str(correlation_id or event_id)
        envelope["idempotency_key"] = str(idempotency_key or event_id)
        envelope["source"] = source
        validate_outbox_envelope(envelope)

        payload_json = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        db.execute(
            """INSERT INTO integration_outbox(
                   event_id, tenant_id, event_type, payload_json, created_at,
                   status, attempts, next_attempt_at, last_error, published_at
               ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, NULL)""",
            (event_id, resolved_tid, event_type, payload_json, now_ts, now_ts),
        )
        return envelope

    def _serialize_order_action_in_tx(self, db, row, *, now: float | None = None) -> dict:
        now_ts = self._now() if now is None else float(now)
        d = dict(row)
        ord_row = db.execute("SELECT * FROM orders WHERE id = ?", (d["order_id"],)).fetchone()
        order_dict = dict(ord_row) if ord_row is not None else None
        delivered_at = order_dict.get("delivered_at") if order_dict is not None else None
        if delivered_at is None:
            days_since_delivery = None
            delivery_age_label = "chưa có ngày giao"
        else:
            days_since_delivery = max(0, int((now_ts - float(delivered_at)) // 86400))
            delivery_age_label = f"{days_since_delivery} ngày kể từ khi giao"
        decisions = [
            dict(r)
            for r in db.execute(
                """SELECT decision_id, request_id, case_id, order_id, conversation_id,
                          action, from_status, to_status, from_refund_status, to_refund_status,
                          refund_decision, inspection_outcome, actor_principal_id, actor_role,
                          note, created_at
                   FROM order_action_decisions
                   WHERE request_id = ?
                   ORDER BY created_at ASC, decision_id ASC""",
                (d["request_id"],),
            ).fetchall()
        ]
        ev_rows = db.execute(
            """SELECT evidence_id, request_id, case_id, uploaded_by_role, mime_type,
                      byte_size, width, height, sha256, created_at, file_purged_at
               FROM order_action_evidence
               WHERE request_id = ?
               ORDER BY created_at ASC, evidence_id ASC""",
            (d["request_id"],),
        ).fetchall()
        evidence = []
        for ev in ev_rows:
            ev_d = dict(ev)
            ev_d["purged"] = ev_d.get("file_purged_at") is not None
            ev_d["download_url"] = f"/api/order-actions/{d['request_id']}/evidence/{ev_d['evidence_id']}"
            evidence.append(ev_d)
        reason_label = ORDER_ACTION_REASONS.get(d["type"], {}).get(d["reason_code"])
        return {
            **d,
            "expected_order_version": int(d["expected_order_version"]),
            "version": int(d["version"]),
            "reason_label": reason_label or d["reason_code"],
            "order": order_dict,
            "delivered_at": delivered_at,
            "days_since_delivery": days_since_delivery,
            "delivery_age_label": delivery_age_label,
            "decisions": decisions,
            "evidence": evidence,
        }

    def _resolve_or_open_conversation_for_action_in_tx(
        self,
        db,
        *,
        customer_id: str,
        order_id: str,
        product_id: str | None,
        conversation_id: str | None,
        case_id: str | None,
        now_ts: float,
    ) -> str:
        if case_id is not None:
            case_row = db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            require(case_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
            require(
                case_row["customer_id"] == customer_id,
                403,
                "object_scope_denied",
                "Đơn hàng không thuộc khách hàng của ca hỗ trợ.",
            )
            cid = case_row["conversation_id"]
            conv = db.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
            if conv is None:
                self._ensure_customer_in_tx(db, customer_id)
                db.execute(
                    """INSERT INTO conversations(id, customer_id, order_id, product_id, revision, expires_at, provider_id)
                       VALUES (?, ?, ?, ?, 0, ?, 'custom')""",
                    (cid, customer_id, order_id, product_id, now_ts + self.CONVERSATION_TTL),
                )
            elif float(conv["expires_at"]) <= now_ts:
                db.execute(
                    "UPDATE conversations SET expires_at = ? WHERE id = ?",
                    (now_ts + self.CONVERSATION_TTL, cid),
                )
            return cid

        if conversation_id is not None:
            require(
                isinstance(conversation_id, str) and bool(re.fullmatch(r"[a-f0-9-]{36}", conversation_id)),
                400,
                "invalid_conversation",
                "Mã cuộc trò chuyện không hợp lệ.",
            )
            return conversation_id

        existing = db.execute(
            """SELECT id FROM conversations
               WHERE customer_id = ? AND order_id = ? AND expires_at > ?
               ORDER BY expires_at DESC LIMIT 1""",
            (customer_id, order_id, now_ts),
        ).fetchone()
        if existing is not None:
            return existing["id"]

        cid = str(uuid.uuid4())
        self._ensure_customer_in_tx(db, customer_id)
        db.execute(
            """INSERT INTO conversations(id, customer_id, order_id, product_id, revision, expires_at, provider_id)
               VALUES (?, ?, ?, ?, 0, ?, 'custom')""",
            (cid, customer_id, order_id, product_id, now_ts + self.CONVERSATION_TTL),
        )
        self._ensure_active_case_in_tx(db, cid, customer_id, now_ts)
        return cid

    def _create_order_action_request_in_tx(
        self,
        db,
        *,
        customer_id: str,
        order_id: str,
        action_type: str,
        expected_order_version: int,
        reason_code: str,
        reason_text: str | None = None,
        exchange_kind: str | None = None,
        conversation_id: str | None = None,
        case_id: str | None = None,
        actor: dict | None = None,
        raised_by_role: str = "customer",
        delivery_failure_attempts: int | None = None,
        consent_turn_id: int | None = None,
        consent_excerpt: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        proposal_id: str | None = None,
        now: float | None = None,
    ) -> dict:
        require(
            isinstance(action_type, str) and action_type in ("cancel", "return", "exchange"),
            400,
            "invalid_action_type",
            "Loại yêu cầu đơn hàng phải là cancel, return hoặc exchange.",
        )
        require(
            type(expected_order_version) is int and expected_order_version >= 1,
            400,
            "invalid_order_version",
            "Phiên bản đơn hàng dự kiến không hợp lệ.",
        )
        require(
            isinstance(reason_code, str) and bool(re.fullmatch(r"[a-z0-9_-]{2,64}", reason_code.strip())),
            400,
            "invalid_reason_code",
            "Mã lý do bắt buộc và phải đúng định dạng.",
        )
        clean_reason_code = reason_code.strip()
        require(
            raised_by_role in ("customer", "staff", "manager"),
            400,
            "invalid_role",
            "Vai trò tạo yêu cầu không hợp lệ.",
        )
        if raised_by_role == "customer":
            require(
                clean_reason_code != "delivery_failed" and delivery_failure_attempts is None,
                403,
                "permission_denied",
                "Khách hàng không được tạo yêu cầu hủy do giao thất bại.",
            )
        if action_type == "exchange":
            require(
                exchange_kind in ("size", "one_to_one"),
                400,
                "invalid_exchange_kind",
                "Yêu cầu đổi hàng phải chọn kiểu size hoặc one_to_one.",
            )
        else:
            require(
                exchange_kind is None,
                400,
                "invalid_exchange_kind",
                "Chỉ yêu cầu đổi hàng mới có trường exchange_kind.",
            )

        clean_reason_text = self._sanitize_reason_text(reason_text)
        if clean_reason_text is None:
            default_label = ORDER_ACTION_REASONS.get(action_type, {}).get(clean_reason_code)
            if default_label:
                clean_reason_text = default_label

        now_ts = self._now() if now is None else float(now)
        order = self.owned(db, customer_id, order_id)
        require(
            int(order["version"]) == expected_order_version,
            409,
            "stale_order",
            "Đơn đã thay đổi; vui lòng tải lại thông tin trước khi gửi yêu cầu.",
        )
        if action_type == "cancel":
            require(
                order["status"] == "pending",
                409,
                "not_cancellable",
                "Đơn không ở trạng thái pending nên không đủ điều kiện yêu cầu hủy.",
            )
        else:
            require(
                order["status"] == "delivered",
                409,
                "order_not_eligible",
                "Yêu cầu trả hoặc đổi hàng chỉ áp dụng cho đơn đã giao (delivered).",
            )

        existing_open = db.execute(
            "SELECT request_id FROM order_action_requests WHERE order_id = ? AND closed_at IS NULL LIMIT 1",
            (order_id,),
        ).fetchone()
        require(
            existing_open is None,
            409,
            "order_action_conflict",
            "Đơn hàng này đang có một yêu cầu xử lý chưa hoàn tất.",
        )

        resolved_cid = self._resolve_or_open_conversation_for_action_in_tx(
            db,
            customer_id=customer_id,
            order_id=order_id,
            product_id=order.get("product_id"),
            conversation_id=conversation_id,
            case_id=case_id,
            now_ts=now_ts,
        )
        type_vi = {"cancel": "hủy đơn", "return": "trả hàng", "exchange": "đổi hàng"}[action_type]
        handoff_comment = f"Yêu cầu {type_vi} {order_id}: {clean_reason_text or clean_reason_code}"[:300]
        handoff = self._request_human_handoff_in_tx(
            db,
            customer_id,
            resolved_cid,
            reason_code="order_action_review",
            comment=handoff_comment,
            now=now_ts,
        )
        resolved_case_id = handoff["case_id"]
        req_id = f"oar_{uuid.uuid4().hex}"
        norm_actor = self._normalize_actor(actor, customer_id, raised_by_role)

        try:
            db.execute(
                """INSERT INTO order_action_requests(
                       request_id, order_id, customer_id, case_id, conversation_id,
                       type, exchange_kind, status, inspection_outcome,
                       refund_status, refund_decision, reason_code, reason_text,
                       raised_by_role, delivery_failure_attempts, expected_order_version,
                       version, created_at, updated_at, reviewed_at, received_at,
                       inspected_at, completed_at, closed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 'requested', NULL, 'not_applicable', NULL,
                             ?, ?, ?, ?, ?, 1, ?, ?, NULL, NULL, NULL, NULL, NULL)""",
                (
                    req_id,
                    order_id,
                    customer_id,
                    resolved_case_id,
                    resolved_cid,
                    action_type,
                    exchange_kind,
                    clean_reason_code,
                    clean_reason_text,
                    raised_by_role,
                    delivery_failure_attempts,
                    expected_order_version,
                    now_ts,
                    now_ts,
                ),
            )
        except Exception as exc:
            if self._is_db_integrity_error(exc):
                raise ApiError(
                    409,
                    "order_action_conflict",
                    "Đơn hàng này đang có một yêu cầu xử lý chưa hoàn tất.",
                ) from None
            raise

        dec_id = f"oad_{uuid.uuid4().hex}"
        if consent_turn_id is not None:
            consent_tag = f'[consent_turn_id={consent_turn_id}] "{consent_excerpt or ""}"'
            submit_note = (
                f"{consent_tag} · {clean_reason_text}"[:500]
                if clean_reason_text
                else consent_tag[:500]
            )
        else:
            submit_note = clean_reason_text
        db.execute(
            """INSERT INTO order_action_decisions(
                   decision_id, request_id, case_id, order_id, conversation_id,
                   action, from_status, to_status, from_refund_status, to_refund_status,
                   refund_decision, inspection_outcome, actor_principal_id, actor_role,
                   note, created_at
               ) VALUES (?, ?, ?, ?, ?, 'submit', NULL, 'requested', 'not_applicable', 'not_applicable',
                         NULL, NULL, ?, ?, ?, ?)""",
            (
                dec_id,
                req_id,
                resolved_case_id,
                order_id,
                resolved_cid,
                norm_actor["principal_id"],
                norm_actor["role"],
                submit_note,
                now_ts,
            ),
        )

        log_payload = {
            "request_id": req_id,
            "case_id": resolved_case_id,
            "handoff_id": handoff["handoff_id"],
            "conversation_id": resolved_cid,
            "type": action_type,
            "exchange_kind": exchange_kind,
            "status": "requested",
            "reason_code": clean_reason_code,
            "raised_by_role": raised_by_role,
            "expected_order_version": expected_order_version,
        }
        if delivery_failure_attempts is not None:
            log_payload["delivery_failure_attempts"] = delivery_failure_attempts
        if consent_turn_id is not None:
            log_payload["consent_turn_id"] = consent_turn_id
            log_payload["consent_excerpt"] = consent_excerpt
        if proposal_id is not None:
            log_payload["proposal_id"] = proposal_id
        if actor is not None:
            log_payload["actor"] = norm_actor
        self.log(db, customer_id, "order_action_requested", order_id, **log_payload)

        outbox_event_type = {
            "cancel": "cancel_requested",
            "return": "return_requested",
            "exchange": "exchange_requested",
        }[action_type]
        outbox_extra: dict[str, object] = {}
        if exchange_kind:
            outbox_extra["exchange_kind"] = exchange_kind
        if consent_turn_id is not None:
            outbox_extra["consent_turn_id"] = consent_turn_id
        self._enqueue_outbox_in_tx(
            db,
            event_type=outbox_event_type,
            actor={"principal_id": norm_actor["principal_id"], "role": norm_actor["role"], "tenant_id": norm_actor.get("tenant_id")},
            customer_id=customer_id,
            case_id=resolved_case_id,
            order_action_request_id=req_id,
            order_id=order_id,
            before={"status": order["status"], "version": int(order["version"])},
            after={"status": "requested", "version": 1},
            reason_code=clean_reason_code,
            reason_text=clean_reason_text,
            correlation_id=correlation_id or proposal_id or req_id,
            idempotency_key=idempotency_key or proposal_id or req_id,
            source="app",
            now=now_ts,
            extra_fields=outbox_extra or None,
        )

        req_row = db.execute(
            "SELECT * FROM order_action_requests WHERE request_id = ?",
            (req_id,),
        ).fetchone()
        return self._serialize_order_action_in_tx(db, req_row, now=now_ts)

    def create_order_action_request(
        self,
        customer_id: str,
        body: dict,
        *,
        actor: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        require(isinstance(body, dict), 400, "invalid_body", "Yêu cầu phải là đối tượng JSON.")
        allowed = {
            "order_id",
            "type",
            "action_type",
            "exchange_kind",
            "expected_order_version",
            "order_version",
            "reason_code",
            "reason_text",
            "conversation_id",
        }
        require(
            set(body).issubset(allowed),
            400,
            "invalid_fields",
            "Các trường của yêu cầu không hợp lệ.",
        )
        if "type" in body and "action_type" in body:
            require(body["type"] == body["action_type"], 400, "invalid_action_type", "Trường type và action_type xung đột.")
        action_type = body.get("type") if "type" in body else body.get("action_type")
        if "expected_order_version" in body and "order_version" in body:
            require(
                body["expected_order_version"] == body["order_version"],
                400,
                "invalid_order_version",
                "Trường expected_order_version và order_version xung đột.",
            )
        expected_ver = (
            body.get("expected_order_version")
            if "expected_order_version" in body
            else body.get("order_version")
        )
        oid = body.get("order_id")
        require(isinstance(oid, str) and bool(oid.strip()), 400, "invalid_order_id", "Thiếu mã đơn hàng.")
        now_ts = self._now()
        with self.connection(write=True) as db:
            req = self._create_order_action_request_in_tx(
                db,
                customer_id=customer_id,
                order_id=oid.strip(),
                action_type=action_type,
                expected_order_version=expected_ver,
                reason_code=body.get("reason_code"),
                reason_text=body.get("reason_text"),
                exchange_kind=body.get("exchange_kind"),
                conversation_id=body.get("conversation_id"),
                actor=actor,
                raised_by_role="customer",
                correlation_id=idempotency_key,
                idempotency_key=idempotency_key,
                now=now_ts,
            )
        type_msg = {
            "cancel": "Đã gửi yêu cầu hủy, chờ cửa hàng duyệt",
            "return": "Đã gửi yêu cầu trả hàng, chờ cửa hàng duyệt",
            "exchange": "Đã gửi yêu cầu đổi hàng, chờ cửa hàng duyệt",
        }[req["type"]]
        return {
            "status": req["status"],
            "order_action_request_id": req["request_id"],
            "order_action": req,
            "order": req["order"],
            "case_id": req["case_id"],
            "conversation_id": req["conversation_id"],
            "message": type_msg,
        }

    def list_customer_order_actions(self, customer_id: str, *, limit: int = 50) -> list[dict]:
        now_ts = self._now()
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM order_action_requests
                   WHERE customer_id = ?
                   ORDER BY created_at DESC, request_id DESC
                   LIMIT ?""",
                (customer_id, limit),
            ).fetchall()
            return [self._serialize_order_action_in_tx(db, r, now=now_ts) for r in rows]

    STAFF_CONSENT_WINDOW_SECONDS = 30 * 60

    @staticmethod
    def _case_opening_bounds_in_tx(db, case_row) -> tuple[float, int]:
        d = dict(case_row)
        open_since = float(d["resumed_at"] if d.get("resumed_at") is not None else d["created_at"])
        cid = d.get("conversation_id")
        if not cid:
            return open_since, 0
        last_resolve = db.execute(
            "SELECT MAX(id) AS max_id FROM agent_turns WHERE conversation_id = ? AND request_id LIKE ?",
            (cid, "sys-notice-resolve-%"),
        ).fetchone()
        min_turn_id = int(last_resolve["max_id"] or 0) if last_resolve is not None else 0
        return open_since, min_turn_id

    @staticmethod
    def _extract_customer_consent_excerpt(turn_row) -> str | None:
        if turn_row is None:
            return None
        d = dict(turn_row)
        req_id = str(d.get("request_id") or "")
        if req_id.startswith(("sys-notice-", "sys-reminder-", "sys-oar-", "staff-")):
            return None
        inp_hash = str(d.get("input_hash") or "")
        if inp_hash in ("staff-reply", "system-case-notice", "system-reminder", "system-order-action"):
            return None
        res_raw = d.get("result")
        try:
            res_obj = json.loads(res_raw) if isinstance(res_raw, str) else (res_raw or {})
        except Exception:
            return None
        if not isinstance(res_obj, dict):
            return None
        author = res_obj.get("author")
        if author in (
            "staff",
            "bot",
            "assistant",
            "system_case_notice",
            "system_reminder",
            "system_order_action",
        ):
            return None
        if author != "customer" and bool(res_obj.get("message")):
            return None
        msgs_raw = d.get("messages")
        try:
            msgs = json.loads(msgs_raw) if isinstance(msgs_raw, str) else msgs_raw
        except Exception:
            return None
        if not isinstance(msgs, list) or not msgs:
            return None
        if not all(isinstance(m, dict) and m.get("role") == "user" for m in msgs):
            return None
        raw_text = " ".join(
            str(m.get("content") or "").strip()
            for m in msgs
            if str(m.get("content") or "").strip()
        ).strip()
        if not raw_text:
            return None
        excerpt = re.sub(r"\s+", " ", raw_text).strip()[:160]
        if contains_canary_or_secret(excerpt):
            _, cleaned = sanitize_structured_payload(excerpt, preserve_reasoning=False)
            excerpt = str(cleaned)[:160]
        return excerpt

    def list_case_orders(self, case_id: str) -> dict:
        require(
            isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)),
            400,
            "invalid_case_id",
            "Mã ca hỗ trợ không hợp lệ.",
        )
        now_ts = self._now()
        with self.connection() as db:
            case_row = db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            require(case_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
            cust_id = case_row["customer_id"]
            ord_rows = db.execute(
                "SELECT * FROM orders WHERE customer_id = ? ORDER BY id",
                (cust_id,),
            ).fetchall()
            open_req_rows = db.execute(
                """SELECT * FROM order_action_requests
                   WHERE customer_id = ? AND closed_at IS NULL
                   ORDER BY created_at DESC, request_id DESC""",
                (cust_id,),
            ).fetchall()
            open_by_order: dict[str, dict] = {}
            for r in open_req_rows:
                oid = r["order_id"]
                if oid not in open_by_order:
                    open_by_order[oid] = self._serialize_order_action_in_tx(db, r, now=now_ts)

            enriched_orders: list[dict] = []
            for o in ord_rows:
                od = dict(o)
                st = od.get("status")
                if st == "pending":
                    allowed_types = ["cancel"]
                elif st == "delivered":
                    allowed_types = ["return", "exchange"]
                else:
                    allowed_types = []
                delivered_at = od.get("delivered_at")
                if delivered_at is None:
                    days_since_delivery = None
                    delivery_age_label = "chưa có ngày giao"
                else:
                    days_since_delivery = max(0, int((now_ts - float(delivered_at)) // 86400))
                    delivery_age_label = f"{days_since_delivery} ngày kể từ khi giao"
                od["allowed_action_types"] = allowed_types
                od["open_order_action"] = open_by_order.get(od["id"])
                od["days_since_delivery"] = days_since_delivery
                od["delivery_age_label"] = delivery_age_label
                enriched_orders.append(od)

            consent_turns: list[dict] = []
            if case_row["status"] != "resolved" and case_row["conversation_id"]:
                open_since, min_turn_id = self._case_opening_bounds_in_tx(db, case_row)
                earliest_allowed = max(open_since - 1e-6, now_ts - self.STAFF_CONSENT_WINDOW_SECONDS)
                cand_turns = db.execute(
                    """SELECT id, conversation_id, customer_id, request_id, input_hash, messages, result, created_at
                       FROM agent_turns
                       WHERE conversation_id = ?
                         AND customer_id = ?
                         AND id > ?
                         AND created_at >= ?
                         AND created_at <= ?
                       ORDER BY id DESC""",
                    (
                        case_row["conversation_id"],
                        cust_id,
                        min_turn_id,
                        earliest_allowed,
                        now_ts + 5.0,
                    ),
                ).fetchall()
                for trow in cand_turns:
                    excerpt = self._extract_customer_consent_excerpt(trow)
                    if excerpt is not None:
                        consent_turns.append(
                            {
                                "turn_id": int(trow["id"]),
                                "excerpt": excerpt,
                                "created_at": float(trow["created_at"]),
                            }
                        )

        return {
            "case_id": case_id,
            "customer_id": cust_id,
            "orders": enriched_orders,
            "consent_turns": consent_turns,
        }

    def create_staff_consented_order_action_request(
        self,
        case_id: str,
        body: dict | None,
        *,
        actor: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        require(
            isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)),
            400,
            "invalid_case_id",
            "Mã ca hỗ trợ không hợp lệ.",
        )
        require(isinstance(body, dict), 400, "invalid_body", "Yêu cầu phải là đối tượng JSON.")
        allowed = {
            "order_id",
            "expected_order_version",
            "order_version",
            "type",
            "action_type",
            "exchange_kind",
            "reason_code",
            "reason_text",
            "consent_turn_id",
        }
        require(set(body).issubset(allowed), 400, "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
        if "type" in body and "action_type" in body:
            require(
                body["type"] == body["action_type"],
                400,
                "invalid_action_type",
                "Trường type và action_type xung đột.",
            )
        action_type = body.get("type") if "type" in body else body.get("action_type")
        if "expected_order_version" in body and "order_version" in body:
            require(
                body["expected_order_version"] == body["order_version"],
                400,
                "invalid_order_version",
                "Trường expected_order_version và order_version xung đột.",
            )
        expected_ver = (
            body.get("expected_order_version")
            if "expected_order_version" in body
            else body.get("order_version")
        )
        consent_turn_id = body.get("consent_turn_id")
        require(
            type(consent_turn_id) is int and consent_turn_id >= 1,
            400,
            "invalid_consent_turn",
            "Cần chọn tin nhắn đồng ý hợp lệ của khách hàng (consent_turn_id).",
        )
        oid = body.get("order_id")
        require(isinstance(oid, str) and bool(oid.strip()), 400, "invalid_order_id", "Thiếu mã đơn hàng.")

        norm_actor = self._normalize_actor(actor, "", "")
        now_ts = self._now()

        with self.connection(write=True) as db:
            case_row = self._check_case_reviewer_authority_in_tx(
                db, case_id, norm_actor, require_holding=False
            )
            turn_row = db.execute(
                """SELECT id, conversation_id, customer_id, request_id, input_hash, messages, result, created_at
                   FROM agent_turns WHERE id = ?""",
                (consent_turn_id,),
            ).fetchone()
            require(
                turn_row is not None
                and turn_row["conversation_id"] == case_row["conversation_id"]
                and turn_row["customer_id"] == case_row["customer_id"],
                400,
                "invalid_consent_turn",
                "Tin nhắn đồng ý không thuộc hội thoại của ca hỗ trợ này.",
            )
            open_since, min_turn_id = self._case_opening_bounds_in_tx(db, case_row)
            require(
                float(turn_row["created_at"]) >= open_since - 1e-6 and int(turn_row["id"]) > min_turn_id,
                400,
                "invalid_consent_turn",
                "Tin nhắn đồng ý không thuộc lần mở ca hiện tại.",
            )
            turn_age = now_ts - float(turn_row["created_at"])
            require(
                -5.0 <= turn_age <= self.STAFF_CONSENT_WINDOW_SECONDS,
                400,
                "consent_turn_expired",
                "Tin nhắn đồng ý của khách phải nằm trong vòng 30 phút gần nhất.",
            )
            excerpt = self._extract_customer_consent_excerpt(turn_row)
            require(
                excerpt is not None,
                400,
                "consent_turn_not_customer",
                "Chỉ chấp nhận tin nhắn do chính khách hàng gửi làm bằng chứng đồng ý.",
            )

            req = self._create_order_action_request_in_tx(
                db,
                customer_id=case_row["customer_id"],
                order_id=oid.strip(),
                action_type=action_type,
                expected_order_version=expected_ver,
                reason_code=body.get("reason_code"),
                reason_text=body.get("reason_text"),
                exchange_kind=body.get("exchange_kind"),
                case_id=case_id,
                actor=norm_actor,
                raised_by_role="customer",
                consent_turn_id=consent_turn_id,
                consent_excerpt=excerpt,
                correlation_id=idempotency_key,
                idempotency_key=idempotency_key,
                now=now_ts,
            )

        type_msg = {
            "cancel": "Đã tạo yêu cầu hủy theo đồng ý của khách hàng",
            "return": "Đã tạo yêu cầu trả hàng theo đồng ý của khách hàng",
            "exchange": "Đã tạo yêu cầu đổi hàng theo đồng ý của khách hàng",
        }[req["type"]]
        return {
            "status": req["status"],
            "order_action_request_id": req["request_id"],
            "order_action": req,
            "order": req["order"],
            "case_id": req["case_id"],
            "conversation_id": req["conversation_id"],
            "consent_turn_id": consent_turn_id,
            "consent_excerpt": excerpt,
            "message": type_msg,
        }

    def list_case_order_actions(self, case_id: str) -> list[dict]:
        require(
            isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)),
            400,
            "invalid_case_id",
            "Mã ca hỗ trợ không hợp lệ.",
        )
        now_ts = self._now()
        with self.connection() as db:
            case_row = db.execute("SELECT case_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            require(case_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
            rows = db.execute(
                """SELECT * FROM order_action_requests
                   WHERE case_id = ?
                   ORDER BY created_at DESC, request_id DESC""",
                (case_id,),
            ).fetchall()
            return [self._serialize_order_action_in_tx(db, r, now=now_ts) for r in rows]

    def propose(self, customer, body):
        fields(body, {"order_id", "order_version", "cancel_reason"})
        oid, version, reason = body["order_id"], body["order_version"], body["cancel_reason"]
        require(isinstance(oid, str) and type(version) is int and isinstance(reason, str) and reason in REASONS,
                400, "invalid_proposal", "Chọn mã đơn và một lý do được hỗ trợ.")
        now_ts = self._now()
        with self.connection(write=True) as db:
            order = self.owned(db, customer, oid)
            require(order["status"] == "pending", 409, "not_cancellable", "Đơn không còn ở trạng thái cho phép hủy.")
            require(order["version"] == version, 409, "stale_order", "Đơn đã thay đổi. Vui lòng tải lại thông tin.")
            pid, expires = str(uuid.uuid4()), now_ts + 600
            db.execute("INSERT INTO proposals(id,customer_id,order_id,order_version,reason,expires_at) VALUES (?,?,?,?,?,?)",
                       (pid, customer, oid, version, reason, expires))
            self.log(db, customer, "cancellation_proposed", oid, proposal_id=pid, reason=reason)
        return {"proposal_id": pid, "order": order, "reason": reason, "expires_at": expires,
                "message": "Đơn chưa bị hủy. Vui lòng xem lại và xác nhận."}

    def confirm(self, customer, pid, body, key, actor=None):
        fields(body, {"confirmed"})
        require(body["confirmed"] is True, 400, "confirmation_required", "Cần xác nhận rõ ràng trước khi hủy.")
        require(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key),
                400, "idempotency_required", "Thiếu mã chống thực hiện lặp.")
        now_ts = self._now()
        with self.connection(write=True) as db:
            p = db.execute("SELECT * FROM proposals WHERE id=? AND customer_id=?", (pid, customer)).fetchone()
            require(p is not None, 404, "proposal_not_found", "Không tìm thấy đề xuất của bạn.")
            if p["state"] == "confirmed":
                require(hmac.compare_digest(p["confirm_key"], key), 409, "already_confirmed", "Đề xuất đã được thực hiện.")
                return {**json.loads(p["result"]), "replayed": True}
            require(p["state"] == "pending" and float(p["expires_at"]) > now_ts,
                    409, "inactive_proposal", "Đề xuất đã hết hạn hoặc bị bỏ. Hãy tạo yêu cầu mới.")
            used = db.execute("SELECT id FROM proposals WHERE customer_id=? AND confirm_key=?", (customer, key)).fetchone()
            require(used is None, 409, "idempotency_conflict", "Mã xác nhận đã dùng cho đề xuất khác.")
            req = self._create_order_action_request_in_tx(
                db,
                customer_id=customer,
                order_id=p["order_id"],
                action_type="cancel",
                expected_order_version=int(p["order_version"]),
                reason_code=p["reason"],
                reason_text=ORDER_ACTION_REASONS["cancel"].get(p["reason"], p["reason"]),
                actor=actor,
                raised_by_role="customer",
                correlation_id=key,
                idempotency_key=key,
                proposal_id=pid,
                now=now_ts,
            )
            order = self.owned(db, customer, p["order_id"])
            result = {
                "order": order,
                "proposal_id": pid,
                "order_action_request_id": req["request_id"],
                "status": req["status"],
                "order_action": req,
                "case_id": req["case_id"],
                "conversation_id": req["conversation_id"],
                "replayed": False,
                "message": "Đã gửi yêu cầu hủy, chờ cửa hàng duyệt",
            }
            db.execute("UPDATE proposals SET state='confirmed', confirm_key=?, result=? WHERE id=?",
                       (key, json.dumps(result, ensure_ascii=False), pid))
            return result

    def dismiss(self, customer, pid):
        with self.connection(write=True) as db:
            p = db.execute("SELECT * FROM proposals WHERE id=? AND customer_id=?", (pid, customer)).fetchone()
            require(p is not None, 404, "proposal_not_found", "Không tìm thấy đề xuất của bạn.")
            require(p["state"] != "confirmed", 409, "already_confirmed", "Yêu cầu hủy đã được gửi; không thể bỏ đề xuất bằng thao tác này.")
            if p["state"] == "pending":
                db.execute("UPDATE proposals SET state='dismissed' WHERE id=?", (pid,))
                self.log(db, customer, "proposal_dismissed", p["order_id"], proposal_id=pid)
        return {"message": "Đã bỏ đề xuất. Trạng thái đơn được giữ nguyên."}

    @staticmethod
    def _order_action_notice_text(
        action_type: str,
        exchange_kind: str | None,
        order_id: str,
        new_status: str,
        inspection_outcome: str | None = None,
    ) -> str:
        if action_type == "cancel":
            type_label = "hủy đơn"
        elif action_type == "return":
            type_label = "trả hàng"
        elif exchange_kind == "size":
            type_label = "đổi size"
        elif exchange_kind == "one_to_one":
            type_label = "đổi 1-1"
        else:
            type_label = "đổi hàng"

        if new_status == "under_review":
            return f"Cập nhật yêu cầu {type_label} đơn {order_id}: Nhân viên đã tiếp nhận ca và đang xem xét yêu cầu của bạn."
        if new_status == "approved":
            if action_type == "cancel":
                return f"Cập nhật yêu cầu hủy đơn {order_id}: Cửa hàng đã duyệt yêu cầu và đơn hàng {order_id} đã chuyển sang trạng thái Đã hủy."
            return f"Cập nhật yêu cầu {type_label} đơn {order_id}: Cửa hàng đã duyệt bước đầu. Vui lòng gửi lại sản phẩm để cửa hàng tiếp nhận và kiểm tra."
        if new_status == "rejected":
            return f"Cập nhật yêu cầu {type_label} đơn {order_id}: Cửa hàng từ chối yêu cầu sau khi kiểm tra điều kiện xử lý."
        if new_status == "received":
            return f"Cập nhật yêu cầu {type_label} đơn {order_id}: Cửa hàng đã nhận được hàng gửi về và đang tiến hành kiểm tra."
        if new_status == "inspected":
            outcome_vi = {
                "refund": "đủ điều kiện hoàn tiền",
                "exchange": "đủ điều kiện đổi sản phẩm",
                "no_action": "không phát sinh đổi/hoàn",
            }.get(str(inspection_outcome or ""), str(inspection_outcome or ""))
            return f"Cập nhật yêu cầu {type_label} đơn {order_id}: Đã hoàn tất kiểm tra sản phẩm ({outcome_vi})."
        if new_status == "completed":
            return f"Cập nhật yêu cầu {type_label} đơn {order_id}: Quy trình {type_label} đã hoàn tất."
        return f"Cập nhật yêu cầu {type_label} đơn {order_id}: Trạng thái chuyển sang {new_status}."

    def _append_order_action_notice_in_tx(
        self,
        db,
        *,
        req_row,
        new_status: str,
        new_version: int,
        inspection_outcome: str | None = None,
        now: float | None = None,
    ) -> str:
        now_ts = self._now() if now is None else float(now)
        notice_text = self._order_action_notice_text(
            req_row["type"],
            req_row["exchange_kind"],
            req_row["order_id"],
            new_status,
            inspection_outcome=inspection_outcome,
        )
        cid = req_row["conversation_id"]
        if not cid:
            return notice_text
        conv = db.execute(
            "SELECT id, order_id, product_id, expires_at FROM conversations WHERE id = ?",
            (cid,),
        ).fetchone()
        if conv is None:
            return notice_text
        turn_messages = [{"role": "assistant", "content": notice_text}]
        turn_result = {
            "message": notice_text,
            "author": "system_order_action",
            "source": "store_data",
            "case_id": req_row["case_id"],
            "order_action_request_id": req_row["request_id"],
            "order_id": req_row["order_id"],
            "order_action_status": new_status,
            "context": {
                "order_id": conv["order_id"] or req_row["order_id"],
                "product_id": conv["product_id"],
            },
            "trace": {
                "order_action_notice": new_status,
                "request_id": req_row["request_id"],
                "request_version": int(new_version),
            },
        }
        db.execute(
            """INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
               VALUES (?, ?, ?, 'system-order-action', ?, ?, ?)
               ON CONFLICT(conversation_id, request_id) DO NOTHING""",
            (
                cid,
                req_row["customer_id"],
                f"sys-oar-{req_row['request_id']}-v{int(new_version)}",
                json.dumps(turn_messages, ensure_ascii=False),
                json.dumps(turn_result, ensure_ascii=False),
                now_ts,
            ),
        )
        new_exp = max(float(conv["expires_at"]), now_ts + self.CONVERSATION_TTL)
        db.execute("UPDATE conversations SET expires_at = ? WHERE id = ?", (new_exp, cid))
        return notice_text

    def _check_case_reviewer_authority_in_tx(
        self,
        db,
        case_id: str,
        norm_actor: dict,
        *,
        require_holding: bool = False,
    ) -> dict:
        case_row = db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        require(case_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ của yêu cầu.")
        require(
            case_row["status"] != "resolved",
            409,
            "case_already_resolved",
            "Ca hỗ trợ đã đóng, không thể thao tác trên yêu cầu đơn hàng.",
        )
        caller_role = norm_actor.get("role")
        caller_id = norm_actor.get("principal_id")
        require(
            caller_role in ("staff", "manager") and bool(caller_id),
            403,
            "permission_denied",
            "Chỉ nhân viên hoặc quản lý mới được xử lý yêu cầu đơn hàng.",
        )
        holder = case_row["holder"]
        if require_holding:
            require(
                case_row["status"] == "in_progress" and holder is not None,
                409,
                "case_not_claimed",
                "Cần nhận ca trước khi thực hiện thao tác này.",
            )
            require(
                holder == caller_id,
                409,
                "case_held_by_other",
                "Chỉ người đang trực tiếp giữ ca mới được tạo yêu cầu này.",
            )
        elif caller_role != "manager":
            require(
                case_row["status"] == "in_progress" and holder is not None,
                409,
                "case_not_claimed",
                "Nhân viên cần nhận ca trước khi duyệt hoặc cập nhật yêu cầu đơn hàng.",
            )
            require(
                holder == caller_id,
                409,
                "case_held_by_other",
                "Ca hỗ trợ đang do nhân viên khác phụ trách.",
            )
        return dict(case_row)

    def transition_order_action_request(
        self,
        request_id: str,
        action: str,
        body: dict | None,
        *,
        actor: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        require(
            isinstance(request_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id)),
            400,
            "invalid_request_id",
            "Mã yêu cầu đơn hàng không hợp lệ.",
        )
        require(
            action in ("approve", "reject", "mark_received", "mark_inspected", "complete"),
            400,
            "invalid_action",
            "Hành động duyệt yêu cầu không hợp lệ.",
        )
        require(isinstance(body, dict), 400, "invalid_body", "Yêu cầu phải là đối tượng JSON.")
        allowed = {"version", "note"}
        if action == "mark_inspected":
            allowed.add("inspection_outcome")
        require(set(body).issubset(allowed), 400, "invalid_fields", "Các trường của yêu cầu không hợp lệ.")

        expected_ver = body.get("version")
        require(
            type(expected_ver) is int and expected_ver >= 1,
            400,
            "invalid_version",
            "Thiếu hoặc sai trường version của yêu cầu đơn hàng.",
        )
        clean_note = self._sanitize_reason_text(body.get("note"))
        outcome = None
        if action == "mark_inspected":
            outcome = body.get("inspection_outcome")
            require(
                outcome in ("refund", "exchange", "no_action"),
                400,
                "invalid_inspection_outcome",
                "Kết quả kiểm tra phải là refund, exchange hoặc no_action.",
            )

        norm_actor = self._normalize_actor(actor, "", "")
        now_ts = self._now()
        order_mutated = False
        with self.connection(write=True) as db:
            req_row = db.execute(
                "SELECT * FROM order_action_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            require(req_row is not None, 404, "order_action_not_found", "Không tìm thấy yêu cầu đơn hàng.")

            is_delivery_failure = (
                req_row["delivery_failure_attempts"] is not None
                or req_row["reason_code"] == "delivery_failed"
                or req_row["raised_by_role"] in ("staff", "manager")
            )
            if action in ("approve", "reject") and is_delivery_failure:
                require(
                    norm_actor["role"] == "manager",
                    403,
                    "permission_denied",
                    "Chỉ Quản lý mới được duyệt hoặc từ chối yêu cầu hủy do giao thất bại.",
                )

            self._check_case_reviewer_authority_in_tx(db, req_row["case_id"], norm_actor)

            cur_ver = int(req_row["version"])
            require(
                cur_ver == expected_ver,
                409,
                "order_action_version_conflict",
                "Phiên bản yêu cầu đơn hàng đã thay đổi; vui lòng tải lại trước khi thao tác.",
            )

            req_type = req_row["type"]
            cur_status = req_row["status"]
            if action == "approve" and cur_status in ("requested", "under_review"):
                new_status = "approved"
            elif action == "reject" and cur_status in ("requested", "under_review"):
                new_status = "rejected"
            elif action == "mark_received" and req_type in ("return", "exchange") and cur_status == "approved":
                new_status = "received"
            elif action == "mark_inspected" and req_type in ("return", "exchange") and cur_status == "received":
                new_status = "inspected"
            elif action == "complete" and req_type in ("return", "exchange") and cur_status == "inspected":
                new_status = "completed"
            else:
                raise ApiError(
                    409,
                    "invalid_order_action_transition",
                    f"Không thể chuyển yêu cầu ({req_type}) từ '{cur_status}' bằng thao tác '{action}'.",
                )

            new_ver = cur_ver + 1
            reviewed_at = req_row["reviewed_at"]
            received_at = req_row["received_at"]
            inspected_at = req_row["inspected_at"]
            completed_at = req_row["completed_at"]
            closed_at = req_row["closed_at"]
            next_outcome = req_row["inspection_outcome"]

            if action in ("approve", "reject"):
                reviewed_at = reviewed_at if reviewed_at is not None else now_ts
            if action == "reject":
                closed_at = now_ts
            elif action == "approve" and req_type == "cancel":
                closed_at = now_ts
            elif action == "mark_received":
                received_at = now_ts
            elif action == "mark_inspected":
                inspected_at = now_ts
                next_outcome = outcome
            elif action == "complete":
                completed_at = now_ts
                closed_at = now_ts

            order_before_ver = None
            if action == "approve" and req_type == "cancel":
                ord_row = db.execute("SELECT * FROM orders WHERE id = ?", (req_row["order_id"],)).fetchone()
                require(ord_row is not None, 404, "order_not_found", "Không tìm thấy đơn hàng của yêu cầu.")
                require(
                    ord_row["status"] == "pending",
                    409,
                    "not_cancellable",
                    "Đơn hàng không còn ở trạng thái pending nên không thể duyệt hủy.",
                )
                expected_ord_ver = int(req_row["expected_order_version"])
                require(
                    int(ord_row["version"]) == expected_ord_ver,
                    409,
                    "stale_order",
                    "Đơn hàng đã thay đổi sau khi tạo yêu cầu hủy; không thể duyệt tự động.",
                )
                order_before_ver = expected_ord_ver
                ord_won = db.execute(
                    """UPDATE orders
                       SET status = 'cancelled', cancel_reason = ?, version = version + 1
                       WHERE id = ? AND status = 'pending' AND version = ?""",
                    (req_row["reason_code"], req_row["order_id"], expected_ord_ver),
                ).rowcount
                require(ord_won == 1, 409, "stale_order", "Đơn hàng vừa thay đổi đồng thời.")
                order_mutated = True

            won = db.execute(
                """UPDATE order_action_requests
                   SET status = ?,
                       inspection_outcome = ?,
                       version = ?,
                       updated_at = ?,
                       reviewed_at = ?,
                       received_at = ?,
                       inspected_at = ?,
                       completed_at = ?,
                       closed_at = ?
                   WHERE request_id = ? AND version = ? AND status = ?""",
                (
                    new_status,
                    next_outcome,
                    new_ver,
                    now_ts,
                    reviewed_at,
                    received_at,
                    inspected_at,
                    completed_at,
                    closed_at,
                    request_id,
                    cur_ver,
                    cur_status,
                ),
            ).rowcount
            require(
                won == 1,
                409,
                "order_action_version_conflict",
                "Yêu cầu đơn hàng vừa được người khác cập nhật đồng thời.",
            )

            db.execute(
                """INSERT INTO order_action_decisions(
                       decision_id, request_id, case_id, order_id, conversation_id,
                       action, from_status, to_status, from_refund_status, to_refund_status,
                       refund_decision, inspection_outcome, actor_principal_id, actor_role,
                       note, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"oad_{uuid.uuid4().hex}",
                    request_id,
                    req_row["case_id"],
                    req_row["order_id"],
                    req_row["conversation_id"],
                    action,
                    cur_status,
                    new_status,
                    req_row["refund_status"],
                    req_row["refund_status"],
                    req_row["refund_decision"],
                    next_outcome,
                    norm_actor["principal_id"],
                    norm_actor["role"],
                    clean_note,
                    now_ts,
                ),
            )

            self.log(
                db,
                req_row["customer_id"],
                "order_action_status_changed",
                req_row["order_id"],
                request_id=request_id,
                case_id=req_row["case_id"],
                action=action,
                from_status=cur_status,
                to_status=new_status,
                inspection_outcome=next_outcome,
                version=new_ver,
                note=clean_note,
                actor=norm_actor,
            )
            if order_mutated:
                self.log(
                    db,
                    req_row["customer_id"],
                    "order_cancelled",
                    req_row["order_id"],
                    request_id=request_id,
                    case_id=req_row["case_id"],
                    reason=req_row["reason_code"],
                    actor=norm_actor,
                )

            outbox_type = (
                "request_approved"
                if action == "approve"
                else ("request_rejected" if action == "reject" else "request_status_changed")
            )
            after_state = {"status": new_status, "version": new_ver}
            if next_outcome is not None:
                after_state["inspection_outcome"] = next_outcome
            self._enqueue_outbox_in_tx(
                db,
                event_type=outbox_type,
                actor=norm_actor,
                customer_id=req_row["customer_id"],
                case_id=req_row["case_id"],
                order_action_request_id=request_id,
                order_id=req_row["order_id"],
                before={"status": cur_status, "version": cur_ver},
                after=after_state,
                reason_code=req_row["reason_code"],
                reason_text=clean_note,
                correlation_id=idempotency_key or f"{request_id}:v{new_ver}",
                idempotency_key=idempotency_key or f"{request_id}:{action}:v{new_ver}",
                source="app",
                now=now_ts,
            )
            if order_mutated and order_before_ver is not None:
                self._enqueue_outbox_in_tx(
                    db,
                    event_type="order_status_changed",
                    actor=norm_actor,
                    customer_id=req_row["customer_id"],
                    case_id=req_row["case_id"],
                    order_action_request_id=request_id,
                    order_id=req_row["order_id"],
                    before={"status": "pending", "version": order_before_ver},
                    after={"status": "cancelled", "version": order_before_ver + 1},
                    reason_code=req_row["reason_code"],
                    reason_text=clean_note,
                    correlation_id=idempotency_key or f"{request_id}:v{new_ver}",
                    idempotency_key=f"{request_id}:order_cancelled:v{order_before_ver + 1}",
                    source="app",
                    now=now_ts,
                )

            notice = self._append_order_action_notice_in_tx(
                db,
                req_row=req_row,
                new_status=new_status,
                new_version=new_ver,
                inspection_outcome=next_outcome,
                now=now_ts,
            )
            updated_row = db.execute(
                "SELECT * FROM order_action_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            serialized = self._serialize_order_action_in_tx(db, updated_row, now=now_ts)

        return {
            "status": serialized["status"],
            "order_action_request_id": serialized["request_id"],
            "order_action": serialized,
            "order": serialized["order"],
            "order_mutated": order_mutated,
            "customer_notice": notice,
        }

    def create_delivery_failure_cancel_request(
        self,
        case_id: str,
        body: dict | None,
        *,
        actor: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        require(
            isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)),
            400,
            "invalid_case_id",
            "Mã ca hỗ trợ không hợp lệ.",
        )
        require(isinstance(body, dict), 400, "invalid_body", "Yêu cầu phải là đối tượng JSON.")
        allowed = {
            "order_id",
            "type",
            "action_type",
            "expected_order_version",
            "order_version",
            "delivery_failure_attempts",
            "note",
            "reason_text",
        }
        require(set(body).issubset(allowed), 400, "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
        for tkey in ("type", "action_type"):
            if tkey in body and body[tkey] is not None:
                require(body[tkey] == "cancel", 400, "invalid_action_type", "Hủy do giao thất bại chỉ hỗ trợ loại cancel.")

        attempts = body.get("delivery_failure_attempts")
        require(
            type(attempts) is int and attempts >= 1,
            400,
            "invalid_delivery_failure_attempts",
            "Số lần giao thất bại bắt buộc là số nguyên từ 1 trở lên.",
        )
        raw_note = body.get("note") if "note" in body else body.get("reason_text")
        clean_note = self._sanitize_reason_text(raw_note)
        require(clean_note is not None, 400, "invalid_reason_text", "Ghi chú hủy do giao thất bại là bắt buộc.")

        oid = body.get("order_id")
        require(isinstance(oid, str) and bool(oid.strip()), 400, "invalid_order_id", "Thiếu mã đơn hàng.")
        norm_actor = self._normalize_actor(actor, "", "")
        now_ts = self._now()

        with self.connection(write=True) as db:
            case_row = self._check_case_reviewer_authority_in_tx(
                db, case_id, norm_actor, require_holding=True
            )
            order = self.owned(db, case_row["customer_id"], oid.strip())
            if "expected_order_version" in body and body["expected_order_version"] is not None:
                expected_ver = body["expected_order_version"]
            elif "order_version" in body and body["order_version"] is not None:
                expected_ver = body["order_version"]
            else:
                expected_ver = int(order["version"])
            req = self._create_order_action_request_in_tx(
                db,
                customer_id=case_row["customer_id"],
                order_id=oid.strip(),
                action_type="cancel",
                expected_order_version=expected_ver,
                reason_code="delivery_failed",
                reason_text=clean_note,
                case_id=case_id,
                actor=norm_actor,
                raised_by_role=norm_actor["role"],
                delivery_failure_attempts=attempts,
                correlation_id=idempotency_key,
                idempotency_key=idempotency_key,
                now=now_ts,
            )
        return {
            "status": req["status"],
            "order_action_request_id": req["request_id"],
            "order_action": req,
            "order": req["order"],
            "case_id": req["case_id"],
            "conversation_id": req["conversation_id"],
            "message": "Đã tạo yêu cầu hủy do giao thất bại, chờ Quản lý duyệt",
        }

    def request_order_action_refund(
        self,
        request_id: str,
        body: dict | None,
        *,
        actor: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        require(
            isinstance(request_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id)),
            400,
            "invalid_request_id",
            "Mã yêu cầu đơn hàng không hợp lệ.",
        )
        require(isinstance(body, dict), 400, "invalid_body", "Yêu cầu phải là đối tượng JSON.")
        require(set(body).issubset({"version", "note"}), 400, "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
        expected_ver = body.get("version")
        require(type(expected_ver) is int and expected_ver >= 1, 400, "invalid_version", "Thiếu hoặc sai version.")
        clean_note = self._sanitize_reason_text(body.get("note"))
        norm_actor = self._normalize_actor(actor, "", "")
        now_ts = self._now()

        with self.connection(write=True) as db:
            req_row = db.execute("SELECT * FROM order_action_requests WHERE request_id = ?", (request_id,)).fetchone()
            require(req_row is not None, 404, "order_action_not_found", "Không tìm thấy yêu cầu đơn hàng.")
            self._check_case_reviewer_authority_in_tx(db, req_row["case_id"], norm_actor)
            cur_ver = int(req_row["version"])
            require(cur_ver == expected_ver, 409, "order_action_version_conflict", "Phiên bản yêu cầu đã thay đổi.")
            require(
                req_row["status"] in ("approved", "received", "inspected", "completed"),
                409,
                "invalid_refund_state",
                "Chỉ được gửi yêu cầu hoàn tiền trên yêu cầu đơn hàng đã được duyệt.",
            )
            require(
                req_row["refund_status"] == "not_applicable",
                409,
                "invalid_refund_state",
                "Yêu cầu hoàn tiền đã được gửi hoặc đã có kết quả.",
            )
            new_ver = cur_ver + 1
            won = db.execute(
                """UPDATE order_action_requests
                   SET refund_status = 'pending',
                       refund_decision = NULL,
                       version = ?,
                       updated_at = ?
                   WHERE request_id = ? AND version = ? AND refund_status = 'not_applicable'""",
                (new_ver, now_ts, request_id, cur_ver),
            ).rowcount
            require(won == 1, 409, "order_action_version_conflict", "Yêu cầu vừa được cập nhật đồng thời.")
            db.execute(
                """INSERT INTO order_action_decisions(
                       decision_id, request_id, case_id, order_id, conversation_id,
                       action, from_status, to_status, from_refund_status, to_refund_status,
                       refund_decision, inspection_outcome, actor_principal_id, actor_role,
                       note, created_at
                   ) VALUES (?, ?, ?, ?, ?, 'refund_request', ?, ?, ?, 'pending', NULL, ?, ?, ?, ?, ?)""",
                (
                    f"oad_{uuid.uuid4().hex}",
                    request_id,
                    req_row["case_id"],
                    req_row["order_id"],
                    req_row["conversation_id"],
                    req_row["status"],
                    req_row["status"],
                    req_row["refund_status"],
                    req_row["inspection_outcome"],
                    norm_actor["principal_id"],
                    norm_actor["role"],
                    clean_note,
                    now_ts,
                ),
            )
            self.log(
                db,
                req_row["customer_id"],
                "order_action_refund_updated",
                req_row["order_id"],
                request_id=request_id,
                case_id=req_row["case_id"],
                action="refund_request",
                from_refund_status=req_row["refund_status"],
                to_refund_status="pending",
                version=new_ver,
                note=clean_note,
                actor=norm_actor,
            )
            self._enqueue_outbox_in_tx(
                db,
                event_type="refund_requested",
                actor=norm_actor,
                customer_id=req_row["customer_id"],
                case_id=req_row["case_id"],
                order_action_request_id=request_id,
                order_id=req_row["order_id"],
                before={"status": req_row["status"], "version": cur_ver, "refund_status": req_row["refund_status"]},
                after={"status": req_row["status"], "version": new_ver, "refund_status": "pending"},
                reason_code=req_row["reason_code"],
                reason_text=clean_note,
                correlation_id=idempotency_key or f"{request_id}:v{new_ver}",
                idempotency_key=idempotency_key or f"{request_id}:refund_request:v{new_ver}",
                source="app",
                now=now_ts,
            )
            updated_row = db.execute("SELECT * FROM order_action_requests WHERE request_id = ?", (request_id,)).fetchone()
            serialized = self._serialize_order_action_in_tx(db, updated_row, now=now_ts)
        return {
            "status": serialized["status"],
            "refund_status": serialized["refund_status"],
            "refund_decision": serialized["refund_decision"],
            "order_action_request_id": serialized["request_id"],
            "order_action": serialized,
            "order": serialized["order"],
        }

    def decide_order_action_refund(
        self,
        request_id: str,
        body: dict | None,
        *,
        actor: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        norm_actor = self._normalize_actor(actor, "", "")
        require(
            norm_actor["role"] == "manager",
            403,
            "permission_denied",
            "Chỉ Quản lý mới được duyệt hoặc từ chối yêu cầu hoàn tiền.",
        )
        require(
            isinstance(request_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id)),
            400,
            "invalid_request_id",
            "Mã yêu cầu đơn hàng không hợp lệ.",
        )
        require(isinstance(body, dict), 400, "invalid_body", "Yêu cầu phải là đối tượng JSON.")
        require(
            set(body).issubset({"version", "decision", "note"}),
            400,
            "invalid_fields",
            "Các trường của yêu cầu không hợp lệ.",
        )
        expected_ver = body.get("version")
        require(type(expected_ver) is int and expected_ver >= 1, 400, "invalid_version", "Thiếu hoặc sai version.")
        decision = body.get("decision")
        require(
            decision in ("approved", "rejected"),
            400,
            "invalid_refund_decision",
            "Quyết định hoàn tiền phải là approved hoặc rejected.",
        )
        clean_note = self._sanitize_reason_text(body.get("note"))
        now_ts = self._now()

        with self.connection(write=True) as db:
            req_row = db.execute("SELECT * FROM order_action_requests WHERE request_id = ?", (request_id,)).fetchone()
            require(req_row is not None, 404, "order_action_not_found", "Không tìm thấy yêu cầu đơn hàng.")
            cur_ver = int(req_row["version"])
            require(cur_ver == expected_ver, 409, "order_action_version_conflict", "Phiên bản yêu cầu đã thay đổi.")
            require(
                req_row["refund_status"] == "pending" and req_row["refund_decision"] is None,
                409,
                "invalid_refund_state",
                "Yêu cầu hoàn tiền hiện không ở trạng thái chờ duyệt.",
            )
            next_refund_status = "pending" if decision == "approved" else "not_applicable"
            new_ver = cur_ver + 1
            won = db.execute(
                """UPDATE order_action_requests
                   SET refund_status = ?,
                       refund_decision = ?,
                       version = ?,
                       updated_at = ?
                   WHERE request_id = ? AND version = ? AND refund_status = 'pending' AND refund_decision IS NULL""",
                (next_refund_status, decision, new_ver, now_ts, request_id, cur_ver),
            ).rowcount
            require(won == 1, 409, "order_action_version_conflict", "Yêu cầu hoàn tiền vừa được cập nhật đồng thời.")
            action_name = "refund_approve" if decision == "approved" else "refund_reject"
            db.execute(
                """INSERT INTO order_action_decisions(
                       decision_id, request_id, case_id, order_id, conversation_id,
                       action, from_status, to_status, from_refund_status, to_refund_status,
                       refund_decision, inspection_outcome, actor_principal_id, actor_role,
                       note, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"oad_{uuid.uuid4().hex}",
                    request_id,
                    req_row["case_id"],
                    req_row["order_id"],
                    req_row["conversation_id"],
                    action_name,
                    req_row["status"],
                    req_row["status"],
                    next_refund_status,
                    decision,
                    req_row["inspection_outcome"],
                    norm_actor["principal_id"],
                    norm_actor["role"],
                    clean_note,
                    now_ts,
                ),
            )
            self.log(
                db,
                req_row["customer_id"],
                "order_action_refund_updated",
                req_row["order_id"],
                request_id=request_id,
                case_id=req_row["case_id"],
                action=action_name,
                refund_decision=decision,
                from_refund_status="pending",
                to_refund_status=next_refund_status,
                version=new_ver,
                note=clean_note,
                actor=norm_actor,
            )
            self._enqueue_outbox_in_tx(
                db,
                event_type="refund_decided",
                actor=norm_actor,
                customer_id=req_row["customer_id"],
                case_id=req_row["case_id"],
                order_action_request_id=request_id,
                order_id=req_row["order_id"],
                before={"status": req_row["status"], "version": cur_ver, "refund_status": "pending", "refund_decision": None},
                after={
                    "status": req_row["status"],
                    "version": new_ver,
                    "refund_status": next_refund_status,
                    "refund_decision": decision,
                },
                reason_code=req_row["reason_code"],
                reason_text=clean_note,
                correlation_id=idempotency_key or f"{request_id}:v{new_ver}",
                idempotency_key=idempotency_key or f"{request_id}:{action_name}:v{new_ver}",
                source="app",
                now=now_ts,
            )
            updated_row = db.execute("SELECT * FROM order_action_requests WHERE request_id = ?", (request_id,)).fetchone()
            serialized = self._serialize_order_action_in_tx(db, updated_row, now=now_ts)
        return {
            "status": serialized["status"],
            "refund_status": serialized["refund_status"],
            "refund_decision": serialized["refund_decision"],
            "order_action_request_id": serialized["request_id"],
            "order_action": serialized,
            "order": serialized["order"],
        }

    def record_order_action_refund_outcome(
        self,
        request_id: str,
        body: dict | None,
        *,
        actor: dict,
        idempotency_key: str | None = None,
    ) -> dict:
        norm_actor = self._normalize_actor(actor, "", "")
        require(
            norm_actor["role"] == "manager",
            403,
            "permission_denied",
            "Chỉ Quản lý mới được ghi nhận kết quả hoàn tiền.",
        )
        require(
            isinstance(request_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id)),
            400,
            "invalid_request_id",
            "Mã yêu cầu đơn hàng không hợp lệ.",
        )
        require(isinstance(body, dict), 400, "invalid_body", "Yêu cầu phải là đối tượng JSON.")
        require(
            set(body).issubset({"version", "outcome", "refund_status", "note"}),
            400,
            "invalid_fields",
            "Các trường của yêu cầu không hợp lệ.",
        )
        expected_ver = body.get("version")
        require(type(expected_ver) is int and expected_ver >= 1, 400, "invalid_version", "Thiếu hoặc sai version.")
        outcome = body.get("outcome") if "outcome" in body else body.get("refund_status")
        require(
            outcome in ("refunded", "failed"),
            400,
            "invalid_refund_outcome",
            "Kết quả hoàn tiền phải là refunded hoặc failed.",
        )
        clean_note = self._sanitize_reason_text(body.get("note"))
        now_ts = self._now()

        with self.connection(write=True) as db:
            req_row = db.execute("SELECT * FROM order_action_requests WHERE request_id = ?", (request_id,)).fetchone()
            require(req_row is not None, 404, "order_action_not_found", "Không tìm thấy yêu cầu đơn hàng.")
            cur_ver = int(req_row["version"])
            require(cur_ver == expected_ver, 409, "order_action_version_conflict", "Phiên bản yêu cầu đã thay đổi.")
            require(
                req_row["refund_status"] == "pending" and req_row["refund_decision"] == "approved",
                409,
                "refund_not_approved",
                "Chưa thể ghi kết quả hoàn tiền khi Quản lý chưa duyệt yêu cầu hoàn tiền.",
            )
            new_ver = cur_ver + 1
            won = db.execute(
                """UPDATE order_action_requests
                   SET refund_status = ?,
                       version = ?,
                       updated_at = ?
                   WHERE request_id = ? AND version = ? AND refund_status = 'pending' AND refund_decision = 'approved'""",
                (outcome, new_ver, now_ts, request_id, cur_ver),
            ).rowcount
            require(won == 1, 409, "order_action_version_conflict", "Yêu cầu hoàn tiền vừa được cập nhật đồng thời.")
            db.execute(
                """INSERT INTO order_action_decisions(
                       decision_id, request_id, case_id, order_id, conversation_id,
                       action, from_status, to_status, from_refund_status, to_refund_status,
                       refund_decision, inspection_outcome, actor_principal_id, actor_role,
                       note, created_at
                   ) VALUES (?, ?, ?, ?, ?, 'refund_outcome', ?, ?, 'pending', ?, 'approved', ?, ?, ?, ?, ?)""",
                (
                    f"oad_{uuid.uuid4().hex}",
                    request_id,
                    req_row["case_id"],
                    req_row["order_id"],
                    req_row["conversation_id"],
                    req_row["status"],
                    req_row["status"],
                    outcome,
                    req_row["inspection_outcome"],
                    norm_actor["principal_id"],
                    norm_actor["role"],
                    clean_note,
                    now_ts,
                ),
            )
            self.log(
                db,
                req_row["customer_id"],
                "order_action_refund_updated",
                req_row["order_id"],
                request_id=request_id,
                case_id=req_row["case_id"],
                action="refund_outcome",
                refund_decision="approved",
                from_refund_status="pending",
                to_refund_status=outcome,
                version=new_ver,
                note=clean_note,
                actor=norm_actor,
            )
            self._enqueue_outbox_in_tx(
                db,
                event_type="request_status_changed",
                actor=norm_actor,
                customer_id=req_row["customer_id"],
                case_id=req_row["case_id"],
                order_action_request_id=request_id,
                order_id=req_row["order_id"],
                before={
                    "status": req_row["status"],
                    "version": cur_ver,
                    "refund_status": "pending",
                    "refund_decision": "approved",
                },
                after={
                    "status": req_row["status"],
                    "version": new_ver,
                    "refund_status": outcome,
                    "refund_decision": "approved",
                },
                reason_code=req_row["reason_code"],
                reason_text=clean_note,
                correlation_id=idempotency_key or f"{request_id}:v{new_ver}",
                idempotency_key=idempotency_key or f"{request_id}:refund_outcome:{outcome}:v{new_ver}",
                source="app",
                now=now_ts,
            )
            updated_row = db.execute("SELECT * FROM order_action_requests WHERE request_id = ?", (request_id,)).fetchone()
            serialized = self._serialize_order_action_in_tx(db, updated_row, now=now_ts)
        return {
            "status": serialized["status"],
            "refund_status": serialized["refund_status"],
            "refund_decision": serialized["refund_decision"],
            "order_action_request_id": serialized["request_id"],
            "order_action": serialized,
            "order": serialized["order"],
        }

    def manager_update_order_status(
        self,
        order_id: str,
        new_status: str,
        *,
        expected_version=None,
        actor: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        require(isinstance(order_id, str) and bool(order_id.strip()), 400, "invalid_order_id", "Thiếu order_id.")
        oid = order_id.strip()
        require(
            new_status in ("pending", "delivered", "cancelled"),
            400,
            "invalid_status",
            "Trạng thái phải là pending, delivered hoặc cancelled.",
        )
        if expected_version is not None:
            require(
                type(expected_version) is int and expected_version >= 1,
                400,
                "invalid_order_version",
                "Phiên bản đơn hàng dự kiến phải là số nguyên dương.",
            )
        norm_actor = self._normalize_actor(actor, "manager", "manager")
        now_ts = self._now()

        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
            require(row is not None, 404, "order_not_found", f"Không tìm thấy đơn hàng {oid}.")
            cur_ver = int(row["version"])
            if expected_version is not None:
                require(
                    cur_ver == expected_version,
                    409,
                    "stale_order",
                    f"Phiên bản đơn hàng {oid} không khớp (hiện tại v{cur_ver}).",
                )
            cur_status = row["status"]
            if cur_status == new_status:
                return {
                    "status": "ok",
                    "order_id": oid,
                    "customer_id": row["customer_id"],
                    "new_status": new_status,
                    "version": cur_ver,
                    "delivered_at": row["delivered_at"],
                    "changed": False,
                    "message": f"Đơn hàng {oid} đã ở trạng thái {new_status}.",
                }
            require(
                cur_status == "pending",
                400,
                "invalid_transition",
                f"Không thể chuyển trạng thái từ '{cur_status}' sang '{new_status}'. Đơn đã vào trạng thái kết thúc.",
            )
            new_ver = cur_ver + 1
            if new_status == "delivered":
                won = db.execute(
                    """UPDATE orders
                       SET status = ?, delivered_at = COALESCE(delivered_at, ?), version = ?
                       WHERE id = ? AND version = ?""",
                    (new_status, now_ts, new_ver, oid, cur_ver),
                ).rowcount
            else:
                won = db.execute(
                    "UPDATE orders SET status = ?, version = ? WHERE id = ? AND version = ?",
                    (new_status, new_ver, oid, cur_ver),
                ).rowcount
            require(won == 1, 409, "stale_order", f"Đơn hàng {oid} vừa thay đổi đồng thời.")
            updated_ord = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
            self.log(
                db,
                row["customer_id"],
                "order_status_updated_by_manager",
                oid,
                new_status=new_status,
                previous_status=cur_status,
                version=new_ver,
                delivered_at=updated_ord["delivered_at"],
                actor=actor if actor is not None else norm_actor,
            )
            self._enqueue_outbox_in_tx(
                db,
                event_type="order_status_changed",
                actor=norm_actor,
                customer_id=row["customer_id"],
                order_id=oid,
                before={"status": cur_status, "version": cur_ver},
                after={"status": new_status, "version": new_ver},
                correlation_id=idempotency_key or f"mgr_order:{oid}:v{new_ver}",
                idempotency_key=idempotency_key or f"mgr_order:{oid}:{new_status}:v{new_ver}",
                source="app",
                now=now_ts,
            )
        return {
            "status": "ok",
            "order_id": oid,
            "customer_id": row["customer_id"],
            "new_status": new_status,
            "version": new_ver,
            "delivered_at": updated_ord["delivered_at"],
            "changed": True,
            "message": f"Đã cập nhật trạng thái đơn {oid} sang {new_status}.",
        }

    def _effective_data_root(self) -> Path:
        explicit = getattr(self, "data_root", None)
        if explicit is not None:
            return Path(explicit)
        db_path = getattr(self, "path", None)
        if db_path is not None:
            p = Path(db_path)
            if p.parent.name in ("tenants", "public-guests"):
                return p.parent.parent
            return p.parent
        env_out = os.environ.get("RETAILOPS_OUTPUT", "").strip()
        if env_out:
            return Path(env_out)
        return Path(tempfile.gettempdir()) / "retailops_runtime_data"

    def upload_order_action_evidence(
        self,
        request_id: str,
        raw_bytes: bytes,
        *,
        customer_id: str | None = None,
        actor: dict | None = None,
    ) -> dict:
        require(
            isinstance(request_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id)),
            400,
            "invalid_request_id",
            "Mã yêu cầu đơn hàng không hợp lệ.",
        )
        clean = inspect_and_reencode_evidence(raw_bytes)
        norm_actor = self._normalize_actor(actor, str(customer_id or "customer"), "customer")
        caller_role = norm_actor["role"]
        require(
            caller_role in ("customer", "staff", "manager"),
            403,
            "permission_denied",
            "Tài khoản không có quyền tải ảnh bằng chứng.",
        )

        safe_tid, _, target_dir = resolve_protected_subdir(
            self._effective_data_root(), "evidence", self._effective_tenant_id(actor)
        )
        now_ts = self._now()
        evidence_id = f"ev_{uuid.uuid4().hex}"
        storage_relpath = f"evidence/{safe_tid}/{evidence_id}"
        written_path: Path | None = None

        try:
            with self.connection(write=True) as db:
                req_row = db.execute(
                    "SELECT * FROM order_action_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                require(req_row is not None, 404, "order_action_not_found", "Không tìm thấy yêu cầu đơn hàng.")

                if caller_role == "customer":
                    require(
                        bool(customer_id) and req_row["customer_id"] == customer_id,
                        404,
                        "order_action_not_found",
                        "Không tìm thấy yêu cầu đơn hàng.",
                    )
                    require(
                        req_row["status"] == "requested" and req_row["closed_at"] is None,
                        409,
                        "evidence_upload_closed",
                        "Khách hàng chỉ được đính kèm ảnh khi yêu cầu còn ở trạng thái requested.",
                    )
                    case_row = db.execute(
                        "SELECT status FROM cases WHERE case_id = ?",
                        (req_row["case_id"],),
                    ).fetchone()
                    require(
                        case_row is not None and case_row["status"] != "resolved",
                        409,
                        "case_already_resolved",
                        "Ca hỗ trợ đã đóng, không thể tải thêm ảnh bằng chứng.",
                    )
                    uploaded_by_principal = norm_actor["principal_id"]
                    uploaded_by_role = "customer"
                else:
                    self._check_case_reviewer_authority_in_tx(db, req_row["case_id"], norm_actor)
                    require(
                        req_row["closed_at"] is None,
                        409,
                        "evidence_upload_closed",
                        "Yêu cầu đơn hàng đã đóng, không thể tải thêm ảnh bằng chứng.",
                    )
                    uploaded_by_principal = norm_actor["principal_id"]
                    uploaded_by_role = caller_role

                cnt_row = db.execute(
                    "SELECT COUNT(*) AS cnt FROM order_action_evidence WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                existing_count = int(cnt_row["cnt"] if cnt_row and "cnt" in cnt_row else (cnt_row[0] if cnt_row else 0))
                require(
                    existing_count < EVIDENCE_MAX_COUNT,
                    409,
                    "evidence_limit_exceeded",
                    f"Mỗi yêu cầu đơn hàng chỉ được đính kèm tối đa {EVIDENCE_MAX_COUNT} ảnh bằng chứng.",
                )

                written_path = atomic_write_bytes(target_dir, evidence_id, clean["bytes"])
                db.execute(
                    """INSERT INTO order_action_evidence(
                           evidence_id, request_id, case_id, customer_id, conversation_id,
                           uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size,
                           width, height, sha256, storage_relpath, created_at, file_purged_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (
                        evidence_id,
                        request_id,
                        req_row["case_id"],
                        req_row["customer_id"],
                        req_row["conversation_id"],
                        uploaded_by_principal,
                        uploaded_by_role,
                        clean["mime_type"],
                        clean["byte_size"],
                        clean["width"],
                        clean["height"],
                        clean["sha256"],
                        storage_relpath,
                        now_ts,
                    ),
                )
                self.log(
                    db,
                    req_row["customer_id"],
                    "order_action_evidence_uploaded",
                    req_row["order_id"],
                    request_id=request_id,
                    case_id=req_row["case_id"],
                    evidence_id=evidence_id,
                    mime_type=clean["mime_type"],
                    byte_size=clean["byte_size"],
                    width=clean["width"],
                    height=clean["height"],
                    sha256=clean["sha256"],
                    actor=actor if actor is not None else norm_actor,
                )
                serialized = self._serialize_order_action_in_tx(db, req_row, now=now_ts)
        except Exception:
            if written_path is not None:
                written_path.unlink(missing_ok=True)
            raise

        return {
            "status": "ok",
            "evidence": {
                "evidence_id": evidence_id,
                "request_id": request_id,
                "case_id": req_row["case_id"],
                "mime_type": clean["mime_type"],
                "byte_size": clean["byte_size"],
                "width": clean["width"],
                "height": clean["height"],
                "sha256": clean["sha256"],
                "uploaded_by_role": uploaded_by_role,
                "created_at": now_ts,
                "purged": False,
                "download_url": f"/api/order-actions/{request_id}/evidence/{evidence_id}",
            },
            "order_action": serialized,
            "message": "Đã lưu ảnh bằng chứng (đã xóa dữ liệu EXIF/GPS).",
        }

    def get_order_action_evidence_record(self, request_id: str, evidence_id: str) -> tuple[dict, dict]:
        require(
            isinstance(request_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id)),
            400,
            "invalid_request_id",
            "Mã yêu cầu đơn hàng không hợp lệ.",
        )
        require(
            isinstance(evidence_id, str) and bool(re.fullmatch(r"ev_[a-f0-9]{32}", evidence_id)),
            400,
            "invalid_evidence_id",
            "Mã bằng chứng không hợp lệ.",
        )
        with self.connection() as db:
            req_row = db.execute(
                "SELECT * FROM order_action_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            require(req_row is not None, 404, "order_action_not_found", "Không tìm thấy yêu cầu đơn hàng.")
            ev_row = db.execute(
                "SELECT * FROM order_action_evidence WHERE evidence_id = ? AND request_id = ?",
                (evidence_id, request_id),
            ).fetchone()
            require(ev_row is not None, 404, "evidence_not_found", "Không tìm thấy tệp bằng chứng trên yêu cầu này.")
        return dict(req_row), dict(ev_row)

    def _resolve_evidence_file_path(self, storage_relpath: str) -> Path:
        _, base_root, _ = resolve_protected_subdir(
            self._effective_data_root(), "evidence", getattr(self, "tenant_id", "default")
        )
        rel = str(storage_relpath or "").strip().lstrip("/")
        parts = rel.split("/")
        require(
            len(parts) == 3 and parts[0] == "evidence" and all(pt and pt not in (".", "..") for pt in parts),
            500,
            "unsafe_storage_path",
            "Đường dẫn bằng chứng lưu trữ không hợp lệ.",
        )
        evidence_root = (base_root / "evidence").resolve()
        full_path = (base_root / Path(*parts)).resolve()
        require(
            full_path.is_relative_to(evidence_root),
            500,
            "unsafe_storage_path",
            "Đường dẫn bằng chứng nằm ngoài vùng lưu trữ bảo vệ.",
        )
        return full_path

    def read_order_action_evidence_bytes(self, evidence_row: dict) -> tuple[bytes, str]:
        require(
            evidence_row.get("file_purged_at") is None,
            410,
            "evidence_purged",
            "Tệp ảnh bằng chứng đã được xóa sau 90 ngày đóng yêu cầu; chỉ còn lưu mã băm và metadata.",
        )
        full_path = self._resolve_evidence_file_path(evidence_row["storage_relpath"])
        require(full_path.is_file(), 404, "evidence_file_missing", "Không tìm thấy tệp ảnh bằng chứng trên kho lưu trữ.")
        data = full_path.read_bytes()
        require(
            hashlib.sha256(data).hexdigest() == evidence_row["sha256"],
            500,
            "evidence_integrity_error",
            "Mã băm tệp bằng chứng không khớp với bản ghi kiểm toán.",
        )
        return data, str(evidence_row["mime_type"])

    def purge_expired_evidence(self, *, now: float | None = None) -> dict:
        now_ts = self._now() if now is None else float(now)
        cutoff = now_ts - float(EVIDENCE_RETENTION_SECONDS)
        with self.connection() as db:
            due = [
                dict(r)
                for r in db.execute(
                    """SELECT e.evidence_id, e.request_id, e.case_id, e.customer_id,
                              e.sha256, e.storage_relpath, r.order_id
                       FROM order_action_evidence e
                       JOIN order_action_requests r ON r.request_id = e.request_id
                       WHERE e.file_purged_at IS NULL
                         AND r.closed_at IS NOT NULL
                         AND r.closed_at <= ?
                       ORDER BY r.closed_at ASC, e.evidence_id ASC""",
                    (cutoff,),
                ).fetchall()
            ]
        purged = 0
        for item in due:
            try:
                fpath = self._resolve_evidence_file_path(item["storage_relpath"])
                fpath.unlink(missing_ok=True)
            except ApiError:
                continue
            with self.connection(write=True) as db:
                won = db.execute(
                    """UPDATE order_action_evidence
                       SET file_purged_at = ?
                       WHERE evidence_id = ? AND file_purged_at IS NULL""",
                    (now_ts, item["evidence_id"]),
                ).rowcount
                if won == 1:
                    purged += 1
                    self.log(
                        db,
                        item["customer_id"],
                        "order_action_evidence_purged",
                        item["order_id"],
                        evidence_id=item["evidence_id"],
                        request_id=item["request_id"],
                        case_id=item["case_id"],
                        sha256=item["sha256"],
                        purged_at=now_ts,
                    )
        return {"purged": purged}

    def _open_outbox_claim_tx(self):
        if getattr(self, "_supports_skip_locked", False):
            return self.connection(write=True, lock_schema=False)
        return self.connection(write=True)

    def process_outbox_batch(
        self,
        *,
        now: float | None = None,
        batch_size: int = 50,
        sink_writer=None,
    ) -> dict:
        now_ts = self._now() if now is None else float(now)
        max_items = max(1, min(int(batch_size), 500))
        published = 0
        retried = 0
        dead = 0

        select_sql = (
            """SELECT event_id, tenant_id, event_type, payload_json, created_at, status, attempts, next_attempt_at
               FROM integration_outbox
               WHERE status = 'pending' AND next_attempt_at <= ?
               ORDER BY created_at ASC, event_id ASC
               LIMIT 1"""
        )
        if getattr(self, "_supports_skip_locked", False):
            select_sql += " FOR UPDATE SKIP LOCKED"

        data_root = self._effective_data_root()
        seen_tenants = {self._effective_tenant_id(None)}

        for _ in range(max_items):
            claimed_none = False
            with self._open_outbox_claim_tx() as db:
                row = db.execute(select_sql, (now_ts,)).fetchone()
                if row is None:
                    claimed_none = True
                else:
                    ev_id = row["event_id"]
                    row_tid = str(row["tenant_id"] or self._effective_tenant_id(None)).strip() or "default"
                    seen_tenants.add(row_tid)
                    prev_attempts = int(row["attempts"])
                    try:
                        envelope = json.loads(row["payload_json"])
                        validate_outbox_envelope(envelope)
                        if sink_writer is not None:
                            sink_writer(data_root, row_tid, envelope, now_ts=now_ts)
                        else:
                            append_outbox_jsonl_line(data_root, row_tid, envelope, now_ts=now_ts)
                    except Exception as exc:
                        new_attempts = prev_attempts + 1
                        err_text = f"{exc.__class__.__name__}: {str(exc)[:300]}"
                        if contains_canary_or_secret(err_text):
                            _, err_text = sanitize_structured_payload(err_text, preserve_reasoning=False)
                        if new_attempts >= OUTBOX_MAX_ATTEMPTS:
                            db.execute(
                                """UPDATE integration_outbox
                                   SET status = 'dead',
                                       attempts = ?,
                                       last_error = ?
                                   WHERE event_id = ? AND status = 'pending'""",
                                (new_attempts, err_text, ev_id),
                            )
                            dead += 1
                        else:
                            delay = compute_next_backoff_seconds(new_attempts)
                            db.execute(
                                """UPDATE integration_outbox
                                   SET status = 'pending',
                                       attempts = ?,
                                       next_attempt_at = ?,
                                       last_error = ?
                                   WHERE event_id = ? AND status = 'pending'""",
                                (new_attempts, now_ts + float(delay), err_text, ev_id),
                            )
                            retried += 1
                    else:
                        db.execute(
                            """UPDATE integration_outbox
                               SET status = 'published',
                                   attempts = ?,
                                   published_at = ?,
                                   last_error = NULL
                               WHERE event_id = ? AND status = 'pending'""",
                            (prev_attempts + 1, now_ts, ev_id),
                        )
                        published += 1
            if claimed_none:
                break

        manifests_sealed = 0
        if sink_writer is None:
            for tid in sorted(seen_tenants):
                try:
                    manifests_sealed += seal_closed_integration_days(data_root, tid, now_ts=now_ts)
                except Exception:
                    pass

        return {
            "published": published,
            "retried": retried,
            "dead": dead,
            "manifests_sealed": manifests_sealed,
        }

    def outbox_status_summary(self) -> dict:
        counts = {"pending": 0, "published": 0, "dead": 0}
        oldest_pending_at = None
        latest_dead_error = None
        with self.connection(write=False) as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS cnt FROM integration_outbox GROUP BY status"
            ).fetchall()
            for r in rows:
                st = r["status"]
                if st in counts:
                    counts[st] = int(r["cnt"] if "cnt" in r else r[1])
            pend = db.execute(
                "SELECT MIN(created_at) AS min_ts FROM integration_outbox WHERE status = 'pending'"
            ).fetchone()
            if pend is not None:
                val = pend["min_ts"] if "min_ts" in pend else pend[0]
                if val is not None:
                    oldest_pending_at = float(val)
            dead_row = db.execute(
                """SELECT event_id, event_type, attempts, last_error, created_at
                   FROM integration_outbox
                   WHERE status = 'dead'
                   ORDER BY created_at DESC, event_id DESC
                   LIMIT 1"""
            ).fetchone()
            if dead_row is not None:
                latest_dead_error = {
                    "event_id": dead_row["event_id"],
                    "event_type": dead_row["event_type"],
                    "attempts": int(dead_row["attempts"]),
                    "last_error": dead_row["last_error"],
                    "created_at": float(dead_row["created_at"]),
                }
        return {
            **counts,
            "oldest_pending_at": oldest_pending_at,
            "latest_dead": latest_dead_error,
        }


def inspect_sqlite_outbox_status(target_path: Path) -> dict:
    """Strictly read-only operator summary of integration_outbox across SQLite tenant databases."""
    target = Path(target_path)
    totals = {"pending": 0, "published": 0, "dead": 0}
    tenant_reports = []

    if target.is_file():
        store = BusinessStore(target, create=False, initialize_db=False, read_only=True)
        store.tenant_id = target.stem
        summary = store.outbox_status_summary()
        tenant_reports.append({"tenant_id": target.stem, **summary})
        for k in ("pending", "published", "dead"):
            totals[k] += int(summary[k])
        return {
            "result": "OUTBOX_STATUS",
            "backend": "sqlite",
            "read_only": True,
            "totals": totals,
            "tenants": tenant_reports,
        }

    pers = target / "persistent" if (target / "persistent").is_dir() else target
    id_file = pers / "identity.sqlite3"
    if not id_file.is_file():
        raise ApiError(404, "database_not_found", "Không tìm thấy kho identity SQLite để kiểm tra outbox.")

    id_uri = id_file.resolve().as_uri() + "?mode=ro"
    id_conn = sqlite3.connect(id_uri, uri=True, timeout=5)
    id_conn.row_factory = sqlite3.Row
    try:
        t_rows = id_conn.execute("SELECT id, storage_key FROM tenants ORDER BY id ASC").fetchall()
    finally:
        id_conn.close()

    for trow in t_rows:
        tid = trow["id"]
        skey = trow["storage_key"]
        t_file = pers / "tenants" / f"{skey}.sqlite3"
        if not t_file.is_file():
            continue
        store = BusinessStore(t_file, create=False, initialize_db=False, read_only=True)
        store.tenant_id = tid
        summary = store.outbox_status_summary()
        tenant_reports.append({"tenant_id": tid, **summary})
        for k in ("pending", "published", "dead"):
            totals[k] += int(summary[k])

    return {
        "result": "OUTBOX_STATUS",
        "backend": "sqlite",
        "read_only": True,
        "totals": totals,
        "tenants": tenant_reports,
    }
