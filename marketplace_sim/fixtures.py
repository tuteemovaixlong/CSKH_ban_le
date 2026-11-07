"""Dữ liệu giả lập cố định cho khách hàng, người nhận, địa chỉ và bưu tá.

Tuyệt đối không chứa dữ liệu cá nhân thật, không có email, không có thẻ/tài khoản.
"""

from __future__ import annotations

from typing import TypedDict


class AddressTemplate(TypedDict):
    street: str
    ward: str
    district: str
    province: str
    zone: str  # intra_city | same_region | inter_region


class ShipperTemplate(TypedDict):
    name: str
    phone_masked: str


SYNTHETIC_DISPLAY_NAMES: tuple[str, ...] = (
    "Nguyễn Minh Châu",
    "Trần Quốc Khánh",
    "Lê Thu Hà",
    "Phạm Gia Huy",
    "Hoàng Ngọc Ánh",
    "Vũ Đức Anh",
    "Đặng Phương Thảo",
    "Bùi Quang Minh",
    "Đỗ Thanh Tùng",
    "Hồ Khánh Linh",
    "Ngô Tuấn Kiệt",
    "Dương Bảo Ngọc",
    "Lý Hoàng Nam",
    "Phan Mỹ Duyên",
    "Trương Hữu Phước",
    "Đinh Thảo Vy",
    "Mai Xuân Trường",
    "Lâm Nhã Phương",
    "Tạ Minh Khôi",
    "Võ Tuyết Nhi",
    "Hà Anh Tuấn",
    "Chu Hồng Nhung",
    "Đoàn Gia Bảo",
    "Lương Thùy Trang",
)

HOUSE_NUMBERS: tuple[str, ...] = (
    "12",
    "18A",
    "25",
    "39",
    "46B",
    "68",
    "84",
    "102",
    "119",
    "145",
    "178",
    "206",
    "235",
    "289",
    "312",
    "356",
)

ADDRESS_TEMPLATES: tuple[AddressTemplate, ...] = (
    {
        "street": "Đường Nguyễn Trãi",
        "ward": "Phường Bến Thành",
        "district": "Quận 1",
        "province": "TP. Hồ Chí Minh",
        "zone": "intra_city",
    },
    {
        "street": "Đường Cộng Hòa",
        "ward": "Phường 13",
        "district": "Quận Tân Bình",
        "province": "TP. Hồ Chí Minh",
        "zone": "intra_city",
    },
    {
        "street": "Đường Nguyễn Thị Thập",
        "ward": "Phường Tân Phong",
        "district": "Quận 7",
        "province": "TP. Hồ Chí Minh",
        "zone": "intra_city",
    },
    {
        "street": "Đường Võ Văn Ngân",
        "ward": "Phường Linh Chiểu",
        "district": "TP. Thủ Đức",
        "province": "TP. Hồ Chí Minh",
        "zone": "intra_city",
    },
    {
        "street": "Đại lộ Bình Dương",
        "ward": "Phường Phú Hòa",
        "district": "TP. Thủ Dầu Một",
        "province": "Bình Dương",
        "zone": "same_region",
    },
    {
        "street": "Đường Phạm Văn Thuận",
        "ward": "Phường Tân Tiến",
        "district": "TP. Biên Hòa",
        "province": "Đồng Nai",
        "zone": "same_region",
    },
    {
        "street": "Đường 30 Tháng 4",
        "ward": "Phường Xuân Khánh",
        "district": "Quận Ninh Kiều",
        "province": "Cần Thơ",
        "zone": "same_region",
    },
    {
        "street": "Đường Nguyễn Văn Linh",
        "ward": "Phường Nam Dương",
        "district": "Quận Hải Châu",
        "province": "Đà Nẵng",
        "zone": "inter_region",
    },
    {
        "street": "Đường Trần Phú",
        "ward": "Phường Lộc Thọ",
        "district": "TP. Nha Trang",
        "province": "Khánh Hòa",
        "zone": "inter_region",
    },
    {
        "street": "Đường Cầu Giấy",
        "ward": "Phường Dịch Vọng",
        "district": "Quận Cầu Giấy",
        "province": "Hà Nội",
        "zone": "inter_region",
    },
    {
        "street": "Đường Giải Phóng",
        "ward": "Phường Đồng Tâm",
        "district": "Quận Hai Bà Trưng",
        "province": "Hà Nội",
        "zone": "inter_region",
    },
    {
        "street": "Đường Lạch Tray",
        "ward": "Phường Lạch Tray",
        "district": "Quận Ngô Quyền",
        "province": "Hải Phòng",
        "zone": "inter_region",
    },
)

ORIGIN_WAREHOUSE = {
    "hub_name": "Kho Xuất Hàng Tân Bình",
    "district": "Quận Tân Bình",
    "province": "TP. Hồ Chí Minh",
}

SORTING_HUB_BY_ZONE: dict[str, dict[str, str]] = {
    "intra_city": {
        "hub_name": "Kho Phân Loại HCM SOC",
        "district": "Huyện Củ Chi",
        "province": "TP. Hồ Chí Minh",
    },
    "same_region": {
        "hub_name": "Kho Trung Chuyển Miền Nam SOC",
        "district": "TP. Thuận An",
        "province": "Bình Dương",
    },
    "inter_region": {
        "hub_name": "Kho Liên Vùng Bắc Ninh Mega SOC",
        "district": "TP. Từ Sơn",
        "province": "Bắc Ninh",
    },
}

SHIPPERS: tuple[ShipperTemplate, ...] = (
    {"name": "Lê Quốc Bảo", "phone_masked": "0903.xxx.418"},
    {"name": "Phạm Văn Hùng", "phone_masked": "0941.xxx.331"},
    {"name": "Nguyễn Đức Long", "phone_masked": "0905.xxx.788"},
    {"name": "Trần Minh Quân", "phone_masked": "0912.xxx.455"},
    {"name": "Đỗ Văn Tuấn", "phone_masked": "0983.xxx.244"},
    {"name": "Hoàng Gia Phúc", "phone_masked": "0977.xxx.619"},
    {"name": "Võ Thành Đạt", "phone_masked": "0938.xxx.502"},
    {"name": "Bùi Đình Khang", "phone_masked": "0964.xxx.870"},
)

DELIVERY_FAIL_REASONS: tuple[str, ...] = (
    "Khách không nghe máy, không liên lạc được khi bưu tá đến giao",
    "Người nhận vắng mặt tại địa chỉ giao hàng, hẹn giao lại ca sau",
    "Khu vực giao hàng tạm thời không tiếp cận được, chờ phát lại",
)

REFUND_FAIL_REASONS: tuple[str, ...] = (
    "Tài khoản ví điện tử nhận hoàn đã khóa hoặc hết hạn xác thực",
    "Ngân hàng thụ hưởng từ chối giao dịch hoàn do sai trạng thái tài khoản nhận",
)
