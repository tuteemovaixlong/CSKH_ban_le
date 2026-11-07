"""13 kịch bản có tên cố định tương đối so với đồng hồ mô phỏng (W6.1a mục 7)."""

from __future__ import annotations

from datetime import datetime, timedelta
import random
import sqlite3
from typing import Any, Callable

from .contract import parse_iso_vn
from .fixtures import ORIGIN_WAREHOUSE, SHIPPERS, SORTING_HUB_BY_ZONE, SYNTHETIC_DISPLAY_NAMES
from .simulator import MarketplaceSimulator, derive_seed

STORY_NAMES: tuple[str, ...] = (
    "giao_dung_han_cod",
    "dang_trung_chuyen",
    "cap_nhat_ao_giao_lai",
    "giao_that_bai_hoan_ve",
    "nghen_kho_mega_sale",
    "hoan_tien_cham",
    "hoan_tien_that_bai",
    "thanh_toan_that_bai_roi_thanh_cong",
    "huy_truoc_khi_giao",
    "doi_size_trong_han",
    "qua_han_doi_tra",
    "het_bao_hanh",
    "giao_tre_han_cam_ket",
)


def _find_sku(sim: MarketplaceSimulator, sku: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for prod in sim.catalog:
        for var in prod["variants"]:
            if var["sku"] == sku:
                return prod, var
    raise KeyError(f"Không tìm thấy SKU '{sku}' trong catalog.")


def _alloc_story_context(
    sim: MarketplaceSimulator,
    conn: sqlite3.Connection,
    story_name: str,
    *,
    sku: str,
    zone_filter: str = "intra_city",
    carrier: str = "GHN",
) -> dict[str, Any]:
    seed = int(sim._get_meta(conn, "seed"))
    story_seq = sim._alloc_counter(conn, "next_story_no")
    c_no = sim._alloc_counter(conn, "next_customer_no")
    o_no = sim._alloc_counter(conn, "next_order_no")

    rng = random.Random(derive_seed(seed, "story", story_name, story_seq))
    clock_dt = parse_iso_vn(sim._get_meta(conn, "clock_iso"), "clock_iso")
    assert clock_dt is not None

    cust_id = f"SIM-C-{c_no:04d}"
    cust_name = SYNTHETIC_DISPLAY_NAMES[(c_no - 1) % len(SYNTHETIC_DISPLAY_NAMES)]
    order_id = f"SIM-O-ST-{story_seq:03d}"

    recipient, zone = sim.build_synthetic_recipient(
        rng, preferred_name=cust_name, zone_filter=zone_filter
    )
    shipping_fee = int(sim.params["shipping_fee_by_zone"][zone])

    prod, var = _find_sku(sim, sku)
    item = {
        "sku": var["sku"],
        "external_product_id": prod["external_product_id"],
        "title": prod["title"],
        "variant_name": var["variant_name"],
        "quantity": 1,
        "unit_price": int(var["price"]),
    }
    total = int(var["price"]) + shipping_fee
    shipper = SHIPPERS[(story_seq - 1) % len(SHIPPERS)]

    return {
        "story_seq": story_seq,
        "clock_dt": clock_dt,
        "cust_id": cust_id,
        "cust_name": cust_name,
        "order_id": order_id,
        "recipient": recipient,
        "zone": zone,
        "carrier": carrier,
        "shipping_fee": shipping_fee,
        "items": [item],
        "subtotal": int(var["price"]),
        "total": total,
        "shipper": shipper,
    }


def _emit_standard_prepaid(
    sim: MarketplaceSimulator,
    conn: sqlite3.Connection,
    *,
    order_id: str,
    method: str,
    amount: int,
    start_dt: datetime,
) -> str:
    p_no = sim._alloc_counter(conn, "next_payment_no")
    txn_ref = f"PAYSIM-TXN-ST-{p_no:05d}"
    sim.emit_payment_updated(
        conn,
        provider="PAYSIM_GATEWAY",
        provider_txn_ref=txn_ref,
        external_order_id=order_id,
        method=method,
        amount=amount,
        provider_status_raw="PAY_PENDING",
        occurred_dt=start_dt,
    )
    sim.emit_payment_updated(
        conn,
        provider="PAYSIM_GATEWAY",
        provider_txn_ref=txn_ref,
        external_order_id=order_id,
        method=method,
        amount=amount,
        provider_status_raw="PAY_SUCCEEDED",
        occurred_dt=start_dt + timedelta(minutes=3),
    )
    return txn_ref


def _emit_shipment_to_sorting(
    sim: MarketplaceSimulator,
    conn: sqlite3.Connection,
    *,
    order_id: str,
    carrier: str,
    zone: str,
    start_dt: datetime,
    est_dt: datetime,
    sorting_dt: datetime | None = None,
    sorting_hub_override: dict[str, str] | None = None,
    sorting_desc: str = "Kiện hàng đang được phân loại tại tổng kho trung chuyển.",
) -> tuple[str, str]:
    s_no = sim._alloc_counter(conn, "next_shipment_no")
    shp_id = f"SIM-SHP-ST-{s_no:04d}"
    tracking = f"{sim.carriers[carrier]['tracking_prefix']}ST{s_no:04d}"
    soc = sorting_hub_override or SORTING_HUB_BY_ZONE[zone]

    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=order_id,
        carrier=carrier,
        tracking_code=tracking,
        stage="ready_to_pick",
        hub_name=ORIGIN_WAREHOUSE["hub_name"],
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Shop đã tạo vận đơn, chờ lấy hàng.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=est_dt,
        occurred_dt=start_dt,
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=order_id,
        carrier=carrier,
        tracking_code=tracking,
        stage="picking",
        hub_name=ORIGIN_WAREHOUSE["hub_name"],
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Bưu tá đang tới kho lấy hàng.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=est_dt,
        occurred_dt=start_dt + timedelta(hours=1),
    )
    t_picked = start_dt + timedelta(hours=2)
    sim.emit_order_status_changed(
        conn,
        external_order_id=order_id,
        target_status="shipping",
        reason=None,
        occurred_dt=t_picked,
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=order_id,
        carrier=carrier,
        tracking_code=tracking,
        stage="picked",
        hub_name=ORIGIN_WAREHOUSE["hub_name"],
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Đã lấy hàng thành công từ kho bán.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=est_dt,
        occurred_dt=t_picked,
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=order_id,
        carrier=carrier,
        tracking_code=tracking,
        stage="storing",
        hub_name="Bưu cục thu gom Tân Bình",
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Kiện hàng đã nhập bưu cục gửi.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=est_dt,
        occurred_dt=start_dt + timedelta(hours=4),
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=order_id,
        carrier=carrier,
        tracking_code=tracking,
        stage="transporting",
        hub_name=soc["hub_name"],
        district=soc["district"],
        province=soc["province"],
        description="Kiện hàng đang trung chuyển tới tổng kho phân loại.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=est_dt,
        occurred_dt=start_dt + timedelta(hours=7),
    )
    t_sort = sorting_dt if sorting_dt is not None else (start_dt + timedelta(hours=12))
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=order_id,
        carrier=carrier,
        tracking_code=tracking,
        stage="sorting",
        hub_name=soc["hub_name"],
        district=soc["district"],
        province=soc["province"],
        description=sorting_desc,
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=est_dt,
        occurred_dt=t_sort,
    )
    return shp_id, tracking


def _complete_delivery(
    sim: MarketplaceSimulator,
    conn: sqlite3.Connection,
    *,
    shp_id: str,
    order_id: str,
    carrier: str,
    tracking: str,
    recipient: dict[str, str],
    shipper: dict[str, str],
    delivering_dt: datetime,
    delivered_dt: datetime,
    cod_amount: int | None = None,
) -> None:
    dest_hub = f"Bưu cục phát {recipient['district']}"
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=order_id,
        carrier=carrier,
        tracking_code=tracking,
        stage="delivering",
        hub_name=dest_hub,
        district=recipient["district"],
        province=recipient["province"],
        description="Bưu tá đang đi giao kiện hàng tới người nhận.",
        fail_reason=None,
        shipper_name=shipper["name"],
        shipper_phone_masked=shipper["phone_masked"],
        estimated_delivery_dt=delivered_dt,
        occurred_dt=delivering_dt,
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=order_id,
        carrier=carrier,
        tracking_code=tracking,
        stage="delivered",
        hub_name=dest_hub,
        district=recipient["district"],
        province=recipient["province"],
        description="Giao hàng thành công cho người nhận.",
        fail_reason=None,
        shipper_name=shipper["name"],
        shipper_phone_masked=shipper["phone_masked"],
        estimated_delivery_dt=None,
        occurred_dt=delivered_dt,
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=order_id,
        target_status="delivered",
        reason=None,
        occurred_dt=delivered_dt,
    )
    if cod_amount is not None:
        cp_no = sim._alloc_counter(conn, "next_payment_no")
        sim.emit_payment_updated(
            conn,
            provider=carrier,
            provider_txn_ref=f"COD-TXN-ST-{cp_no:05d}",
            external_order_id=order_id,
            method="cod",
            amount=cod_amount,
            provider_status_raw="COD_SETTLED",
            occurred_dt=delivered_dt,
        )


# ----------------------------------------------------------------------
# 13 kịch bản cụ thể
# ----------------------------------------------------------------------
def _story_giao_dung_han_cod(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, "giao_dung_han_cod", sku="SKU-P101-TRANG-M", zone_filter="same_region"
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(days=3)
    promised_dt = ordered_dt + timedelta(days=4)
    delivered_dt = now

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="cod",
        recipient=ctx["recipient"],
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=30),
    )
    shp_id, tracking = _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=2),
        est_dt=promised_dt,
    )
    _complete_delivery(
        sim,
        conn,
        shp_id=shp_id,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking=tracking,
        recipient=ctx["recipient"],
        shipper=ctx["shipper"],
        delivering_dt=delivered_dt - timedelta(hours=3),
        delivered_dt=delivered_dt,
        cod_amount=ctx["total"],
    )
    return {"story": "giao_dung_han_cod", "external_order_id": ctx["order_id"]}


def _story_dang_trung_chuyen(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, "dang_trung_chuyen", sku="SKU-P102-DEN-L", zone_filter="inter_region"
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(hours=24)
    promised_dt = ordered_dt + timedelta(hours=96)

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="bank_transfer",
        recipient=ctx["recipient"],
    )
    _emit_standard_prepaid(
        sim,
        conn,
        order_id=ctx["order_id"],
        method="bank_transfer",
        amount=ctx["total"],
        start_dt=ordered_dt + timedelta(minutes=2),
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=30),
    )

    s_no = sim._alloc_counter(conn, "next_shipment_no")
    shp_id = f"SIM-SHP-ST-{s_no:04d}"
    tracking = f"{sim.carriers[ctx['carrier']]['tracking_prefix']}ST{s_no:04d}"
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="ready_to_pick",
        hub_name=ORIGIN_WAREHOUSE["hub_name"],
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Shop đã chuẩn bị hàng, chờ bưu tá nhận kiện.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=promised_dt,
        occurred_dt=ordered_dt + timedelta(hours=2),
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="picking",
        hub_name=ORIGIN_WAREHOUSE["hub_name"],
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Bưu tá đang tới kho người bán.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=promised_dt,
        occurred_dt=ordered_dt + timedelta(hours=4),
    )
    t_picked = ordered_dt + timedelta(hours=5)
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="shipping",
        reason=None,
        occurred_dt=t_picked,
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="picked",
        hub_name=ORIGIN_WAREHOUSE["hub_name"],
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Đã lấy hàng khỏi kho bán.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=promised_dt,
        occurred_dt=t_picked,
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="storing",
        hub_name="Bưu cục thu gom Tân Bình",
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Kiện hàng lưu kho chờ xuất tuyến liên tỉnh.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=promised_dt,
        occurred_dt=ordered_dt + timedelta(hours=8),
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="transporting",
        hub_name="Trạm Trung Chuyển Liên Tỉnh Đà Nẵng",
        district="Quận Liên Chiểu",
        province="Đà Nẵng",
        description="Kiện hàng đang trên xe tải liên tỉnh hướng Bắc.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=promised_dt,
        occurred_dt=now - timedelta(hours=3),
    )
    return {"story": "dang_trung_chuyen", "external_order_id": ctx["order_id"]}


def _story_cap_nhat_ao_giao_lai(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, "cap_nhat_ao_giao_lai", sku="SKU-P202-XANH-M", zone_filter="intra_city"
    )
    now = ctx["clock_dt"]
    # Chọn ngày giao sao cho lần báo thất bại buổi sáng và giao lại buổi chiều nằm trọn trong cùng một ngày dương lịch <= now
    if now.hour >= 17:
        delivery_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        delivery_day = (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    ordered_dt = delivery_day - timedelta(days=2) + timedelta(hours=9)
    promised_dt = ordered_dt + timedelta(hours=72)

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="card",
        recipient=ctx["recipient"],
    )
    _emit_standard_prepaid(
        sim,
        conn,
        order_id=ctx["order_id"],
        method="card",
        amount=ctx["total"],
        start_dt=ordered_dt + timedelta(minutes=1),
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=20),
    )
    shp_id, tracking = _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=2),
        est_dt=promised_dt,
    )
    dest_hub = f"Bưu cục phát {ctx['recipient']['district']}"
    t_morning_out = delivery_day + timedelta(hours=8, minutes=30)
    t_morning_fail = delivery_day + timedelta(hours=10, minutes=15)
    t_afternoon_out = delivery_day + timedelta(hours=14, minutes=0)
    t_afternoon_ok = delivery_day + timedelta(hours=16, minutes=20)

    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="delivering",
        hub_name=dest_hub,
        district=ctx["recipient"]["district"],
        province=ctx["recipient"]["province"],
        description="Bưu tá xuất kho giao ca sáng.",
        fail_reason=None,
        shipper_name=ctx["shipper"]["name"],
        shipper_phone_masked=ctx["shipper"]["phone_masked"],
        estimated_delivery_dt=delivery_day + timedelta(hours=12),
        occurred_dt=t_morning_out,
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="delivery_fail",
        hub_name=dest_hub,
        district=ctx["recipient"]["district"],
        province=ctx["recipient"]["province"],
        description="Bưu tá báo chưa giao được kiện hàng.",
        fail_reason="Khách không nghe máy, không liên lạc được",
        shipper_name=ctx["shipper"]["name"],
        shipper_phone_masked=ctx["shipper"]["phone_masked"],
        estimated_delivery_dt=delivery_day + timedelta(hours=18),
        occurred_dt=t_morning_fail,
    )
    _complete_delivery(
        sim,
        conn,
        shp_id=shp_id,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking=tracking,
        recipient=ctx["recipient"],
        shipper=ctx["shipper"],
        delivering_dt=t_afternoon_out,
        delivered_dt=t_afternoon_ok,
    )
    return {"story": "cap_nhat_ao_giao_lai", "external_order_id": ctx["order_id"]}


def _story_giao_that_bai_hoan_ve(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, "giao_that_bai_hoan_ve", sku="SKU-P103-TRANG-M", zone_filter="same_region"
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(days=7)
    promised_dt = ordered_dt + timedelta(hours=72)

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="cod",
        recipient=ctx["recipient"],
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=30),
    )
    shp_id, tracking = _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=2),
        est_dt=promised_dt,
    )
    dest_hub = f"Bưu cục phát {ctx['recipient']['district']}"
    soc = SORTING_HUB_BY_ZONE[ctx["zone"]]
    reasons = [
        "Lần 1: Khách không nghe máy khi bưu tá gọi",
        "Lần 2: Địa chỉ đóng cửa, người nhận hẹn giao lại",
        "Lần 3: Không liên lạc được với người nhận quá thời hạn giữ hàng",
    ]
    for idx in range(3):
        t_out = ordered_dt + timedelta(days=2 + idx, hours=2)
        t_fail = t_out + timedelta(hours=3)
        sim.emit_shipment_updated(
            conn,
            external_shipment_id=shp_id,
            external_order_id=ctx["order_id"],
            carrier=ctx["carrier"],
            tracking_code=tracking,
            stage="delivering",
            hub_name=dest_hub,
            district=ctx["recipient"]["district"],
            province=ctx["recipient"]["province"],
            description=f"Bưu tá đi phát lần {idx + 1}.",
            fail_reason=None,
            shipper_name=ctx["shipper"]["name"],
            shipper_phone_masked=ctx["shipper"]["phone_masked"],
            estimated_delivery_dt=t_out + timedelta(hours=5),
            occurred_dt=t_out,
        )
        sim.emit_shipment_updated(
            conn,
            external_shipment_id=shp_id,
            external_order_id=ctx["order_id"],
            carrier=ctx["carrier"],
            tracking_code=tracking,
            stage="delivery_fail",
            hub_name=dest_hub,
            district=ctx["recipient"]["district"],
            province=ctx["recipient"]["province"],
            description=f"Giao hàng thất bại lần {idx + 1}.",
            fail_reason=reasons[idx],
            shipper_name=ctx["shipper"]["name"],
            shipper_phone_masked=ctx["shipper"]["phone_masked"],
            estimated_delivery_dt=None,
            occurred_dt=t_fail,
        )

    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="waiting_to_return",
        hub_name=dest_hub,
        district=ctx["recipient"]["district"],
        province=ctx["recipient"]["province"],
        description="Đã thất bại đủ 3 lần, chờ chuyển hoàn về người bán.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=None,
        occurred_dt=now - timedelta(hours=36),
    )
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="return",
        hub_name=soc["hub_name"],
        district=soc["district"],
        province=soc["province"],
        description="Kiện hàng đang hoàn trả về kho người bán.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=None,
        occurred_dt=now - timedelta(hours=20),
    )
    t_returned = now - timedelta(hours=2)
    sim.emit_shipment_updated(
        conn,
        external_shipment_id=shp_id,
        external_order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking_code=tracking,
        stage="returned",
        hub_name=ORIGIN_WAREHOUSE["hub_name"],
        district=ORIGIN_WAREHOUSE["district"],
        province=ORIGIN_WAREHOUSE["province"],
        description="Đã hoàn trả kiện hàng cho người bán.",
        fail_reason=None,
        shipper_name=None,
        shipper_phone_masked=None,
        estimated_delivery_dt=None,
        occurred_dt=t_returned,
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="cancelled",
        reason="Giao thất bại 3 lần, kiện hàng đã hoàn về shop",
        occurred_dt=t_returned,
    )
    return {"story": "giao_that_bai_hoan_ve", "external_order_id": ctx["order_id"]}


def _story_nghen_kho_mega_sale(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, "nghen_kho_mega_sale", sku="SKU-P503-BE-M", zone_filter="inter_region"
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(hours=68)
    promised_dt = ordered_dt + timedelta(hours=72)
    sorting_entered_dt = now - timedelta(hours=54)  # Kẹt > 48 giờ tính tới đồng hồ hiện tại

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="e_wallet",
        recipient=ctx["recipient"],
    )
    _emit_standard_prepaid(
        sim,
        conn,
        order_id=ctx["order_id"],
        method="e_wallet",
        amount=ctx["total"],
        start_dt=ordered_dt + timedelta(minutes=2),
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=25),
    )
    _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=1),
        est_dt=now + timedelta(hours=36),
        sorting_dt=sorting_entered_dt,
        sorting_hub_override={
            "hub_name": "Kho Phân Loại Bắc Ninh Mega SOC",
            "district": "TP. Từ Sơn",
            "province": "Bắc Ninh",
        },
        sorting_desc="Kiện hàng đợt Mega Sale đang chờ phân loại tại tổng kho Mega SOC quá tải.",
    )
    return {"story": "nghen_kho_mega_sale", "external_order_id": ctx["order_id"]}


def _story_hoan_tien_cham(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, "hoan_tien_cham", sku="SKU-P401-BAC-BO3", zone_filter="intra_city"
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(days=16)
    promised_dt = ordered_dt + timedelta(hours=48)
    delivered_dt = now - timedelta(days=13)

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="bank_transfer",
        recipient=ctx["recipient"],
    )
    _emit_standard_prepaid(
        sim,
        conn,
        order_id=ctx["order_id"],
        method="bank_transfer",
        amount=ctx["total"],
        start_dt=ordered_dt + timedelta(minutes=2),
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=30),
    )
    shp_id, tracking = _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=2),
        est_dt=promised_dt,
    )
    _complete_delivery(
        sim,
        conn,
        shp_id=shp_id,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking=tracking,
        recipient=ctx["recipient"],
        shipper=ctx["shipper"],
        delivering_dt=delivered_dt - timedelta(hours=3),
        delivered_dt=delivered_dt,
    )

    r_no = sim._alloc_counter(conn, "next_refund_no")
    rfd_ref = f"PAYSIM-RFD-ST-{r_no:05d}"
    init_dt = now - timedelta(days=11)
    proc_dt = now - timedelta(days=10, hours=6)
    sim.emit_refund_updated(
        conn,
        provider_refund_ref=rfd_ref,
        external_order_id=ctx["order_id"],
        amount=ctx["subtotal"],
        channel="original_method",
        provider_status_raw="REFUND_INITIATED",
        failure_reason=None,
        initiated_dt=init_dt,
        occurred_dt=init_dt,
    )
    sim.emit_refund_updated(
        conn,
        provider_refund_ref=rfd_ref,
        external_order_id=ctx["order_id"],
        amount=ctx["subtotal"],
        channel="original_method",
        provider_status_raw="REFUND_PROCESSING",
        failure_reason=None,
        initiated_dt=init_dt,
        occurred_dt=proc_dt,
    )
    return {"story": "hoan_tien_cham", "external_order_id": ctx["order_id"]}


def _story_hoan_tien_that_bai(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, "hoan_tien_that_bai", sku="SKU-P301-TC-42", zone_filter="intra_city"
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(days=8)
    promised_dt = ordered_dt + timedelta(hours=48)
    delivered_dt = now - timedelta(days=5)

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="e_wallet",
        recipient=ctx["recipient"],
    )
    _emit_standard_prepaid(
        sim,
        conn,
        order_id=ctx["order_id"],
        method="e_wallet",
        amount=ctx["total"],
        start_dt=ordered_dt + timedelta(minutes=2),
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=30),
    )
    shp_id, tracking = _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=2),
        est_dt=promised_dt,
    )
    _complete_delivery(
        sim,
        conn,
        shp_id=shp_id,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking=tracking,
        recipient=ctx["recipient"],
        shipper=ctx["shipper"],
        delivering_dt=delivered_dt - timedelta(hours=3),
        delivered_dt=delivered_dt,
    )

    r_no = sim._alloc_counter(conn, "next_refund_no")
    rfd_ref = f"PAYSIM-RFD-ST-{r_no:05d}"
    init_dt = now - timedelta(hours=48)
    sim.emit_refund_updated(
        conn,
        provider_refund_ref=rfd_ref,
        external_order_id=ctx["order_id"],
        amount=ctx["subtotal"],
        channel="e_wallet",
        provider_status_raw="REFUND_INITIATED",
        failure_reason=None,
        initiated_dt=init_dt,
        occurred_dt=init_dt,
    )
    sim.emit_refund_updated(
        conn,
        provider_refund_ref=rfd_ref,
        external_order_id=ctx["order_id"],
        amount=ctx["subtotal"],
        channel="e_wallet",
        provider_status_raw="REFUND_PROCESSING",
        failure_reason=None,
        initiated_dt=init_dt,
        occurred_dt=now - timedelta(hours=44),
    )
    sim.emit_refund_updated(
        conn,
        provider_refund_ref=rfd_ref,
        external_order_id=ctx["order_id"],
        amount=ctx["subtotal"],
        channel="e_wallet",
        provider_status_raw="REFUND_FAILED",
        failure_reason="Tài khoản ví điện tử nhận hoàn đã khóa hoặc hết hạn xác thực",
        initiated_dt=init_dt,
        occurred_dt=now - timedelta(hours=24),
    )
    return {"story": "hoan_tien_that_bai", "external_order_id": ctx["order_id"]}


def _story_thanh_toan_that_bai_roi_thanh_cong(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim,
        conn,
        "thanh_toan_that_bai_roi_thanh_cong",
        sku="SKU-P601-TRANG-M",
        zone_filter="intra_city",
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(days=4)
    promised_dt = ordered_dt + timedelta(hours=48)
    delivered_dt = now - timedelta(days=2)

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="bank_transfer",
        recipient=ctx["recipient"],
    )

    p1_no = sim._alloc_counter(conn, "next_payment_no")
    txn_fail = f"PAYSIM-TXN-ST-{p1_no:05d}"
    sim.emit_payment_updated(
        conn,
        provider="PAYSIM_GATEWAY",
        provider_txn_ref=txn_fail,
        external_order_id=ctx["order_id"],
        method="bank_transfer",
        amount=ctx["total"],
        provider_status_raw="PAY_PENDING",
        occurred_dt=ordered_dt + timedelta(minutes=2),
    )
    sim.emit_payment_updated(
        conn,
        provider="PAYSIM_GATEWAY",
        provider_txn_ref=txn_fail,
        external_order_id=ctx["order_id"],
        method="bank_transfer",
        amount=ctx["total"],
        provider_status_raw="PAY_FAILED",
        occurred_dt=ordered_dt + timedelta(minutes=8),
    )

    _emit_standard_prepaid(
        sim,
        conn,
        order_id=ctx["order_id"],
        method="bank_transfer",
        amount=ctx["total"],
        start_dt=ordered_dt + timedelta(minutes=15),
    )

    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=30),
    )
    shp_id, tracking = _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=2),
        est_dt=promised_dt,
    )
    _complete_delivery(
        sim,
        conn,
        shp_id=shp_id,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking=tracking,
        recipient=ctx["recipient"],
        shipper=ctx["shipper"],
        delivering_dt=delivered_dt - timedelta(hours=3),
        delivered_dt=delivered_dt,
    )
    return {
        "story": "thanh_toan_that_bai_roi_thanh_cong",
        "external_order_id": ctx["order_id"],
    }


def _story_huy_truoc_khi_giao(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, "huy_truoc_khi_giao", sku="SKU-P101-TRANG-S", zone_filter="intra_city"
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(hours=12)
    promised_dt = ordered_dt + timedelta(hours=48)

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="cod",
        recipient=ctx["recipient"],
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(hours=1),
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="cancelled",
        reason="Khách hủy đơn khi đơn còn ở trạng thái confirmed, chưa bàn giao vận chuyển",
        occurred_dt=ordered_dt + timedelta(hours=2),
    )
    return {"story": "huy_truoc_khi_giao", "external_order_id": ctx["order_id"]}


def _build_delivered_days_ago(
    sim: MarketplaceSimulator,
    conn: sqlite3.Connection,
    *,
    story_name: str,
    sku: str,
    days_ago: int,
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim, conn, story_name, sku=sku, zone_filter="intra_city"
    )
    now = ctx["clock_dt"]
    delivered_dt = now - timedelta(days=days_ago)
    ordered_dt = delivered_dt - timedelta(days=2)
    promised_dt = ordered_dt + timedelta(hours=72)

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="bank_transfer",
        recipient=ctx["recipient"],
    )
    _emit_standard_prepaid(
        sim,
        conn,
        order_id=ctx["order_id"],
        method="bank_transfer",
        amount=ctx["total"],
        start_dt=ordered_dt + timedelta(minutes=2),
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=30),
    )
    shp_id, tracking = _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=2),
        est_dt=promised_dt,
    )
    _complete_delivery(
        sim,
        conn,
        shp_id=shp_id,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking=tracking,
        recipient=ctx["recipient"],
        shipper=ctx["shipper"],
        delivering_dt=delivered_dt - timedelta(hours=3),
        delivered_dt=delivered_dt,
    )
    return {"story": story_name, "external_order_id": ctx["order_id"]}


def _story_doi_size_trong_han(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    return _build_delivered_days_ago(
        sim,
        conn,
        story_name="doi_size_trong_han",
        sku="SKU-P101-TRANG-L",
        days_ago=5,
    )


def _story_qua_han_doi_tra(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    return _build_delivered_days_ago(
        sim,
        conn,
        story_name="qua_han_doi_tra",
        sku="SKU-P102-DEN-M",
        days_ago=20,
    )


def _story_het_bao_hanh(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    return _build_delivered_days_ago(
        sim,
        conn,
        story_name="het_bao_hanh",
        sku="SKU-P104-DEN-M",
        days_ago=100,
    )


def _story_giao_tre_han_cam_ket(
    sim: MarketplaceSimulator, conn: sqlite3.Connection
) -> dict[str, Any]:
    ctx = _alloc_story_context(
        sim,
        conn,
        "giao_tre_han_cam_ket",
        sku="SKU-P202-XANH-L",
        zone_filter="same_region",
    )
    now = ctx["clock_dt"]
    ordered_dt = now - timedelta(days=7)
    promised_dt = ordered_dt + timedelta(hours=72)  # now - 4 days
    delivered_dt = promised_dt + timedelta(hours=72)  # Đúng 72 giờ (3 ngày) sau hạn cam kết

    sim.emit_customer_upserted(
        conn,
        external_customer_id=ctx["cust_id"],
        display_name=ctx["cust_name"],
        occurred_dt=ordered_dt - timedelta(minutes=1),
    )
    sim.emit_order_created(
        conn,
        external_order_id=ctx["order_id"],
        external_customer_id=ctx["cust_id"],
        ordered_dt=ordered_dt,
        promised_dt=promised_dt,
        items=ctx["items"],
        shipping_fee=ctx["shipping_fee"],
        payment_method="e_wallet",
        recipient=ctx["recipient"],
    )
    _emit_standard_prepaid(
        sim,
        conn,
        order_id=ctx["order_id"],
        method="e_wallet",
        amount=ctx["total"],
        start_dt=ordered_dt + timedelta(minutes=2),
    )
    sim.emit_order_status_changed(
        conn,
        external_order_id=ctx["order_id"],
        target_status="confirmed",
        reason=None,
        occurred_dt=ordered_dt + timedelta(minutes=30),
    )
    shp_id, tracking = _emit_shipment_to_sorting(
        sim,
        conn,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        zone=ctx["zone"],
        start_dt=ordered_dt + timedelta(hours=2),
        est_dt=delivered_dt,
        sorting_dt=ordered_dt + timedelta(hours=96),
        sorting_desc="Kiện hàng trung chuyển chậm hơn dự kiến tại kho phân loại vùng.",
    )
    _complete_delivery(
        sim,
        conn,
        shp_id=shp_id,
        order_id=ctx["order_id"],
        carrier=ctx["carrier"],
        tracking=tracking,
        recipient=ctx["recipient"],
        shipper=ctx["shipper"],
        delivering_dt=delivered_dt - timedelta(hours=4),
        delivered_dt=delivered_dt,
    )
    return {"story": "giao_tre_han_cam_ket", "external_order_id": ctx["order_id"]}


STORY_BUILDERS: dict[
    str, Callable[[MarketplaceSimulator, sqlite3.Connection], dict[str, Any]]
] = {
    "giao_dung_han_cod": _story_giao_dung_han_cod,
    "dang_trung_chuyen": _story_dang_trung_chuyen,
    "cap_nhat_ao_giao_lai": _story_cap_nhat_ao_giao_lai,
    "giao_that_bai_hoan_ve": _story_giao_that_bai_hoan_ve,
    "nghen_kho_mega_sale": _story_nghen_kho_mega_sale,
    "hoan_tien_cham": _story_hoan_tien_cham,
    "hoan_tien_that_bai": _story_hoan_tien_that_bai,
    "thanh_toan_that_bai_roi_thanh_cong": _story_thanh_toan_that_bai_roi_thanh_cong,
    "huy_truoc_khi_giao": _story_huy_truoc_khi_giao,
    "doi_size_trong_han": _story_doi_size_trong_han,
    "qua_han_doi_tra": _story_qua_han_doi_tra,
    "het_bao_hanh": _story_het_bao_hanh,
    "giao_tre_han_cam_ket": _story_giao_tre_han_cam_ket,
}
