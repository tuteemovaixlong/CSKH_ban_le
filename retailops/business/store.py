"""SQLite business repository and atomic cancellation rules.

No HTTP, session or model dependency. This module never deletes a database or
seeds demo data implicitly; its owner explicitly chooses those lifecycle actions.
"""
from __future__ import annotations
import hmac
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from retailops.core import REASONS, fields, require
from retailops.schema import migrate
from retailops.business.schema import initialize as initialize_schema

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


class BusinessStore:
    CONVERSATION_TTL = 7 * 86400  # 7 days persistent chat history

    def __init__(self, path, *, create=True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(create=create) as db:
            db.execute('PRAGMA journal_mode=WAL')
        with self.connection(write=True) as db:
            migrate(db, 'business', initialize_schema)

    @contextmanager
    def connection(self, write=False, *, create=False):
        # Only explicit construction may create a database. A lost mount must not
        # silently create a blank database while a cached repository is in use.
        uri = self.path.resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw')
        db = sqlite3.connect(uri, uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
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
            db.executemany("INSERT INTO orders(id, customer_id, name, variant, amount, status, product_id) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", orders)
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
                stock = p.get("stock", 0)
                warranty_days = p.get("warranty_days", 90)
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
                    else:
                        var_stock = max(1, stock // len(raw_variants)) if raw_variants and stock else 5

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
    def _row_to_product(row):
        d = dict(row)
        aliases = json.loads(d['aliases']) if isinstance(d['aliases'], str) else (d['aliases'] or [])
        variants = json.loads(d['variants']) if isinstance(d['variants'], str) else (d['variants'] or [])
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
        aliases = json.dumps(p.get("aliases", [name.lower(), pid.lower()]), ensure_ascii=False)
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
                var_stock = max(0, stock // len(raw_variants)) if raw_variants and stock is not None else stock
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
                params.append(json.dumps(updates["aliases"], ensure_ascii=False))

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
                "SELECT id, customer_id, created_at, kind, order_id, payload FROM business_events ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d['payload'] = json.loads(d['payload']) if isinstance(d['payload'], str) else d['payload']
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

    def events(self, customer):
        with self.connection() as db:
            result = [dict(r) for r in db.execute(
                "SELECT id,created_at,kind,order_id,payload FROM business_events WHERE customer_id=? ORDER BY id DESC LIMIT 30", (customer,))]
        for row in result:
            row["payload"] = json.loads(row["payload"])
        return result

    def new_conversation(self, customer, provider_id='custom'):
        cid = str(uuid.uuid4())
        with self.connection(write=True) as db:
            db.execute('DELETE FROM conversations WHERE expires_at < ?', (time.time(),))
            db.execute('INSERT INTO conversations(id,customer_id,expires_at,provider_id) VALUES (?,?,?,?)',
                       (cid, customer, time.time() + self.CONVERSATION_TTL, provider_id))
        return {'conversation_id': cid, 'provider_id': provider_id, 'context': {'order_id': None, 'product_id': None}}

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
        with self.connection() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=? AND customer_id=?', (cid, customer)).fetchone()
        require(row is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của bạn. Hãy mở cuộc trò chuyện mới.')
        require(row['expires_at'] > time.time(), 409, 'conversation_expired', 'Cuộc trò chuyện đã hết hạn. Hãy bấm Cuộc trò chuyện mới.')
        return dict(row)

    def remember(self, customer, snapshot, oid, pid):
        if snapshot is None:
            return
        with self.connection(write=True) as db:
            if oid is not None:
                self.owned(db, customer, oid)
            updated = db.execute('''UPDATE conversations SET order_id=?,product_id=?,revision=revision+1,expires_at=?
                WHERE id=? AND customer_id=? AND revision=? AND expires_at>?''',
                (oid, pid, time.time() + self.CONVERSATION_TTL, snapshot['id'], customer, snapshot['revision'], time.time())).rowcount
            require(updated == 1, 409, 'conversation_changed', 'Ngữ cảnh đã thay đổi hoặc hết hạn. Hãy gửi lại yêu cầu trong cuộc trò chuyện hiện tại.')

    def replay(self, customer, cid, request_id, digest):
        with self.connection() as db:
            row = db.execute('''SELECT id,input_hash,result FROM agent_turns
                WHERE conversation_id=? AND customer_id=? AND request_id=?''',
                (cid, customer, request_id)).fetchone()
        if row:
            require(row['input_hash'] == digest, 409, 'request_conflict', 'Mã yêu cầu đã dùng cho nội dung khác.')
            result = json.loads(row['result'])
            result['turn_id'] = row['id'] if 'id' in row else row[0]
            # The answer is explicitly an old result. Never reopen a stale cancel card.
            return {**result, 'replayed': True, 'action': 'reply'}
        return None

    def history(self, customer, cid):
        with self.connection() as db:
            rows = db.execute('''SELECT messages FROM agent_turns WHERE conversation_id=? AND customer_id=?
                ORDER BY id DESC LIMIT 6''', (cid, customer)).fetchall()
        turns, characters, count = [], 0, 0
        preserved_recent_image = False
        for row in rows:
            raw = json.loads(row['messages'])
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
        with self.connection(write=True) as db:
            for oid, version in versions.items():
                require(self.owned(db, customer, oid)['version'] == version, 409, 'order_changed_during_chat',
                        'Đơn đã thay đổi trong lúc model trả lời. Hãy gửi lại để đọc trạng thái mới.')
            context = result['context']
            updated = db.execute('''UPDATE conversations SET order_id=?,product_id=?,revision=revision+1,expires_at=?
                WHERE id=? AND customer_id=? AND revision=? AND expires_at>?''',
                (context['order_id'], context['product_id'], time.time() + self.CONVERSATION_TTL, snapshot['id'], customer,
                 snapshot['revision'], time.time())).rowcount
            require(updated == 1, 409, 'conversation_changed', 'Ngữ cảnh đã thay đổi hoặc hết hạn. Hãy gửi lại trong cuộc trò chuyện hiện tại.')
            cursor = db.execute('''INSERT INTO agent_turns(conversation_id,customer_id,request_id,input_hash,messages,result,created_at)
                VALUES (?,?,?,?,?,?,?) RETURNING id''', (snapshot['id'], customer, request_id, digest,
                json.dumps(messages, ensure_ascii=False), json.dumps(result, ensure_ascii=False), time.time()))
            row = cursor.fetchone()
            turn_id = row['id'] if row and 'id' in row else (row[0] if row else getattr(cursor, 'lastrowid', None))
            result['turn_id'] = turn_id
            # Prune turns beyond 6 to satisfy bounded conversation history contract
            db.execute('''DELETE FROM agent_turns WHERE conversation_id=? AND id NOT IN
                (SELECT id FROM agent_turns WHERE conversation_id=? ORDER BY id DESC LIMIT 6)''',
                (snapshot['id'], snapshot['id']))
            self.log(db, customer, 'agent_replied', context['order_id'], trace=result['trace'])
            return turn_id

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

        reason_code = body.get('reason_code')
        if reason_code is not None:
            require(isinstance(reason_code, str) and len(reason_code) <= 64, 400, 'invalid_reason_code', 'Mã lý do không hợp lệ.')

        comment = body.get('comment')
        if comment is not None:
            require(isinstance(comment, str) and len(comment) <= 1000, 400, 'comment_too_long', 'Nhận xét tối đa 1000 ký tự.')

        now = time.time()
        with self.connection(write=True) as db:
            conv = db.execute('SELECT id FROM conversations WHERE id=? AND customer_id=?', (cid, customer)).fetchone()
            require(conv is not None, 404, 'conversation_not_found', 'Không tìm thấy cuộc trò chuyện của khách hàng.')

            cursor = db.execute('''INSERT INTO conversation_feedback
                (conversation_id, turn_id, customer_id, feedback_type, rating, sentiment_flag, reason_code, comment, created_at)
                VALUES (?,?,?,?,?,?,?,?,?) RETURNING id''',
                (cid, turn_id, customer, fb_type, rating, sentiment, reason_code, comment, now))
            row = cursor.fetchone()
            feedback_id = row['id'] if row and 'id' in row else (row[0] if row else getattr(cursor, 'lastrowid', None))
            self.log(db, customer, 'feedback_received', None,
                     feedback_id=feedback_id, feedback_type=fb_type, rating=rating, sentiment_flag=sentiment)
        return {
            'status': 'ok',
            'feedback_id': feedback_id,
            'feedback_type': fb_type,
            'created_at': now
        }

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
            return [dict(r) for r in db.execute(query, tuple(params))]

    def escalations(self, limit=20):
        with self.connection() as db:
            rows = db.execute('''
                SELECT f.id, f.conversation_id, f.customer_id, f.reason_code, f.comment,
                       f.sentiment_flag, f.created_at, c.name as customer_name, conv.order_id
                FROM conversation_feedback f
                JOIN customers c ON f.customer_id = c.id
                LEFT JOIN conversations conv ON f.conversation_id = conv.id
                WHERE f.feedback_type = 'human_handoff'
                ORDER BY f.id DESC LIMIT ?
            ''', (limit,)).fetchall()
        return [dict(r) for r in rows]

    def list_conversations(self, customer, limit=20):
        with self.connection() as db:
            rows = db.execute('''
                SELECT c.id, c.customer_id, c.order_id, c.product_id, c.provider_id, c.expires_at,
                       COUNT(t.id) as turns_count,
                       MAX(t.created_at) as last_activity,
                       MIN(t.created_at) as first_activity
                FROM conversations c
                LEFT JOIN agent_turns t ON c.id = t.conversation_id
                WHERE c.customer_id = ? AND c.expires_at > ?
                GROUP BY c.id, c.customer_id, c.order_id, c.product_id, c.provider_id, c.expires_at
                ORDER BY COALESCE(MAX(t.created_at), c.expires_at) DESC
                LIMIT ?
            ''', (customer, time.time(), limit)).fetchall()

            conversations = []
            for r in rows:
                item = dict(r)
                cid = item['id']
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

                handoff = db.execute('''
                    SELECT reason_code FROM conversation_feedback
                    WHERE conversation_id=? AND feedback_type='human_handoff'
                    ORDER BY id DESC LIMIT 1
                ''', (cid,)).fetchone()

                item['snippet'] = snippet or f"Cuộc trò chuyện {cid[:8]}"
                item['has_human_handoff'] = bool(handoff and handoff['reason_code'] != 'resolved')
                conversations.append(item)
            return conversations

    def conversation_transcript(self, cid):
        with self.connection() as db:
            conv = db.execute('''
                SELECT conv.*, c.name as customer_name
                FROM conversations conv
                JOIN customers c ON conv.customer_id = c.id
                WHERE conv.id=?
            ''', (cid,)).fetchone()
            turns = db.execute('''
                SELECT id, customer_id, request_id, messages, result, created_at
                FROM agent_turns WHERE conversation_id=?
                ORDER BY id ASC
            ''', (cid,)).fetchall()
            feedbacks = db.execute('''
                SELECT * FROM conversation_feedback WHERE conversation_id=?
                ORDER BY id ASC
            ''', (cid,)).fetchall()
        return {
            'conversation': dict(conv) if conv else None,
            'turns': [dict(t) for t in turns],
            'feedbacks': [dict(f) for f in feedbacks]
        }

    def staff_reply(self, customer_id, cid, staff_name, message):
        require(isinstance(message, str) and message.strip(), 400, 'invalid_message', 'Tin nhắn không được để trống.')
        staff_name = staff_name.strip() if (staff_name and isinstance(staff_name, str)) else "Mai Anh (Chuyên viên CSKH)"
        now = time.time()
        req_id = f"staff-{uuid.uuid4().hex[:12]}"
        with self.connection(write=True) as db:
            conv = db.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone()
            require(conv is not None, 404, 'conversation_not_found', 'Cuộc trò chuyện không tồn tại hoặc đã bị xóa.')
            
            turn_messages = [
                {"role": "assistant", "content": message}
            ]
            turn_result = {
                "message": message,
                "author": "staff",
                "staff_name": staff_name,
                "context": {"order_id": conv["order_id"], "product_id": conv["product_id"]},
                "trace": {"staff": True, "staff_name": staff_name}
            }
            
            cursor = db.execute('''
                INSERT INTO agent_turns(conversation_id, customer_id, request_id, input_hash, messages, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
            ''', (cid, customer_id, req_id, "staff-reply",
                  json.dumps(turn_messages, ensure_ascii=False),
                  json.dumps(turn_result, ensure_ascii=False), now))
            row = cursor.fetchone()
            turn_id = row['id'] if row and 'id' in row else (row[0] if row else getattr(cursor, 'lastrowid', None))
            
            db.execute('UPDATE conversations SET revision=revision+1, expires_at=? WHERE id=?', (now + self.CONVERSATION_TTL, cid))
            db.execute('''
                UPDATE conversation_feedback
                SET comment=?
                WHERE conversation_id=? AND feedback_type='human_handoff' AND reason_code!='resolved'
            ''', (f"Đang xử lý bởi {staff_name}: {message[:120]}", cid))
            
            self.log(db, customer_id, 'staff_replied', conv['order_id'], staff_name=staff_name, message=message)
            
        return {
            'status': 'ok',
            'turn_id': turn_id,
            'request_id': req_id,
            'staff_name': staff_name,
            'message': message,
            'created_at': now
        }

    def customer_message(self, customer_id, cid, message):
        require(isinstance(message, str) and message.strip(), 400, 'invalid_message', 'Tin nhắn không được để trống.')
        now = time.time()
        req_id = f"cust-{uuid.uuid4().hex[:12]}"
        with self.connection(write=True) as db:
            conv = db.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone()
            require(conv is not None, 404, 'conversation_not_found', 'Cuộc trò chuyện không tồn tại hoặc đã bị xóa.')
            require(conv['customer_id'] == customer_id, 403, 'forbidden', 'Không có quyền gửi tin nhắn trong cuộc trò chuyện này.')
            
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
            
            existing_fb = db.execute('''
                SELECT id FROM conversation_feedback
                WHERE conversation_id=? AND feedback_type='human_handoff' AND reason_code!='resolved'
                ORDER BY id DESC LIMIT 1
            ''', (cid,)).fetchone()
            if existing_fb:
                db.execute('UPDATE conversation_feedback SET comment=? WHERE id=?', (message[:200], existing_fb['id']))
            else:
                db.execute('''
                    INSERT INTO conversation_feedback(conversation_id, turn_id, customer_id, feedback_type, reason_code, comment, created_at)
                    VALUES (?, ?, ?, 'human_handoff', 'customer_message', ?, ?)
                ''', (cid, turn_id, customer_id, message[:200], now))
            
            self.log(db, customer_id, 'customer_messaged_staff', conv['order_id'], message=message)
            
        return {
            'status': 'ok',
            'turn_id': turn_id,
            'request_id': req_id,
            'message': message,
            'created_at': now
        }

    def resolve_escalation(self, cid, staff_name=None):
        staff_name = staff_name or "Mai Anh (Chuyên viên CSKH)"
        with self.connection(write=True) as db:
            conv = db.execute('SELECT customer_id, order_id FROM conversations WHERE id=?', (cid,)).fetchone()
            if conv:
                db.execute('''
                    UPDATE conversation_feedback
                    SET reason_code='resolved'
                    WHERE conversation_id=? AND feedback_type='human_handoff'
                ''', (cid,))
                self.log(db, conv['customer_id'], 'escalation_resolved', conv['order_id'], staff_name=staff_name)
        return {'status': 'ok', 'resolved': True}


    def propose(self, customer, body):
        fields(body, {"order_id", "order_version", "cancel_reason"})
        oid, version, reason = body["order_id"], body["order_version"], body["cancel_reason"]
        require(isinstance(oid, str) and type(version) is int and isinstance(reason, str) and reason in REASONS,
                400, "invalid_proposal", "Chọn mã đơn và một lý do được hỗ trợ.")
        with self.connection(write=True) as db:
            order = self.owned(db, customer, oid)
            require(order["status"] == "pending", 409, "not_cancellable", "Đơn không còn ở trạng thái cho phép hủy.")
            require(order["version"] == version, 409, "stale_order", "Đơn đã thay đổi. Vui lòng tải lại thông tin.")
            pid, expires = str(uuid.uuid4()), time.time() + 600
            db.execute("INSERT INTO proposals(id,customer_id,order_id,order_version,reason,expires_at) VALUES (?,?,?,?,?,?)",
                       (pid, customer, oid, version, reason, expires))
            self.log(db, customer, "cancellation_proposed", oid, proposal_id=pid, reason=reason)
        return {"proposal_id": pid, "order": order, "reason": reason, "expires_at": expires,
                "message": "Đơn chưa bị hủy. Vui lòng xem lại và xác nhận."}

    def confirm(self, customer, pid, body, key):
        fields(body, {"confirmed"})
        require(body["confirmed"] is True, 400, "confirmation_required", "Cần xác nhận rõ ràng trước khi hủy.")
        require(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key),
                400, "idempotency_required", "Thiếu mã chống thực hiện lặp.")
        with self.connection(write=True) as db:
            p = db.execute("SELECT * FROM proposals WHERE id=? AND customer_id=?", (pid, customer)).fetchone()
            require(p is not None, 404, "proposal_not_found", "Không tìm thấy đề xuất của bạn.")
            if p["state"] == "confirmed":
                require(hmac.compare_digest(p["confirm_key"], key), 409, "already_confirmed", "Đề xuất đã được thực hiện.")
                return {**json.loads(p["result"]), "replayed": True}
            require(p["state"] == "pending" and p["expires_at"] > time.time(),
                    409, "inactive_proposal", "Đề xuất đã hết hạn hoặc bị bỏ. Hãy tạo yêu cầu mới.")
            used = db.execute("SELECT id FROM proposals WHERE customer_id=? AND confirm_key=?", (customer, key)).fetchone()
            require(used is None, 409, "idempotency_conflict", "Mã xác nhận đã dùng cho đề xuất khác.")
            order = self.owned(db, customer, p["order_id"])
            require(order["status"] == "pending" and order["version"] == p["order_version"],
                    409, "stale_order", "Đơn đã thay đổi; yêu cầu hủy chưa được thực hiện.")
            db.execute("UPDATE orders SET status='cancelled', version=version+1, cancel_reason=? WHERE id=? AND customer_id=?",
                       (p["reason"], p["order_id"], customer))
            order = self.owned(db, customer, p["order_id"])
            result = {"order": order, "proposal_id": pid, "replayed": False, "message": "Đã hủy đơn mẫu và lưu nhật ký."}
            db.execute("UPDATE proposals SET state='confirmed', confirm_key=?, result=? WHERE id=?",
                       (key, json.dumps(result, ensure_ascii=False), pid))
            self.log(db, customer, "order_cancelled", order["id"], proposal_id=pid, reason=p["reason"], version=order["version"])
            return result

    def dismiss(self, customer, pid):
        with self.connection(write=True) as db:
            p = db.execute("SELECT * FROM proposals WHERE id=? AND customer_id=?", (pid, customer)).fetchone()
            require(p is not None, 404, "proposal_not_found", "Không tìm thấy đề xuất của bạn.")
            require(p["state"] != "confirmed", 409, "already_confirmed", "Đơn đã được hủy; không thể giữ lại bằng thao tác này.")
            if p["state"] == "pending":
                db.execute("UPDATE proposals SET state='dismissed' WHERE id=?", (pid,))
                self.log(db, customer, "proposal_dismissed", p["order_id"], proposal_id=pid)
        return {"message": "Đã bỏ đề xuất. Trạng thái đơn được giữ nguyên."}
