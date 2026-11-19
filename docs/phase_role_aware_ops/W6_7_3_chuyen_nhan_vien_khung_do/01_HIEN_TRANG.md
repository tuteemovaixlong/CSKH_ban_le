# 01 — Hiện trạng (đo 19/11/2026)

## Dữ liệu
- `main` = W6.7.2 (#132) + tài liệu (#133). Bộ ca/lời khách **v4** trên Drive `retailops_colab/w67_utterances/084b39b/full`
  (W6.7.1: drop-cache 92 phiếu + Glimmer viết lại, migrate-injection 10 phiếu t09; `verify` 0 lỗi; ca điền SHA256
  `1634173fc339…`). 64 ca của 6 khung W6.7.1 phải chạy lại quỹ đạo.
- Chấm: vòng 1 + trọng tài (A 548 ca), vòng 2 (giám khảo Neon High + Codex 6.1 Sol, khớp 87,8 %, kappa 0,71) → **605 ca
  có Tier A**. Còn ~389 ca Qwen chưa có mẫu đạt (đích của khung đỡ). Tier S vòng 1 đang chấm (263 cặp).

## Chuyển nhân viên — tập SFT so với bộ đo
| | Tập SFT (1.200 ca) | Bộ đo (250 ca) |
|---|---|---|
| Lượt kỳ vọng chuyển (`request_human_support`) | 32 (2,7 %) — chỉ 3 khung: `t07_doi_gap_nhan_vien`, `t07_doa_dang_bai`, `t12_xuat_vat_cong_ty` | 16 (6,4 %) |
| …trong đó rào an toàn chặn trước model | 18 (12 `t07_doa_dang_bai` + 6 `t07_doi_gap_nhan_vien`) → không có mẫu | 4 |
| …model phải tự chuyển | 14, **11 ca có Tier A** | **12** |
| Lượt cấm chuyển tường minh (`tools_not_called`) | 0 (có 1.130 lượt `human_support: false` thường) | 18 |

Bộ đo có những tình huống model tự chuyển mà SFT chưa có: dọa khiếu nại sàn (`s07_004`), dọa kiện (`s07_005`), đổi địa
chỉ/người nhận (`s07_011`, `s07_013`, `s07_014`, `s08_016`, `s08_018`), khôi phục đơn hủy (`s07_016`), chuyển nhà rồi
đổi địa chỉ (`s07_015`), bot không hiểu rồi đòi người (`s07_002`), khiếu nại shipper báo giao thất bại sai (`s01_008`).

## Rào an toàn (`retailops/workflow/safety.py`) — chỉ bắt từ khóa có dấu
Các câu sau đều **lọt** rào (đi thẳng tới model): `shop oi neu khong xu ly tui boc phot len hoi nhom fb`,
`tôi sẽ đăng lên mạng cho mọi người biết shop làm ăn thế này`, `mai mà ko xử lý tui đăng lên group review cho cả xóm
biết`, `toi se kien shop ra toa`. Trong SFT, 12/12 ca dọa bóc phốt bị rào chặn (không ca nào viết không dấu) → model có
**0 mẫu** xử lý lời đe dọa. Rào xử lý ca nó bắt thì đúng (108/108 lượt qua kỳ vọng). Không có hàng đợi ưu tiên cho SOP 5:
cả rào lẫn model đều tạo yêu cầu `sentiment='neutral'`; rào chỉ ghi "SOP 5 … Strict Mode" vào lý do và vết.

## Thước hiện tại (`scripts/sft_cases.py`)
`HANDOFF_EITHER = {t07_xin_hotline_zalo, t12_xin_zalo, t03_hoa_don_vat, t07_ngon_ngu_gay_gat, t07_phan_nan_lap_lai}` →
bỏ `human_support`, bỏ `request_human_support` khỏi `tools_called` ("tự do"). Trần tool của các khung t07 sau
`relax_tool_caps` là 3–4 (khớp bộ đo) — không cần sửa. Ảnh hưởng của quyết định owner lên mẫu đã có (ứng viên A_code /
Tier A sẽ trượt khi chấm lại bằng thước mới):

| Khung | Quyết định owner | A_code trượt | Tier A trượt |
|---|---|---|---|
| `t07_xin_hotline_zalo` | không chuyển | 19/66 | 4/6 |
| `t03_hoa_don_vat` | không chuyển | 15/19 | 8/12 |
| `t07_phan_nan_lap_lai` | **bắt buộc chuyển** | 21/33 | 13/18 |
| `t07_ngon_ngu_gay_gat` | tra đơn trước, chuyển tùy model | 3/10 | 2/6 |

Lỗ tiềm ẩn ở `eval_regrade.regrade_record_v3`: tính "đã chuyển" khi có gọi `request_human_support` (trừ lời gọi hỏng
tham số), không xét tool có thành công — runner (`grade_turn`) thì đòi `result.human_support` (thành công). Dữ liệu hiện
có chưa lọt (121/121 lời gọi `ok`).

## Quyết định của owner (19/11)
1. Chuyển nhân viên là nghiệp vụ cốt lõi → **tăng mạnh số mẫu**; câu khách phải là câu **lọt được rào** (model mới thấy).
2. Xin hotline/Zalo (`t07_xin_hotline_zalo`): **không chuyển** — trả lời từ KB (shop không có hotline, liên hệ qua khung
   chat). `t12_xin_zalo` giữ tự do (bộ đo `s12_014` tự do).
3. Hỏi thông tin hóa đơn VAT (`t03_hoa_don_vat`): **không chuyển** — tự trả lời bằng dữ liệu đơn + KB `invoice_vat.md`.
   Yêu cầu xuất hóa đơn thật vẫn chuyển (`t12_xuat_vat_cong_ty`, bộ đo `s12_013`).
4. Phàn nàn lặp lại (`t07_phan_nan_lap_lai`): **khuyến khích chuyển luôn** → bắt buộc gọi `request_human_support`.
5. Bực lần đầu, chưa đòi người, chưa dọa (`t07_ngon_ngu_gay_gat`): **tra đơn trước**, trả lời bằng dữ liệu, chuyển khi
   model tự quyết không xử lý được. Bản không cần chuyển (đơn đang giao bình thường) thì **không chuyển** (bộ đo `s07_010`).
6. Khiếu nại shipper báo giao thất bại sai: **ưu tiên trả lời bằng ngữ cảnh hệ thống** (tra vận đơn + KB
   `policy_shipper_complaint.md`: đối chiếu hành trình, ghi nhận, đề nghị chuyển; không tự khiếu nại hãng, không hứa giờ
   giao lại). Gọi `request_human_support` khi khách **đòi việc của nhân viên** (khiếu nại hãng, sắp xếp giao lại) hoặc đòi
   người — khớp mô tả tool trong `agent_protocol.py` và bộ đo `s01_008`.
7. Khung đỡ + phiếu đỡ phải thiết kế cho cả nhóm chuyển nhân viên. "Suy luận nhiều hơn" = trần tool đủ rộng + gợi ý tra
   cứu trước khi quyết; **không** nâng `max_tokens` (cấu hình chạy thật và đo: thinking bật, 2.048 token/lần gọi).
8. Không sửa ứng dụng trong W6.7.3 (rào không dấu, hàng đợi ưu tiên, câu `RAGE_REPLY` hứa quá → backlog F59–F61) để phép
   so model gốc ↔ sau SFT trên cùng ứng dụng vẫn công bằng.
