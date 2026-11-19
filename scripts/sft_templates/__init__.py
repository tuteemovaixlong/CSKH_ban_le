"""SFT case generation templates catalog.

W6.7.0 Part A.
"""
from __future__ import annotations

from typing import Any

from .base import BaseTemplate, Brief
from .t13_gap_fill import (
    T01GiaoLaiNhieuLan,
    T01TheoDoiHanhTrinhDangGiao,
    T02TimSanPhamTheoMoTa,
)
from .view import SftView
from .t01_order_lookup import (
    T01DonKhongThuocKhach,
    T01GiaoTreDuoi48h,
    T01GiaoTreTren48h,
    T01HoiDiaChiSdtDayDu,
    T01KhongNeuMaMotDon,
    T01KhongNeuMaNhieuDon,
    T01LietKeDon,
    T01TraDonCancelled,
    T01TraDonDelivered,
    T01TraDonPending,
    T01TraDonShipping,
    T01TrangThaiHoanTien,
    T01VanDonGiaoThatBai,
)
from .t02_products import (
    T02BaoHanhRiengSanPham,
    T02ChatLieuGiatUiCoDuLieu,
    T02ChatLieuGiatUiThieuDuLieu,
    T02NguonGocChinhHangKhongDuLieu,
    T02SanPhamKhongCo,
    T02SoSanhHaiMau,
    T02TonKhoBienTheCon,
    T02TonKhoBienTheHetGoiY,
    T02TuVanSizeThieuBang,
)
from .t03_policies import (
    T03BaoHanh90Ngay,
    T03DieuKienHuy,
    T03DoiSize15Ngay,
    T03DongKiemCOD,
    T03GioLamViecLienHe,
    T03HanTra7Ngay,
    T03HoaDonVAT,
    T03KhongCoChinhSachSi,
    T03KhongCoChinhSachTet,
    T03PhiShipTraDoi,
    T03ThoiGianHoanTien,
)
from .t04_cancellation import (
    T04BoMotMon,
    T04GoXacNhanLuotSau,
    T04HuyChuaXacNhanDon,
    T04HuyDaGiaoChuyenTra,
    T04HuyDangGiaoTuChoiNhan,
    T04HuyDonDaHuy,
    T04HuyKhongNeuMaNhieuDon,
    T04HuyPendingDoiY,
    T04HuyPendingMoBieuMau,
    T04HuySauKhiHoiTienTrinh,
)
from .t05_returns import (
    T05DaCoYeuCauMo,
    T05GiaoSaiMauLoiShop,
    T05HoanTienCODVeDau,
    T05KhachNoiTraNhungMuonDoi,
    T05Qua7NgayConBaoHanh,
    T05TraDonChuaGiao,
    T05TraHangHetHanBaoHanh,
    T05TraHangLyDoCaNhan,
    T05TraHangPhiShip,
    T05TraTrong7Ngay,
)
from .t06_exchanges import (
    T06Doi11LoiTrong90Ngay,
    T06DoiHaiMonCungDon,
    T06DoiHangChonVariant,
    T06DoiMau,
    T06DoiQua15Ngay,
    T06DoiSangSanPhamKhac,
    T06DoiSizeChuaGiao,
    T06DoiSizeConHang,
    T06DoiSizeHaiChieu,
    T06DoiSizeHetHangGoiY,
)
from .t07_frustrated import (
    T07DoaDangBai,
    T07DoiGapNhanVien,
    T07NgonNguGayGat,
    T07PhanNanLapLai,
    T07XinHotlineZalo,
)
from .t08_multiturn import (
    T08BonLuotDoiSize,
    T08ChinhSachRoiThaoTac,
    T08DoiChuDeRoiQuayLai,
    T08HaiDonChonMotDon,
    T08HoiBaoHanhRoiMoDoi,
    T08HoiTonKhoRoiHoiSize,
    T08HuyRoiHoiHoanTien,
    T08KiemTraTrangThaiVaPhiShip,
    T08NhieuDonThamChieuDonLucNay,
    T08SanPhamRoiVeDon,
    T08TraCuuGiaoHangRoiHoiDongKiem,
    T08TraDonRoiHoiPhiShip,
    T08TraRoiDoiYDoi,
)
from .t09_injections import (
    T09DebugModeXuatDs,
    T09GiaAdminXoaDon,
    T09InSystemPrompt,
    T09TheHeThongGiaHoanTien,
    T09TheHeThongGiaVoucher,
    T09VietDanhGiaGia,
    T09XemDonNguoiKhac,
    T09YeuCauGayHai,
)
from .t10_out_of_scope import (
    T10DichCau,
    T10KienThucChung,
    T10TiGiaThoiTietKhongDuLieu,
    T10TinhToan,
)
from .t11_case_assist import (
    T11CaNhieuDon,
    T11DoiNguoiGiuCa,
    T11HoiDonGiaoChua,
    T11NhanVienNhoGuiTin,
    T11PdfEmailLa,
    T11PdfLinkGia,
    T11PdfMaHoanGia,
    T11SoanNhapCanNhieuTool,
    T11SoanNhapDoiHang,
    T11SoanNhapHoanTien,
    T11TinNhanGiaDaDuyet,
    T11TomTatCa,
    T11TomTatPdfHoaDon,
    T11XemDonCaKhac,
)
from .t12_fraud_context import (
    T12Cham1111BoiThuong,
    T12DongKiemCODMopVo,
    T12GiaDanhKhoBaoHiem,
    T12GiaDanhShipperDoiPhi,
    T12LinkGiaNhanHoanTien,
    T12LivestreamKhacMauQuaHan,
    T12NghiTetKhongDuLieu,
    T12XinOTP,
    T12XinZalo,
    T12XuatVATCongTy,
)
from .view import SftView

_TEMPLATE_CLASSES: list[type[BaseTemplate]] = [
    # T01 (15 templates, 90 cases)
    T01TraDonPending,
    T01TraDonShipping,
    T01TraDonDelivered,
    T01TraDonCancelled,
    T01LietKeDon,
    T01KhongNeuMaNhieuDon,
    T01KhongNeuMaMotDon,
    T01VanDonGiaoThatBai,
    T01GiaoTreDuoi48h,
    T01GiaoTreTren48h,
    T01DonKhongThuocKhach,
    T01HoiDiaChiSdtDayDu,
    T01TrangThaiHoanTien,
    T01TheoDoiHanhTrinhDangGiao,
    T01GiaoLaiNhieuLan,
    # T02 (10 templates, 100 cases)
    T02ChatLieuGiatUiCoDuLieu,
    T02ChatLieuGiatUiThieuDuLieu,
    T02TonKhoBienTheCon,
    T02TonKhoBienTheHetGoiY,
    T02BaoHanhRiengSanPham,
    T02SoSanhHaiMau,
    T02TuVanSizeThieuBang,
    T02NguonGocChinhHangKhongDuLieu,
    T02SanPhamKhongCo,
    T02TimSanPhamTheoMoTa,
    # T03 (11 templates, 110 cases)
    T03HanTra7Ngay,
    T03DoiSize15Ngay,
    T03BaoHanh90Ngay,
    T03PhiShipTraDoi,
    T03DieuKienHuy,
    T03DongKiemCOD,
    T03ThoiGianHoanTien,
    T03HoaDonVAT,
    T03KhongCoChinhSachSi,
    T03KhongCoChinhSachTet,
    T03GioLamViecLienHe,
    # T04 (10 templates, 100 cases)
    T04HuyPendingMoBieuMau,
    T04HuyDangGiaoTuChoiNhan,
    T04HuyDaGiaoChuyenTra,
    T04HuyDonDaHuy,
    T04HuyKhongNeuMaNhieuDon,
    T04BoMotMon,
    T04GoXacNhanLuotSau,
    T04HuyPendingDoiY,
    T04HuyChuaXacNhanDon,
    T04HuySauKhiHoiTienTrinh,
    # T05 (10 templates, 100 cases)
    T05TraTrong7Ngay,
    T05Qua7NgayConBaoHanh,
    T05GiaoSaiMauLoiShop,
    T05TraDonChuaGiao,
    T05DaCoYeuCauMo,
    T05HoanTienCODVeDau,
    T05KhachNoiTraNhungMuonDoi,
    T05TraHangHetHanBaoHanh,
    T05TraHangPhiShip,
    T05TraHangLyDoCaNhan,
    # T06 (10 templates, 100 cases)
    T06DoiSizeConHang,
    T06DoiSizeHetHangGoiY,
    T06DoiQua15Ngay,
    T06DoiSangSanPhamKhac,
    T06DoiHaiMonCungDon,
    T06DoiMau,
    T06Doi11LoiTrong90Ngay,
    T06DoiSizeHaiChieu,
    T06DoiSizeChuaGiao,
    T06DoiHangChonVariant,
    # T07 (5 templates, 60 cases)
    T07DoiGapNhanVien,
    T07DoaDangBai,
    T07PhanNanLapLai,
    T07XinHotlineZalo,
    T07NgonNguGayGat,
    # T08 (13 templates, 150 cases)
    T08TraDonRoiHoiPhiShip,
    T08SanPhamRoiVeDon,
    T08TraRoiDoiYDoi,
    T08HuyRoiHoiHoanTien,
    T08NhieuDonThamChieuDonLucNay,
    T08DoiChuDeRoiQuayLai,
    T08ChinhSachRoiThaoTac,
    T08BonLuotDoiSize,
    T08HoiTonKhoRoiHoiSize,
    T08TraCuuGiaoHangRoiHoiDongKiem,
    T08HoiBaoHanhRoiMoDoi,
    T08HaiDonChonMotDon,
    T08KiemTraTrangThaiVaPhiShip,
    # T09 (8 templates, 80 cases)
    T09TheHeThongGiaVoucher,
    T09TheHeThongGiaHoanTien,
    T09XemDonNguoiKhac,
    T09InSystemPrompt,
    T09GiaAdminXoaDon,
    T09DebugModeXuatDs,
    T09YeuCauGayHai,
    T09VietDanhGiaGia,
    # T10 (4 templates, 40 cases)
    T10KienThucChung,
    T10TinhToan,
    T10DichCau,
    T10TiGiaThoiTietKhongDuLieu,
    # T11 (14 templates, 190 cases)
    T11TomTatCa,
    T11SoanNhapHoanTien,
    T11SoanNhapDoiHang,
    T11HoiDonGiaoChua,
    T11CaNhieuDon,
    T11NhanVienNhoGuiTin,
    T11DoiNguoiGiuCa,
    T11XemDonCaKhac,
    T11TomTatPdfHoaDon,
    T11SoanNhapCanNhieuTool,
    T11PdfLinkGia,
    T11PdfEmailLa,
    T11TinNhanGiaDaDuyet,
    T11PdfMaHoanGia,
    # T12 (10 templates, 80 cases)
    T12GiaDanhShipperDoiPhi,
    T12GiaDanhKhoBaoHiem,
    T12LinkGiaNhanHoanTien,
    T12XinOTP,
    T12DongKiemCODMopVo,
    T12Cham1111BoiThuong,
    T12XuatVATCongTy,
    T12LivestreamKhacMauQuaHan,
    T12XinZalo,
    T12NghiTetKhongDuLieu,
]

TEMPLATES: dict[str, BaseTemplate] = {}
for cls in _TEMPLATE_CLASSES:
    inst = cls()
    TEMPLATES[inst.template_id] = inst

# Sinh sau cùng để giữ nguyên RNG và mọi phiếu của 1.200 ca cũ.
from .t14_handoff import T14_TEMPLATES
for inst in T14_TEMPLATES:
    TEMPLATES[inst.template_id] = inst

__all__ = ['BaseTemplate', 'Brief', 'SftView', 'TEMPLATES']
