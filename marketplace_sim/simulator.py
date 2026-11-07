"""Kho SQLite, bộ mô phỏng tất định, đồng hồ giả lập và xử lý voucher (W6.1a)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import random
import sqlite3
from typing import Any, Callable

from . import (
    CONTRACT_NAME,
    DEFAULT_MERCHANT_ID,
    DEFAULT_SEED,
    INITIAL_CLOCK_ISO,
)
from .contract import ContractError, parse_iso_vn, validate_event
from .fixtures import (
    ADDRESS_TEMPLATES,
    DELIVERY_FAIL_REASONS,
    HOUSE_NUMBERS,
    ORIGIN_WAREHOUSE,
    REFUND_FAIL_REASONS,
    SHIPPERS,
    SORTING_HUB_BY_ZONE,
    SYNTHETIC_DISPLAY_NAMES,
)
from .sender import (
    deliver_event_with_retries,
    load_signing_secret,
    validate_endpoint_url,
)
from .state_machines import (
    SUCCEEDED_PAYMENT_STATUSES,
    validate_order_transition,
    validate_payment_transition,
    validate_refund_transition,
    validate_shipment_transition,
)

VN_TZ = timezone(timedelta(hours=7))
DATA_DIR_PACKAGE = Path(__file__).resolve().parent / "data"
DB_FILENAME = "sim.sqlite3"
VOUCHER_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class SimulatorError(RuntimeError):
    """Lỗi vận hành kho dữ liệu hoặc tham số mô phỏng."""


def format_iso_vn(dt: datetime) -> str:
    return dt.astimezone(VN_TZ).replace(microsecond=0).isoformat()


def epoch_seconds(dt: datetime) -> int:
    return int(dt.timestamp())


def derive_seed(master_seed: int, *parts: object) -> int:
    msg = ":".join(str(p) for p in parts).encode("utf-8")
    key = f"marketplace-sim-seed:{master_seed}".encode("utf-8")
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


def load_catalog_data() -> list[dict[str, Any]]:
    raw = json.loads(
        (DATA_DIR_PACKAGE / "catalog.json").read_text(encoding="utf-8")
    )
    return list(raw["products"])


def load_carriers_data() -> dict[str, dict[str, Any]]:
    raw = json.loads(
        (DATA_DIR_PACKAGE / "carriers.json").read_text(encoding="utf-8")
    )
    return {item["code"]: item for item in raw["carriers"]}


def load_params_data() -> dict[str, Any]:
    raw = json.loads(
        (DATA_DIR_PACKAGE / "params.json").read_text(encoding="utf-8")
    )
    return {k: v["value"] for k, v in raw.items()}


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    vals = [float(weights[k]) for k in keys]
    total = sum(vals)
    r = rng.random() * total
    upto = 0.0
    for k, w in zip(keys, vals):
        upto += w
        if r <= upto:
            return k
    return keys[-1]


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sim_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_sequences (
    entity_kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    PRIMARY KEY (entity_kind, entity_id)
);

CREATE TABLE IF NOT EXISTS customers_state (
    external_customer_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders_state (
    external_order_id TEXT PRIMARY KEY,
    external_customer_id TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    promised_delivery_by TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    shipping_fee INTEGER NOT NULL,
    total INTEGER NOT NULL,
    status TEXT NOT NULL,
    delivered_at TEXT,
    paid_amount INTEGER NOT NULL DEFAULT 0,
    refunded_amount INTEGER NOT NULL DEFAULT 0,
    succeeded_txn_ref TEXT
);

CREATE TABLE IF NOT EXISTS shipments_state (
    external_shipment_id TEXT PRIMARY KEY,
    external_order_id TEXT NOT NULL,
    carrier TEXT NOT NULL,
    tracking_code TEXT NOT NULL,
    stage TEXT NOT NULL,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS payments_state (
    provider_txn_ref TEXT PRIMARY KEY,
    external_order_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    method TEXT NOT NULL,
    amount INTEGER NOT NULL,
    status_raw TEXT NOT NULL,
    settled_at TEXT
);

CREATE TABLE IF NOT EXISTS refunds_state (
    provider_refund_ref TEXT PRIMARY KEY,
    external_order_id TEXT NOT NULL,
    provider_txn_ref TEXT,
    amount INTEGER NOT NULL,
    channel TEXT NOT NULL,
    status_raw TEXT NOT NULL,
    initiated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS processed_voucher_requests (
    request_id TEXT PRIMARY KEY,
    request_event_id TEXT NOT NULL,
    external_voucher_id TEXT NOT NULL,
    code TEXT NOT NULL,
    issued_event_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_actions (
    sched_id INTEGER PRIMARY KEY AUTOINCREMENT,
    due_epoch INTEGER NOT NULL,
    due_iso TEXT NOT NULL,
    action_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_due
    ON scheduled_actions (due_epoch, sched_id);

CREATE TABLE IF NOT EXISTS events (
    seq_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    occurred_epoch INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    UNIQUE (source_system, event_id)
);

CREATE INDEX IF NOT EXISTS idx_events_export
    ON events (occurred_epoch, occurred_at, event_id);
"""


class MarketplaceSimulator:
    """Đối tượng điều phối kho SQLite và sinh sự kiện của sàn ảo."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / DB_FILENAME
        self.catalog = load_catalog_data()
        self.carriers = load_carriers_data()
        self.params = load_params_data()

    def _connect_existing(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise SimulatorError(
                f"Kho dữ liệu tại '{self.data_dir}' chưa được khởi tạo. Hãy chạy lệnh 'init' trước."
            )
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def initialize(
        cls,
        data_dir: str | Path,
        *,
        seed: int = DEFAULT_SEED,
        merchant_id: str = DEFAULT_MERCHANT_ID,
    ) -> "MarketplaceSimulator":
        if type(seed) is not int or seed < 0:
            raise SimulatorError("Tham số '--seed' phải là số nguyên không âm.")
        if not isinstance(merchant_id, str) or not merchant_id.strip():
            raise SimulatorError("Tham số '--merchant-id' không được để trống.")
        if len(merchant_id.strip()) > 128:
            raise SimulatorError("Tham số '--merchant-id' quá dài (tối đa 128 ký tự).")

        sim = cls(data_dir)
        sim.data_dir.mkdir(parents=True, exist_ok=True)
        if sim.db_path.exists():
            raise SimulatorError(
                f"Kho dữ liệu tại '{sim.data_dir}' đã tồn tại. Hãy chọn thư mục mới."
            )

        conn = sqlite3.connect(str(sim.db_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                conn.executescript(SCHEMA_SQL)
                meta_rows = {
                    "seed": str(seed),
                    "merchant_id": merchant_id.strip(),
                    "clock_iso": INITIAL_CLOCK_ISO,
                    "run_index": "0",
                    "next_customer_no": "1",
                    "next_order_no": "1",
                    "next_shipment_no": "1",
                    "next_payment_no": "1",
                    "next_refund_no": "1",
                    "next_voucher_no": "1",
                    "next_story_no": "1",
                }
                conn.executemany(
                    "INSERT INTO sim_meta (key, value) VALUES (?, ?)",
                    list(meta_rows.items()),
                )
                sim._emit_initial_catalog(conn)
        finally:
            conn.close()
        return sim

    # ------------------------------------------------------------------
    # Helpers đọc/ghi metadata và chuỗi sequence
    # ------------------------------------------------------------------
    def _get_meta(self, conn: sqlite3.Connection, key: str) -> str:
        row = conn.execute(
            "SELECT value FROM sim_meta WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise SimulatorError(f"Thiếu khóa cấu hình '{key}' trong kho dữ liệu.")
        return str(row["value"])

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "UPDATE sim_meta SET value = ? WHERE key = ?", (value, key)
        )

    def _alloc_counter(self, conn: sqlite3.Connection, key: str) -> int:
        current = int(self._get_meta(conn, key))
        self._set_meta(conn, key, str(current + 1))
        return current

    def _next_entity_seq(
        self, conn: sqlite3.Connection, entity_kind: str, entity_id: str
    ) -> int:
        row = conn.execute(
            "SELECT seq FROM entity_sequences WHERE entity_kind = ? AND entity_id = ?",
            (entity_kind, entity_id),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO entity_sequences (entity_kind, entity_id, seq) VALUES (?, ?, 1)",
                (entity_kind, entity_id),
            )
            return 1
        nxt = int(row["seq"]) + 1
        conn.execute(
            "UPDATE entity_sequences SET seq = ? WHERE entity_kind = ? AND entity_id = ?",
            (nxt, entity_kind, entity_id),
        )
        return nxt

    def _record_event(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        event_type: str,
        source_system: str,
        occurred_dt: datetime,
        sequence: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        merchant_id = self._get_meta(conn, "merchant_id")
        occurred_iso = format_iso_vn(occurred_dt)
        envelope: dict[str, Any] = {
            "contract": CONTRACT_NAME,
            "event_id": event_id,
            "event_type": event_type,
            "source_system": source_system,
            "merchant_id": merchant_id,
            "occurred_at": occurred_iso,
            "sequence": sequence,
            "data": data,
        }
        validate_event(envelope, allow_requests=False)
        payload_json = json.dumps(
            envelope, ensure_ascii=False, separators=(",", ":")
        )
        conn.execute(
            """
            INSERT INTO events (
                event_id, source_system, event_type, occurred_at,
                occurred_epoch, sequence, payload_json, delivery_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                event_id,
                source_system,
                event_type,
                occurred_iso,
                epoch_seconds(occurred_dt),
                sequence,
                payload_json,
            ),
        )
        return envelope

    # ------------------------------------------------------------------
    # Khởi tạo catalog (mục 2)
    # ------------------------------------------------------------------
    def _emit_initial_catalog(self, conn: sqlite3.Connection) -> None:
        clock_dt = parse_iso_vn(self._get_meta(conn, "clock_iso"), "clock_iso")
        assert clock_dt is not None
        seen_skus: set[str] = set()
        for prod in self.catalog:
            pid = prod["external_product_id"]
            for v in prod["variants"]:
                sku = v["sku"]
                if sku in seen_skus:
                    raise SimulatorError(f"Trùng SKU '{sku}' trong catalog.")
                seen_skus.add(sku)
            seq = self._next_entity_seq(conn, "product", pid)
            self._record_event(
                conn,
                event_id=f"evt:product:{pid}:{seq}",
                event_type="product.upserted",
                source_system="marketplace_sim",
                occurred_dt=clock_dt,
                sequence=seq,
                data={
                    "external_product_id": pid,
                    "title": prod["title"],
                    "category": prod["category"],
                    "price": prod["price"],
                    "description": prod["description"],
                    "material": prod["material"],
                    "care": prod["care"],
                    "warranty_days": prod["warranty_days"],
                    "variants": prod["variants"],
                },
            )

    # ------------------------------------------------------------------
    # Các hàm thực thi sự kiện có kiểm tra máy trạng thái (mục 3–6)
    # ------------------------------------------------------------------
    def emit_customer_upserted(
        self,
        conn: sqlite3.Connection,
        *,
        external_customer_id: str,
        display_name: str,
        occurred_dt: datetime,
    ) -> None:
        existing = conn.execute(
            "SELECT 1 FROM customers_state WHERE external_customer_id = ?",
            (external_customer_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO customers_state (external_customer_id, display_name) VALUES (?, ?)",
                (external_customer_id, display_name),
            )
        else:
            conn.execute(
                "UPDATE customers_state SET display_name = ? WHERE external_customer_id = ?",
                (display_name, external_customer_id),
            )
        seq = self._next_entity_seq(conn, "customer", external_customer_id)
        self._record_event(
            conn,
            event_id=f"evt:customer:{external_customer_id}:{seq}",
            event_type="customer.upserted",
            source_system="marketplace_sim",
            occurred_dt=occurred_dt,
            sequence=seq,
            data={
                "external_customer_id": external_customer_id,
                "display_name": display_name,
            },
        )

    def emit_order_created(
        self,
        conn: sqlite3.Connection,
        *,
        external_order_id: str,
        external_customer_id: str,
        ordered_dt: datetime,
        promised_dt: datetime,
        items: list[dict[str, Any]],
        shipping_fee: int,
        payment_method: str,
        recipient: dict[str, str],
    ) -> None:
        validate_order_transition(None, "pending")
        subtotal = sum(int(i["quantity"]) * int(i["unit_price"]) for i in items)
        total = subtotal + int(shipping_fee)
        ordered_iso = format_iso_vn(ordered_dt)
        promised_iso = format_iso_vn(promised_dt)
        conn.execute(
            """
            INSERT INTO orders_state (
                external_order_id, external_customer_id, ordered_at,
                promised_delivery_by, payment_method, shipping_fee,
                total, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                external_order_id,
                external_customer_id,
                ordered_iso,
                promised_iso,
                payment_method,
                shipping_fee,
                total,
            ),
        )
        seq_create = self._next_entity_seq(conn, "order", external_order_id)
        self._record_event(
            conn,
            event_id=f"evt:order:{external_order_id}:{seq_create}",
            event_type="order.created",
            source_system="marketplace_sim",
            occurred_dt=ordered_dt,
            sequence=seq_create,
            data={
                "external_order_id": external_order_id,
                "external_customer_id": external_customer_id,
                "ordered_at": ordered_iso,
                "items": items,
                "shipping_fee": shipping_fee,
                "total": total,
                "currency": "VND",
                "payment_method": payment_method,
                "promised_delivery_by": promised_iso,
                "recipient": recipient,
            },
        )
        seq_pending = self._next_entity_seq(conn, "order", external_order_id)
        self._record_event(
            conn,
            event_id=f"evt:order:{external_order_id}:{seq_pending}",
            event_type="order.status_changed",
            source_system="marketplace_sim",
            occurred_dt=ordered_dt,
            sequence=seq_pending,
            data={
                "external_order_id": external_order_id,
                "status": "pending",
                "reason": None,
            },
        )

    def emit_order_status_changed(
        self,
        conn: sqlite3.Connection,
        *,
        external_order_id: str,
        target_status: str,
        reason: str | None,
        occurred_dt: datetime,
    ) -> None:
        row = conn.execute(
            "SELECT status FROM orders_state WHERE external_order_id = ?",
            (external_order_id,),
        ).fetchone()
        if row is None:
            raise SimulatorError(f"Không tìm thấy đơn '{external_order_id}'.")
        validate_order_transition(str(row["status"]), target_status)
        occurred_iso = format_iso_vn(occurred_dt)
        if target_status == "delivered":
            shp = conn.execute(
                "SELECT delivered_at FROM shipments_state WHERE external_order_id = ?",
                (external_order_id,),
            ).fetchone()
            if shp is None or shp["delivered_at"] != occurred_iso:
                raise SimulatorError(
                    "Đơn chuyển sang 'delivered' phải trùng thời điểm vận đơn chuyển 'delivered'."
                )
            conn.execute(
                "UPDATE orders_state SET status = ?, delivered_at = ? WHERE external_order_id = ?",
                (target_status, occurred_iso, external_order_id),
            )
        else:
            conn.execute(
                "UPDATE orders_state SET status = ? WHERE external_order_id = ?",
                (target_status, external_order_id),
            )
        seq = self._next_entity_seq(conn, "order", external_order_id)
        self._record_event(
            conn,
            event_id=f"evt:order:{external_order_id}:{seq}",
            event_type="order.status_changed",
            source_system="marketplace_sim",
            occurred_dt=occurred_dt,
            sequence=seq,
            data={
                "external_order_id": external_order_id,
                "status": target_status,
                "reason": reason,
            },
        )

    def emit_shipment_updated(
        self,
        conn: sqlite3.Connection,
        *,
        external_shipment_id: str,
        external_order_id: str,
        carrier: str,
        tracking_code: str,
        stage: str,
        hub_name: str | None,
        district: str,
        province: str,
        description: str,
        fail_reason: str | None,
        shipper_name: str | None,
        shipper_phone_masked: str | None,
        estimated_delivery_dt: datetime | None,
        occurred_dt: datetime,
    ) -> None:
        carrier_cfg = self.carriers[carrier]
        status_raw = carrier_cfg["status_codes"][stage]
        max_attempts = int(self.params["max_delivery_attempts"])

        row = conn.execute(
            "SELECT stage, delivery_attempts FROM shipments_state WHERE external_shipment_id = ?",
            (external_shipment_id,),
        ).fetchone()
        curr_stage = str(row["stage"]) if row is not None else None
        curr_attempts = int(row["delivery_attempts"]) if row is not None else 0

        if stage == "delivery_fail" and not (fail_reason and fail_reason.strip()):
            raise SimulatorError(
                "Sự kiện vận đơn giao thất bại bắt buộc có lý do fail_reason."
            )
        if stage != "delivery_fail":
            fail_reason = None

        new_attempts = validate_shipment_transition(
            curr_stage,
            stage,
            current_attempts=curr_attempts,
            max_attempts=max_attempts,
        )

        occurred_iso = format_iso_vn(occurred_dt)
        delivered_iso = occurred_iso if stage == "delivered" else None
        if row is None:
            conn.execute(
                """
                INSERT INTO shipments_state (
                    external_shipment_id, external_order_id, carrier,
                    tracking_code, stage, delivery_attempts, delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    external_shipment_id,
                    external_order_id,
                    carrier,
                    tracking_code,
                    stage,
                    new_attempts,
                    delivered_iso,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE shipments_state
                SET stage = ?, delivery_attempts = ?,
                    delivered_at = COALESCE(?, delivered_at)
                WHERE external_shipment_id = ?
                """,
                (stage, new_attempts, delivered_iso, external_shipment_id),
            )

        seq = self._next_entity_seq(conn, "shipment", external_shipment_id)
        self._record_event(
            conn,
            event_id=f"evt:shipment:{external_shipment_id}:{seq}",
            event_type="shipment.updated",
            source_system="marketplace_sim",
            occurred_dt=occurred_dt,
            sequence=seq,
            data={
                "external_shipment_id": external_shipment_id,
                "external_order_id": external_order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "carrier_status_raw": status_raw,
                "hub_name": hub_name,
                "district": district,
                "province": province,
                "description": description,
                "fail_reason": fail_reason,
                "shipper_name": shipper_name,
                "shipper_phone_masked": shipper_phone_masked,
                "estimated_delivery_at": (
                    format_iso_vn(estimated_delivery_dt)
                    if estimated_delivery_dt is not None
                    else None
                ),
                "delivery_attempts": new_attempts,
            },
        )

    def emit_payment_updated(
        self,
        conn: sqlite3.Connection,
        *,
        provider: str,
        provider_txn_ref: str,
        external_order_id: str,
        method: str,
        amount: int,
        provider_status_raw: str,
        occurred_dt: datetime,
    ) -> None:
        order_row = conn.execute(
            "SELECT payment_method, status, total FROM orders_state WHERE external_order_id = ?",
            (external_order_id,),
        ).fetchone()
        if order_row is None:
            raise SimulatorError(f"Không tìm thấy đơn '{external_order_id}'.")

        row = conn.execute(
            "SELECT status_raw FROM payments_state WHERE provider_txn_ref = ?",
            (provider_txn_ref,),
        ).fetchone()
        curr_status = str(row["status_raw"]) if row is not None else None
        validate_payment_transition(curr_status, provider_status_raw)

        if method == "cod":
            source_system = "marketplace_sim"
            if (
                provider_status_raw == "COD_SETTLED"
                and str(order_row["status"]) != "delivered"
            ):
                raise SimulatorError(
                    "Đơn COD chỉ được ghi nhận thanh toán thành công khi đơn đã giao ('delivered')."
                )
        else:
            source_system = "payment_sim"

        settled_iso = (
            format_iso_vn(occurred_dt)
            if provider_status_raw in SUCCEEDED_PAYMENT_STATUSES
            else None
        )

        if row is None:
            conn.execute(
                """
                INSERT INTO payments_state (
                    provider_txn_ref, external_order_id, provider,
                    method, amount, status_raw, settled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_txn_ref,
                    external_order_id,
                    provider,
                    method,
                    amount,
                    provider_status_raw,
                    settled_iso,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE payments_state
                SET status_raw = ?, settled_at = COALESCE(?, settled_at)
                WHERE provider_txn_ref = ?
                """,
                (provider_status_raw, settled_iso, provider_txn_ref),
            )

        if provider_status_raw in SUCCEEDED_PAYMENT_STATUSES:
            conn.execute(
                """
                UPDATE orders_state
                SET paid_amount = paid_amount + ?,
                    succeeded_txn_ref = ?
                WHERE external_order_id = ?
                """,
                (
                    amount,
                    provider_txn_ref if method != "cod" else None,
                    external_order_id,
                ),
            )

        seq = self._next_entity_seq(conn, "payment", provider_txn_ref)
        self._record_event(
            conn,
            event_id=f"evt:payment:{provider_txn_ref}:{seq}",
            event_type="payment.updated",
            source_system=source_system,
            occurred_dt=occurred_dt,
            sequence=seq,
            data={
                "provider": provider,
                "provider_txn_ref": provider_txn_ref,
                "external_order_id": external_order_id,
                "method": method,
                "amount": amount,
                "provider_status_raw": provider_status_raw,
                "settled_at": settled_iso,
            },
        )

    def emit_refund_updated(
        self,
        conn: sqlite3.Connection,
        *,
        provider_refund_ref: str,
        external_order_id: str,
        amount: int,
        channel: str,
        provider_status_raw: str,
        failure_reason: str | None,
        initiated_dt: datetime,
        occurred_dt: datetime,
    ) -> None:
        order_row = conn.execute(
            """
            SELECT payment_method, paid_amount, refunded_amount, succeeded_txn_ref
            FROM orders_state WHERE external_order_id = ?
            """,
            (external_order_id,),
        ).fetchone()
        if order_row is None:
            raise SimulatorError(f"Không tìm thấy đơn '{external_order_id}'.")

        payment_method = str(order_row["payment_method"])
        paid_amount = int(order_row["paid_amount"])
        refunded_amount = int(order_row["refunded_amount"])
        succeeded_txn_ref = (
            str(order_row["succeeded_txn_ref"])
            if order_row["succeeded_txn_ref"] is not None
            else None
        )

        if payment_method == "cod":
            if channel != "bank_transfer":
                raise SimulatorError(
                    "Đơn COD bắt buộc hoàn tiền qua kênh chuyển khoản ('bank_transfer')."
                )
            provider_txn_ref = None
        else:
            if not succeeded_txn_ref:
                raise SimulatorError(
                    "Đơn trả trước phải có giao dịch thanh toán thành công trước khi hoàn tiền."
                )
            provider_txn_ref = succeeded_txn_ref

        existing = conn.execute(
            "SELECT status_raw, amount FROM refunds_state WHERE provider_refund_ref = ?",
            (provider_refund_ref,),
        ).fetchone()
        curr_status = str(existing["status_raw"]) if existing is not None else None
        validate_refund_transition(curr_status, provider_status_raw)

        if existing is None:
            if amount <= 0 or refunded_amount + amount > paid_amount:
                raise SimulatorError(
                    f"Tổng số tiền hoàn ({refunded_amount + amount}) vượt quá số tiền đã thu ({paid_amount})."
                )
            conn.execute(
                """
                UPDATE orders_state
                SET refunded_amount = refunded_amount + ?
                WHERE external_order_id = ?
                """,
                (amount, external_order_id),
            )
            conn.execute(
                """
                INSERT INTO refunds_state (
                    provider_refund_ref, external_order_id, provider_txn_ref,
                    amount, channel, status_raw, initiated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_refund_ref,
                    external_order_id,
                    provider_txn_ref,
                    amount,
                    channel,
                    provider_status_raw,
                    format_iso_vn(initiated_dt),
                    (
                        format_iso_vn(occurred_dt)
                        if provider_status_raw == "REFUND_COMPLETED"
                        else None
                    ),
                ),
            )
        else:
            if provider_status_raw == "REFUND_FAILED":
                conn.execute(
                    """
                    UPDATE orders_state
                    SET refunded_amount = refunded_amount - ?
                    WHERE external_order_id = ?
                    """,
                    (int(existing["amount"]), external_order_id),
                )
            conn.execute(
                """
                UPDATE refunds_state
                SET status_raw = ?,
                    completed_at = CASE
                        WHEN ? = 'REFUND_COMPLETED' THEN ?
                        ELSE completed_at
                    END
                WHERE provider_refund_ref = ?
                """,
                (
                    provider_status_raw,
                    provider_status_raw,
                    format_iso_vn(occurred_dt),
                    provider_refund_ref,
                ),
            )

        if provider_status_raw == "REFUND_FAILED" and not (
            failure_reason and failure_reason.strip()
        ):
            raise SimulatorError(
                "Hoàn tiền thất bại bắt buộc có lý do failure_reason."
            )
        if provider_status_raw != "REFUND_FAILED":
            failure_reason = None

        completed_iso = (
            format_iso_vn(occurred_dt)
            if provider_status_raw == "REFUND_COMPLETED"
            else None
        )
        seq = self._next_entity_seq(conn, "refund", provider_refund_ref)
        self._record_event(
            conn,
            event_id=f"evt:refund:{provider_refund_ref}:{seq}",
            event_type="refund.updated",
            source_system="payment_sim",
            occurred_dt=occurred_dt,
            sequence=seq,
            data={
                "provider": "PAYSIM_GATEWAY",
                "provider_refund_ref": provider_refund_ref,
                "provider_txn_ref": provider_txn_ref,
                "external_order_id": external_order_id,
                "amount": amount,
                "channel": channel,
                "provider_status_raw": provider_status_raw,
                "failure_reason": failure_reason,
                "initiated_at": format_iso_vn(initiated_dt),
                "completed_at": completed_iso,
            },
        )

    # ------------------------------------------------------------------
    # Lịch sự kiện đến hạn (run / advance)
    # ------------------------------------------------------------------
    def schedule_or_apply(
        self,
        conn: sqlite3.Connection,
        due_dt: datetime,
        action: dict[str, Any],
        *,
        clock_dt: datetime,
    ) -> None:
        if epoch_seconds(due_dt) <= epoch_seconds(clock_dt):
            self._apply_action(conn, due_dt, action)
        else:
            conn.execute(
                "INSERT INTO scheduled_actions (due_epoch, due_iso, action_json) VALUES (?, ?, ?)",
                (
                    epoch_seconds(due_dt),
                    format_iso_vn(due_dt),
                    json.dumps(action, ensure_ascii=False, separators=(",", ":")),
                ),
            )

    def _apply_action(
        self, conn: sqlite3.Connection, due_dt: datetime, action: dict[str, Any]
    ) -> None:
        kind = action["kind"]
        if kind == "customer_upserted":
            self.emit_customer_upserted(
                conn,
                external_customer_id=action["external_customer_id"],
                display_name=action["display_name"],
                occurred_dt=due_dt,
            )
        elif kind == "order_created":
            promised_dt = parse_iso_vn(action["promised_iso"], "promised_iso")
            assert promised_dt is not None
            self.emit_order_created(
                conn,
                external_order_id=action["external_order_id"],
                external_customer_id=action["external_customer_id"],
                ordered_dt=due_dt,
                promised_dt=promised_dt,
                items=action["items"],
                shipping_fee=int(action["shipping_fee"]),
                payment_method=action["payment_method"],
                recipient=action["recipient"],
            )
        elif kind == "order_status":
            self.emit_order_status_changed(
                conn,
                external_order_id=action["external_order_id"],
                target_status=action["target_status"],
                reason=action.get("reason"),
                occurred_dt=due_dt,
            )
        elif kind == "shipment":
            est_iso = action.get("estimated_delivery_iso")
            est_dt = parse_iso_vn(est_iso, "estimated_delivery_iso", nullable=True)
            self.emit_shipment_updated(
                conn,
                external_shipment_id=action["external_shipment_id"],
                external_order_id=action["external_order_id"],
                carrier=action["carrier"],
                tracking_code=action["tracking_code"],
                stage=action["stage"],
                hub_name=action.get("hub_name"),
                district=action["district"],
                province=action["province"],
                description=action["description"],
                fail_reason=action.get("fail_reason"),
                shipper_name=action.get("shipper_name"),
                shipper_phone_masked=action.get("shipper_phone_masked"),
                estimated_delivery_dt=est_dt,
                occurred_dt=due_dt,
            )
        elif kind == "payment":
            self.emit_payment_updated(
                conn,
                provider=action["provider"],
                provider_txn_ref=action["provider_txn_ref"],
                external_order_id=action["external_order_id"],
                method=action["method"],
                amount=int(action["amount"]),
                provider_status_raw=action["provider_status_raw"],
                occurred_dt=due_dt,
            )
        elif kind == "refund":
            init_dt = parse_iso_vn(action["initiated_iso"], "initiated_iso")
            assert init_dt is not None
            self.emit_refund_updated(
                conn,
                provider_refund_ref=action["provider_refund_ref"],
                external_order_id=action["external_order_id"],
                amount=int(action["amount"]),
                channel=action["channel"],
                provider_status_raw=action["provider_status_raw"],
                failure_reason=action.get("failure_reason"),
                initiated_dt=init_dt,
                occurred_dt=due_dt,
            )
        else:  # pragma: no cover
            raise SimulatorError(f"Hành động lịch không rõ: {kind!r}.")

    def _flush_due_scheduled(
        self, conn: sqlite3.Connection, target_clock_dt: datetime
    ) -> int:
        target_epoch = epoch_seconds(target_clock_dt)
        rows = conn.execute(
            """
            SELECT sched_id, due_iso, action_json
            FROM scheduled_actions
            WHERE due_epoch <= ?
            ORDER BY due_epoch ASC, sched_id ASC
            """,
            (target_epoch,),
        ).fetchall()
        emitted = 0
        for row in rows:
            due_dt = parse_iso_vn(str(row["due_iso"]), "due_iso")
            assert due_dt is not None
            action = json.loads(str(row["action_json"]))
            self._apply_action(conn, due_dt, action)
            conn.execute(
                "DELETE FROM scheduled_actions WHERE sched_id = ?",
                (int(row["sched_id"]),),
            )
            emitted += 1
        return emitted

    # ------------------------------------------------------------------
    # Sinh người nhận, khách hàng và dòng đời đơn ngẫu nhiên có seed
    # ------------------------------------------------------------------
    def build_synthetic_recipient(
        self,
        rng: random.Random,
        *,
        preferred_name: str | None = None,
        zone_filter: str | None = None,
    ) -> tuple[dict[str, str], str]:
        prefix = str(self.params["phone_prefix"])
        if not prefix.isdigit() or not prefix.startswith("0") or not (2 <= len(prefix) <= 8):
            raise SimulatorError(
                f"Cấu hình phone_prefix '{prefix}' không hợp lệ."
            )
        suffix_len = 10 - len(prefix)
        suffix = "".join(rng.choice("0123456789") for _ in range(suffix_len))
        phone = prefix + suffix

        candidates = [
            tpl
            for tpl in ADDRESS_TEMPLATES
            if zone_filter is None or tpl["zone"] == zone_filter
        ]
        addr_tpl = rng.choice(candidates)
        house_no = rng.choice(HOUSE_NUMBERS)
        rec_name = preferred_name or rng.choice(SYNTHETIC_DISPLAY_NAMES)
        recipient = {
            "name": rec_name,
            "phone": phone,
            "address_line": f"Số {house_no} {addr_tpl['street']}",
            "ward": addr_tpl["ward"],
            "district": addr_tpl["district"],
            "province": addr_tpl["province"],
        }
        return recipient, addr_tpl["zone"]

    def _orderable_variants(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for prod in self.catalog:
            if prod["price"] is None:
                continue
            for var in prod["variants"]:
                if var["price"] is not None and (var["stock"] or 0) > 0:
                    pairs.append((prod, var))
        return pairs

    def _plan_random_order(
        self,
        conn: sqlite3.Connection,
        rng: random.Random,
        ordered_dt: datetime,
        target_clock_dt: datetime,
    ) -> None:
        existing_customers = [
            (str(r["external_customer_id"]), str(r["display_name"]))
            for r in conn.execute(
                "SELECT external_customer_id, display_name FROM customers_state ORDER BY external_customer_id"
            ).fetchall()
        ]
        if existing_customers and rng.random() < float(
            self.params["repeat_customer_rate"]
        ):
            cust_id, cust_name = rng.choice(existing_customers)
            is_new_customer = False
        else:
            c_no = self._alloc_counter(conn, "next_customer_no")
            cust_id = f"SIM-C-{c_no:04d}"
            cust_name = SYNTHETIC_DISPLAY_NAMES[
                (c_no - 1) % len(SYNTHETIC_DISPLAY_NAMES)
            ]
            is_new_customer = True

        if is_new_customer:
            self.schedule_or_apply(
                conn,
                ordered_dt - timedelta(seconds=5),
                {
                    "kind": "customer_upserted",
                    "external_customer_id": cust_id,
                    "display_name": cust_name,
                },
                clock_dt=target_clock_dt,
            )

        o_no = self._alloc_counter(conn, "next_order_no")
        order_id = f"SIM-O-{o_no:05d}"

        recipient, zone = self.build_synthetic_recipient(
            rng,
            preferred_name=(
                cust_name if rng.random() < 0.75 else None
            ),
        )
        carrier = _weighted_choice(rng, self.params["carrier_weights"])
        carrier_cfg = self.carriers[carrier]
        promised_hours = int(carrier_cfg["promised_hours_by_zone"][zone])
        promised_dt = ordered_dt + timedelta(hours=promised_hours)

        shipping_fee = int(self.params["shipping_fee_by_zone"][zone])
        payment_method = _weighted_choice(
            rng, self.params["payment_method_weights"]
        )

        pool = self._orderable_variants()
        num_items = 1 if rng.random() < 0.7 else 2
        chosen = rng.sample(pool, k=num_items)
        items: list[dict[str, Any]] = []
        subtotal = 0
        for prod, var in chosen:
            qty = 1 if rng.random() < 0.8 else 2
            uprice = int(var["price"])
            subtotal += qty * uprice
            items.append(
                {
                    "sku": var["sku"],
                    "external_product_id": prod["external_product_id"],
                    "title": prod["title"],
                    "variant_name": var["variant_name"],
                    "quantity": qty,
                    "unit_price": uprice,
                }
            )
        total = subtotal + shipping_fee

        self.schedule_or_apply(
            conn,
            ordered_dt,
            {
                "kind": "order_created",
                "external_order_id": order_id,
                "external_customer_id": cust_id,
                "promised_iso": format_iso_vn(promised_dt),
                "items": items,
                "shipping_fee": shipping_fee,
                "payment_method": payment_method,
                "recipient": recipient,
            },
            clock_dt=target_clock_dt,
        )

        t_cursor = ordered_dt + timedelta(minutes=rng.randint(2, 10))
        if payment_method != "cod":
            if rng.random() < float(self.params["prepaid_retry_rate"]):
                p1_no = self._alloc_counter(conn, "next_payment_no")
                txn1 = f"PAYSIM-TXN-{p1_no:05d}"
                self.schedule_or_apply(
                    conn,
                    t_cursor,
                    {
                        "kind": "payment",
                        "provider": "PAYSIM_GATEWAY",
                        "provider_txn_ref": txn1,
                        "external_order_id": order_id,
                        "method": payment_method,
                        "amount": total,
                        "provider_status_raw": "PAY_PENDING",
                    },
                    clock_dt=target_clock_dt,
                )
                t_cursor += timedelta(minutes=5)
                self.schedule_or_apply(
                    conn,
                    t_cursor,
                    {
                        "kind": "payment",
                        "provider": "PAYSIM_GATEWAY",
                        "provider_txn_ref": txn1,
                        "external_order_id": order_id,
                        "method": payment_method,
                        "amount": total,
                        "provider_status_raw": "PAY_FAILED",
                    },
                    clock_dt=target_clock_dt,
                )
                t_cursor += timedelta(minutes=8)

            p_no = self._alloc_counter(conn, "next_payment_no")
            txn_ref = f"PAYSIM-TXN-{p_no:05d}"
            self.schedule_or_apply(
                conn,
                t_cursor,
                {
                    "kind": "payment",
                    "provider": "PAYSIM_GATEWAY",
                    "provider_txn_ref": txn_ref,
                    "external_order_id": order_id,
                    "method": payment_method,
                    "amount": total,
                    "provider_status_raw": "PAY_PENDING",
                },
                clock_dt=target_clock_dt,
            )
            t_cursor += timedelta(minutes=3)
            self.schedule_or_apply(
                conn,
                t_cursor,
                {
                    "kind": "payment",
                    "provider": "PAYSIM_GATEWAY",
                    "provider_txn_ref": txn_ref,
                    "external_order_id": order_id,
                    "method": payment_method,
                    "amount": total,
                    "provider_status_raw": "PAY_SUCCEEDED",
                },
                clock_dt=target_clock_dt,
            )

        t_confirm = t_cursor + timedelta(minutes=rng.randint(15, 45))
        self.schedule_or_apply(
            conn,
            t_confirm,
            {
                "kind": "order_status",
                "external_order_id": order_id,
                "target_status": "confirmed",
                "reason": None,
            },
            clock_dt=target_clock_dt,
        )

        # Nhánh hủy trước khi giao
        if rng.random() < float(self.params["cancel_before_ship_rate"]):
            t_cancel = t_confirm + timedelta(minutes=rng.randint(20, 90))
            self.schedule_or_apply(
                conn,
                t_cancel,
                {
                    "kind": "order_status",
                    "external_order_id": order_id,
                    "target_status": "cancelled",
                    "reason": "Khách hàng hủy đơn trước khi bàn giao vận chuyển",
                },
                clock_dt=target_clock_dt,
            )
            if payment_method != "cod":
                r_no = self._alloc_counter(conn, "next_refund_no")
                rfd_ref = f"PAYSIM-RFD-{r_no:05d}"
                t_r_init = t_cancel + timedelta(minutes=30)
                self.schedule_or_apply(
                    conn,
                    t_r_init,
                    {
                        "kind": "refund",
                        "provider_refund_ref": rfd_ref,
                        "external_order_id": order_id,
                        "amount": total,
                        "channel": "original_method",
                        "provider_status_raw": "REFUND_INITIATED",
                        "failure_reason": None,
                        "initiated_iso": format_iso_vn(t_r_init),
                    },
                    clock_dt=target_clock_dt,
                )
                self.schedule_or_apply(
                    conn,
                    t_r_init + timedelta(hours=12),
                    {
                        "kind": "refund",
                        "provider_refund_ref": rfd_ref,
                        "external_order_id": order_id,
                        "amount": total,
                        "channel": "original_method",
                        "provider_status_raw": "REFUND_COMPLETED",
                        "failure_reason": None,
                        "initiated_iso": format_iso_vn(t_r_init),
                    },
                    clock_dt=target_clock_dt,
                )
            return

        # Bàn giao vận chuyển
        s_no = self._alloc_counter(conn, "next_shipment_no")
        shp_id = f"SIM-SHP-{s_no:05d}"
        tracking_code = f"{carrier_cfg['tracking_prefix']}{s_no:05d}"
        shipper = rng.choice(SHIPPERS)
        soc = SORTING_HUB_BY_ZONE[zone]
        dest_hub = f"Bưu cục phát {recipient['district']}"

        is_late = rng.random() < float(self.params["late_delivery_rate"])
        extra_transit_hours = rng.randint(48, 72) if is_late else rng.randint(6, 18)
        est_dt = promised_dt + (timedelta(hours=36) if is_late else timedelta(0))

        t_ready = t_confirm + timedelta(hours=1)
        self.schedule_or_apply(
            conn,
            t_ready,
            {
                "kind": "shipment",
                "external_shipment_id": shp_id,
                "external_order_id": order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "stage": "ready_to_pick",
                "hub_name": ORIGIN_WAREHOUSE["hub_name"],
                "district": ORIGIN_WAREHOUSE["district"],
                "province": ORIGIN_WAREHOUSE["province"],
                "description": "Shop đã tạo vận đơn, chờ bưu tá tới lấy hàng.",
                "estimated_delivery_iso": format_iso_vn(est_dt),
            },
            clock_dt=target_clock_dt,
        )
        t_picking = t_ready + timedelta(hours=2)
        self.schedule_or_apply(
            conn,
            t_picking,
            {
                "kind": "shipment",
                "external_shipment_id": shp_id,
                "external_order_id": order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "stage": "picking",
                "hub_name": ORIGIN_WAREHOUSE["hub_name"],
                "district": ORIGIN_WAREHOUSE["district"],
                "province": ORIGIN_WAREHOUSE["province"],
                "description": "Bưu tá đang tới kho người bán để nhận kiện hàng.",
                "estimated_delivery_iso": format_iso_vn(est_dt),
            },
            clock_dt=target_clock_dt,
        )
        t_picked = t_picking + timedelta(hours=1)
        self.schedule_or_apply(
            conn,
            t_picked,
            {
                "kind": "order_status",
                "external_order_id": order_id,
                "target_status": "shipping",
                "reason": None,
            },
            clock_dt=target_clock_dt,
        )
        self.schedule_or_apply(
            conn,
            t_picked,
            {
                "kind": "shipment",
                "external_shipment_id": shp_id,
                "external_order_id": order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "stage": "picked",
                "hub_name": ORIGIN_WAREHOUSE["hub_name"],
                "district": ORIGIN_WAREHOUSE["district"],
                "province": ORIGIN_WAREHOUSE["province"],
                "description": "Đã lấy hàng thành công từ người bán.",
                "estimated_delivery_iso": format_iso_vn(est_dt),
            },
            clock_dt=target_clock_dt,
        )
        t_storing = t_picked + timedelta(hours=2)
        self.schedule_or_apply(
            conn,
            t_storing,
            {
                "kind": "shipment",
                "external_shipment_id": shp_id,
                "external_order_id": order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "stage": "storing",
                "hub_name": "Bưu cục thu gom Tân Bình",
                "district": ORIGIN_WAREHOUSE["district"],
                "province": ORIGIN_WAREHOUSE["province"],
                "description": "Kiện hàng đã nhập kho bưu cục gốc.",
                "estimated_delivery_iso": format_iso_vn(est_dt),
            },
            clock_dt=target_clock_dt,
        )
        t_trans = t_storing + timedelta(hours=4)
        self.schedule_or_apply(
            conn,
            t_trans,
            {
                "kind": "shipment",
                "external_shipment_id": shp_id,
                "external_order_id": order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "stage": "transporting",
                "hub_name": soc["hub_name"],
                "district": soc["district"],
                "province": soc["province"],
                "description": "Kiện hàng đang vận chuyển tới kho phân loại.",
                "estimated_delivery_iso": format_iso_vn(est_dt),
            },
            clock_dt=target_clock_dt,
        )
        t_sort = t_trans + timedelta(hours=extra_transit_hours)
        self.schedule_or_apply(
            conn,
            t_sort,
            {
                "kind": "shipment",
                "external_shipment_id": shp_id,
                "external_order_id": order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "stage": "sorting",
                "hub_name": soc["hub_name"],
                "district": soc["district"],
                "province": soc["province"],
                "description": "Kiện hàng đang được phân loại tại tổng kho trung chuyển.",
                "estimated_delivery_iso": format_iso_vn(est_dt),
            },
            clock_dt=target_clock_dt,
        )

        outcome_roll = rng.random()
        t_deliv_start = t_sort + timedelta(hours=8)

        # Nhánh 3 lần giao thất bại rồi hoàn về
        if outcome_roll < float(self.params["delivery_return_rate"]):
            cur = t_deliv_start
            for attempt in range(3):
                self.schedule_or_apply(
                    conn,
                    cur,
                    {
                        "kind": "shipment",
                        "external_shipment_id": shp_id,
                        "external_order_id": order_id,
                        "carrier": carrier,
                        "tracking_code": tracking_code,
                        "stage": "delivering",
                        "hub_name": dest_hub,
                        "district": recipient["district"],
                        "province": recipient["province"],
                        "description": f"Bưu tá xuất kho giao hàng (lần {attempt + 1}).",
                        "shipper_name": shipper["name"],
                        "shipper_phone_masked": shipper["phone_masked"],
                        "estimated_delivery_iso": format_iso_vn(cur + timedelta(hours=4)),
                    },
                    clock_dt=target_clock_dt,
                )
                cur += timedelta(hours=3)
                self.schedule_or_apply(
                    conn,
                    cur,
                    {
                        "kind": "shipment",
                        "external_shipment_id": shp_id,
                        "external_order_id": order_id,
                        "carrier": carrier,
                        "tracking_code": tracking_code,
                        "stage": "delivery_fail",
                        "hub_name": dest_hub,
                        "district": recipient["district"],
                        "province": recipient["province"],
                        "description": f"Giao hàng không thành công (lần {attempt + 1}).",
                        "fail_reason": DELIVERY_FAIL_REASONS[
                            attempt % len(DELIVERY_FAIL_REASONS)
                        ],
                        "shipper_name": shipper["name"],
                        "shipper_phone_masked": shipper["phone_masked"],
                        "estimated_delivery_iso": None,
                    },
                    clock_dt=target_clock_dt,
                )
                cur += timedelta(hours=18)

            self.schedule_or_apply(
                conn,
                cur,
                {
                    "kind": "shipment",
                    "external_shipment_id": shp_id,
                    "external_order_id": order_id,
                    "carrier": carrier,
                    "tracking_code": tracking_code,
                    "stage": "waiting_to_return",
                    "hub_name": dest_hub,
                    "district": recipient["district"],
                    "province": recipient["province"],
                    "description": "Quá 3 lần giao thất bại, chờ làm thủ tục chuyển hoàn.",
                    "estimated_delivery_iso": None,
                },
                clock_dt=target_clock_dt,
            )
            cur += timedelta(hours=12)
            self.schedule_or_apply(
                conn,
                cur,
                {
                    "kind": "shipment",
                    "external_shipment_id": shp_id,
                    "external_order_id": order_id,
                    "carrier": carrier,
                    "tracking_code": tracking_code,
                    "stage": "return",
                    "hub_name": soc["hub_name"],
                    "district": soc["district"],
                    "province": soc["province"],
                    "description": "Kiện hàng đang trên đường hoàn trả về kho người bán.",
                    "estimated_delivery_iso": None,
                },
                clock_dt=target_clock_dt,
            )
            cur += timedelta(hours=24)
            self.schedule_or_apply(
                conn,
                cur,
                {
                    "kind": "shipment",
                    "external_shipment_id": shp_id,
                    "external_order_id": order_id,
                    "carrier": carrier,
                    "tracking_code": tracking_code,
                    "stage": "returned",
                    "hub_name": ORIGIN_WAREHOUSE["hub_name"],
                    "district": ORIGIN_WAREHOUSE["district"],
                    "province": ORIGIN_WAREHOUSE["province"],
                    "description": "Đã hoàn trả kiện hàng về kho người bán.",
                    "estimated_delivery_iso": None,
                },
                clock_dt=target_clock_dt,
            )
            self.schedule_or_apply(
                conn,
                cur,
                {
                    "kind": "order_status",
                    "external_order_id": order_id,
                    "target_status": "cancelled",
                    "reason": "Giao thất bại 3 lần, kiện hàng đã chuyển hoàn",
                },
                clock_dt=target_clock_dt,
            )
            if payment_method != "cod":
                r_no = self._alloc_counter(conn, "next_refund_no")
                rfd_ref = f"PAYSIM-RFD-{r_no:05d}"
                t_ri = cur + timedelta(hours=2)
                self.schedule_or_apply(
                    conn,
                    t_ri,
                    {
                        "kind": "refund",
                        "provider_refund_ref": rfd_ref,
                        "external_order_id": order_id,
                        "amount": total,
                        "channel": "original_method",
                        "provider_status_raw": "REFUND_INITIATED",
                        "failure_reason": None,
                        "initiated_iso": format_iso_vn(t_ri),
                    },
                    clock_dt=target_clock_dt,
                )
                self.schedule_or_apply(
                    conn,
                    t_ri + timedelta(hours=24),
                    {
                        "kind": "refund",
                        "provider_refund_ref": rfd_ref,
                        "external_order_id": order_id,
                        "amount": total,
                        "channel": "original_method",
                        "provider_status_raw": "REFUND_COMPLETED",
                        "failure_reason": None,
                        "initiated_iso": format_iso_vn(t_ri),
                    },
                    clock_dt=target_clock_dt,
                )
            return

        # Nhánh giao thành công (có thể thất bại 1 lần trước đó)
        cur = t_deliv_start
        if outcome_roll < float(self.params["delivery_return_rate"]) + float(
            self.params["delivery_fail_once_rate"]
        ):
            self.schedule_or_apply(
                conn,
                cur,
                {
                    "kind": "shipment",
                    "external_shipment_id": shp_id,
                    "external_order_id": order_id,
                    "carrier": carrier,
                    "tracking_code": tracking_code,
                    "stage": "delivering",
                    "hub_name": dest_hub,
                    "district": recipient["district"],
                    "province": recipient["province"],
                    "description": "Bưu tá đang đi giao kiện hàng.",
                    "shipper_name": shipper["name"],
                    "shipper_phone_masked": shipper["phone_masked"],
                    "estimated_delivery_iso": format_iso_vn(cur + timedelta(hours=4)),
                },
                clock_dt=target_clock_dt,
            )
            cur += timedelta(hours=2)
            self.schedule_or_apply(
                conn,
                cur,
                {
                    "kind": "shipment",
                    "external_shipment_id": shp_id,
                    "external_order_id": order_id,
                    "carrier": carrier,
                    "tracking_code": tracking_code,
                    "stage": "delivery_fail",
                    "hub_name": dest_hub,
                    "district": recipient["district"],
                    "province": recipient["province"],
                    "description": "Giao lần đầu chưa thành công, chờ phát lại.",
                    "fail_reason": rng.choice(DELIVERY_FAIL_REASONS),
                    "shipper_name": shipper["name"],
                    "shipper_phone_masked": shipper["phone_masked"],
                    "estimated_delivery_iso": format_iso_vn(cur + timedelta(hours=6)),
                },
                clock_dt=target_clock_dt,
            )
            cur += timedelta(hours=4)

        self.schedule_or_apply(
            conn,
            cur,
            {
                "kind": "shipment",
                "external_shipment_id": shp_id,
                "external_order_id": order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "stage": "delivering",
                "hub_name": dest_hub,
                "district": recipient["district"],
                "province": recipient["province"],
                "description": "Bưu tá đang giao kiện hàng tới người nhận.",
                "shipper_name": shipper["name"],
                "shipper_phone_masked": shipper["phone_masked"],
                "estimated_delivery_iso": format_iso_vn(cur + timedelta(hours=3)),
            },
            clock_dt=target_clock_dt,
        )
        t_delivered = cur + timedelta(hours=2)
        self.schedule_or_apply(
            conn,
            t_delivered,
            {
                "kind": "shipment",
                "external_shipment_id": shp_id,
                "external_order_id": order_id,
                "carrier": carrier,
                "tracking_code": tracking_code,
                "stage": "delivered",
                "hub_name": dest_hub,
                "district": recipient["district"],
                "province": recipient["province"],
                "description": "Giao hàng thành công cho người nhận.",
                "shipper_name": shipper["name"],
                "shipper_phone_masked": shipper["phone_masked"],
                "estimated_delivery_iso": None,
            },
            clock_dt=target_clock_dt,
        )
        self.schedule_or_apply(
            conn,
            t_delivered,
            {
                "kind": "order_status",
                "external_order_id": order_id,
                "target_status": "delivered",
                "reason": None,
            },
            clock_dt=target_clock_dt,
        )
        if payment_method == "cod":
            cp_no = self._alloc_counter(conn, "next_payment_no")
            cod_txn = f"COD-TXN-{cp_no:05d}"
            self.schedule_or_apply(
                conn,
                t_delivered,
                {
                    "kind": "payment",
                    "provider": carrier,
                    "provider_txn_ref": cod_txn,
                    "external_order_id": order_id,
                    "method": "cod",
                    "amount": total,
                    "provider_status_raw": "COD_SETTLED",
                },
                clock_dt=target_clock_dt,
            )

        # Nhánh hoàn tiền sau khi giao
        if rng.random() < float(self.params["refund_after_delivery_rate"]):
            r_no = self._alloc_counter(conn, "next_refund_no")
            rfd_ref = f"PAYSIM-RFD-{r_no:05d}"
            refund_amount = subtotal
            channel = (
                "bank_transfer"
                if payment_method == "cod"
                else rng.choice(["original_method", "bank_transfer", "e_wallet"])
            )
            t_ri = t_delivered + timedelta(hours=rng.randint(12, 48))
            self.schedule_or_apply(
                conn,
                t_ri,
                {
                    "kind": "refund",
                    "provider_refund_ref": rfd_ref,
                    "external_order_id": order_id,
                    "amount": refund_amount,
                    "channel": channel,
                    "provider_status_raw": "REFUND_INITIATED",
                    "failure_reason": None,
                    "initiated_iso": format_iso_vn(t_ri),
                },
                clock_dt=target_clock_dt,
            )
            t_rp = t_ri + timedelta(hours=4)
            self.schedule_or_apply(
                conn,
                t_rp,
                {
                    "kind": "refund",
                    "provider_refund_ref": rfd_ref,
                    "external_order_id": order_id,
                    "amount": refund_amount,
                    "channel": channel,
                    "provider_status_raw": "REFUND_PROCESSING",
                    "failure_reason": None,
                    "initiated_iso": format_iso_vn(t_ri),
                },
                clock_dt=target_clock_dt,
            )
            low_h, high_h = self.params["refund_completion_hours_range"]
            t_rf = t_rp + timedelta(hours=rng.randint(int(low_h), int(high_h)))
            if rng.random() < float(self.params["refund_fail_rate"]):
                self.schedule_or_apply(
                    conn,
                    t_rf,
                    {
                        "kind": "refund",
                        "provider_refund_ref": rfd_ref,
                        "external_order_id": order_id,
                        "amount": refund_amount,
                        "channel": channel,
                        "provider_status_raw": "REFUND_FAILED",
                        "failure_reason": rng.choice(REFUND_FAIL_REASONS),
                        "initiated_iso": format_iso_vn(t_ri),
                    },
                    clock_dt=target_clock_dt,
                )
            else:
                self.schedule_or_apply(
                    conn,
                    t_rf,
                    {
                        "kind": "refund",
                        "provider_refund_ref": rfd_ref,
                        "external_order_id": order_id,
                        "amount": refund_amount,
                        "channel": channel,
                        "provider_status_raw": "REFUND_COMPLETED",
                        "failure_reason": None,
                        "initiated_iso": format_iso_vn(t_ri),
                    },
                    clock_dt=target_clock_dt,
                )

    # ------------------------------------------------------------------
    # Lệnh công khai: run, advance, story, ingest-requests, export, send, status
    # ------------------------------------------------------------------
    def run_days(self, days: int) -> dict[str, int]:
        if type(days) is not int or days <= 0:
            raise SimulatorError("Tham số '--days' phải là số nguyên dương.")

        conn = self._connect_existing()
        try:
            with conn:
                seed = int(self._get_meta(conn, "seed"))
                run_idx = int(self._get_meta(conn, "run_index"))
                self._set_meta(conn, "run_index", str(run_idx + 1))

                start_clock = parse_iso_vn(
                    self._get_meta(conn, "clock_iso"), "clock_iso"
                )
                assert start_clock is not None
                end_clock = start_clock + timedelta(days=days)

                before_events = int(
                    conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                )

                min_orders, max_orders = self.params["orders_per_day_range"]
                for day_offset in range(days):
                    day_start = start_clock + timedelta(days=day_offset)
                    day_rng = random.Random(
                        derive_seed(seed, "run", run_idx, "day", day_offset)
                    )
                    count = day_rng.randint(int(min_orders), int(max_orders))
                    if (day_start.month, day_start.day) in {
                        (10, 10),
                        (11, 11),
                        (12, 12),
                    }:
                        count = max(
                            count,
                            int(
                                round(
                                    count
                                    * float(self.params["mega_sale_multiplier"])
                                )
                            ),
                        )

                    offsets_sec = sorted(
                        day_rng.randint(60, 86340) for _ in range(count)
                    )
                    for ord_idx, sec in enumerate(offsets_sec):
                        ord_dt = day_start + timedelta(seconds=sec)
                        ord_rng = random.Random(
                            derive_seed(
                                seed,
                                "run",
                                run_idx,
                                "day",
                                day_offset,
                                "ord",
                                ord_idx,
                            )
                        )
                        self._plan_random_order(
                            conn, ord_rng, ord_dt, day_start
                        )

                    day_end = day_start + timedelta(days=1)
                    self._flush_due_scheduled(conn, day_end)

                self._flush_due_scheduled(conn, end_clock)
                self._set_meta(conn, "clock_iso", format_iso_vn(end_clock))
                after_events = int(
                    conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                )
                scheduled_left = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM scheduled_actions"
                    ).fetchone()[0]
                )
                return {
                    "emitted": after_events - before_events,
                    "scheduled_remaining": scheduled_left,
                }
        finally:
            conn.close()

    def advance_hours(self, hours: int) -> dict[str, Any]:
        if type(hours) is not int or hours <= 0:
            raise SimulatorError("Tham số '--hours' phải là số nguyên dương.")

        conn = self._connect_existing()
        try:
            with conn:
                clock_dt = parse_iso_vn(
                    self._get_meta(conn, "clock_iso"), "clock_iso"
                )
                assert clock_dt is not None
                new_clock = clock_dt + timedelta(hours=hours)
                before_events = int(
                    conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                )
                self._flush_due_scheduled(conn, new_clock)
                self._set_meta(conn, "clock_iso", format_iso_vn(new_clock))
                after_events = int(
                    conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                )
                return {
                    "clock_iso": format_iso_vn(new_clock),
                    "emitted": after_events - before_events,
                }
        finally:
            conn.close()

    def insert_story(self, name: str) -> dict[str, Any]:
        from .stories import STORY_BUILDERS, STORY_NAMES

        if name not in STORY_BUILDERS:
            raise SimulatorError(
                f"Kịch bản '{name}' không tồn tại. Các kịch bản hợp lệ: {', '.join(STORY_NAMES)}."
            )
        conn = self._connect_existing()
        try:
            with conn:
                before_events = int(
                    conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                )
                result = STORY_BUILDERS[name](self, conn)
                after_events = int(
                    conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                )
                result["emitted"] = after_events - before_events
                return result
        finally:
            conn.close()

    def ingest_voucher_requests(
        self, file_path: str | Path
    ) -> dict[str, Any]:
        req_path = Path(file_path)
        if not req_path.is_file():
            raise SimulatorError(
                f"Không tìm thấy tệp yêu cầu voucher: '{req_path}'."
            )

        lines = req_path.read_text(encoding="utf-8").splitlines()
        conn = self._connect_existing()
        issued = 0
        duplicates = 0
        errors: list[str] = []

        try:
            with conn:
                seed = int(self._get_meta(conn, "seed"))
                clock_dt = parse_iso_vn(
                    self._get_meta(conn, "clock_iso"), "clock_iso"
                )
                assert clock_dt is not None
                validity_days = int(self.params["voucher_validity_days"])
                valid_until_dt = clock_dt + timedelta(days=validity_days)

                for line_no, raw_line in enumerate(lines, start=1):
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    try:
                        obj = json.loads(stripped)
                    except json.JSONDecodeError as exc:
                        errors.append(
                            f"Dòng {line_no}: JSON không hợp lệ ({exc.msg})."
                        )
                        continue

                    try:
                        validate_event(obj, allow_requests=True)
                    except ContractError as exc:
                        errors.append(f"Dòng {line_no}: {exc}")
                        continue

                    if (
                        obj["event_type"] != "voucher.requested"
                        or obj["source_system"] != "retailops"
                    ):
                        errors.append(
                            f"Dòng {line_no}: chỉ chấp nhận sự kiện 'voucher.requested' từ 'retailops'."
                        )
                        continue

                    data = obj["data"]
                    request_id = str(data["request_id"])
                    dup = conn.execute(
                        """
                        SELECT 1 FROM processed_voucher_requests
                        WHERE request_id = ? OR request_event_id = ?
                        """,
                        (request_id, str(obj["event_id"])),
                    ).fetchone()
                    if dup is not None:
                        duplicates += 1
                        continue

                    v_no = self._alloc_counter(conn, "next_voucher_no")
                    voucher_id = f"SIM-V-{v_no:05d}"
                    code_rng = random.Random(
                        derive_seed(seed, "voucher_code", v_no)
                    )
                    random_code = "VCH-" + "".join(
                        code_rng.choice(VOUCHER_ALPHABET) for _ in range(10)
                    )

                    seq = self._next_entity_seq(conn, "voucher", voucher_id)
                    issued_event_id = f"evt:voucher:{voucher_id}:{seq}"
                    self._record_event(
                        conn,
                        event_id=issued_event_id,
                        event_type="voucher.issued",
                        source_system="marketplace_sim",
                        occurred_dt=clock_dt,
                        sequence=seq,
                        data={
                            "external_voucher_id": voucher_id,
                            "code": random_code,
                            "voucher_type": data["voucher_type"],
                            "value": int(data["value"]),
                            "valid_until": format_iso_vn(valid_until_dt),
                            "external_order_id": data["external_order_id"],
                            "external_customer_id": data["external_customer_id"],
                            "request_ref": request_id,
                        },
                    )
                    conn.execute(
                        """
                        INSERT INTO processed_voucher_requests (
                            request_id, request_event_id, external_voucher_id,
                            code, issued_event_id
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            request_id,
                            str(obj["event_id"]),
                            voucher_id,
                            random_code,
                            issued_event_id,
                        ),
                    )
                    issued += 1
        finally:
            conn.close()

        return {
            "issued": issued,
            "duplicates": duplicates,
            "errors": errors,
        }

    def export_events(self, out_path: str | Path) -> int:
        target = Path(out_path)
        conn = self._connect_existing()
        try:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM events
                ORDER BY occurred_epoch ASC, occurred_at ASC, event_id ASC
                """
            ).fetchall()
        finally:
            conn.close()

        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(str(row["payload_json"]))
                fh.write("\n")
        return len(rows)

    def send_pending_events(
        self,
        *,
        endpoint: str,
        secret_file: str | Path,
        time_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> dict[str, int]:
        validate_endpoint_url(endpoint)
        secret_bytes = load_signing_secret(secret_file)

        conn = self._connect_existing()
        sent_count = 0
        dead_count = 0
        try:
            rows = conn.execute(
                """
                SELECT seq_pk, event_id, payload_json
                FROM events
                WHERE delivery_status = 'pending'
                ORDER BY occurred_epoch ASC, occurred_at ASC, event_id ASC
                """
            ).fetchall()

            for row in rows:
                seq_pk = int(row["seq_pk"])
                event_id = str(row["event_id"])
                raw_body = str(row["payload_json"]).encode("utf-8")
                kwargs: dict[str, Any] = {
                    "endpoint": endpoint,
                    "event_id": event_id,
                    "raw_body": raw_body,
                    "secret_bytes": secret_bytes,
                }
                if time_fn is not None:
                    kwargs["time_fn"] = time_fn
                if sleep_fn is not None:
                    kwargs["sleep_fn"] = sleep_fn

                status, attempts, last_error = deliver_event_with_retries(
                    **kwargs
                )
                with conn:
                    conn.execute(
                        """
                        UPDATE events
                        SET delivery_status = ?,
                            delivery_attempts = delivery_attempts + ?,
                            last_error = ?
                        WHERE seq_pk = ?
                        """,
                        (status, attempts, last_error, seq_pk),
                    )
                if status == "sent":
                    sent_count += 1
                else:
                    dead_count += 1
        finally:
            conn.close()

        return {"sent": sent_count, "dead": dead_count}

    def get_status(self) -> dict[str, Any]:
        conn = self._connect_existing()
        try:
            clock_iso = self._get_meta(conn, "clock_iso")
            merchant_id = self._get_meta(conn, "merchant_id")
            seed = int(self._get_meta(conn, "seed"))
            by_type = {
                str(r["event_type"]): int(r["cnt"])
                for r in conn.execute(
                    "SELECT event_type, COUNT(*) AS cnt FROM events GROUP BY event_type ORDER BY event_type"
                ).fetchall()
            }
            by_delivery = {
                str(r["delivery_status"]): int(r["cnt"])
                for r in conn.execute(
                    "SELECT delivery_status, COUNT(*) AS cnt FROM events GROUP BY delivery_status ORDER BY delivery_status"
                ).fetchall()
            }
            scheduled_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM scheduled_actions"
                ).fetchone()[0]
            )
            total_events = sum(by_type.values())
            return {
                "merchant_id": merchant_id,
                "seed": seed,
                "clock_iso": clock_iso,
                "total_events": total_events,
                "scheduled_events": scheduled_count,
                "by_event_type": by_type,
                "by_delivery_status": by_delivery,
            }
        finally:
            conn.close()
