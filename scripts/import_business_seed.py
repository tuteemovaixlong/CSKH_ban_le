#!/usr/bin/env python3
"""Script import dữ liệu nghiệp vụ thực tế từ DeepSeek (Lần 1 - Business Mock Data).

Đọc file data/deepseek_seed_data.json, kiểm tra hợp lệ toàn vẹn schema,
sau đó nạp vào SQLite database, data/products.json và cập nhật telemetry.
Bảo toàn 100% dữ liệu kiểm thử hồi quy (C-001..C-004, O-101..O-102, O-301..O-304).
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = ROOT / "data" / "deepseek_seed_data.json"
PRODUCTS_FILE = ROOT / "data" / "products.json"
DB_FILE = ROOT / "artifacts" / "business.sqlite3"

PROTECTED_ORDERS = {"O-101", "O-102", "O-103", "O-202", "O-301", "O-302", "O-303", "O-304"}
PROTECTED_CUSTOMERS = {"C-001", "C-002", "C-003", "C-004"}
PROTECTED_PRODUCTS = {"P-101", "P-102", "P-103", "P-104", "P-202", "P-203", "P-301", "P-401"}


def validate_seed_data(data: dict):
    """Kiểm tra tính toàn vẹn của dữ liệu sinh từ DeepSeek trước khi nạp."""
    errors = []

    # 1. Kiểm tra Products
    products = data.get("products", [])
    if not isinstance(products, list) or len(products) == 0:
        errors.append("Trường 'products' phải là danh sách không rỗng.")
    for p in products:
        pid = p.get("id", "")
        if pid in PROTECTED_PRODUCTS:
            errors.append(f"Product ID '{pid}' trùng với ID bảo vệ của bài kiểm thử!")
        if not re.fullmatch(r"P-[0-9]{3,4}", pid):
            errors.append(f"Product ID '{pid}' không đúng định dạng P-xxx.")
        if not p.get("name") or not isinstance(p.get("price"), (int, float)):
            errors.append(f"Product '{pid}' thiếu name hoặc price hợp lệ.")

    # 2. Kiểm tra Customers
    customers = data.get("customers", [])
    if not isinstance(customers, list) or len(customers) == 0:
        errors.append("Trường 'customers' phải là danh sách không rỗng.")
    for c in customers:
        cid = c.get("id", "")
        if cid in PROTECTED_CUSTOMERS:
            errors.append(f"Customer ID '{cid}' trùng với ID bảo vệ của bài kiểm thử!")
        if not re.fullmatch(r"C-[0-9]{3,4}", cid):
            errors.append(f"Customer ID '{cid}' không đúng định dạng C-xxx.")

    # 3. Kiểm tra Orders
    orders = data.get("orders", [])
    if not isinstance(orders, list) or len(orders) == 0:
        errors.append("Trường 'orders' phải là danh sách không rỗng.")
    for o in orders:
        oid = o.get("id", "")
        if oid in PROTECTED_ORDERS:
            errors.append(f"Order ID '{oid}' trùng với ID bảo vệ của bài kiểm thử!")
        if not re.fullmatch(r"O-[0-9]{3,4}", oid):
            errors.append(f"Order ID '{oid}' không đúng định dạng O-xxx.")
        status = o.get("status", "")
        if status not in ("pending", "delivered", "cancelled"):
            errors.append(f"Order '{oid}' có status='{status}' không hợp lệ (chỉ được: pending, delivered, cancelled).")
        for req_field in ("customer_id", "name", "variant", "amount"):
            if req_field not in o:
                errors.append(f"Order '{oid}' thiếu trường bắt buộc: {req_field}")

    if errors:
        raise ValueError("Dữ liệu seed không hợp lệ:\n- " + "\n- ".join(errors))


def apply_seed_data(data: dict):
    """Nạp dữ liệu an toàn vào SQLite và files cấu hình."""
    print("===> 1. Cập nhật data/products.json...")
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    existing_pids = {p["id"] for p in catalog.get("products", [])}
    added_products = 0
    for p in data.get("products", []):
        if p["id"] not in existing_pids:
            item = {
                "id": p["id"],
                "name": p["name"],
                "category": p.get("category", "Sản phẩm TMĐT"),
                "price": p["price"],
                "description": p.get("description", ""),
                "attributes": p.get("attributes", {}),
                "aliases": p.get("aliases", [p["name"].lower()])
            }
            catalog["products"].append(item)
            added_products += 1

    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    print(f"   Đã thêm {added_products} sản phẩm mới vào catalog.")

    print("===> 2. Nạp dữ liệu vào Database SQLite (artifacts/business.sqlite3)...")
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as db:
        db.execute("CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                name TEXT NOT NULL,
                variant TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'delivered', 'cancelled')),
                version INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """)

        added_cust = 0
        for c in data.get("customers", []):
            cur = db.execute("INSERT OR IGNORE INTO customers (id, name) VALUES (?, ?)", (c["id"], c["name"]))
            if cur.rowcount > 0:
                added_cust += 1

        added_ord = 0
        for o in data.get("orders", []):
            cur = db.execute(
                "INSERT OR IGNORE INTO orders (id, customer_id, name, variant, amount, status) VALUES (?, ?, ?, ?, ?, ?)",
                (o["id"], o["customer_id"], o["name"], o["variant"], o["amount"], o["status"])
            )
            if cur.rowcount > 0:
                added_ord += 1

    print(f"   Đã thêm {added_cust} khách hàng, {added_ord} đơn hàng vào SQLite.")

    # 3. Lưu Shipments Telemetry
    shipments = data.get("shipments", {})
    if shipments:
        print("===> 3. Cập nhật telemetry vận chuyển (data/mock_shipments.json)...")
        ship_file = ROOT / "data" / "mock_shipments.json"
        existing_ships = {}
        if ship_file.exists():
            try:
                with open(ship_file, "r", encoding="utf-8") as f:
                    existing_ships = json.load(f)
            except Exception:
                pass
        existing_ships.update(shipments)
        with open(ship_file, "w", encoding="utf-8") as f:
            json.dump(existing_ships, f, ensure_ascii=False, indent=2)
        print(f"   Đã cập nhật {len(shipments)} vận đơn vào data/mock_shipments.json.")

    # 4. Đồng bộ lại Colab Notebook
    print("===> 4. Đồng bộ hóa Google Colab Notebook...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_agent_notebook.py")], check=True)
    print("   Đã đồng bộ notebooks/colab_agent.ipynb thành công!")

    # 4. Chạy test kiểm tra toàn vẹn
    print("===> 4. Chạy kiểm tra hồi quy hệ thống (261 tests)...")
    res = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], capture_output=True, text=True)
    if res.returncode == 0:
        print("   TẤT CẢ CÁC BÀI KIỂM THỬ ĐỀU XANH 100%! HỆ THỐNG AN TOÀN.")
    else:
        print("   CẢNH BÁO: Có bài test bị ảnh hưởng:")
        print(res.stderr[-500:])


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else SEED_FILE
    if not target.exists():
        print(f"Lỗi: Không tìm thấy file dữ liệu tại {target}")
        print("Hướng dẫn: Tạo file data/deepseek_seed_data.json và dán JSON từ DeepSeek vào.")
        sys.exit(1)

    print(f"Đọc dữ liệu từ {target}...")
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)

    validate_seed_data(data)
    apply_seed_data(data)
    print("\nHOÀN TẤT NẠP DỮ LIỆU NGHIỆP VỤ THỰC TẾ LẦN 1 TỪ DEEPSEEK!")


if __name__ == "__main__":
    main()
