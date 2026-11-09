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
    EVIDENCE_MAX_BYTES,
    EVIDENCE_MAX_COUNT,
    EVIDENCE_RETENTION_SECONDS,
    PDF_EVIDENCE_MAX_BYTES,
    fields,
    require,
)
from retailops.business.eligibility import (
    LATE_DELIVERY_COMPENSATION_THRESHOLD_HOURS,
    LATE_DELIVERY_COMPENSATION_VOUCHER_TYPE,
    LATE_DELIVERY_COMPENSATION_VOUCHER_VND,
    compute_order_eligibility,
    deterministic_compensation_id,
    format_vn_iso,
)
from retailops.integration.recipient_crypto import (
    load_recipient_keyring,
    sync_order_recipient_retention_in_tx,
)

SHIPMENT_STATUS_TEXT_VI = {
    "created": "Đã tạo vận đơn",
    "ready_to_pick": "Chờ lấy hàng",
    "picked": "Đã lấy hàng",
    "picked_up": "Đã lấy hàng",
    "in_transit": "Đang trung chuyển",
    "sorting": "Đang phân loại tại kho",
    "out_for_delivery": "Đang giao hàng",
    "delivery_failed": "Giao hàng không thành công",
    "delivered": "Đã giao thành công",
    "returning": "Đang hoàn hàng",
    "returned": "Đã hoàn hàng về kho",
    "cancelled": "Đã hủy vận đơn",
    "lost": "Thất lạc kiện hàng",
    "damaged": "Kiện hàng hư hỏng",
}

_VN_FULL_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)\d(?:[\s.\-]?\d){8,9}(?!\d)")


def mask_shipper_phone_text(text: str | None) -> str | None:
    """Ensure any full phone number in shipper fields or descriptions is masked."""
    if text is None:
        return None
    clean = str(text).strip()
    if not clean:
        return None

    def _repl(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if digits.startswith("84") and len(digits) >= 11:
            digits = "0" + digits[2:]
        if len(digits) >= 9:
            return f"{digits[:3]}****{digits[-3:]}"
        return "***"

    return _VN_FULL_PHONE_RE.sub(_repl, clean)
from retailops.business.variants import fold_attribute
from retailops.order_reasons import reason_catalog
from retailops.business.clamav import ClamdScanner
from retailops.business.evidence import (
    atomic_write_bytes,
    decode_attachment_data_payload,
    encode_image_data_url,
    inspect_and_reencode_evidence,
    inspect_evidence_bytes,
    project_image_for_model,
    project_pdf_for_model,
    resolve_protected_subdir,
    sanitize_attachment_filename,
)
from retailops.business.outbox import (
    OUTBOX_MAX_ATTEMPTS,
    append_outbox_jsonl_line,
    compute_customer_ref,
    compute_next_backoff_seconds,
    resolve_customer_ref_key,
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
    BUSINESS_V7_VERSION_MAPPING,
    BUSINESS_V8_VERSION_MAPPING,
    BUSINESS_V9_VERSION_MAPPING,
    EXCHANGE_KINDS,
    REQUIRED_V9_TABLES,
    SQLITE_BUSINESS_SCHEMA_CURRENT,
    SQLITE_BUSINESS_V5_SCHEMA_VERSION,
    SQLITE_BUSINESS_V6_SCHEMA_VERSION,
    SQLITE_BUSINESS_V7_SCHEMA_VERSION,
    SQLITE_BUSINESS_V8_SCHEMA_VERSION,
    backfill_business_v5_cases,
    ensure_case_assist_tables,
    ensure_case_tables,
    ensure_import_tables,
    ensure_order_action_tables,
    ensure_v9_tables,
    initialize as initialize_schema,
)

ROOT = Path(__file__).resolve().parents[2]

_MIGRATE_HINT = 'Hãy chạy lệnh operator database migrate-v9 với --confirm-preflight --confirm-backup.'

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

    Returns 'empty' for a missing, zero-byte, or zero-table file; 'v7_ready' when already at
    SQLite business schema v6 (logical Business v7) with all Business v5 and v6 tables,
    orders.delivered_at and the general-exchange columns; 'v6_ready' / 'v5_ready' for the
    earlier milestones when `target_version` asks only for those; raises ValueError for wrong
    component / unsupported future version; and raises ApiError(503, 'business_migration_required', ...)
    when an existing business DB older than `target_version` is found.
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
                    f'Kho dữ liệu cửa hàng thiếu dấu vết schema Business v9; khởi động bị chặn fail-closed. {_MIGRATE_HINT}',
                )
            ver = rows[0]['version']
            if ver not in range(1, SQLITE_BUSINESS_SCHEMA_CURRENT + 1):
                raise ValueError('Unsupported database schema version; use the matching application version.')
            if ver < target_version:
                raise ApiError(
                    503,
                    'business_migration_required',
                    f'Kho dữ liệu cửa hàng đang ở SQLite schema v{ver} (trước Business v9); khởi động bị chặn fail-closed. '
                    f'{_MIGRATE_HINT}',
                )
            required_v5_tables = {'cases', 'handoff_episodes', 'case_feedback_events'}
            if not required_v5_tables.issubset(tables):
                raise ApiError(
                    503,
                    'business_migration_required',
                    f'Kho dữ liệu cửa hàng chưa đầy đủ các bảng Business v5; khởi động bị chặn fail-closed. {_MIGRATE_HINT}',
                )
            if target_version >= SQLITE_BUSINESS_V6_SCHEMA_VERSION:
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
                        f'Kho dữ liệu cửa hàng chưa đầy đủ các bảng/cột Business v6; khởi động bị chặn fail-closed. {_MIGRATE_HINT}',
                    )
                if target_version >= SQLITE_BUSINESS_V7_SCHEMA_VERSION:
                    request_cols = {row['name'] for row in ro_db.execute('PRAGMA table_info(order_action_requests)')}
                    if not {'target_variant_id', 'target_variant_label'} <= request_cols:
                        raise ApiError(
                            503,
                            'business_migration_required',
                            f'Kho dữ liệu cửa hàng chưa đầy đủ các cột đổi hàng Business v7; khởi động bị chặn fail-closed. '
                            f'{_MIGRATE_HINT}',
                        )
                    if target_version >= SQLITE_BUSINESS_V8_SCHEMA_VERSION:
                        if 'case_assist_turns' not in tables:
                            raise ApiError(
                                503,
                                'business_migration_required',
                                f'Kho dữ liệu cửa hàng thiếu bảng lịch sử trợ lý ca Business v8; khởi động bị chặn fail-closed. '
                                f'{_MIGRATE_HINT}',
                            )
                        ev_info = list(ro_db.execute('PRAGMA table_info(order_action_evidence)'))
                        ev_cols = {row['name'] for row in ev_info}
                        ev_not_null = {row['name'] for row in ev_info if int(row['notnull']) != 0}
                        ev_master = ro_db.execute(
                            "SELECT sql FROM sqlite_master WHERE type='table' AND name='order_action_evidence'"
                        ).fetchone()
                        ev_ddl = str(ev_master['sql'] or '') if ev_master else ''
                        required_v8_ev_cols = {'filename', 'page_count', 'scan_status', 'scan_engine', 'scanned_at'}
                        if (
                            not (required_v8_ev_cols <= ev_cols)
                            or 'application/pdf' not in ev_ddl
                            or bool({'request_id', 'case_id', 'width', 'height'} & ev_not_null)
                        ):
                            raise ApiError(
                                503,
                                'business_migration_required',
                                f'Kho dữ liệu cửa hàng chưa đầy đủ cấu trúc bằng chứng Business v8; khởi động bị chặn fail-closed. '
                                f'{_MIGRATE_HINT}',
                            )
                        if target_version >= SQLITE_BUSINESS_SCHEMA_CURRENT:
                            if not set(REQUIRED_V9_TABLES).issubset(tables) or 'imported_events' not in tables:
                                raise ApiError(
                                    503,
                                    'business_migration_required',
                                    f'Kho dữ liệu cửa hàng thiếu các bảng tích hợp Business v9; khởi động bị chặn fail-closed. '
                                    f'{_MIGRATE_HINT}',
                                )
                            ord_info = list(ro_db.execute('PRAGMA table_info(orders)'))
                            ord_cols = {row['name'] for row in ord_info}
                            ord_not_null = {row['name'] for row in ord_info if int(row['notnull']) != 0}
                            ord_master = ro_db.execute(
                                "SELECT sql FROM sqlite_master WHERE type='table' AND name='orders'"
                            ).fetchone()
                            ord_ddl = str(ord_master['sql'] or '') if ord_master else ''
                            required_v9_ord_cols = {
                                'source_system',
                                'external_order_id',
                                'ordered_at',
                                'ordered_at_backfilled',
                                'payment_method',
                                'payment_status',
                                'shipping_fee',
                                'ship_to_area',
                                'promised_delivery_by',
                            }
                            if (
                                not (required_v9_ord_cols <= ord_cols)
                                or "'shipping'" not in ord_ddl
                                or 'orders_source_external_v9_unique' not in ord_ddl
                                or not ({'source_system', 'ordered_at', 'ordered_at_backfilled', 'payment_status'} <= ord_not_null)
                            ):
                                raise ApiError(
                                    503,
                                    'business_migration_required',
                                    f'Kho dữ liệu cửa hàng chưa đầy đủ bảng orders Business v9; khởi động bị chặn fail-closed. '
                                    f'{_MIGRATE_HINT}',
                                )
                            ie_info = list(ro_db.execute('PRAGMA table_info(imported_events)'))
                            ie_cols = {row['name'] for row in ie_info}
                            ie_not_null = {row['name'] for row in ie_info if int(row['notnull']) != 0}
                            required_v9_ie_cols = {'event_type', 'sequence', 'received_via', 'payload_digest', 'redacted_fields'}
                            legacy_ie_nullable = {
                                'external_customer_id',
                                'customer_id',
                                'order_id',
                                'status',
                                'total',
                                'currency',
                                'signature',
                            }
                            if not (required_v9_ie_cols <= ie_cols) or bool(legacy_ie_nullable & ie_not_null):
                                raise ApiError(
                                    503,
                                    'business_migration_required',
                                    f'Kho dữ liệu cửa hàng chưa cập nhật imported_events Business v9; khởi động bị chặn fail-closed. '
                                    f'{_MIGRATE_HINT}',
                                )
                            idx_names = {
                                r[0]
                                for r in ro_db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
                            }
                            trg_names = {
                                r[0]
                                for r in ro_db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
                            }
                            if (
                                'idx_product_variants_sku_unique' not in idx_names
                                or not {'shipment_events_no_update', 'shipment_events_no_delete'} <= trg_names
                            ):
                                raise ApiError(
                                    503,
                                    'business_migration_required',
                                    f'Kho dữ liệu cửa hàng thiếu chỉ mục hoặc trigger Business v9; khởi động bị chặn fail-closed. '
                                    f'{_MIGRATE_HINT}',
                                )
                            return 'v9_ready'
                        return 'v8_ready'
                    return 'v7_ready'
                return 'v6_ready'
            return 'v5_ready'
        if 'memberships' in tables or 'tenants' in tables:
            raise ValueError('Database belongs to another RetailOps component.')
        if tables & {'orders', 'conversations', 'proposals', 'business_events', 'products'}:
            raise ApiError(
                503,
                'business_migration_required',
                f'Kho dữ liệu cửa hàng legacy chưa nâng cấp lên Business v9; khởi động bị chặn fail-closed. {_MIGRATE_HINT}',
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


def backfill_legacy_turn_attachments_v8(
    db,
    *,
    data_root: Path,
    tenant_id: str,
    malware_scanner=None,
    now: float | None = None,
) -> tuple[dict, list[Path]]:
    """Business v8 (W4-D6, W4-D9): migrate inline attachments in agent_turns to evidence store or removed markers.

    Works on both SQLite connections and PostgreSQL Queries inside the caller's open transaction.
    Returns `(stats_dict, written_paths)` so the caller can unlink newly written files on rollback.
    """
    active_scanner = malware_scanner if malware_scanner is not None else ClamdScanner.from_environment()
    now_ts = float(now if now is not None else time.time())
    safe_tid, _, target_dir = resolve_protected_subdir(Path(data_root), 'evidence', tenant_id or 'default')
    ext_map = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp',
        'application/pdf': '.pdf',
    }
    written_paths: list[Path] = []
    attachments_migrated = 0
    attachments_removed = 0
    turns_updated = 0

    rows = db.execute(
        'SELECT id, conversation_id, customer_id, messages, created_at FROM agent_turns ORDER BY id ASC'
    ).fetchall()
    for row in rows:
        raw_messages = row['messages']
        try:
            messages = json.loads(raw_messages) if isinstance(raw_messages, str) else raw_messages
        except (TypeError, ValueError):
            continue
        if not isinstance(messages, list):
            continue

        turn_changed = False
        cid = str(row['conversation_id'] or '')
        customer_id = str(row['customer_id'] or '')
        turn_created_at = float(row['created_at'] or now_ts)

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            att = msg.get('attachment')
            if not isinstance(att, dict) or 'data' not in att:
                continue

            turn_changed = True
            att_type_hint = str(att.get('type') or 'image').strip()
            if att_type_hint not in ('image', 'document'):
                att_type_hint = 'image'
            orig_name = sanitize_attachment_filename(att.get('name'), default_name='attachment')

            try:
                cust_exists = db.execute(
                    'SELECT id FROM customers WHERE id = ?',
                    (customer_id,),
                ).fetchone()
                if cust_exists is None:
                    raise ApiError(400, 'unknown_customer', 'Khách hàng của lượt hội thoại không tồn tại.')
                raw_bytes = decode_attachment_data_payload(
                    att.get('data'),
                    max_raw_bytes=PDF_EVIDENCE_MAX_BYTES,
                )
                clean = inspect_evidence_bytes(raw_bytes, scanner=active_scanner)
            except ApiError as exc:
                msg['attachment'] = {
                    'type': att_type_hint,
                    'name': orig_name,
                    'removed': True,
                    'removed_reason': exc.code,
                    'removed_at': now_ts,
                }
                attachments_removed += 1
                continue
            except Exception:
                msg['attachment'] = {
                    'type': att_type_hint,
                    'name': orig_name,
                    'removed': True,
                    'removed_reason': 'invalid_attachment',
                    'removed_at': now_ts,
                }
                attachments_removed += 1
                continue

            default_name = 'attachment' + ext_map.get(clean['mime_type'], '')
            safe_name = sanitize_attachment_filename(att.get('name'), default_name=default_name)
            evidence_id = f'ev_{uuid.uuid4().hex}'
            storage_relpath = f'evidence/{safe_tid}/{evidence_id}'

            case_row = db.execute(
                'SELECT case_id FROM cases WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1',
                (cid,),
            ).fetchone()
            case_id = case_row['case_id'] if case_row else None

            written_path = atomic_write_bytes(target_dir, evidence_id, clean['bytes'])
            written_paths.append(written_path)
            db.execute(
                """INSERT INTO order_action_evidence(
                       evidence_id, request_id, case_id, customer_id, conversation_id, filename,
                       uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size,
                       width, height, page_count, sha256, storage_relpath,
                       scan_status, scan_engine, scanned_at, created_at, file_purged_at
                   ) VALUES (?, NULL, ?, ?, ?, ?, ?, 'customer', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    evidence_id,
                    case_id,
                    customer_id,
                    cid,
                    safe_name,
                    customer_id,
                    clean['mime_type'],
                    clean['byte_size'],
                    clean.get('width'),
                    clean.get('height'),
                    clean.get('page_count'),
                    clean['sha256'],
                    storage_relpath,
                    clean.get('scan_status'),
                    clean.get('scan_engine'),
                    clean.get('scanned_at'),
                    turn_created_at,
                ),
            )
            ref_meta = {
                'evidence_id': evidence_id,
                'type': 'document' if clean['mime_type'] == 'application/pdf' else 'image',
                'mime_type': clean['mime_type'],
                'name': safe_name,
                'sha256': clean['sha256'],
                'download_url': f'/api/conversations/{cid}/evidence/{evidence_id}',
            }
            if clean['mime_type'] == 'application/pdf':
                ref_meta['page_count'] = clean.get('page_count')
                ref_meta['pdf_mode'] = clean.get('pdf_mode')
            msg['attachment'] = ref_meta
            attachments_migrated += 1

        if turn_changed:
            db.execute(
                'UPDATE agent_turns SET messages = ? WHERE id = ?',
                (json.dumps(messages, ensure_ascii=False), row['id']),
            )
            turns_updated += 1

    return (
        {
            'attachments_migrated': attachments_migrated,
            'attachments_removed': attachments_removed,
            'turns_updated': turns_updated,
        },
        written_paths,
    )


def _migrate_single_sqlite_business_file(
    db_path: Path,
    *,
    target_version: int = SQLITE_BUSINESS_SCHEMA_CURRENT,
    backfill_attachments: bool = False,
    data_root: Path | None = None,
    tenant_id: str = 'default',
    malware_scanner=None,
):
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
    written_paths: list[Path] = []
    try:
        db.execute('PRAGMA journal_mode=WAL')
        # Business v7/v8 steps rebuild order_action_requests / order_action_evidence: foreign keys are
        # switched off before BEGIN and foreign_key_check below proves consistency before commit.
        db.execute('PRAGMA foreign_keys=' + ('OFF' if target_version >= SQLITE_BUSINESS_V7_SCHEMA_VERSION else 'ON'))
        db.execute('BEGIN IMMEDIATE')
        ver_before_row = (
            db.execute("SELECT version FROM retailops_schema WHERE component='business'").fetchone()
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retailops_schema'").fetchone()
            else None
        )
        ver_before = int(ver_before_row['version']) if ver_before_row else 0
        has_requests = bool(
            db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_action_requests'").fetchone()
        )
        requests_before = db.execute('SELECT COUNT(*) FROM order_action_requests').fetchone()[0] if has_requests else 0
        legacy_exchange_rows = (
            db.execute("SELECT COUNT(*) FROM order_action_requests WHERE exchange_kind IN ('size', 'one_to_one')").fetchone()[0]
            if has_requests else 0
        )
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
        orders_backfilled = 0
        if target_version >= SQLITE_BUSINESS_SCHEMA_CURRENT and (ver_before < target_version or state == 'needs_migration'):
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='orders'").fetchone():
                ord_cols_pre = {row['name'] for row in db.execute('PRAGMA table_info(orders)')}
                if 'source_system' in ord_cols_pre and 'ordered_at' in ord_cols_pre:
                    orders_backfilled = int(
                        db.execute(
                            'SELECT COUNT(*) FROM orders WHERE source_system IS NULL OR ordered_at IS NULL'
                        ).fetchone()[0]
                    )
                else:
                    orders_backfilled = int(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0])

        if ver_before < target_version or state == 'needs_migration':
            migrate(db, 'business', initialize_schema, target_version=target_version)
            ensure_import_tables(db)
            ensure_case_tables(db)
            backfill_res = backfill_business_v5_cases(db)
            if target_version >= SQLITE_BUSINESS_V6_SCHEMA_VERSION:
                ensure_order_action_tables(db)
            if target_version >= SQLITE_BUSINESS_V8_SCHEMA_VERSION:
                ensure_case_assist_tables(db)
            if target_version >= SQLITE_BUSINESS_SCHEMA_CURRENT:
                ensure_v9_tables(db)
        else:
            backfill_res = {'cases_created': 0, 'episodes_created': 0}
            legacy_exchange_rows = 0

        att_stats = {'attachments_migrated': 0, 'attachments_removed': 0, 'turns_updated': 0}
        if backfill_attachments and target_version >= SQLITE_BUSINESS_V8_SCHEMA_VERSION:
            eff_root = Path(data_root) if data_root is not None else db_path.parent
            att_stats, written_paths = backfill_legacy_turn_attachments_v8(
                db,
                data_root=eff_root,
                tenant_id=tenant_id,
                malware_scanner=malware_scanner,
            )

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
        requests_after = (
            db.execute('SELECT COUNT(*) FROM order_action_requests').fetchone()[0]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_action_requests'").fetchone()
            else 0
        )
        if requests_after < requests_before:
            raise sqlite3.IntegrityError(
                f'Business migration lost order-action requests ({requests_before} -> {requests_after}).')
        db.commit()
        return {
            'upgraded': bool(
                ver_before < target_version
                or state == 'needs_migration'
                or backfill_res['cases_created'] > 0
                or att_stats['turns_updated'] > 0
            ),
            'cases_created': int(cases_after - cases_before),
            'episodes_created': int(episodes_after - episodes_before),
            'order_action_requests': int(requests_after),
            'exchange_requests_mapped': int(legacy_exchange_rows) if target_version >= SQLITE_BUSINESS_V7_SCHEMA_VERSION else 0,
            'attachments_migrated': int(att_stats['attachments_migrated']),
            'attachments_removed': int(att_stats['attachments_removed']),
            'turns_updated': int(att_stats['turns_updated']),
            'orders_backfilled': int(orders_backfilled),
        }
    except Exception:
        if db.in_transaction:
            db.rollback()
        for wp in written_paths:
            wp.unlink(missing_ok=True)
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
        single = _migrate_single_sqlite_business_file(target, target_version=SQLITE_BUSINESS_V6_SCHEMA_VERSION)
        return {
            'result': 'BUSINESS_V6_MIGRATED',
            'backend': 'sqlite',
            'schema_version': SQLITE_BUSINESS_V6_SCHEMA_VERSION,
            'logical_version': BUSINESS_V6_VERSION_MAPPING['postgresql'],
            'tenants': 1,
            'upgraded': single['upgraded'],
        }

    tenant_files = _resolve_sqlite_tenant_files(target, milestone_label='Business v6')
    any_upgraded = False
    for tf in tenant_files:
        res = _migrate_single_sqlite_business_file(tf, target_version=SQLITE_BUSINESS_V6_SCHEMA_VERSION)
        any_upgraded = any_upgraded or res['upgraded']

    return {
        'result': 'BUSINESS_V6_MIGRATED',
        'backend': 'sqlite',
        'schema_version': SQLITE_BUSINESS_V6_SCHEMA_VERSION,
        'logical_version': BUSINESS_V6_VERSION_MAPPING['postgresql'],
        'tenants': len(tenant_files),
        'upgraded': any_upgraded,
    }


def migrate_sqlite_business_v7(path, *, preflight_confirmed=False, backup_confirmed=False):
    """Explicit operator migration command for SQLite Business v7 (W3.2-D1, W3.2-D6).

    Upgrades every tenant business database to SQLite schema v6 (logical Business v7): the request
    table is rebuilt for general exchange, `size` becomes `other_variant` (target left empty) and
    `one_to_one` becomes `same_variant`, and no row is deleted. Idempotent; databases older than
    Business v6 are brought through the earlier steps first. Never invoked automatically.
    """
    require(
        preflight_confirmed is True and backup_confirmed is True,
        400,
        'migration_confirmation_required',
        'Lệnh nâng cấp Business v7 yêu cầu xác nhận tường minh --confirm-preflight và --confirm-backup theo runbook §11.5.',
    )
    target = Path(path)
    tenant_files = [target] if target.is_file() else _resolve_sqlite_tenant_files(target, milestone_label='Business v7')
    any_upgraded, mapped, requests = False, 0, 0
    for tf in tenant_files:
        res = _migrate_single_sqlite_business_file(tf, target_version=SQLITE_BUSINESS_V7_SCHEMA_VERSION)
        any_upgraded = any_upgraded or res['upgraded']
        mapped += res['exchange_requests_mapped']
        requests += res['order_action_requests']

    return {
        'result': 'BUSINESS_V7_MIGRATED',
        'backend': 'sqlite',
        'schema_version': SQLITE_BUSINESS_V7_SCHEMA_VERSION,
        'logical_version': BUSINESS_V7_VERSION_MAPPING['postgresql'],
        'tenants': len(tenant_files),
        'upgraded': any_upgraded,
        'order_action_requests': requests,
        'exchange_requests_mapped': mapped,
    }


def _resolve_sqlite_tenant_id_map(target: Path) -> tuple[Path, dict[str, str]]:
    if target.is_file():
        if target.parent.name == 'tenants' and (target.parent.parent / 'identity.sqlite3').is_file():
            pers_dir = target.parent.parent
        else:
            return target.parent, {}
    else:
        pers_dir = target / 'persistent' if (target / 'persistent').is_dir() else target
    eff_root = pers_dir.parent if pers_dir.name == 'persistent' else pers_dir
    key_map: dict[str, str] = {}
    id_file = pers_dir / 'identity.sqlite3'
    if id_file.is_file():
        ro_uri = id_file.resolve().as_uri() + '?mode=ro'
        ro_id = sqlite3.connect(ro_uri, uri=True, timeout=5)
        ro_id.row_factory = sqlite3.Row
        try:
            for row in ro_id.execute('SELECT id, storage_key FROM tenants ORDER BY id').fetchall():
                key_map[str(row['storage_key'])] = str(row['id'])
        finally:
            ro_id.close()
    return eff_root, key_map


def migrate_sqlite_business_v8(
    path,
    *,
    preflight_confirmed=False,
    backup_confirmed=False,
    data_root: Path | None = None,
    malware_scanner=None,
):
    """Explicit operator migration command for SQLite Business v8 (W4-D4, W4-D6, W4-D9).

    Upgrades every tenant business database to SQLite schema v7 (logical Business v8): adds
    `case_assist_turns`, expands `order_action_evidence` for `application/pdf` (<=20 MB) and malware
    scan metadata, and migrates inline `agent_turns` attachments to the evidence store (or replaces
    invalid/infected payloads with removed markers). Idempotent; never invoked automatically.
    """
    require(
        preflight_confirmed is True and backup_confirmed is True,
        400,
        'migration_confirmation_required',
        'Lệnh nâng cấp Business v8 yêu cầu xác nhận tường minh --confirm-preflight và --confirm-backup theo runbook §11.5.',
    )
    target = Path(path)
    inferred_root, key_to_tid = _resolve_sqlite_tenant_id_map(target)
    eff_root = Path(data_root) if data_root is not None else inferred_root
    tenant_files = [target] if target.is_file() else _resolve_sqlite_tenant_files(target, milestone_label='Business v8')

    any_upgraded = False
    attachments_migrated = 0
    attachments_removed = 0
    turns_updated = 0
    for tf in tenant_files:
        tid = key_to_tid.get(tf.stem, 'default')
        res = _migrate_single_sqlite_business_file(
            tf,
            target_version=SQLITE_BUSINESS_V8_SCHEMA_VERSION,
            backfill_attachments=True,
            data_root=eff_root,
            tenant_id=tid,
            malware_scanner=malware_scanner,
        )
        any_upgraded = any_upgraded or res['upgraded']
        attachments_migrated += res['attachments_migrated']
        attachments_removed += res['attachments_removed']
        turns_updated += res['turns_updated']

    return {
        'result': 'BUSINESS_V8_MIGRATED',
        'backend': 'sqlite',
        'schema_version': SQLITE_BUSINESS_V8_SCHEMA_VERSION,
        'logical_version': BUSINESS_V8_VERSION_MAPPING['postgresql'],
        'tenants': len(tenant_files),
        'upgraded': any_upgraded,
        'attachments_migrated': attachments_migrated,
        'attachments_removed': attachments_removed,
        'turns_updated': turns_updated,
    }


def migrate_sqlite_business_v9(
    path,
    *,
    preflight_confirmed=False,
    backup_confirmed=False,
    data_root: Path | None = None,
    malware_scanner=None,
):
    """Explicit operator migration command for SQLite Business v9 (W6.1b-D1, B2, B3, B6).

    Upgrades every tenant business database to SQLite schema v8 (logical Business v9) in one
    transaction per tenant: adds canonical v9 columns and 'shipping' status to `orders` (backfilling
    legacy rows with `source_system='retailops_seed'`, `external_order_id=id`, `ordered_at=<migrate_ts>`,
    `ordered_at_backfilled=1`), updates `imported_events` to v2 shape, adds partial unique index on
    `product_variants.sku`, and creates all 8 Business v9 tables plus append-only `shipment_events`
    triggers. Idempotent; never invoked automatically.
    """
    require(
        preflight_confirmed is True and backup_confirmed is True,
        400,
        'migration_confirmation_required',
        'Lệnh nâng cấp Business v9 yêu cầu xác nhận tường minh --confirm-preflight và --confirm-backup theo runbook.',
    )
    target = Path(path)
    inferred_root, key_to_tid = _resolve_sqlite_tenant_id_map(target)
    eff_root = Path(data_root) if data_root is not None else inferred_root
    tenant_files = [target] if target.is_file() else _resolve_sqlite_tenant_files(target, milestone_label='Business v9')

    any_upgraded = False
    orders_backfilled = 0
    for tf in tenant_files:
        tid = key_to_tid.get(tf.stem, 'default')
        res = _migrate_single_sqlite_business_file(
            tf,
            target_version=SQLITE_BUSINESS_SCHEMA_CURRENT,
            backfill_attachments=True,
            data_root=eff_root,
            tenant_id=tid,
            malware_scanner=malware_scanner,
        )
        any_upgraded = any_upgraded or res['upgraded']
        orders_backfilled += res['orders_backfilled']

    return {
        'result': 'BUSINESS_V9_MIGRATED',
        'backend': 'sqlite',
        'schema_version': SQLITE_BUSINESS_SCHEMA_CURRENT,
        'logical_version': BUSINESS_V9_VERSION_MAPPING['postgresql'],
        'tenants': len(tenant_files),
        'upgraded': any_upgraded,
        'orders_backfilled': orders_backfilled,
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
        # Populate system actors, base product catalog, and fixed simulator demo events (W6.1b-D2, D11).
        from retailops.integration.demo_seed import seed_demo_store_events

        with self.connection(write=True) as db:
            db.executemany(
                "INSERT INTO customers (id, name) VALUES (?, ?) ON CONFLICT DO NOTHING",
                [
                    ('manager', 'Quản lý cửa hàng'),
                    ('system', 'Hệ thống'),
                ],
            )
            self.seed_catalog(db)
        seed_demo_store_events(self)

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

    def has_demo_store_seed(self, db=None) -> bool:
        """Return True when this tenant has loaded the marketplace_sim demo store seed."""
        def _check(conn) -> bool:
            row = conn.execute(
                "SELECT 1 FROM imported_events "
                "WHERE source_system = 'marketplace_sim' AND event_id = 'evt:customer:SIM-C-0088:1' "
                "LIMIT 1"
            ).fetchone()
            return row is not None

        if db is not None:
            return _check(db)
        with self.connection() as conn:
            return _check(conn)

    def seed_demo_sample_orders(self, customer_id, db=None, *, sessions=None):
        """Instantiate the 3-order simulator account template for a new demo customer (W6.1b-D2, D11)."""
        from retailops.integration.demo_seed import seed_demo_account_orders

        return seed_demo_account_orders(self, customer_id, sessions=sessions, db=db)

    def purge_legacy_demo_orders(self, *, dry_run: bool = False) -> dict:
        """Remove legacy ``retailops_seed`` orders that have no linked cancel/return/exchange requests (W6.1b-D2).

        Any ``retailops_seed`` order with >= 1 row in ``order_action_requests`` is retained and listed.
        When ``dry_run=True``, mutates nothing and returns exact counts and order lists.
        """
        tenant_clean = str(getattr(self, "tenant_id", None) or "default")
        with self.connection(write=not bool(dry_run)) as conn:
            rows = conn.execute(
                """SELECT id, customer_id, status, name, amount
                   FROM orders
                   WHERE source_system = 'retailops_seed'
                   ORDER BY id ASC"""
            ).fetchall()
            removable: list[dict] = []
            retained: list[dict] = []
            for row in rows:
                oid = str(row["id"])
                req_rows = conn.execute(
                    """SELECT request_id, type, status
                       FROM order_action_requests
                       WHERE order_id = ?
                       ORDER BY created_at ASC, request_id ASC""",
                    (oid,),
                ).fetchall()
                entry = {
                    "order_id": oid,
                    "customer_id": str(row["customer_id"]),
                    "status": str(row["status"]),
                    "name": str(row["name"]),
                    "amount": int(row["amount"]),
                }
                if req_rows:
                    retained.append(
                        {
                            **entry,
                            "request_ids": [str(r["request_id"]) for r in req_rows],
                        }
                    )
                else:
                    removable.append(entry)

            removed_count = 0
            removed_order_ids: list[str] = []
            if not dry_run and removable:
                for entry in removable:
                    oid = entry["order_id"]
                    conn.execute("UPDATE conversations SET order_id = NULL WHERE order_id = ?", (oid,))
                    conn.execute("DELETE FROM proposals WHERE order_id = ?", (oid,))
                    conn.execute("DELETE FROM order_items WHERE order_id = ?", (oid,))
                    deleted = conn.execute(
                        "DELETE FROM orders WHERE id = ? AND source_system = 'retailops_seed'",
                        (oid,),
                    ).rowcount
                    if int(deleted or 0) > 0:
                        removed_count += int(deleted or 0)
                        removed_order_ids.append(oid)
                        self.log(
                            conn,
                            entry["customer_id"],
                            "legacy_demo_order_purged",
                            oid,
                            tenant_id=tenant_clean,
                            status=entry["status"],
                            name=entry["name"],
                            amount=entry["amount"],
                        )

            return {
                "result": "PURGE_LEGACY_DEMO_DRY_RUN" if dry_run else "PURGE_LEGACY_DEMO_OK",
                "tenant_id": tenant_clean,
                "dry_run": bool(dry_run),
                "would_remove_count": len(removable),
                "removed_count": 0 if dry_run else removed_count,
                "removed_order_ids": [] if dry_run else removed_order_ids,
                "removable_orders": removable,
                "retained_count": len(retained),
                "retained_orders": retained,
            }

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
    def resolve_customer_order_in_tx(db, customer, oid):
        """Resolve an order belonging strictly to `customer` by internal `id` or `external_order_id`.

        Returns `(order_dict, None)` when unique, or `(None, candidates)` when multiple orders of
        this same customer share the identifier across connectors (W6.1b-D8: never auto-pick).
        Raises `ApiError(404, 'order_not_found', ...)` when invalid or zero rows belong to `customer`.
        """
        if not isinstance(oid, str) or not oid.isascii() or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', oid):
            require(False, 404, "order_not_found", "Không tìm thấy đơn hàng của bạn.")
        rows = db.execute(
            "SELECT * FROM orders WHERE customer_id = ? AND (id = ? OR external_order_id = ?) "
            "ORDER BY ordered_at DESC, id ASC",
            (customer, oid, oid),
        ).fetchall()
        require(len(rows) > 0, 404, "order_not_found", "Không tìm thấy đơn hàng của bạn.")
        if len(rows) == 1:
            return dict(rows[0]), None
        # If `oid` matches a unique internal `id` among the rows, internal `id` is globally unique per tenant.
        exact_internal = [r for r in rows if r["id"] == oid and r["external_order_id"] != oid]
        if len(exact_internal) == 1:
            return dict(exact_internal[0]), None
        candidates = []
        for r in rows:
            rd = dict(r)
            item_rows = db.execute(
                "SELECT product_title FROM order_items WHERE order_id = ? ORDER BY id ASC",
                (rd["id"],),
            ).fetchall()
            item_names = [str(ir["product_title"]) for ir in item_rows if ir["product_title"]]
            if not item_names and rd.get("name"):
                item_names = [str(rd["name"])]
            ordered_iso = (
                None
                if int(rd.get("ordered_at_backfilled") or 0) == 1
                else format_vn_iso(rd.get("ordered_at"))
            )
            candidates.append(
                {
                    "internal_order_id": rd["id"],
                    "external_order_id": rd["external_order_id"],
                    "source_system": rd["source_system"],
                    "ordered_at": ordered_iso,
                    "item_names": item_names,
                    "name": rd.get("name"),
                    "amount": int(rd["amount"]) if rd.get("amount") is not None else None,
                    "status": rd.get("status"),
                }
            )
        return None, candidates

    @staticmethod
    def owned(db, customer, oid):
        order, candidates = BusinessStore.resolve_customer_order_in_tx(db, customer, oid)
        if candidates is not None:
            raise ApiError(
                409,
                "ambiguous_order",
                "Có nhiều đơn hàng của bạn trùng mã này từ các nguồn khác nhau; vui lòng xác định rõ đơn hàng.",
            )
        return order

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
            self.log(db, customer, "order_viewed", order["id"])
            return order

    def read_order_details_in_tx(self, db, order_dict: dict, *, now: float | None = None) -> dict:
        """Read DB-backed payment, refund summary, shipment presence, and computed eligibility for one order."""
        now_ts = self._now() if now is None else float(now)
        oid = str(order_dict["id"])
        eligibility = self._order_eligibility_in_tx(db, order_dict, now=now_ts)
        pay_rows = db.execute(
            "SELECT payment_id, provider, provider_txn_ref, method, amount, status, created_at, settled_at "
            "FROM payment_transactions WHERE order_id = ? ORDER BY created_at ASC, payment_id ASC",
            (oid,),
        ).fetchall()
        ref_rows = db.execute(
            "SELECT refund_id, provider, provider_refund_ref, amount, status, failure_reason, initiated_at, completed_at "
            "FROM refunds WHERE order_id = ? ORDER BY initiated_at ASC, refund_id ASC",
            (oid,),
        ).fetchall()
        ship_row = db.execute(
            "SELECT shipment_id, carrier, tracking_code, status, carrier_status_raw, current_area, "
            "estimated_delivery_at, delivered_at, delivery_attempts "
            "FROM shipments WHERE order_id = ? ORDER BY updated_at DESC, shipment_id DESC LIMIT 1",
            (oid,),
        ).fetchone()

        is_unrecorded_seed = (
            order_dict.get("source_system") == "retailops_seed"
            and order_dict.get("payment_method") is None
            and not pay_rows
            and not ref_rows
        )
        payment_status = None if is_unrecorded_seed else order_dict.get("payment_status")
        if pay_rows or order_dict.get("payment_method") is not None:
            paid_total = sum(int(r["amount"]) for r in pay_rows if r["status"] == "succeeded")
            latest_pay_ts = (pay_rows[-1]["settled_at"] or pay_rows[-1]["created_at"]) if pay_rows else None
            payment_summary = {
                "method": order_dict.get("payment_method"),
                "status": payment_status,
                "paid_total": paid_total if pay_rows else None,
                "transactions_count": len(pay_rows),
                "latest_updated_at": format_vn_iso(latest_pay_ts) if pay_rows else None,
            }
        else:
            payment_summary = None

        if ref_rows:
            latest_ref_ts = ref_rows[-1]["completed_at"] or ref_rows[-1]["initiated_at"]
            refund_summary = {
                "count": len(ref_rows),
                "refunded_total": sum(int(r["amount"]) for r in ref_rows if r["status"] == "completed"),
                "pending_total": sum(int(r["amount"]) for r in ref_rows if r["status"] in ("pending", "processing")),
                "latest_status": ref_rows[-1]["status"],
                "latest_reason": ref_rows[-1]["failure_reason"],
                "latest_updated_at": format_vn_iso(latest_ref_ts),
            }
        else:
            refund_summary = None

        if (
            ship_row is not None
            or order_dict.get("delivered_at") is not None
            or order_dict.get("promised_delivery_by") is not None
        ):
            delivery_summary = {
                "carrier": ship_row["carrier"] if ship_row is not None else None,
                "tracking_code": ship_row["tracking_code"] if ship_row is not None else None,
                "status": ship_row["status"] if ship_row is not None else None,
                "current_area": ship_row["current_area"] if ship_row is not None else None,
                "ship_to_area": order_dict.get("ship_to_area"),
                "promised_delivery_by": format_vn_iso(order_dict.get("promised_delivery_by")),
                "estimated_delivery_at": eligibility.get("latest_estimated_delivery_at"),
                "delivered_at": format_vn_iso(order_dict.get("delivered_at")),
            }
        else:
            delivery_summary = None

        rec_safe_row = db.execute(
            "SELECT phone_masked, ward, district, province FROM order_recipients WHERE order_id = ?",
            (oid,),
        ).fetchone()
        recipient_safe = (
            {
                "phone_masked": rec_safe_row["phone_masked"],
                "ward": rec_safe_row["ward"],
                "district": rec_safe_row["district"],
                "province": rec_safe_row["province"],
            }
            if rec_safe_row is not None
            else None
        )

        vch_rows = db.execute(
            """SELECT voucher_id, source_system, external_voucher_id, compensation_id,
                      code, voucher_type, value, valid_until, issued_at
               FROM vouchers
               WHERE order_id = ?
               ORDER BY issued_at ASC, voucher_id ASC""",
            (oid,),
        ).fetchall()
        vouchers_list = [
            {
                "voucher_id": r["voucher_id"],
                "source_system": r["source_system"],
                "external_voucher_id": r["external_voucher_id"],
                "compensation_id": r["compensation_id"],
                "code": r["code"],
                "voucher_type": r["voucher_type"],
                "value": int(r["value"]),
                "valid_until": format_vn_iso(r["valid_until"]),
                "issued_at": format_vn_iso(r["issued_at"]),
            }
            for r in vch_rows
        ]

        ordered_at_iso = (
            None
            if int(order_dict.get("ordered_at_backfilled") or 0) == 1
            else format_vn_iso(order_dict.get("ordered_at"))
        )
        return {
            "ordered_at": ordered_at_iso,
            "payment_method": order_dict.get("payment_method"),
            "payment_status": payment_status,
            "shipping_fee": int(order_dict["shipping_fee"]) if order_dict.get("shipping_fee") is not None else None,
            "ship_to_area": order_dict.get("ship_to_area"),
            "promised_delivery_by": format_vn_iso(order_dict.get("promised_delivery_by")),
            "delivered_at": format_vn_iso(order_dict.get("delivered_at")),
            "refund_summary": refund_summary,
            "payment": payment_summary,
            "delivery": delivery_summary,
            "refund": refund_summary,
            "recipient": recipient_safe,
            "vouchers": vouchers_list,
            "eligibility": eligibility,
            "as_of": eligibility["as_of"],
        }

    def _resolve_store_recipient_keyring(self):
        if os.environ.get("RETAILOPS_RECIPIENT_KEY_FILE", "").strip():
            return load_recipient_keyring()
        if os.environ.get("RETAILOPS_ENV", "").strip().lower() in ("production", "prod", "live"):
            return load_recipient_keyring()
        ephemeral = getattr(self, "_ephemeral_recipient_keyring", None)
        if ephemeral is not None:
            return ephemeral
        return load_recipient_keyring()

    def read_order_recipient_masked_in_tx(self, db, order_id: str) -> dict | None:
        row = db.execute(
            """SELECT phone_masked, ward, district, province, name_enc, phone_enc, address_line_enc
               FROM order_recipients WHERE order_id = ?""",
            (str(order_id),),
        ).fetchone()
        if row is None:
            return None
        has_enc = any(
            row[col] is not None for col in ("name_enc", "phone_enc", "address_line_enc")
        )
        return {
            "phone_masked": row["phone_masked"],
            "ward": row["ward"],
            "district": row["district"],
            "province": row["province"],
            "has_encrypted_recipient": has_enc,
            "purged": not has_enc,
        }

    def read_order_recipient_masked(self, order_id: str) -> dict | None:
        with self.connection() as db:
            return self.read_order_recipient_masked_in_tx(db, order_id)

    def decrypt_order_recipient_in_tx(
        self,
        db,
        order_id: str,
        *,
        tenant_id: str | None = None,
    ) -> dict | None:
        oid = str(order_id)
        row = db.execute(
            """SELECT order_id, name_enc, phone_enc, address_line_enc,
                      phone_masked, ward, district, province, retention_until
               FROM order_recipients WHERE order_id = ?""",
            (oid,),
        ).fetchone()
        if row is None:
            return None
        has_enc = any(
            row[col] is not None for col in ("name_enc", "phone_enc", "address_line_enc")
        )
        if not has_enc:
            return {
                "name": None,
                "phone": None,
                "address_line": None,
                "phone_masked": row["phone_masked"],
                "ward": row["ward"],
                "district": row["district"],
                "province": row["province"],
                "purged": True,
            }
        keyring = self._resolve_store_recipient_keyring()
        eff_tid = str(tenant_id or getattr(self, "tenant_id", None) or "default")
        name_val = (
            keyring.decrypt_field(
                row["name_enc"], tenant_id=eff_tid, order_id=oid, field_name="name"
            )
            if row["name_enc"] is not None
            else None
        )
        phone_val = (
            keyring.decrypt_field(
                row["phone_enc"], tenant_id=eff_tid, order_id=oid, field_name="phone"
            )
            if row["phone_enc"] is not None
            else None
        )
        addr_val = (
            keyring.decrypt_field(
                row["address_line_enc"],
                tenant_id=eff_tid,
                order_id=oid,
                field_name="address_line",
            )
            if row["address_line_enc"] is not None
            else None
        )
        return {
            "name": name_val,
            "phone": phone_val,
            "address_line": addr_val,
            "phone_masked": row["phone_masked"],
            "ward": row["ward"],
            "district": row["district"],
            "province": row["province"],
            "purged": False,
        }

    def read_customer_order_recipient(
        self,
        customer_id: str,
        order_id: str,
        *,
        tenant_id: str | None = None,
    ) -> dict | None:
        """Decrypt recipient strictly for an order owned by ``customer_id`` (W6.1b-2-D3)."""
        with self.connection() as db:
            ord_row = self.owned(db, customer_id, order_id)
            return self.decrypt_order_recipient_in_tx(
                db, str(ord_row["id"]), tenant_id=tenant_id
            )

    def authorize_and_decrypt_order_recipient(
        self,
        order_id: str,
        *,
        actor_role: str,
        actor_principal_id: str | None,
        tenant_id: str | None = None,
        case_id: str | None = None,
    ) -> dict:
        """Authorize Staff (holding open case linked to order) or Manager, and decrypt recipient."""
        raw_oid = str(order_id or "").strip()
        require(bool(raw_oid), 400, "invalid_order", "Mã đơn hàng không hợp lệ.")
        clean_case = str(case_id).strip() if isinstance(case_id, str) and case_id.strip() else None

        with self.connection() as db:
            ord_row = db.execute("SELECT * FROM orders WHERE id = ?", (raw_oid,)).fetchone()
            if ord_row is None:
                ext_matches = db.execute(
                    "SELECT * FROM orders WHERE LOWER(external_order_id) = LOWER(?) ORDER BY id ASC",
                    (raw_oid,),
                ).fetchall()
                if len(ext_matches) > 1:
                    raise ApiError(
                        409,
                        "ambiguous_order",
                        "Có nhiều đơn hàng trùng mã sàn này; vui lòng dùng mã nội bộ của đơn hàng.",
                    )
                if len(ext_matches) == 1:
                    ord_row = ext_matches[0]
            require(ord_row is not None, 404, "order_not_found", "Không tìm thấy đơn hàng.")
            canonical_oid = str(ord_row["id"])
            ord_customer_id = str(ord_row["customer_id"])

            matched_case_id: str | None = None
            if actor_role == "manager":
                if clean_case is not None:
                    c_row = db.execute(
                        "SELECT case_id FROM cases WHERE case_id = ?", (clean_case,)
                    ).fetchone()
                    require(c_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
                    matched_case_id = str(c_row["case_id"])
            elif actor_role == "staff":
                pid = str(actor_principal_id or "").strip()
                require(
                    bool(pid),
                    403,
                    "recipient_reveal_denied",
                    "Nhân viên phải đăng nhập và đang giữ ca mở có gắn đơn hàng để xem người nhận.",
                )
                params: list = [pid, ord_customer_id, canonical_oid, canonical_oid]
                case_filter_sql = ""
                if clean_case is not None:
                    case_filter_sql = " AND c.case_id = ?"
                    params.append(clean_case)
                held_row = db.execute(
                    f"""SELECT c.case_id
                        FROM cases c
                        LEFT JOIN conversations conv ON conv.id = c.conversation_id
                        WHERE c.status = 'in_progress'
                          AND c.holder = ?
                          AND c.customer_id = ?
                          AND (
                              conv.order_id = ?
                              OR EXISTS (
                                  SELECT 1 FROM order_action_requests oar
                                  WHERE oar.case_id = c.case_id AND oar.order_id = ?
                              )
                          )
                          {case_filter_sql}
                        ORDER BY c.updated_at DESC
                        LIMIT 1""",
                    tuple(params),
                ).fetchone()
                require(
                    held_row is not None,
                    403,
                    "recipient_reveal_denied",
                    "Chỉ nhân viên đang giữ ca mở có gắn đơn hàng này hoặc Quản lý mới được xem thông tin người nhận.",
                )
                matched_case_id = str(held_row["case_id"])
            else:
                raise ApiError(
                    403,
                    "permission_denied",
                    "Tài khoản này không có quyền xem thông tin người nhận.",
                )

            revealed = self.decrypt_order_recipient_in_tx(
                db, canonical_oid, tenant_id=tenant_id
            )
            require(
                revealed is not None,
                404,
                "recipient_not_found",
                "Đơn hàng này không có dữ liệu người nhận.",
            )
            return {
                "order_id": canonical_oid,
                "external_order_id": ord_row["external_order_id"],
                "case_id": matched_case_id,
                "recipient": revealed,
            }

    def purge_expired_recipients(
        self,
        *,
        dry_run: bool = False,
        now: float | None = None,
    ) -> dict:
        """NULL out encrypted recipient columns and phone_lookup_hmac past retention_until (W6.1b-2-D4)."""
        now_ts = float(self._now() if now is None else now)
        eff_tid = str(getattr(self, "tenant_id", None) or "default")
        where_clause = """
            retention_until IS NOT NULL
            AND retention_until <= ?
            AND (
                name_enc IS NOT NULL
                OR phone_enc IS NOT NULL
                OR address_line_enc IS NOT NULL
                OR phone_lookup_hmac IS NOT NULL
            )
        """
        if dry_run:
            with self.connection() as db:
                rows = db.execute(
                    f"SELECT order_id FROM order_recipients WHERE {where_clause} ORDER BY order_id ASC",
                    (now_ts,),
                ).fetchall()
            oids = [str(r["order_id"]) for r in rows]
            return {
                "result": "PURGE_EXPIRED_RECIPIENTS_DRY_RUN",
                "tenant_id": eff_tid,
                "dry_run": True,
                "as_of": now_ts,
                "would_purge_count": len(oids),
                "purged_count": 0,
                "order_ids": oids,
            }

        with self.connection(write=True) as db:
            rows = db.execute(
                f"SELECT order_id FROM order_recipients WHERE {where_clause} ORDER BY order_id ASC",
                (now_ts,),
            ).fetchall()
            oids = [str(r["order_id"]) for r in rows]
            purged = 0
            if oids:
                purged = int(
                    db.execute(
                        f"""UPDATE order_recipients
                            SET name_enc = NULL,
                                phone_enc = NULL,
                                address_line_enc = NULL,
                                phone_lookup_hmac = NULL
                            WHERE {where_clause}""",
                        (now_ts,),
                    ).rowcount
                )
        return {
            "result": "PURGE_EXPIRED_RECIPIENTS_COMPLETED",
            "tenant_id": eff_tid,
            "dry_run": False,
            "as_of": now_ts,
            "would_purge_count": len(oids),
            "purged_count": purged,
            "order_ids": oids,
        }

    def _serialize_compensation_in_tx(self, db, row) -> dict:
        comp_id = str(row["compensation_id"])
        oid = str(row["order_id"])
        ord_row = db.execute(
            "SELECT id, external_order_id, source_system, status, customer_id, promised_delivery_by, delivered_at "
            "FROM orders WHERE id = ?",
            (oid,),
        ).fetchone()
        ship_id = row["shipment_id"]
        ship_row = (
            db.execute(
                "SELECT shipment_id, carrier, tracking_code, status FROM shipments WHERE shipment_id = ?",
                (str(ship_id),),
            ).fetchone()
            if ship_id is not None
            else None
        )
        v_row = db.execute(
            "SELECT voucher_id, code, valid_until, issued_at FROM vouchers WHERE compensation_id = ? ORDER BY issued_at DESC LIMIT 1",
            (comp_id,),
        ).fetchone()
        return {
            "compensation_id": comp_id,
            "order_id": oid,
            "external_order_id": ord_row["external_order_id"] if ord_row is not None else None,
            "source_system": ord_row["source_system"] if ord_row is not None else None,
            "order_status": ord_row["status"] if ord_row is not None else None,
            "shipment_id": str(ship_id) if ship_id is not None else None,
            "carrier": ship_row["carrier"] if ship_row is not None else None,
            "tracking_code": ship_row["tracking_code"] if ship_row is not None else None,
            "reason": str(row["reason"]),
            "late_by_hours": round(float(row["late_by_hours"]), 2),
            "voucher_type": str(row["voucher_type"]),
            "value": int(row["value"]),
            "status": str(row["status"]),
            "decided_by_principal_id": row["decided_by_principal_id"],
            "decided_at": float(row["decided_at"]) if row["decided_at"] is not None else None,
            "decided_at_iso": format_vn_iso(row["decided_at"]),
            "note": row["note"],
            "request_id": row["request_id"],
            "voucher_code": v_row["code"] if v_row is not None else None,
            "voucher_valid_until": format_vn_iso(v_row["valid_until"]) if v_row is not None else None,
        }

    def scan_late_delivery_compensations(
        self,
        *,
        now: float | None = None,
        _fail_after_first_insert_for_test: bool = False,
    ) -> dict:
        """Detect shipping/delivered orders late past 48h vs promised_delivery_by and propose 50,000 VND vouchers (W6.1b-2-D6, D7)."""
        now_ts = float(self._now() if now is None else now)
        with self.connection() as db:
            candidate_ids = [
                str(r["id"])
                for r in db.execute(
                    """SELECT id FROM orders
                       WHERE status IN ('shipping', 'delivered')
                         AND promised_delivery_by IS NOT NULL
                       ORDER BY id ASC"""
                ).fetchall()
            ]

        proposed_count = 0
        for oid in candidate_ids:
            inserted_this_order = False
            with self.connection(write=True) as db:
                ord_row = db.execute(
                    """SELECT * FROM orders
                       WHERE id = ?
                         AND status IN ('shipping', 'delivered')
                         AND promised_delivery_by IS NOT NULL""",
                    (oid,),
                ).fetchone()
                if ord_row is None:
                    continue
                ord_dict = dict(ord_row)
                elig = self._order_eligibility_in_tx(db, ord_dict, now=now_ts)
                late_by = elig.get("late_by_hours")
                if late_by is None or float(late_by) <= float(LATE_DELIVERY_COMPENSATION_THRESHOLD_HOURS):
                    continue
                ship_row = db.execute(
                    "SELECT shipment_id FROM shipments WHERE order_id = ? ORDER BY updated_at DESC, shipment_id DESC LIMIT 1",
                    (oid,),
                ).fetchone()
                ship_id = str(ship_row["shipment_id"]) if ship_row is not None else None
                comp_id = deterministic_compensation_id(oid, ship_id, "late_delivery")

                existing_for_order = db.execute(
                    """SELECT compensation_id FROM delivery_compensations
                       WHERE order_id = ?
                         AND reason = 'late_delivery'
                         AND (shipment_id = ? OR shipment_id IS NULL OR ? IS NULL)
                       LIMIT 1""",
                    (oid, ship_id, ship_id),
                ).fetchone()
                if existing_for_order is not None:
                    continue

                cur = db.execute(
                    """INSERT INTO delivery_compensations (
                           compensation_id, order_id, shipment_id, reason,
                           late_by_hours, voucher_type, value, status,
                           decided_by_principal_id, decided_at, note, request_id
                       ) VALUES (?, ?, ?, 'late_delivery', ?, ?, ?, 'proposed', NULL, NULL, NULL, NULL)
                       ON CONFLICT(compensation_id) DO NOTHING""",
                    (
                        comp_id,
                        oid,
                        ship_id,
                        round(float(late_by), 2),
                        LATE_DELIVERY_COMPENSATION_VOUCHER_TYPE,
                        int(LATE_DELIVERY_COMPENSATION_VOUCHER_VND),
                    ),
                )
                if cur.rowcount == 1:
                    proposed_count += 1
                    inserted_this_order = True
                    self.log(
                        db,
                        str(ord_dict["customer_id"]),
                        "delivery_compensation_proposed",
                        oid,
                        compensation_id=comp_id,
                        shipment_id=ship_id,
                        late_by_hours=round(float(late_by), 2),
                        voucher_type=LATE_DELIVERY_COMPENSATION_VOUCHER_TYPE,
                        value=int(LATE_DELIVERY_COMPENSATION_VOUCHER_VND),
                    )
            if _fail_after_first_insert_for_test and inserted_this_order and proposed_count == 1:
                raise RuntimeError("Simulated mid-scan crash after first compensation proposal")

        return {"proposed": proposed_count, "scanned": len(candidate_ids)}

    def list_case_compensations(self, case_id: str) -> list[dict]:
        """Return delivery_compensations for orders linked to the given case."""
        require(
            isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)),
            400,
            "invalid_case_id",
            "Mã ca hỗ trợ không hợp lệ.",
        )
        with self.connection() as db:
            case_row = db.execute(
                """SELECT c.case_id, conv.order_id AS conv_order_id
                   FROM cases c
                   LEFT JOIN conversations conv ON conv.id = c.conversation_id
                   WHERE c.case_id = ?""",
                (case_id,),
            ).fetchone()
            require(case_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
            linked_oids: set[str] = set()
            if case_row["conv_order_id"]:
                linked_oids.add(str(case_row["conv_order_id"]))
            for oar_r in db.execute(
                "SELECT DISTINCT order_id FROM order_action_requests WHERE case_id = ?",
                (case_id,),
            ).fetchall():
                if oar_r["order_id"]:
                    linked_oids.add(str(oar_r["order_id"]))
            if not linked_oids:
                return []
            placeholders = ",".join("?" for _ in linked_oids)
            rows = db.execute(
                f"""SELECT * FROM delivery_compensations
                    WHERE order_id IN ({placeholders})
                    ORDER BY CASE WHEN status = 'proposed' THEN 0 ELSE 1 END ASC, compensation_id ASC""",
                tuple(sorted(linked_oids)),
            ).fetchall()
            return [self._serialize_compensation_in_tx(db, r) for r in rows]

    def list_manager_compensations(
        self,
        *,
        status: str = "all",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Paginated store-wide delivery_compensations list for Manager without recipient PII."""
        st_clean = str(status or "all").strip().lower()
        allowed_st = ("all", "proposed", "approved", "requested", "issued", "rejected", "failed")
        require(
            st_clean in allowed_st,
            400,
            "invalid_status",
            "Trạng thái lọc đề xuất bồi thường không hợp lệ.",
        )
        require(type(limit) is int and 1 <= limit <= 50, 400, "invalid_limit", "Giới hạn mỗi trang phải từ 1 đến 50.")
        require(type(offset) is int and offset >= 0, 400, "invalid_offset", "Vị trí phân trang không hợp lệ.")

        with self.connection() as db:
            counts = {k: 0 for k in ("proposed", "approved", "requested", "issued", "rejected", "failed")}
            for gr in db.execute(
                "SELECT status, COUNT(*) AS cnt FROM delivery_compensations GROUP BY status"
            ).fetchall():
                if gr["status"] in counts:
                    counts[gr["status"]] = int(gr["cnt"])
            cnt_all = sum(counts.values())
            counts["all"] = cnt_all
            total_matching = counts[st_clean]

            where_sql = "" if st_clean == "all" else "WHERE dc.status = ?"
            params: list = [] if st_clean == "all" else [st_clean]
            params.extend([limit, offset])

            rows = db.execute(
                f"""SELECT dc.*, c.name AS customer_name
                    FROM delivery_compensations dc
                    LEFT JOIN orders o ON o.id = dc.order_id
                    LEFT JOIN customers c ON c.id = o.customer_id
                    {where_sql}
                    ORDER BY CASE WHEN dc.status = 'proposed' THEN 0 ELSE 1 END ASC, dc.compensation_id ASC
                    LIMIT ? OFFSET ?""",
                tuple(params),
            ).fetchall()

            items = []
            for r in rows:
                base = self._serialize_compensation_in_tx(db, r)
                raw_cname = str(r["customer_name"] or "").strip()
                if "@" in raw_cname:
                    raw_cname = raw_cname.split("@", 1)[0].strip()
                if " - " in raw_cname:
                    raw_cname = raw_cname.split(" - ", 1)[0].strip()
                raw_cname = re.sub(r"(?:\+?84|0)\d[\d\s.\-]{7,12}\d", "", raw_cname).strip(" -|,;·")
                linked_case = db.execute(
                    """SELECT c.case_id
                       FROM cases c
                       LEFT JOIN conversations conv ON conv.id = c.conversation_id
                       WHERE conv.order_id = ?
                          OR EXISTS (
                              SELECT 1 FROM order_action_requests oar
                              WHERE oar.case_id = c.case_id AND oar.order_id = ?
                          )
                       ORDER BY CASE WHEN c.status IN ('in_progress', 'waiting') THEN 0 ELSE 1 END ASC,
                                c.updated_at DESC
                       LIMIT 1""",
                    (base["order_id"], base["order_id"]),
                ).fetchone()
                base["customer_name"] = raw_cname or "Khách hàng"
                base["case_id"] = str(linked_case["case_id"]) if linked_case is not None else None
                items.append(base)

        return {
            "status_filter": st_clean,
            "total": total_matching,
            "limit": limit,
            "offset": offset,
            "counts": counts,
            "items": items,
        }

    def decide_delivery_compensation(
        self,
        compensation_id: str,
        *,
        decision: str,
        actor: dict | None,
        note: str | None = None,
        case_id: str | None = None,
    ) -> dict:
        """Conditionally approve or reject a proposed delivery_compensation (WHERE status='proposed')."""
        comp_clean = str(compensation_id or "").strip()
        require(
            bool(re.fullmatch(r"[A-Za-z0-9_-]{4,80}", comp_clean)),
            400,
            "invalid_compensation_id",
            "Mã đề xuất bồi thường không hợp lệ.",
        )
        require(
            decision in ("approve", "reject"),
            400,
            "invalid_decision",
            "Quyết định bồi thường phải là approve hoặc reject.",
        )
        clean_note: str | None = None
        if note is not None:
            require(isinstance(note, str), 400, "invalid_note", "Ghi chú phải là chuỗi ký tự.")
            stripped_note = note.strip()
            require(len(stripped_note) <= 500, 400, "invalid_note", "Ghi chú không được vượt quá 500 ký tự.")
            clean_note = stripped_note or None

        clean_case: str | None = None
        if case_id is not None:
            require(
                isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id.strip())),
                400,
                "invalid_case_id",
                "Mã ca hỗ trợ không hợp lệ.",
            )
            clean_case = case_id.strip()

        actor_role = str((actor or {}).get("role") or "").strip().lower()
        actor_pid = str((actor or {}).get("principal_id") or "").strip()
        require(
            actor_role in ("staff", "manager") and bool(actor_pid),
            403,
            "permission_denied",
            "Chỉ nhân viên đang giữ ca mở có gắn đơn hoặc Quản lý mới được duyệt bồi thường.",
        )

        now_ts = float(self._now())
        with self.connection(write=True) as db:
            comp_row = db.execute(
                "SELECT * FROM delivery_compensations WHERE compensation_id = ?",
                (comp_clean,),
            ).fetchone()
            require(
                comp_row is not None,
                404,
                "compensation_not_found",
                "Không tìm thấy đề xuất bồi thường.",
            )
            canonical_oid = str(comp_row["order_id"])
            ord_row = db.execute(
                "SELECT * FROM orders WHERE id = ?",
                (canonical_oid,),
            ).fetchone()
            require(ord_row is not None, 404, "order_not_found", "Không tìm thấy đơn hàng của đề xuất bồi thường.")
            ord_customer_id = str(ord_row["customer_id"])

            matched_case_id: str | None = None
            if actor_role == "manager":
                if clean_case is not None:
                    c_row = db.execute(
                        "SELECT case_id FROM cases WHERE case_id = ?",
                        (clean_case,),
                    ).fetchone()
                    require(c_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
                    matched_case_id = str(c_row["case_id"])
            else:
                params: list = [actor_pid, ord_customer_id, canonical_oid, canonical_oid]
                case_filter_sql = ""
                if clean_case is not None:
                    case_filter_sql = " AND c.case_id = ?"
                    params.append(clean_case)
                held_row = db.execute(
                    f"""SELECT c.case_id
                        FROM cases c
                        LEFT JOIN conversations conv ON conv.id = c.conversation_id
                        WHERE c.status = 'in_progress'
                          AND c.holder = ?
                          AND c.customer_id = ?
                          AND (
                              conv.order_id = ?
                              OR EXISTS (
                                  SELECT 1 FROM order_action_requests oar
                                  WHERE oar.case_id = c.case_id AND oar.order_id = ?
                              )
                          )
                          {case_filter_sql}
                        ORDER BY c.updated_at DESC
                        LIMIT 1""",
                    tuple(params),
                ).fetchone()
                require(
                    held_row is not None,
                    403,
                    "compensation_decision_denied",
                    "Chỉ nhân viên đang giữ ca mở có gắn đơn hàng này hoặc Quản lý mới được duyệt/từ chối đề xuất bồi thường.",
                )
                matched_case_id = str(held_row["case_id"])

            next_status = "requested" if decision == "approve" else "rejected"
            next_request_id = comp_clean if decision == "approve" else None
            upd = db.execute(
                """UPDATE delivery_compensations
                   SET status = ?,
                       decided_by_principal_id = ?,
                       decided_at = ?,
                       note = ?,
                       request_id = COALESCE(?, request_id)
                   WHERE compensation_id = ?
                     AND status = 'proposed'""",
                (next_status, actor_pid, now_ts, clean_note, next_request_id, comp_clean),
            )
            if upd.rowcount != 1:
                raise ApiError(
                    409,
                    "compensation_not_proposed",
                    "Đề xuất bồi thường đã được xử lý bởi người khác hoặc không còn ở trạng thái chờ duyệt.",
                )

            if decision == "approve":
                vreq_envelope = self._build_voucher_requested_envelope_in_tx(
                    db,
                    comp_row=comp_row,
                    ord_row=ord_row,
                    occurred_ts=now_ts,
                    approved_by_role=actor_role,
                )
                eff_tid = self._effective_tenant_id((actor or {}).get("tenant_id"))
                db.execute(
                    """INSERT INTO integration_outbox (
                           event_id, tenant_id, event_type, payload_json,
                           created_at, status, attempts, next_attempt_at, last_error, published_at
                       ) VALUES (?, ?, 'voucher.requested', ?, ?, 'pending', 0, ?, NULL, NULL)
                       ON CONFLICT(event_id) DO NOTHING""",
                    (
                        vreq_envelope["event_id"],
                        eff_tid,
                        json.dumps(vreq_envelope, ensure_ascii=False, separators=(",", ":")),
                        now_ts,
                        now_ts,
                    ),
                )

            updated_row = db.execute(
                "SELECT * FROM delivery_compensations WHERE compensation_id = ?",
                (comp_clean,),
            ).fetchone()
            serialized = self._serialize_compensation_in_tx(db, updated_row)
            self.log(
                db,
                ord_customer_id,
                "delivery_compensation_approved" if decision == "approve" else "delivery_compensation_rejected",
                canonical_oid,
                compensation_id=comp_clean,
                status=serialized["status"],
                value=serialized["value"],
                voucher_type=serialized["voucher_type"],
                case_id=matched_case_id,
                note=clean_note,
                actor={
                    "principal_id": actor_pid,
                    "role": actor_role,
                    "tenant_id": (actor or {}).get("tenant_id"),
                    "membership_id": (actor or {}).get("membership_id"),
                },
            )
            return {
                "status": "ok",
                "compensation": serialized,
                "order_id": canonical_oid,
                "customer_id": ord_customer_id,
                "case_id": matched_case_id,
            }

    def _build_voucher_requested_envelope_in_tx(
        self,
        db,
        *,
        comp_row,
        ord_row,
        occurred_ts: float,
        approved_by_role: str,
    ) -> dict:
        from retailops.integration.contract import validate_event_v2

        comp_id = str(comp_row["compensation_id"])
        canonical_oid = str(ord_row["id"])
        ord_source = str(ord_row["source_system"] or "marketplace_sim")
        ord_customer_id = str(ord_row["customer_id"])
        ext_order_id = str(ord_row["external_order_id"] or canonical_oid)

        conn_row = db.execute(
            "SELECT merchant_id FROM integration_connectors WHERE source_system = ?",
            (ord_source,),
        ).fetchone()
        merchant_id: str | None = str(conn_row["merchant_id"]) if conn_row is not None else None
        imp_row = db.execute(
            """SELECT external_customer_id, payload_json
               FROM imported_events
               WHERE order_id = ?
                 AND source_system = ?
               ORDER BY CASE WHEN event_type = 'order.created' THEN 0 ELSE 1 END, id ASC
               LIMIT 1""",
            (canonical_oid, ord_source),
        ).fetchone()
        ext_customer_id: str | None = None
        if imp_row is not None:
            if imp_row["external_customer_id"]:
                ext_customer_id = str(imp_row["external_customer_id"])
            if not merchant_id and imp_row["payload_json"]:
                try:
                    parsed_ev = json.loads(str(imp_row["payload_json"]))
                    if parsed_ev.get("merchant_id"):
                        merchant_id = str(parsed_ev["merchant_id"])
                except Exception:
                    pass

        if not ext_customer_id:
            sref = getattr(self, "_sessions_ref", None)
            sess_obj = sref() if callable(sref) else None
            control = getattr(sess_obj, "control", None) if sess_obj is not None else None
            eff_tid = self._effective_tenant_id(None)
            if control is not None and hasattr(control, "connection"):
                try:
                    with control.connection() as id_db:
                        m_row = id_db.execute(
                            """SELECT external_customer_id
                               FROM external_customer_mappings
                               WHERE tenant_id = ? AND source_system = ? AND customer_id = ?
                               ORDER BY created_at ASC
                               LIMIT 1""",
                            (eff_tid, ord_source, ord_customer_id),
                        ).fetchone()
                        if m_row is not None and m_row["external_customer_id"]:
                            ext_customer_id = str(m_row["external_customer_id"])
                except Exception:
                    pass

        envelope = {
            "contract": "retailops-integration-v2",
            "event_id": f"evt:vreq:{comp_id}",
            "event_type": "voucher.requested",
            "source_system": "retailops",
            "merchant_id": merchant_id or "MERCHANT-DEFAULT",
            "occurred_at": format_vn_iso(occurred_ts),
            "sequence": 1,
            "data": {
                "request_id": comp_id,
                "external_order_id": ext_order_id,
                "external_customer_id": ext_customer_id or ord_customer_id,
                "voucher_type": str(comp_row["voucher_type"]),
                "value": int(comp_row["value"]),
                "reason": str(comp_row["reason"]),
                "approved_by_role": str(approved_by_role),
            },
        }
        return validate_event_v2(envelope, allow_requests=True)

    def export_voucher_requests(self, *, source_system: str) -> list[dict]:
        """Export repeatable JSONL-ready voucher.requested envelopes for all 'requested' compensations of source_system."""
        from retailops.integration.connectors import validate_source_system_name
        from retailops.integration.contract import validate_event_v2

        clean_source = validate_source_system_name(source_system)
        out: list[dict] = []
        with self.connection() as db:
            rows = db.execute(
                """SELECT dc.*, o.id AS ord_internal_id
                   FROM delivery_compensations dc
                   JOIN orders o ON o.id = dc.order_id
                   WHERE dc.status = 'requested'
                     AND o.source_system = ?
                   ORDER BY COALESCE(dc.decided_at, 0) ASC, dc.compensation_id ASC""",
                (clean_source,),
            ).fetchall()
            for dc in rows:
                comp_id = str(dc["compensation_id"])
                ev_id = f"evt:vreq:{comp_id}"
                ob_row = db.execute(
                    "SELECT payload_json FROM integration_outbox WHERE event_id = ?",
                    (ev_id,),
                ).fetchone()
                if ob_row is not None and ob_row["payload_json"]:
                    parsed = json.loads(str(ob_row["payload_json"]))
                    out.append(validate_event_v2(parsed, allow_requests=True))
                else:
                    ord_row = db.execute(
                        "SELECT * FROM orders WHERE id = ?",
                        (str(dc["order_id"]),),
                    ).fetchone()
                    if ord_row is None:
                        continue
                    occ_ts = float(dc["decided_at"]) if dc["decided_at"] is not None else float(self._now())
                    out.append(
                        self._build_voucher_requested_envelope_in_tx(
                            db,
                            comp_row=dc,
                            ord_row=ord_row,
                            occurred_ts=occ_ts,
                            approved_by_role="manager",
                        )
                    )
        return out

    def read_order_shipment_in_tx(self, db, order_dict: dict, *, now: float | None = None) -> dict | None:
        """Read DB-backed shipment and chronological shipment_events for one order, or None if absent."""
        oid = str(order_dict["id"])
        ship_row = db.execute(
            "SELECT * FROM shipments WHERE order_id = ? ORDER BY updated_at DESC, shipment_id DESC LIMIT 1",
            (oid,),
        ).fetchone()
        if ship_row is None:
            return None
        sd = dict(ship_row)
        evt_rows = db.execute(
            "SELECT * FROM shipment_events WHERE shipment_id = ? "
            "ORDER BY occurred_at ASC, shipment_event_id ASC",
            (sd["shipment_id"],),
        ).fetchall()
        events = []
        latest_evt_eta = None
        latest_fail_reason = None
        for er in evt_rows:
            ed = dict(er)
            if ed.get("estimated_delivery_at") is not None:
                latest_evt_eta = ed["estimated_delivery_at"]
            if ed.get("fail_reason"):
                latest_fail_reason = ed["fail_reason"]
            loc_parts = [p for p in (ed.get("hub_name"), ed.get("district"), ed.get("province")) if p]
            events.append(
                {
                    "occurred_at": format_vn_iso(ed.get("occurred_at")),
                    "status": ed.get("status"),
                    "carrier_status_raw": ed.get("carrier_status_raw"),
                    "status_text": SHIPMENT_STATUS_TEXT_VI.get(ed.get("status"), ed.get("status")),
                    "hub_name": ed.get("hub_name"),
                    "district": ed.get("district"),
                    "province": ed.get("province"),
                    "location": ", ".join(loc_parts) if loc_parts else None,
                    "description": mask_shipper_phone_text(ed.get("description")),
                    "fail_reason": mask_shipper_phone_text(ed.get("fail_reason")),
                    "estimated_delivery_at": format_vn_iso(ed.get("estimated_delivery_at")),
                }
            )
        effective_eta = sd.get("estimated_delivery_at") if sd.get("estimated_delivery_at") is not None else latest_evt_eta
        effective_delivered_at = (
            sd.get("delivered_at")
            if sd.get("delivered_at") is not None
            else (order_dict.get("delivered_at") if sd.get("status") == "delivered" else None)
        )
        return {
            "shipment_id": sd["shipment_id"],
            "external_shipment_id": sd["external_shipment_id"],
            "source_system": sd["source_system"],
            "carrier": sd["carrier"],
            "tracking_code": sd["tracking_code"],
            "status": sd["status"],
            "carrier_status_raw": sd["carrier_status_raw"],
            "status_text": SHIPMENT_STATUS_TEXT_VI.get(sd["status"], sd["status"]),
            "current_area": sd.get("current_area"),
            "estimated_delivery_at": format_vn_iso(effective_eta),
            "delivered_at": format_vn_iso(effective_delivered_at),
            "delivery_attempts": int(sd.get("delivery_attempts") or 0),
            "fail_reason": mask_shipper_phone_text(latest_fail_reason),
            "shipper_name": mask_shipper_phone_text(sd.get("shipper_name")),
            "shipper_phone_masked": mask_shipper_phone_text(sd.get("shipper_phone_masked")),
            "events": events,
        }

    def _order_eligibility_in_tx(self, db, order_dict: dict, *, now: float | None = None) -> dict:
        now_ts = self._now() if now is None else float(now)
        product_dict = None
        pid = order_dict.get("product_id")
        if isinstance(pid, str) and pid.strip():
            prod_row = db.execute("SELECT * FROM products WHERE id = ?", (pid.strip(),)).fetchone()
            if prod_row is not None:
                product_dict = self._row_to_product(prod_row)
        oid = str(order_dict["id"])
        ship_row = db.execute(
            "SELECT * FROM shipments WHERE order_id = ? ORDER BY updated_at DESC, shipment_id DESC LIMIT 1",
            (oid,),
        ).fetchone()
        ship_dict = dict(ship_row) if ship_row is not None else None
        latest_evt_eta = None
        if ship_dict is not None and ship_dict.get("estimated_delivery_at") is None:
            eta_row = db.execute(
                "SELECT estimated_delivery_at FROM shipment_events "
                "WHERE shipment_id = ? AND estimated_delivery_at IS NOT NULL "
                "ORDER BY occurred_at DESC, shipment_event_id DESC LIMIT 1",
                (ship_dict["shipment_id"],),
            ).fetchone()
            if eta_row is not None:
                latest_evt_eta = eta_row["estimated_delivery_at"]
        return compute_order_eligibility(
            order_dict,
            product=product_dict,
            shipment=ship_dict,
            latest_event_estimated_delivery_at=latest_evt_eta,
            as_of=now_ts,
        )

    def order_eligibility(
        self,
        order_or_id,
        *,
        customer_id: str | None = None,
        now: float | None = None,
        db=None,
    ) -> dict:
        def _run(conn):
            if isinstance(order_or_id, dict):
                ord_dict = order_or_id
            elif customer_id is not None:
                ord_dict = self.owned(conn, customer_id, str(order_or_id))
            else:
                row = conn.execute("SELECT * FROM orders WHERE id = ?", (str(order_or_id),)).fetchone()
                require(row is not None, 404, "order_not_found", "Không tìm thấy đơn hàng.")
                ord_dict = dict(row)
            return self._order_eligibility_in_tx(conn, ord_dict, now=now)

        if db is not None:
            return _run(db)
        with self.connection() as conn:
            return _run(conn)

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
            canonical_oid = None
            if oid is not None:
                ord_row = self.owned(db, customer, oid)
                canonical_oid = ord_row["id"]
            updated = db.execute('''UPDATE conversations SET order_id=?,product_id=?,revision=revision+1,expires_at=?
                WHERE id=? AND customer_id=? AND revision=? AND expires_at>?''',
                (canonical_oid, pid, now + self.CONVERSATION_TTL, snapshot['id'], customer, snapshot['revision'], now)).rowcount
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
                        if (
                            att.get('type') == 'image'
                            and not att.get('removed')
                            and (att.get('evidence_id') or att.get('data'))
                            and not preserved_recent_image
                        ):
                            ref_entry = {
                                k: att[k]
                                for k in ('evidence_id', 'type', 'mime_type', 'name', 'sha256')
                                if k in att and att[k] is not None
                            }
                            user_entry['attachment'] = ref_entry
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
            # The newest turn is always kept, however large, so one big tool result can never empty the history;
            # older turns stop at 9,000 characters / 32 messages (the 16,384-token window of W3.2).
            if turns and (characters + size > 9000 or count + len(clean_turn) > 32):
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
                if 'attachment' in m:
                    prev['attachment'] = m['attachment']
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

        self.purge_expired_case_assist_turns(now=now_ts)

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
                       he.created_at, k.updated_at, c.name AS customer_name, conv.order_id,
                       ord.external_order_id AS external_order_id
                FROM cases k
                JOIN handoff_episodes he
                  ON he.case_id = k.case_id AND he.status = 'pending'
                JOIN customers c ON k.customer_id = c.id
                LEFT JOIN conversations conv ON k.conversation_id = conv.id
                LEFT JOIN orders ord ON conv.order_id = ord.id AND ord.customer_id = k.customer_id
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
                SELECT c.id, c.customer_id, c.order_id, ord.external_order_id AS external_order_id,
                       c.product_id, c.provider_id, c.expires_at,
                       SUM(CASE WHEN t.id IS NOT NULL
                                 AND t.request_id NOT LIKE ?
                                 AND t.request_id NOT LIKE ?
                                 AND t.request_id NOT LIKE ?
                           THEN 1 ELSE 0 END) as turns_count,
                       COUNT(t.id) as raw_turns_count,
                       MAX(t.created_at) as last_activity,
                       MIN(t.created_at) as first_activity
                FROM conversations c
                LEFT JOIN orders ord ON c.order_id = ord.id AND ord.customer_id = c.customer_id
                LEFT JOIN agent_turns t ON c.id = t.conversation_id
                WHERE c.customer_id = ? AND c.expires_at > ?
                GROUP BY c.id, c.customer_id, c.order_id, ord.external_order_id, c.product_id, c.provider_id, c.expires_at
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
                          c.name AS customer_name, conv.order_id,
                          ord.external_order_id AS external_order_id
                   FROM cases k
                   JOIN handoff_episodes he
                     ON he.case_id = k.case_id AND he.status = 'pending'
                    JOIN customers c ON k.customer_id = c.id
                   LEFT JOIN conversations conv ON k.conversation_id = conv.id
                   LEFT JOIN orders ord ON conv.order_id = ord.id AND ord.customer_id = k.customer_id
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
                          c.name AS customer_name, conv.order_id,
                          ord.external_order_id AS external_order_id
                   FROM cases k
                   LEFT JOIN handoff_episodes he
                     ON he.case_id = k.case_id AND he.status = 'pending'
                   JOIN customers c ON k.customer_id = c.id
                   LEFT JOIN conversations conv ON k.conversation_id = conv.id
                   LEFT JOIN orders ord ON conv.order_id = ord.id AND ord.customer_id = k.customer_id
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
                          c.name AS customer_name, conv.order_id,
                          ord.external_order_id AS external_order_id
                   FROM cases k
                   JOIN customers c ON k.customer_id = c.id
                   JOIN conversations conv ON k.conversation_id = conv.id
                   LEFT JOIN orders ord ON conv.order_id = ord.id AND ord.customer_id = k.customer_id
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
                SELECT conv.*, c.name as customer_name, ord.external_order_id as external_order_id
                FROM conversations conv
                JOIN customers c ON conv.customer_id = c.id
                LEFT JOIN orders ord ON conv.order_id = ord.id AND ord.customer_id = conv.customer_id
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

    def transfer_case(
        self,
        case_id: str,
        *,
        to_principal_id: str,
        target_member: dict | None,
        expected_version: int,
        actor: dict | None = None,
    ) -> dict:
        """Atomically transfer an `in_progress` case directly to another active Staff/Manager in the same store (W5-D2)."""
        require(isinstance(case_id, str) and bool(case_id.strip()), 400, 'invalid_case_id', 'Mã ca hỗ trợ không hợp lệ.')
        require(
            isinstance(to_principal_id, str) and bool(to_principal_id.strip()),
            400,
            'invalid_transfer_target',
            'Thiếu mã nhân sự nhận ca.',
        )
        require(
            type(expected_version) is int and expected_version >= 1,
            400,
            'invalid_version',
            'Phiên bản ca hỗ trợ không hợp lệ.',
        )
        clean_to = to_principal_id.strip()
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
        caller_id = (actor_meta.get('principal_id') if actor_meta else None) or ''
        caller_role = (actor_meta.get('role') if actor_meta else None) or 'staff'
        now = self._now()

        with self.connection(write=True) as db:
            case_row = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
            require(case_row is not None, 404, 'case_not_found', 'Không tìm thấy ca hỗ trợ.')
            if case_row['status'] == 'resolved':
                require(False, 409, 'case_already_resolved', 'Ca hỗ trợ đã đóng; không thể chuyển ca.')
            require(
                case_row['status'] == 'in_progress' and case_row['holder'] is not None,
                409,
                'case_not_claimed',
                'Chỉ chuyển được ca đang có người giữ (in_progress).',
            )
            require(
                case_row['holder'] == caller_id or caller_role == 'manager',
                403,
                'case_held_by_other',
                'Chỉ nhân viên đang giữ ca hoặc Quản lý mới được chuyển ca.',
            )
            require(
                int(case_row['version']) == int(expected_version),
                409,
                'case_version_conflict',
                'Phiên bản ca hỗ trợ đã thay đổi; vui lòng tải lại.',
            )
            require(
                clean_to != case_row['holder'],
                400,
                'invalid_transfer_target',
                'Người nhận ca mới phải khác người đang giữ ca hiện tại.',
            )
            require(
                isinstance(target_member, dict)
                and target_member.get('principal_id') == clean_to
                and target_member.get('role') in ('staff', 'manager'),
                400,
                'invalid_transfer_target',
                'Người nhận phải là Nhân viên hoặc Quản lý đang hoạt động trong cùng cửa hàng.',
            )
            target_name = str(target_member.get('display_name') or '').strip()
            if '@' in target_name:
                target_name = target_name.split('@', 1)[0].strip()
            if not target_name:
                target_name = 'Quản lý cửa hàng' if target_member.get('role') == 'manager' else 'Nhân viên hỗ trợ'

            prev_holder = case_row['holder']
            prev_holder_name = case_row['holder_name']
            new_ver = int(case_row['version']) + 1
            won = db.execute(
                """UPDATE cases
                   SET holder = ?,
                       holder_name = ?,
                       version = ?,
                       updated_at = ?
                   WHERE case_id = ? AND version = ? AND status = 'in_progress' AND holder = ?""",
                (clean_to, target_name, new_ver, now, case_id, int(case_row['version']), prev_holder),
            ).rowcount
            require(won == 1, 409, 'case_version_conflict', 'Trạng thái ca hỗ trợ vừa thay đổi; hãy tải lại.')

            conv = db.execute('SELECT order_id FROM conversations WHERE id = ?', (case_row['conversation_id'],)).fetchone()
            log_kwargs = {
                'case_id': case_id,
                'from_principal_id': prev_holder,
                'from_holder_name': prev_holder_name,
                'to_principal_id': clean_to,
                'to_holder_name': target_name,
                'version': new_ver,
            }
            if actor_meta is not None:
                log_kwargs['actor'] = actor_meta
            self.log(db, case_row['customer_id'], 'case_transferred', conv['order_id'] if conv else None, **log_kwargs)

            notice_turn_id, notice_message = self._append_case_system_notice_in_tx(
                db,
                conversation_id=case_row['conversation_id'],
                customer_id=case_row['customer_id'],
                case_id=case_id,
                request_id=f'sys-notice-transfer-{case_id}-v{new_ver}',
                milestone='case_transferred',
                notice_text=f'Ca của bạn đã được chuyển cho {target_name}',
                staff_name=target_name,
                now=now,
            )
            updated = db.execute('SELECT * FROM cases WHERE case_id = ?', (case_id,)).fetchone()
            silent_secs = self._compute_customer_silent_seconds_in_tx(db, updated, now=now)

        return {
            'status': 'ok',
            'transferred': True,
            'case_id': case_id,
            'case': self._case_public_dict(updated, customer_silent_seconds=silent_secs),
            'from_principal_id': prev_holder,
            'to_principal_id': clean_to,
            'to_holder_name': target_name,
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

    def customer_message(self, customer_id, cid, message, attachment=None):
        require(isinstance(message, str) and message.strip(), 400, 'invalid_message', 'Tin nhắn không được để trống.')
        sanitized_att = None
        if attachment is not None:
            sanitized_att = self.store_chat_attachment(customer_id, cid, attachment)
        clean_comment = message[:200]
        if contains_canary_or_secret(clean_comment):
            _, clean_comment = sanitize_structured_payload(clean_comment, preserve_reasoning=False)
        now = self._now()
        req_id = f"cust-{uuid.uuid4().hex[:12]}"
        with self.connection(write=True) as db:
            conv, _ = self._prepare_customer_activity_in_tx(
                db, customer_id, cid, now, forbidden_on_mismatch=True
            )
            user_turn_msg = {"role": "user", "content": message}
            if sanitized_att is not None:
                user_turn_msg["attachment"] = sanitized_att
            turn_messages = [user_turn_msg]
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

            conv = (
                db.execute('SELECT customer_id, order_id, expires_at FROM conversations WHERE id=?', (cid,)).fetchone()
                if cid
                else None
            )
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

            if case_row['status'] == 'resolved':
                if actor_meta is not None and actor_meta.get('role') not in ('staff', 'manager'):
                    require(False, 403, 'permission_denied', 'Tài khoản này không có quyền thực hiện thao tác.')
                latest_ep = db.execute(
                    'SELECT * FROM handoff_episodes WHERE case_id = ? ORDER BY created_at DESC LIMIT 1',
                    (case_row['case_id'],),
                ).fetchone()
                require(
                    latest_ep is not None,
                    409,
                    'case_not_escalated',
                    'Cuộc trò chuyện không có phiên hỗ trợ đang mở để hoàn tất.',
                )
                within_retention = (
                    conv is not None
                    and float(conv['expires_at']) > now
                    and (case_row['resolved_at'] is None or (now - float(case_row['resolved_at'])) <= self.CONVERSATION_TTL)
                )
                require(
                    within_retention,
                    403,
                    'case_retention_expired',
                    'Ca hỗ trợ đã đóng và quá thời hạn lưu trữ.',
                )
                if handoff_id is not None:
                    require(
                        latest_ep['handoff_id'] == handoff_id,
                        409,
                        'stale_handoff_episode',
                        'Phiên chuyển tiếp đã cũ hoặc không khớp với ca đã đóng.',
                    )
                out = {
                    'status': 'ok',
                    'resolved': True,
                    'already_resolved': True,
                    'case_id': case_row['case_id'],
                    'handoff_id': latest_ep['handoff_id'],
                    'leases_released': 0,
                    'case': self._case_public_dict(case_row),
                    'staff_name': staff_name,
                    'notice_turn_id': None,
                    'notice_message': None,
                }
                if actor_meta is not None:
                    out['actor_role'] = actor_meta['role']
                    out['actor_principal_id'] = actor_meta['principal_id']
                return out

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
            'already_resolved': False,
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

    def _resolve_customer_ref_key(self) -> tuple[str | None, str | None, str | None]:
        explicit = getattr(self, "customer_ref_key", None)
        return resolve_customer_ref_key(explicit_key=explicit)

    @staticmethod
    def _opaque_customer_ref(tenant_id: str, customer_id: str, secret_key: str) -> str:
        return compute_customer_ref(tenant_id, customer_id, secret_key)

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
        ref_key, key_err, key_msg = self._resolve_customer_ref_key()
        if not ref_key:
            return {
                "skipped": True,
                "error": key_err or "customer_ref_key_missing",
                "message": key_msg,
                "event_type": event_type,
            }
        norm_actor = self._normalize_actor(actor, "system", "system")
        actor_principal = norm_actor["principal_id"]
        if norm_actor["role"] == "customer":
            actor_principal = self._opaque_customer_ref(resolved_tid, str(customer_id or actor_principal), ref_key)
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
            envelope["customer_ref"] = self._opaque_customer_ref(resolved_tid, str(customer_id), ref_key)
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

    def _has_enabled_connector_in_tx(self, db, source_system: str | None) -> bool:
        if not source_system:
            return False
        row = db.execute(
            "SELECT 1 FROM integration_connectors WHERE source_system = ? AND enabled = 1 LIMIT 1",
            (str(source_system),),
        ).fetchone()
        return row is not None

    def list_case_unlinked_refunds(self, case_id: str) -> list[dict]:
        """Return unlinked provider refunds (`refunds.request_id IS NULL`) on orders of a case's customer (W6.1b-D10)."""
        require(
            isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)),
            400,
            "invalid_case_id",
            "Mã ca hỗ trợ không hợp lệ.",
        )
        with self.connection() as db:
            case_row = db.execute("SELECT customer_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            require(case_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
            rows = db.execute(
                """SELECT r.refund_id, r.order_id, r.provider, r.provider_refund_ref,
                          r.amount, r.channel, r.status, r.provider_status_raw,
                          r.initiated_at, r.completed_at, r.failure_reason,
                          o.external_order_id, o.source_system,
                          (SELECT COUNT(*) FROM order_action_requests oar
                           WHERE oar.order_id = r.order_id AND oar.refund_status = 'pending') AS waiting_request_count
                   FROM refunds r
                   JOIN orders o ON r.order_id = o.id
                   WHERE o.customer_id = ? AND r.request_id IS NULL
                   ORDER BY r.initiated_at DESC, r.refund_id DESC""",
                (case_row["customer_id"],),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            oid = str(r["order_id"])
            ext_id = str(r["external_order_id"] or oid)
            waiting_cnt = int(r["waiting_request_count"] or 0)
            dual_lbl = f"{ext_id} ({oid})" if ext_id != oid else oid
            if waiting_cnt > 1:
                warn_msg = (
                    f"Cảnh báo hoàn tiền: Đơn {dual_lbl} có giao dịch hoàn tiền {r['provider_refund_ref']} "
                    f"({r['status']}) chưa nối được yêu cầu vì có {waiting_cnt} yêu cầu đang cùng chờ hoàn tiền."
                )
            else:
                warn_msg = (
                    f"Cảnh báo hoàn tiền: Đơn {dual_lbl} có giao dịch hoàn tiền {r['provider_refund_ref']} "
                    f"({r['status']}) từ cổng thanh toán chưa xác định được yêu cầu hủy/trả/đổi tương ứng."
                )
            out.append(
                {
                    "refund_id": r["refund_id"],
                    "order_id": oid,
                    "internal_order_id": oid,
                    "external_order_id": ext_id,
                    "source_system": r["source_system"],
                    "provider": r["provider"],
                    "provider_refund_ref": r["provider_refund_ref"],
                    "amount": int(r["amount"]),
                    "channel": r["channel"],
                    "status": r["status"],
                    "provider_status_raw": r["provider_status_raw"],
                    "initiated_at": format_vn_iso(r["initiated_at"]),
                    "completed_at": format_vn_iso(r["completed_at"]),
                    "failure_reason": r["failure_reason"],
                    "waiting_request_count": waiting_cnt,
                    "warning": warn_msg,
                }
            )
        return out

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
            """SELECT evidence_id, request_id, case_id, filename, uploaded_by_role, mime_type,
                      byte_size, width, height, page_count, sha256, scan_status, scan_engine,
                      scanned_at, created_at, file_purged_at
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
        exchange_view = {}
        if d.get("type") == "exchange":
            exchange_view = {
                "current_variant_label": order_dict.get("variant") if order_dict is not None else None,
                "target_stock_status": None,
                "target_stock": None,
            }
            if d.get("target_variant_id"):
                target_row = db.execute(
                    "SELECT stock FROM product_variants WHERE id = ?", (d["target_variant_id"],)
                ).fetchone()
                stock = target_row["stock"] if target_row is not None else None
                exchange_view["target_stock_status"] = self._stock_status(stock)
                exchange_view["target_stock"] = int(stock) if stock is not None else None
        order_eligibility = (
            self._order_eligibility_in_tx(db, order_dict, now=now_ts)
            if order_dict is not None
            else None
        )
        src_sys = order_dict.get("source_system") if order_dict is not None else None
        return {
            **d,
            **exchange_view,
            "external_order_id": order_dict.get("external_order_id") if order_dict is not None else d.get("order_id"),
            "source_system": src_sys,
            "refund_managed_by_provider": self._has_enabled_connector_in_tx(db, src_sys),
            "expected_order_version": int(d["expected_order_version"]),
            "version": int(d["version"]),
            "reason_label": reason_catalog().label(d["reason_code"]),
            "order": order_dict,
            "order_eligibility": order_eligibility,
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

    # ---- general exchange (W3.2-D1, W3.2-D5) ---------------------------------------------------------
    @staticmethod
    def _stock_status(stock) -> str:
        """Stock is for display only and never blocks a request: in_stock / out_of_stock / unknown."""
        if stock is None:
            return "unknown"
        return "in_stock" if int(stock) > 0 else "out_of_stock"

    @staticmethod
    def _fold_variant(text) -> str | None:
        """Lower-case, accent-free, single-spaced form used to compare variant attributes."""
        return fold_attribute(text)

    @classmethod
    def _variant_attributes(cls, variant_text) -> tuple[str | None, str | None]:
        """(size, color) of an order's free-text variant, e.g. "Trắng · Size M · Số lượng 1" -> ("m", "trang")."""
        if not variant_text:
            return None, None
        size, color = _parse_variant_string(variant_text)
        return cls._fold_variant(size), cls._fold_variant(color)

    def _order_product_in_tx(self, db, order: dict) -> dict | None:
        """The catalog product an order belongs to: its product_id, else a unique match on the product name."""
        if order.get("product_id"):
            row = db.execute("SELECT id, name FROM products WHERE id = ?", (order["product_id"],)).fetchone()
            if row is not None:
                return {"id": row["id"], "name": row["name"]}
        rows = db.execute("SELECT id, name FROM products WHERE name = ? LIMIT 2", (order.get("name"),)).fetchall()
        return {"id": rows[0]["id"], "name": rows[0]["name"]} if len(rows) == 1 else None

    def _exchange_variants_in_tx(self, db, order: dict) -> dict:
        """Variants of the order's product with stock status and which one the order holds.

        The current variant comes from the order's structured items when it has them; otherwise from
        comparing the normalized size/color in its variant text. Only attributes the order states are
        compared, so an order that says just "M" treats every size-M variant as the current one.
        """
        product = self._order_product_in_tx(db, order)
        base = {
            "order_id": order["id"],
            "product_id": product["id"] if product else None,
            "product_name": product["name"] if product else None,
            "current_variant_label": order.get("variant"),
            "variants": [],
        }
        if product is None:
            return base
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT id, variant_name, size, color, stock FROM product_variants WHERE product_id = ? ORDER BY id",
                (product["id"],),
            ).fetchall()
        ]
        known = {r["id"] for r in rows}
        item_ids = {
            r["variant_id"]
            for r in db.execute(
                "SELECT variant_id FROM order_items WHERE order_id = ? AND variant_id IS NOT NULL", (order["id"],)
            ).fetchall()
        } & known
        want_size, want_color = self._variant_attributes(order.get("variant"))
        for r in rows:
            if item_ids:
                is_current = r["id"] in item_ids
            elif want_size is None and want_color is None:
                is_current = False
            else:
                is_current = (
                    (want_size is None or want_size == self._fold_variant(r["size"]))
                    and (want_color is None or want_color == self._fold_variant(r["color"]))
                )
            base["variants"].append(
                {
                    "id": r["id"],
                    "label": r["variant_name"],
                    "size": r["size"],
                    "color": r["color"],
                    "stock": int(r["stock"]) if r["stock"] is not None else None,
                    "stock_status": self._stock_status(r["stock"]),
                    "is_current": is_current,
                }
            )
        return base

    @staticmethod
    def _public_exchange_options(options: dict, *, staff: bool) -> dict:
        out = dict(options)
        out["variants"] = [
            {k: v for k, v in variant.items() if staff or k != "stock"} for variant in options["variants"]
        ]
        return out

    def product_variant_availability(self, product_id: str) -> list[dict]:
        """Every variant of a catalog product with its stock status (never a count), for customer answers."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT variant_name, size, color, stock FROM product_variants WHERE product_id = ? ORDER BY id",
                (product_id,),
            ).fetchall()
        return [
            {"label": r["variant_name"], "size": r["size"], "color": r["color"],
             "stock_status": self._stock_status(r["stock"])}
            for r in rows
        ]

    def exchange_options(self, customer_id: str, order_id: str) -> dict:
        """Variants a customer could swap their own order to, with stock status (customers see no counts)."""
        with self.connection() as db:
            order = self.owned(db, customer_id, order_id)
            options = self._exchange_variants_in_tx(db, order)
        return self._public_exchange_options(options, staff=False)

    def case_exchange_options(self, case_id: str, order_id: str) -> dict:
        """Same list for Staff/Manager, limited to orders of the case's customer; includes stock counts."""
        require(
            isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)),
            400,
            "invalid_case_id",
            "Mã ca hỗ trợ không hợp lệ.",
        )
        with self.connection() as db:
            case_row = db.execute("SELECT customer_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            require(case_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
            order = self.owned(db, case_row["customer_id"], order_id)
            options = self._exchange_variants_in_tx(db, order)
        return self._public_exchange_options(options, staff=True)

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
        target_variant_id: str | None = None,
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
        require(
            raised_by_role in ("customer", "staff", "manager"),
            400,
            "invalid_role",
            "Vai trò tạo yêu cầu không hợp lệ.",
        )
        if raised_by_role == "customer":
            require(
                delivery_failure_attempts is None,
                403,
                "permission_denied",
                "Khách hàng không được tạo yêu cầu hủy do giao thất bại.",
            )
        # One shared catalog decides: the code exists, applies to this request type, is allowed for
        # this role (delivery_failed is staff-only) and carries a description when it requires one.
        clean_reason_text = self._sanitize_reason_text(reason_text)
        reason_entry = reason_catalog().validate(
            reason_code.strip(), action_type, role=raised_by_role, text=clean_reason_text
        )
        clean_reason_code = reason_entry["code"]
        if clean_reason_text is None:
            clean_reason_text = reason_entry["label"]
        if action_type == "exchange":
            require(
                exchange_kind in EXCHANGE_KINDS,
                400,
                "invalid_exchange_kind",
                "Yêu cầu đổi hàng phải chọn đổi sang biến thể khác (other_variant) hoặc đổi cùng biến thể (same_variant).",
            )
            if exchange_kind == "other_variant":
                require(
                    isinstance(target_variant_id, str) and bool(target_variant_id.strip()),
                    400,
                    "target_variant_required",
                    "Đổi sang biến thể khác bắt buộc chọn biến thể đích.",
                )
                target_variant_id = target_variant_id.strip()
                require(
                    len(target_variant_id) <= 128 and target_variant_id.isprintable(),
                    400,
                    "invalid_target_variant",
                    "Mã biến thể đích không hợp lệ.",
                )
            else:
                require(
                    target_variant_id is None,
                    400,
                    "target_variant_not_allowed",
                    "Đổi cùng biến thể không có biến thể đích.",
                )
        else:
            require(
                exchange_kind is None,
                400,
                "invalid_exchange_kind",
                "Chỉ yêu cầu đổi hàng mới có trường exchange_kind.",
            )
            require(
                target_variant_id is None,
                400,
                "target_variant_not_allowed",
                "Chỉ yêu cầu đổi sang biến thể khác mới có biến thể đích.",
            )

        now_ts = self._now() if now is None else float(now)
        order = self.owned(db, customer_id, order_id)
        order_id = str(order["id"])
        require(
            int(order["version"]) == expected_order_version,
            409,
            "stale_order",
            "Đơn đã thay đổi; vui lòng tải lại thông tin trước khi gửi yêu cầu.",
        )
        if action_type == "cancel":
            if order["status"] == "shipping":
                raise ApiError(
                    409,
                    "not_cancellable",
                    "Đơn đang được vận chuyển (shipping) nên không thể mở yêu cầu hủy tự phục vụ; vui lòng liên hệ nhân viên CSKH hỗ trợ.",
                )
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

        target_variant_label = None
        if action_type == "exchange" and exchange_kind == "other_variant":
            # The target must be a variant of this order's own product and differ from the one the order
            # holds. Stock is deliberately not checked: staff decide when they review (W3.2-D5).
            options = self._exchange_variants_in_tx(db, order)
            require(
                options["product_id"] is not None,
                409,
                "order_product_unknown",
                "Đơn chưa liên kết với sản phẩm trong danh mục nên chưa chọn được biến thể đích.",
            )
            target = next((v for v in options["variants"] if v["id"] == target_variant_id), None)
            require(
                target is not None,
                400,
                "invalid_target_variant",
                "Biến thể đích không thuộc sản phẩm của đơn hàng.",
            )
            require(
                not target["is_current"],
                400,
                "target_is_current_variant",
                "Biến thể đích trùng với biến thể hiện tại của đơn; hãy chọn biến thể khác hoặc đổi cùng biến thể.",
            )
            target_variant_label = str(target["label"])[:200]

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
        handoff_comment = f"Yêu cầu {type_vi} {order_id}: {clean_reason_text or clean_reason_code}"
        if target_variant_label:
            handoff_comment += f" → {target_variant_label}"
        handoff_comment = handoff_comment[:300]
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
                       type, exchange_kind, target_variant_id, target_variant_label, status, inspection_outcome,
                       refund_status, refund_decision, reason_code, reason_text,
                       raised_by_role, delivery_failure_attempts, expected_order_version,
                       version, created_at, updated_at, reviewed_at, received_at,
                       inspected_at, completed_at, closed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'requested', NULL, 'not_applicable', NULL,
                             ?, ?, ?, ?, ?, 1, ?, ?, NULL, NULL, NULL, NULL, NULL)""",
                (
                    req_id,
                    order_id,
                    customer_id,
                    resolved_case_id,
                    resolved_cid,
                    action_type,
                    exchange_kind,
                    target_variant_id,
                    target_variant_label,
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
        if target_variant_id is not None:
            log_payload["target_variant_id"] = target_variant_id
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
        if target_variant_id is not None:
            outbox_extra["target_variant_id"] = target_variant_id
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
            "target_variant_id",
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
                target_variant_id=body.get("target_variant_id"),
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
            "target_variant_id",
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
                target_variant_id=body.get("target_variant_id"),
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
        # The compatibility facade takes the same customer-selectable cancel reasons as the new route;
        # a reason that needs a description cannot be sent through this text-less endpoint.
        entry = reason_catalog().get(reason)
        require(isinstance(oid, str) and type(version) is int and entry is not None
                and "cancel" in entry["applies_to"] and not entry["staff_only"] and not entry["requires_text"],
                400, "invalid_proposal", "Chọn mã đơn và một lý do được hỗ trợ.")
        reason = entry["code"]
        now_ts = self._now()
        with self.connection(write=True) as db:
            order = self.owned(db, customer, oid)
            if order["status"] == "shipping":
                raise ApiError(
                    409,
                    "not_cancellable",
                    "Đơn đang được vận chuyển (shipping) nên không thể mở yêu cầu hủy tự phục vụ; vui lòng liên hệ nhân viên CSKH hỗ trợ.",
                )
            require(order["status"] == "pending", 409, "not_cancellable", "Đơn không còn ở trạng thái cho phép hủy.")
            require(order["version"] == version, 409, "stale_order", "Đơn đã thay đổi. Vui lòng tải lại thông tin.")
            pid, expires = str(uuid.uuid4()), now_ts + 600
            canonical_oid = str(order["id"])
            db.execute("INSERT INTO proposals(id,customer_id,order_id,order_version,reason,expires_at) VALUES (?,?,?,?,?,?)",
                       (pid, customer, canonical_oid, version, reason, expires))
            self.log(db, customer, "cancellation_proposed", canonical_oid, proposal_id=pid, reason=reason)
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
                reason_text=reason_catalog().label(p["reason"]),
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
        elif exchange_kind == "other_variant":
            type_label = "đổi sang biến thể khác"
        elif exchange_kind == "same_variant":
            type_label = "đổi cùng biến thể"
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
                sync_order_recipient_retention_in_tx(
                    db,
                    order_id=str(req_row["order_id"]),
                    status="cancelled",
                    transition_ts=float(now_ts),
                )
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
            ord_row = db.execute(
                "SELECT source_system FROM orders WHERE id = ?",
                (req_row["order_id"],),
            ).fetchone()
            if ord_row is not None and self._has_enabled_connector_in_tx(db, ord_row["source_system"]):
                raise ApiError(
                    409,
                    "refund_managed_by_provider",
                    "Đơn hàng thuộc nguồn tích hợp có connector; kết quả hoàn tiền do cổng thanh toán cập nhật tự động.",
                )
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

    def list_manager_order_actions(
        self,
        *,
        status_group: str = "all",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Paginated store-wide `order_action_requests` queue for Manager Console without customer PII (W5-D1)."""
        group = str(status_group or "all").strip().lower()
        if group == "done":
            group = "completed"
        require(
            group in ("needs_manager", "in_progress", "completed", "all"),
            400,
            "invalid_status_group",
            "Nhóm lọc yêu cầu đơn hàng không hợp lệ.",
        )
        require(type(limit) is int and 1 <= limit <= 50, 400, "invalid_limit", "Giới hạn phân trang phải từ 1 đến 50.")
        require(type(offset) is int and offset >= 0, 400, "invalid_offset", "Vị trí phân trang không hợp lệ.")

        where_map = {
            "needs_manager": "WHERE r.refund_status = 'pending' AND r.refund_decision IS NULL",
            "in_progress": "WHERE (r.closed_at IS NULL OR r.refund_status = 'pending') AND NOT (r.refund_status = 'pending' AND r.refund_decision IS NULL)",
            "completed": "WHERE r.closed_at IS NOT NULL AND r.refund_status <> 'pending'",
            "all": "",
        }
        where_sql = where_map[group]

        with self.connection() as db:
            cnt_all = int(db.execute("SELECT COUNT(*) AS cnt FROM order_action_requests").fetchone()["cnt"])
            cnt_needs = int(
                db.execute(
                    "SELECT COUNT(*) AS cnt FROM order_action_requests WHERE refund_status = 'pending' AND refund_decision IS NULL"
                ).fetchone()["cnt"]
            )
            cnt_in_progress = int(
                db.execute(
                    """SELECT COUNT(*) AS cnt FROM order_action_requests
                       WHERE (closed_at IS NULL OR refund_status = 'pending')
                         AND NOT (refund_status = 'pending' AND refund_decision IS NULL)"""
                ).fetchone()["cnt"]
            )
            cnt_completed = int(
                db.execute(
                    "SELECT COUNT(*) AS cnt FROM order_action_requests WHERE closed_at IS NOT NULL AND refund_status <> 'pending'"
                ).fetchone()["cnt"]
            )
            totals_by_group = {
                "needs_manager": cnt_needs,
                "in_progress": cnt_in_progress,
                "completed": cnt_completed,
                "all": cnt_all,
            }
            total_matching = totals_by_group[group]

            rows = db.execute(
                f"""SELECT r.request_id, r.order_id, r.case_id, r.type, r.exchange_kind,
                           r.status, r.refund_status, r.refund_decision,
                           r.created_at, r.updated_at, r.closed_at,
                           c.name AS customer_name,
                           o.external_order_id AS external_order_id,
                           o.source_system AS source_system
                    FROM order_action_requests r
                    LEFT JOIN customers c ON r.customer_id = c.id
                    LEFT JOIN orders o ON r.order_id = o.id
                    {where_sql}
                    ORDER BY r.created_at DESC, r.request_id DESC
                    LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

        items = []
        for r in rows:
            raw_cname = str(r["customer_name"] or "").strip()
            if "@" in raw_cname:
                raw_cname = raw_cname.split("@", 1)[0].strip()
            if " - " in raw_cname:
                raw_cname = raw_cname.split(" - ", 1)[0].strip()
            raw_cname = re.sub(r"(?:\+?84|0)\d[\d\s.\-]{7,12}\d", "", raw_cname).strip(" -|,;·")
            cname = raw_cname or "Khách hàng"
            needs_mgr = bool(r["refund_status"] == "pending" and r["refund_decision"] is None)
            if needs_mgr:
                item_group = "needs_manager"
            elif r["closed_at"] is None or r["refund_status"] == "pending":
                item_group = "in_progress"
            else:
                item_group = "completed"
            items.append({
                "request_id": r["request_id"],
                "order_id": r["order_id"],
                "external_order_id": r["external_order_id"] or r["order_id"],
                "source_system": r["source_system"],
                "case_id": r["case_id"],
                "customer_display_name": cname,
                "customer_name": cname,
                "type": r["type"],
                "exchange_kind": r["exchange_kind"],
                "status": r["status"],
                "refund_status": r["refund_status"],
                "refund_decision": r["refund_decision"],
                "status_group": item_group,
                "needs_manager": needs_mgr,
                "created_at": float(r["created_at"]),
                "updated_at": float(r["updated_at"]),
                "closed_at": float(r["closed_at"]) if r["closed_at"] is not None else None,
            })

        return {
            "items": items,
            "order_actions": items,
            "status_group": group,
            "total": total_matching,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(items)) < total_matching,
            "counts": totals_by_group,
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
            sync_order_recipient_retention_in_tx(
                db,
                order_id=oid,
                status=new_status,
                transition_ts=float(now_ts),
                delivered_at=(
                    float(updated_ord["delivered_at"])
                    if updated_ord["delivered_at"] is not None
                    else None
                ),
            )
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

    def _active_malware_scanner(self):
        return getattr(self, "malware_scanner", None)

    def upload_order_action_evidence(
        self,
        request_id: str,
        raw_bytes: bytes,
        *,
        customer_id: str | None = None,
        actor: dict | None = None,
        filename: str | None = None,
    ) -> dict:
        require(
            isinstance(request_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id)),
            400,
            "invalid_request_id",
            "Mã yêu cầu đơn hàng không hợp lệ.",
        )
        clean = inspect_evidence_bytes(raw_bytes, scanner=self._active_malware_scanner())
        safe_filename = sanitize_attachment_filename(filename, default_name="") if filename else None
        norm_actor = self._normalize_actor(actor, str(customer_id or "customer"), "customer")
        caller_role = norm_actor["role"]
        require(
            caller_role in ("customer", "staff", "manager"),
            403,
            "permission_denied",
            "Tài khoản không có quyền tải tệp bằng chứng.",
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
                        "Khách hàng chỉ được đính kèm bằng chứng khi yêu cầu còn ở trạng thái requested.",
                    )
                    case_row = db.execute(
                        "SELECT status FROM cases WHERE case_id = ?",
                        (req_row["case_id"],),
                    ).fetchone()
                    require(
                        case_row is not None and case_row["status"] != "resolved",
                        409,
                        "case_already_resolved",
                        "Ca hỗ trợ đã đóng, không thể tải thêm tệp bằng chứng.",
                    )
                    uploaded_by_principal = norm_actor["principal_id"]
                    uploaded_by_role = "customer"
                else:
                    self._check_case_reviewer_authority_in_tx(db, req_row["case_id"], norm_actor)
                    require(
                        req_row["closed_at"] is None,
                        409,
                        "evidence_upload_closed",
                        "Yêu cầu đơn hàng đã đóng, không thể tải thêm tệp bằng chứng.",
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
                    f"Mỗi yêu cầu đơn hàng chỉ được đính kèm tối đa {EVIDENCE_MAX_COUNT} tệp bằng chứng.",
                )

                written_path = atomic_write_bytes(target_dir, evidence_id, clean["bytes"])
                db.execute(
                    """INSERT INTO order_action_evidence(
                           evidence_id, request_id, case_id, customer_id, conversation_id, filename,
                           uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size,
                           width, height, page_count, sha256, storage_relpath,
                           scan_status, scan_engine, scanned_at, created_at, file_purged_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (
                        evidence_id,
                        request_id,
                        req_row["case_id"],
                        req_row["customer_id"],
                        req_row["conversation_id"],
                        safe_filename,
                        uploaded_by_principal,
                        uploaded_by_role,
                        clean["mime_type"],
                        clean["byte_size"],
                        clean["width"],
                        clean["height"],
                        clean.get("page_count"),
                        clean["sha256"],
                        storage_relpath,
                        clean.get("scan_status"),
                        clean.get("scan_engine"),
                        clean.get("scanned_at"),
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
                    page_count=clean.get("page_count"),
                    scan_status=clean.get("scan_status"),
                    sha256=clean["sha256"],
                    actor=actor if actor is not None else norm_actor,
                )
                serialized = self._serialize_order_action_in_tx(db, req_row, now=now_ts)
        except Exception:
            if written_path is not None:
                written_path.unlink(missing_ok=True)
            raise

        is_pdf = clean["mime_type"] == "application/pdf"
        return {
            "status": "ok",
            "evidence": {
                "evidence_id": evidence_id,
                "request_id": request_id,
                "case_id": req_row["case_id"],
                "filename": safe_filename,
                "mime_type": clean["mime_type"],
                "byte_size": clean["byte_size"],
                "width": clean["width"],
                "height": clean["height"],
                "page_count": clean.get("page_count"),
                "scan_status": clean.get("scan_status"),
                "scan_engine": clean.get("scan_engine"),
                "scanned_at": clean.get("scanned_at"),
                "sha256": clean["sha256"],
                "uploaded_by_role": uploaded_by_role,
                "created_at": now_ts,
                "purged": False,
                "download_url": f"/api/order-actions/{request_id}/evidence/{evidence_id}",
            },
            "order_action": serialized,
            "message": (
                "Đã quét sạch và lưu tài liệu PDF bằng chứng."
                if is_pdf
                else "Đã lưu ảnh bằng chứng (đã xóa dữ liệu EXIF/GPS)."
            ),
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

    def store_chat_attachment(
        self,
        customer_id: str,
        cid: str,
        attachment: dict,
        *,
        actor: dict | None = None,
    ) -> dict:
        require(
            isinstance(cid, str) and bool(re.fullmatch(r"[a-f0-9-]{36}", cid)),
            400,
            "invalid_conversation",
            "Mã cuộc trò chuyện không hợp lệ.",
        )
        require(isinstance(attachment, dict), 400, "invalid_attachment", "Định dạng tệp đính kèm không hợp lệ.")
        att_type = attachment.get("type")
        require(
            att_type in ("image", "document"),
            400,
            "unsupported_attachment_type",
            "Chỉ hỗ trợ tệp hình ảnh hoặc tài liệu.",
        )
        if attachment.get("evidence_id") and "data" not in attachment:
            ev_row = self.get_chat_evidence_record(cid, str(attachment["evidence_id"]))
            require(
                ev_row["customer_id"] == customer_id,
                404,
                "evidence_not_found",
                "Không tìm thấy tệp đính kèm của cuộc trò chuyện này.",
            )
            return {
                "evidence_id": ev_row["evidence_id"],
                "type": "document" if ev_row["mime_type"] == "application/pdf" else "image",
                "mime_type": ev_row["mime_type"],
                "name": sanitize_attachment_filename(attachment.get("name") or ev_row.get("filename")),
                "sha256": ev_row["sha256"],
                "download_url": f"/api/conversations/{cid}/evidence/{ev_row['evidence_id']}",
            }

        require("data" in attachment, 400, "invalid_attachment", "Thiếu nội dung tệp đính kèm.")
        max_raw = PDF_EVIDENCE_MAX_BYTES if att_type == "document" else EVIDENCE_MAX_BYTES
        raw_bytes = decode_attachment_data_payload(attachment["data"], max_raw_bytes=max_raw)
        clean = inspect_evidence_bytes(raw_bytes, scanner=self._active_malware_scanner())
        ext_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}
        default_name = "attachment" + ext_map.get(clean["mime_type"], "")
        safe_name = sanitize_attachment_filename(attachment.get("name"), default_name=default_name)

        norm_actor = self._normalize_actor(actor, str(customer_id or "customer"), "customer")
        safe_tid, _, target_dir = resolve_protected_subdir(
            self._effective_data_root(), "evidence", self._effective_tenant_id(actor)
        )
        now_ts = self._now()
        evidence_id = f"ev_{uuid.uuid4().hex}"
        storage_relpath = f"evidence/{safe_tid}/{evidence_id}"
        written_path: Path | None = None

        try:
            with self.connection(write=True) as db:
                conv = db.execute(
                    "SELECT id, customer_id, order_id, expires_at FROM conversations WHERE id = ? AND customer_id = ?",
                    (cid, customer_id),
                ).fetchone()
                require(conv is not None, 404, "conversation_not_found", "Không tìm thấy cuộc trò chuyện của bạn.")
                require(float(conv["expires_at"]) > now_ts, 409, "conversation_expired", "Cuộc trò chuyện đã hết hạn.")
                case_row = self._ensure_active_case_in_tx(db, cid, customer_id, now_ts)
                written_path = atomic_write_bytes(target_dir, evidence_id, clean["bytes"])
                db.execute(
                    """INSERT INTO order_action_evidence(
                           evidence_id, request_id, case_id, customer_id, conversation_id, filename,
                           uploaded_by_principal_id, uploaded_by_role, mime_type, byte_size,
                           width, height, page_count, sha256, storage_relpath,
                           scan_status, scan_engine, scanned_at, created_at, file_purged_at
                       ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (
                        evidence_id,
                        case_row["case_id"],
                        customer_id,
                        cid,
                        safe_name,
                        norm_actor["principal_id"],
                        norm_actor["role"] if norm_actor["role"] in ("customer", "staff", "manager") else "customer",
                        clean["mime_type"],
                        clean["byte_size"],
                        clean.get("width"),
                        clean.get("height"),
                        clean.get("page_count"),
                        clean["sha256"],
                        storage_relpath,
                        clean.get("scan_status"),
                        clean.get("scan_engine"),
                        clean.get("scanned_at"),
                        now_ts,
                    ),
                )
                self.log(
                    db,
                    customer_id,
                    "chat_attachment_stored",
                    conv["order_id"],
                    case_id=case_row["case_id"],
                    conversation_id=cid,
                    evidence_id=evidence_id,
                    mime_type=clean["mime_type"],
                    byte_size=clean["byte_size"],
                    page_count=clean.get("page_count"),
                    scan_status=clean.get("scan_status"),
                    sha256=clean["sha256"],
                    actor=actor if actor is not None else norm_actor,
                )
        except Exception:
            if written_path is not None:
                written_path.unlink(missing_ok=True)
            raise

        ref_meta = {
            "evidence_id": evidence_id,
            "type": "document" if clean["mime_type"] == "application/pdf" else "image",
            "mime_type": clean["mime_type"],
            "name": safe_name,
            "sha256": clean["sha256"],
            "download_url": f"/api/conversations/{cid}/evidence/{evidence_id}",
        }
        if clean["mime_type"] == "application/pdf":
            ref_meta["page_count"] = clean.get("page_count")
            ref_meta["pdf_mode"] = clean.get("pdf_mode")
        return ref_meta

    def get_chat_evidence_record(self, cid: str, evidence_id: str) -> dict:
        require(
            isinstance(cid, str) and bool(re.fullmatch(r"[a-f0-9-]{36}", cid)),
            400,
            "invalid_conversation",
            "Mã cuộc trò chuyện không hợp lệ.",
        )
        require(
            isinstance(evidence_id, str) and bool(re.fullmatch(r"ev_[a-f0-9]{32}", evidence_id)),
            400,
            "invalid_evidence_id",
            "Mã tệp đính kèm không hợp lệ.",
        )
        with self.connection() as db:
            ev_row = db.execute(
                "SELECT * FROM order_action_evidence WHERE evidence_id = ? AND conversation_id = ?",
                (evidence_id, cid),
            ).fetchone()
            require(ev_row is not None, 404, "evidence_not_found", "Không tìm thấy tệp đính kèm trên cuộc trò chuyện này.")
        return dict(ev_row)

    def load_attachment_for_model(
        self,
        customer_id: str,
        cid: str,
        att_meta: dict,
        *,
        include_pixels: bool = True,
    ) -> dict:
        if not isinstance(att_meta, dict) or att_meta.get("removed"):
            return {"type": str((att_meta or {}).get("type") or "image"), "name": str((att_meta or {}).get("name") or "")}
        ev_id = att_meta.get("evidence_id")
        base_meta = {
            "type": att_meta.get("type", "image"),
            "name": sanitize_attachment_filename(att_meta.get("name")),
        }
        if att_meta.get("mime_type"):
            base_meta["mime_type"] = att_meta["mime_type"]
        if ev_id:
            base_meta["evidence_id"] = ev_id
        if att_meta.get("sha256"):
            base_meta["sha256"] = att_meta["sha256"]
        if not ev_id:
            return base_meta
        is_pdf_hint = att_meta.get("mime_type") == "application/pdf" or att_meta.get("type") == "document"
        if not include_pixels and not is_pdf_hint:
            return base_meta
        try:
            ev_row = self.get_chat_evidence_record(cid, str(ev_id))
            if ev_row.get("customer_id") != customer_id:
                return base_meta
            raw_bytes, mime_type = self.read_order_action_evidence_bytes(ev_row)
        except ApiError:
            return base_meta
        hydrated = dict(base_meta)
        hydrated["mime_type"] = mime_type
        if mime_type == "application/pdf":
            hydrated["type"] = "document"
            pdf_proj = project_pdf_for_model(raw_bytes, include_pixels=include_pixels)
            hydrated["pdf_mode"] = pdf_proj["pdf_mode"]
            hydrated["page_count"] = pdf_proj["page_count"]
            if pdf_proj["excerpt"]:
                hydrated["excerpt"] = pdf_proj["excerpt"]
            if pdf_proj["images"]:
                hydrated["images"] = pdf_proj["images"]
        elif include_pixels:
            proj = project_image_for_model(raw_bytes)
            hydrated["mime_type"] = proj["mime_type"]
            hydrated["data"] = proj["data_url"]
            hydrated["projected_width"] = proj["width"]
            hydrated["projected_height"] = proj["height"]
        return hydrated

    def purge_expired_evidence(self, *, now: float | None = None) -> dict:
        now_ts = self._now() if now is None else float(now)
        cutoff = now_ts - float(EVIDENCE_RETENTION_SECONDS)
        with self.connection() as db:
            due_oar = [
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
            due_chat = [
                dict(r)
                for r in db.execute(
                    """SELECT e.evidence_id, e.request_id, e.case_id, e.customer_id,
                              e.sha256, e.storage_relpath, NULL AS order_id
                       FROM order_action_evidence e
                       LEFT JOIN cases c ON c.case_id = e.case_id
                       WHERE e.file_purged_at IS NULL
                         AND e.request_id IS NULL
                         AND (
                             (c.resolved_at IS NOT NULL AND c.resolved_at <= ?)
                             OR (e.case_id IS NULL AND e.created_at <= ?)
                         )
                       ORDER BY e.created_at ASC, e.evidence_id ASC""",
                    (cutoff, cutoff),
                ).fetchall()
            ]
            due = [*due_oar, *due_chat]
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
                        "order_action_evidence_purged" if item.get("request_id") else "chat_attachment_purged",
                        item["order_id"],
                        evidence_id=item["evidence_id"],
                        request_id=item["request_id"],
                        case_id=item["case_id"],
                        sha256=item["sha256"],
                        purged_at=now_ts,
                    )
        return {"purged": purged}

    # ---- Staff/Manager Case Assistant storage & retention (W4-D1, W4-D4, W4-D5) -----------------------
    def purge_expired_case_assist_turns(self, *, now: float | None = None) -> dict:
        """Delete Case Assistant history for resolved cases past their retention TTL (W4-D4)."""
        now_ts = self._now() if now is None else float(now)
        cutoff = now_ts - float(self.CONVERSATION_TTL)
        with self.connection(write=True) as db:
            has_table = True
            try:
                deleted = db.execute(
                    """DELETE FROM case_assist_turns
                       WHERE case_id IN (
                           SELECT k.case_id
                           FROM cases k
                           LEFT JOIN conversations conv ON conv.id = k.conversation_id
                           WHERE k.status = 'resolved'
                             AND (
                                 conv.id IS NULL
                                 OR conv.expires_at <= ?
                                 OR (k.resolved_at IS NOT NULL AND k.resolved_at < ?)
                             )
                       )
                       OR NOT EXISTS (
                           SELECT 1 FROM cases k2 WHERE k2.case_id = case_assist_turns.case_id
                       )""",
                    (now_ts, cutoff),
                ).rowcount
            except Exception:
                has_table = False
                deleted = 0
        return {"purged": int(deleted or 0) if has_table else 0}

    def authorize_case_assist(
        self,
        case_id: str,
        *,
        actor: dict | None,
        write_attempt: bool = True,
        mode: str = "ask",
    ) -> dict:
        """Verify Case Assistant access on `case_id` (W4-D1, W4-D4, W4-D5).

        For `write_attempt=True` (`POST /api/staff/cases/<case_id>/assist`), the caller MUST either
        actively hold the case (`status == 'in_progress' and holder == caller_id`) or have role `manager`.
        Denied write attempts are recorded in `business_events` (`staff_case_assist_denied`).
        """
        require(
            isinstance(case_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_id)),
            400,
            "invalid_case_id",
            "Mã ca hỗ trợ không hợp lệ.",
        )
        norm_actor = self._normalize_actor(actor, "", "")
        caller_role = norm_actor.get("role")
        caller_id = norm_actor.get("principal_id")
        require(
            caller_role in ("staff", "manager") and bool(caller_id),
            403,
            "permission_denied",
            "Chỉ nhân viên hoặc quản lý mới được sử dụng Trợ lý ca.",
        )
        resolved_tid = self._effective_tenant_id(actor)
        now_ts = self._now()

        denied_err: ApiError | None = None
        with self.connection(write=True) as db:
            case_row = db.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            require(case_row is not None, 404, "case_not_found", "Không tìm thấy ca hỗ trợ.")
            cid = case_row["conversation_id"]
            conv = (
                db.execute(
                    "SELECT id, customer_id, order_id, product_id, expires_at FROM conversations WHERE id = ?",
                    (cid,),
                ).fetchone()
                if cid
                else None
            )

            if case_row["status"] == "resolved":
                within_retention = (
                    conv is not None
                    and float(conv["expires_at"]) > now_ts
                    and (
                        case_row["resolved_at"] is None
                        or (now_ts - float(case_row["resolved_at"])) <= float(self.CONVERSATION_TTL)
                    )
                )
                if not within_retention:
                    db.execute("DELETE FROM case_assist_turns WHERE case_id = ?", (case_id,))
                    if write_attempt:
                        self.log(
                            db,
                            case_row["customer_id"],
                            "staff_case_assist_denied",
                            conv["order_id"] if conv is not None else None,
                            case_id=case_id,
                            conversation_id=cid,
                            mode=mode,
                            reason="case_retention_expired",
                            actor=norm_actor,
                        )
                    denied_err = ApiError(
                        403,
                        "case_retention_expired",
                        "Ca hỗ trợ đã đóng và quá thời hạn lưu trữ.",
                    )

            is_holder = (
                case_row["status"] == "in_progress"
                and case_row["holder"] is not None
                and case_row["holder"] == caller_id
            )
            is_manager = caller_role == "manager"

            if denied_err is None and write_attempt and not (is_holder or is_manager):
                self.log(
                    db,
                    case_row["customer_id"],
                    "staff_case_assist_denied",
                    conv["order_id"] if conv is not None else None,
                    case_id=case_id,
                    conversation_id=cid,
                    mode=mode,
                    reason="case_not_held",
                    case_status=case_row["status"],
                    actor=norm_actor,
                )
                denied_err = ApiError(
                    403,
                    "case_not_held",
                    "Chỉ nhân viên đang trực tiếp giữ ca hoặc Quản lý mới được gọi Trợ lý ca.",
                )

            if denied_err is None and not write_attempt and not (is_holder or is_manager):
                open_ep = db.execute(
                    "SELECT handoff_id FROM handoff_episodes WHERE case_id = ? AND status = 'pending' LIMIT 1",
                    (case_id,),
                ).fetchone()
                can_view_case = (
                    (case_row["status"] in ("waiting", "in_progress") and (open_ep is not None or case_row["holder"] is not None))
                    or case_row["status"] == "resolved"
                )
                require(
                    can_view_case,
                    403,
                    "case_not_escalated",
                    "Ca hỗ trợ hiện chưa có yêu cầu chuyển tiếp nhân viên.",
                )

        if denied_err is not None:
            raise denied_err

        return {
            "tenant_id": resolved_tid,
            "principal_id": caller_id,
            "actor_role": caller_role,
            "actor": norm_actor,
            "case_id": case_row["case_id"],
            "conversation_id": cid or "",
            "customer_id": case_row["customer_id"],
            "order_id": conv["order_id"] if conv is not None else None,
            "case_status": case_row["status"],
            "can_assist": bool(is_holder or is_manager),
        }

    @staticmethod
    def _serialize_case_assist_turn_row(row) -> dict:
        d = dict(row)
        try:
            sources = json.loads(d.get("sources_json") or "[]")
        except Exception:
            sources = []
        try:
            trace = json.loads(d.get("trace_json") or "{}")
        except Exception:
            trace = {}
        _, clean_trace = sanitize_structured_payload(trace, preserve_reasoning=True)
        clean_trace_dict = clean_trace if isinstance(clean_trace, dict) else {}
        return {
            "turn_id": d["turn_id"],
            "case_id": d["case_id"],
            "request_id": d["request_id"],
            "mode": d["mode"],
            "question": d["question"],
            "answer": d["answer"],
            "draft_reply": d.get("draft_reply"),
            "cancelled": bool(clean_trace_dict.get("cancelled")),
            "sources": sources if isinstance(sources, list) else [],
            "trace": clean_trace_dict,
            "created_at": float(d["created_at"]),
        }

    def has_chat_turn_for_request(self, customer: str, cid: str, request_id: str) -> bool:
        with self.connection() as db:
            row = db.execute(
                "SELECT 1 FROM agent_turns WHERE conversation_id = ? AND customer_id = ? AND request_id = ? LIMIT 1",
                (cid, customer, request_id),
            ).fetchone()
        return row is not None

    def has_case_assist_turn(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        case_id: str,
        request_id: str,
    ) -> bool:
        with self.connection() as db:
            row = db.execute(
                """SELECT 1 FROM case_assist_turns
                   WHERE tenant_id = ? AND principal_id = ? AND case_id = ? AND request_id = ?
                   LIMIT 1""",
                (tenant_id, principal_id, case_id, request_id),
            ).fetchone()
        return row is not None

    def find_case_assist_replay(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        case_id: str,
        request_id: str,
        mode: str,
        question: str,
    ) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                """SELECT * FROM case_assist_turns
                   WHERE tenant_id = ? AND principal_id = ? AND case_id = ? AND request_id = ?""",
                (tenant_id, principal_id, case_id, request_id),
            ).fetchone()
        if row is None:
            return None
        require(
            row["mode"] == mode and row["question"] == question,
            409,
            "request_conflict",
            "Mã yêu cầu Trợ lý ca đã được dùng cho nội dung khác.",
        )
        return self._serialize_case_assist_turn_row(row)

    def case_assist_model_history(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        case_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Load ONLY the caller's own prior Case Assistant turns on this case (W4-D4)."""
        with self.connection() as db:
            rows = db.execute(
                """SELECT mode, question, answer
                   FROM case_assist_turns
                   WHERE tenant_id = ? AND principal_id = ? AND case_id = ?
                   ORDER BY created_at DESC, turn_id DESC
                   LIMIT ?""",
                (tenant_id, principal_id, case_id, max(1, min(int(limit), 20))),
            ).fetchall()
        history: list[dict] = []
        for r in reversed(rows):
            q = f"[Chế độ: {r['mode']}] {r['question']}".strip()[:2000]
            a = str(r["answer"] or "").strip()[:7500]
            if q and a:
                history.append({"role": "user", "content": q})
                history.append({"role": "assistant", "content": a})
        return history

    def save_case_assist_turn(
        self,
        *,
        tenant_id: str,
        actor: dict,
        case_id: str,
        conversation_id: str,
        customer_id: str,
        order_id: str | None,
        request_id: str,
        mode: str,
        question: str,
        answer: str,
        draft_reply: str | None,
        sources: list,
        trace: dict,
    ) -> dict:
        now_ts = self._now()
        turn_id = f"cat_{uuid.uuid4().hex}"
        norm_actor = self._normalize_actor(actor, "", "")
        sources_json = json.dumps(sources if isinstance(sources, list) else [], ensure_ascii=False)
        trace_json = json.dumps(trace if isinstance(trace, dict) else {}, ensure_ascii=False)
        tools_used = [
            t.get("name")
            for t in (trace.get("tools") or [])
            if isinstance(t, dict) and isinstance(t.get("name"), str)
        ]

        with self.connection(write=True) as db:
            existing = db.execute(
                """SELECT * FROM case_assist_turns
                   WHERE tenant_id = ? AND principal_id = ? AND case_id = ? AND request_id = ?""",
                (tenant_id, norm_actor["principal_id"], case_id, request_id),
            ).fetchone()
            if existing is not None:
                require(
                    existing["mode"] == mode and existing["question"] == question,
                    409,
                    "request_conflict",
                    "Mã yêu cầu Trợ lý ca đã được dùng cho nội dung khác.",
                )
                return {**self._serialize_case_assist_turn_row(existing), "replayed": True}

            db.execute(
                """INSERT INTO case_assist_turns(
                       turn_id, tenant_id, principal_id, actor_role, case_id, conversation_id,
                       request_id, mode, question, answer, draft_reply, sources_json, trace_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    turn_id,
                    tenant_id,
                    norm_actor["principal_id"],
                    norm_actor["role"],
                    case_id,
                    conversation_id or "",
                    request_id,
                    mode,
                    question,
                    answer,
                    draft_reply,
                    sources_json,
                    trace_json,
                    now_ts,
                ),
            )
            self.log(
                db,
                customer_id,
                "staff_case_assist_used",
                order_id,
                case_id=case_id,
                conversation_id=conversation_id or None,
                turn_id=turn_id,
                request_id=request_id,
                mode=mode,
                has_draft=bool(draft_reply),
                tool_count=len(tools_used),
                tools=tools_used,
                actor=norm_actor,
            )
            saved = db.execute("SELECT * FROM case_assist_turns WHERE turn_id = ?", (turn_id,)).fetchone()
        return {**self._serialize_case_assist_turn_row(saved), "replayed": False}

    def list_case_assist_turns(self, case_id: str, *, actor: dict | None, limit: int = 50) -> dict:
        """Return ONLY the caller's `(tenant_id, principal_id, case_id)` Case Assistant turns (W4-D4)."""
        self.purge_expired_case_assist_turns()
        ctx = self.authorize_case_assist(case_id, actor=actor, write_attempt=False)
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM case_assist_turns
                   WHERE tenant_id = ? AND principal_id = ? AND case_id = ?
                   ORDER BY created_at ASC, turn_id ASC
                   LIMIT ?""",
                (ctx["tenant_id"], ctx["principal_id"], ctx["case_id"], max(1, min(int(limit), 100))),
            ).fetchall()
        return {
            "case_id": ctx["case_id"],
            "can_assist": ctx["can_assist"],
            "turns": [self._serialize_case_assist_turn_row(r) for r in rows],
        }

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
        ref_key, key_err, key_msg = self._resolve_customer_ref_key()
        summary = {
            **counts,
            "oldest_pending_at": oldest_pending_at,
            "latest_dead": latest_dead_error,
        }
        if not ref_key:
            summary["error"] = key_err or "customer_ref_key_missing"
            summary["error_message"] = key_msg
        return summary


def inspect_sqlite_outbox_status(target_path: Path, *, environ=None) -> dict:
    """Strictly read-only operator summary of integration_outbox across SQLite tenant databases."""
    target = Path(target_path)
    ref_key, key_err, key_msg = resolve_customer_ref_key(environ=environ)
    totals = {"pending": 0, "published": 0, "dead": 0}
    tenant_reports = []

    if target.is_file():
        store = BusinessStore(target, create=False, initialize_db=False, read_only=True)
        store.tenant_id = target.stem
        if environ is not None:
            store.customer_ref_key = ref_key or ""
        summary = store.outbox_status_summary()
        tenant_reports.append({"tenant_id": target.stem, **summary})
        for k in ("pending", "published", "dead"):
            totals[k] += int(summary[k])
        report = {
            "result": "OUTBOX_STATUS",
            "backend": "sqlite",
            "read_only": True,
            "customer_ref_key_configured": bool(ref_key),
            "totals": totals,
            "tenants": tenant_reports,
        }
        if not ref_key:
            report["error"] = key_err or "customer_ref_key_missing"
            report["message"] = key_msg
        return report

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
        if environ is not None:
            store.customer_ref_key = ref_key or ""
        summary = store.outbox_status_summary()
        tenant_reports.append({"tenant_id": tid, **summary})
        for k in ("pending", "published", "dead"):
            totals[k] += int(summary[k])

    report = {
        "result": "OUTBOX_STATUS",
        "backend": "sqlite",
        "read_only": True,
        "customer_ref_key_configured": bool(ref_key),
        "totals": totals,
        "tenants": tenant_reports,
    }
    if not ref_key:
        report["error"] = key_err or "customer_ref_key_missing"
        report["message"] = key_msg
    return report
