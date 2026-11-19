# 03 — Thiết kế chi tiết

Nguyên tắc thước: kỳ vọng mỗi khung **theo ca bộ đo cùng loại** ("ca sinh đôi"), không chặt hơn, không lỏng hơn — trừ chỗ
owner đã chốt khác ở 01. Ca sinh đôi chỉ để lấy **dạng** kỳ vọng (tool nào, nguồn KB nào, loại câu cấm); **không** chép
mã đơn, tên, câu khách, URL/tên miền hay giá trị giả nào của bộ đo (test chống trùng phải xanh).

## A. Thước (`scripts/sft_cases.py`, `scripts/eval_regrade.py`)
| Khung | Kỳ vọng mới (lượt 1) | Ca sinh đôi | Đổi phiếu? |
|---|---|---|---|
| `t07_xin_hotline_zalo` | bỏ khỏi `HANDOFF_EITHER`. `tools_called: [search_knowledge]`, `tools_not_called: [request_human_support]`, `human_support: false`, `sources: [store_hours_contact.md]`; `answer_any` 2 nhóm: (không có hotline/số điện thoại/tổng đài/Zalo/số liên hệ) và (khung chat/tại đây/cuộc trò chuyện này); `answer_not`: câu bịa đã chuyển ("đã chuyển cuộc trò chuyện"), câu bịa số/kênh (không ghi URL/tên miền vào kỳ vọng). `fake_model`: gọi `search_knowledge` rồi trả lời; `final_state.rows.handoff_episodes = 0` | `s07_007`, `s07_008`, `s03_019` | không |
| `t03_hoa_don_vat` | bỏ khỏi `HANDOFF_EITHER`. Thêm `tools_not_called: [request_human_support]`, `human_support: false`; `answer_any` bỏ `"nhân viên"`, dùng nhóm (sàn/nhà cung cấp hóa đơn phát hành; tự nhập trên trang sàn; không cần gửi mã số thuế qua chat); giữ `answer_all: ["7 ngày"]`, `sources: [invoice_vat.md]` | `s03_020` | không |
| `t07_phan_nan_lap_lai` | bỏ khỏi `HANDOFF_EITHER` → giữ `tools_called: [request_human_support]`, `human_support: true` của khung; `final_state.rows.handoff_episodes = 1`. Tra đơn trước khi chuyển **được phép** (trần sau `relax_tool_caps` đủ) | `s07_002` lượt 2, `s07_012` lượt 2 | không |
| `t07_ngon_ngu_gay_gat` | **giữ** trong `HANDOFF_EITHER` (chuyển tùy model) nhưng thêm `tools_any: [[list_orders, get_order, track_shipment]]` — phải tra đơn trước khi quyết; `fake_model` thêm lời gọi `list_orders` | `s07_010` (dạng tra đơn) | không |

`HANDOFF_EITHER` còn `t12_xin_zalo` và `t07_ngon_ngu_gay_gat`. Sửa comment ở đầu tệp cho đúng quyết định mới.

**Vá `regrade_record_v3`:** lượt tính là đã chuyển khi có lời gọi `request_human_support` **có `status == 'ok'`** trong
`turn['tools']` (khớp `grade_turn` đòi `result.human_support`). Lời gọi lỗi → `human support was not requested`.
Bản ghi không có trường `status` (vết cũ) → giữ cách cũ (coi là thành công) và gắn cờ `handoff_status_unknown`.

## B. Khung T14 — `scripts/sft_templates/t14_handoff.py`
- Bộ `T14`, mỗi khung 10 ca (`target=10`), mã ca `t14_NNN_<template>`; đăng ký **sau mọi khung cũ** trong
  `TEMPLATES` (thứ tự 18 khung theo bảng). `EASY_TIGHT` thêm `'T14'` (trần mẫu thứ hai 25 %, mẫu thứ hai chỉ qua Tier S); **không** thêm vào `HARD_SUITES` — xem "Tỉ trọng" cuối mục B.
- **Mọi phiếu T14 có `rail_pass=True`** (mục C): câu khách phải lọt rào, kể cả ca đối chứng — câu bị rào chặn thì model
  không bao giờ thấy, mẫu vô dụng.
- `select` lấy khách/đơn đúng trạng thái từ `SftView` (đơn chưa giao, đang giao, giao thất bại có `fail_reason` kiểu
  "không liên lạc được", đã hủy, đã giao); mỗi đơn ≤ 3 lần/khung (assert sẵn có). Thiếu đơn đúng trạng thái → báo, không
  bịa dữ liệu fixture.
- Kiểu viết: khung nhóm A, B ưu tiên `khong_dau`, `teencode`, `sai_chinh_ta` (đặt `allowed_styles`); nhóm khác dùng
  mặc định. Vì bể kiểu viết 1.200 đã hết, kiểu của T14 lấy bằng `rng.choice(allowed_styles)` (đã có sẵn trong vòng sinh).
- Mỗi khung có `fake_model` để `sft_cases check` qua; `final_state.rows.handoff_episodes` = 1 khi kỳ vọng chuyển, 0 khi cấm.
- Phiếu: `persona`, `intent`, `notes` mô tả ý khách **bằng lời của Codex** (không chép câu bộ đo); `must_include` chỉ mã đơn
  khi cần; khung cấm chuyển và khung "lần đầu" có `must_not_include` các cụm "mấy lần rồi", "lần thứ", "nhắn hoài"
  (phân biệt với phàn nàn lặp lại).

| # | Khung | Lượt | Kỳ vọng (dạng) | Ca sinh đôi |
|---|---|---|---|---|
| **A. Đòi gặp người** |||||
| 1 | `t14_doi_nguoi_khong_dau` | 1 | chuyển; `answer_any` (nhân viên/tư vấn viên/bộ phận/chuyển/hỗ trợ); cấm câu từ chối chuyển, câu bịa đã xử lý | `s07_009` |
| 2 | `t14_doi_nguoi_vong_vo` | 1 | như #1; ý đòi người nói vòng ("có bạn nào thật không", "muốn trao đổi trực tiếp với ai đó") | `s07_009` |
| 3 | `t14_bot_khong_hieu_doi_nguoi` | 2 | L1 hỏi tình trạng đơn: tra đơn, `human_support: false`, cấm chuyển. L2 chê bot trả lời chung chung, đòi người: chuyển | `s07_002` |
| **B. Đe dọa** |||||
| 4 | `t14_doa_khieu_nai_san` | 2 | L1 xin hủy đơn đang giao (không đủ điều kiện): tra đơn, không chuyển, cấm "hủy thành công". L2 dọa khiếu nại/đánh giá xấu trên sàn: chuyển, cấm "hủy thành công"/"đã hoàn tiền" | `s07_004` |
| 5 | `t14_doa_kien` | 1 | khách dọa kiện vì hàng lỗi nguy hiểm: chuyển; cấm tư vấn pháp lý ("tòa án có thẩm quyền", "thuê luật sư"), cấm hứa hoàn/đổi thành công | `s07_005` |
| 6 | `t14_doa_dang_bai_khac_tu` | 1 | dọa đăng mạng xã hội bằng cách nói rào không bắt: chuyển; `answer_any` (xin lỗi/thông cảm/nhân viên/hỗ trợ); cấm hứa đền bù, voucher | `s07_003` |
| **C. Việc chỉ nhân viên làm được** |||||
| 7 | `t14_doi_dia_chi_giao` | 1 | đơn chưa giao/đang giao, xin đổi địa chỉ: chuyển; cấm "đã đổi địa chỉ", "cập nhật địa chỉ thành công" | `s07_011`, `s07_013` |
| 8 | `t14_doi_nguoi_nhan` | 1 | xin đổi tên/số người nhận: chuyển; cấm câu bịa đã đổi | `s07_013` |
| 9 | `t14_khoi_phuc_don_huy` | 2 | L1 xin gỡ hủy đơn đã hủy: tra đơn, giải thích (chuyển tùy model). L2 khăng khăng vì gấp: chuyển; cấm "đã khôi phục", "giao ngay" | `s07_016` |
| 10 | `t14_khieu_nai_shipper_nho_xu_ly` | 1 | đơn giao thất bại ("không liên lạc được") dù khách ở nhà, khách **nhờ shop khiếu nại hãng/sắp xếp giao lại**: `tools_any` tra vận đơn/đơn, `tools_called: [search_knowledge]`, `sources: [policy_shipper_complaint.md]`, chuyển; `answer_all` mã đơn; cấm "đã gửi khiếu nại tới hãng", hứa giờ giao lại | `s01_008` |
| 11 | `t14_khieu_nai_shipper_chi_phan_anh` | 1 | **đối chứng của #10** (cùng loại đơn): khách chỉ phản ánh/hỏi vì sao bị báo thất bại, không nhờ làm gì: tra vận đơn + KB, `human_support: false`, cấm chuyển; câu trả lời đối chiếu hành trình, đề nghị chuyển nếu khách muốn | `s01_008` (dạng), `t01_giao_lai_nhieu_lan` |
| **D. Nhiều lượt** |||||
| 12 | `t14_hoi_roi_doi_nguoi` | 3 | L1 hỏi tình trạng đơn (tra đơn), L2 hỏi chính sách (KB), cả hai `human_support: false`. L3 đòi người: chuyển | `s07_002` |
| 13 | `t14_chuyen_nha_doi_dia_chi` | 2 | L1 hỏi sản phẩm (tra sản phẩm), không chuyển. L2 báo mới chuyển nhà, xin đổi địa chỉ đơn đang giao: chuyển; cấm "đã cập nhật địa chỉ" | `s07_015` |
| **E. Đối chứng — không được chuyển** |||||
| 14 | `t14_hoi_gio_lam_viec` | 1 | hỏi giờ trực CSKH/cuối tuần: `search_knowledge`, `sources: [store_hours_contact.md]`, cấm chuyển, cấm câu bịa đã chuyển | `s07_006`, `s03_019` |
| 15 | `t14_nhac_shipper_hoi_don` | 1 | nhắc "anh shipper/nhân viên giao hàng" khi hỏi đơn ở đâu: tra vận đơn, cấm chuyển | `s07_010` (dạng) |
| 16 | `t14_khen_nhan_vien_roi_hoi` | 1 | khen bạn nhân viên lần trước rồi hỏi một chính sách: KB, cấm chuyển | `s03_019` (dạng) |
| 17 | `t14_buc_lan_dau_hoi_don` | 1 | bực vì chờ lâu, lần đầu hỏi, đơn đang giao bình thường: tra đơn/vận đơn, cấm chuyển, `answer_all` mã đơn; cấm "giao thất bại", "đã hoàn tiền" | `s07_010` |
| 18 | `t14_buc_don_co_van_de` | 1 | bực lần đầu, đơn có vấn đề thật (giao thất bại nhiều lần / trễ quá hạn cam kết): tra đơn/vận đơn bắt buộc, **chuyển tùy model** (không `human_support`), cấm hứa đền bù không căn cứ | `s07_010` + quyết định owner 5 |

Tổng **18 khung × 10 = 180 ca** (chuyển: #1–10, #12–13 và lượt cuối các khung nhiều lượt; cấm chuyển: #11, #14–17;
tùy model: #18). Yêu cầu xuất hóa đơn thật giữ khung sẵn có `t12_xuat_vat_cong_ty` (8 ca), không thêm.

Trần tool: đặt theo ca sinh đôi (3–6), để `relax_tool_caps` nâng nếu thiếu. Lượt chuyển nhân viên: `action: reply`.

**Tỉ trọng (Claude đo 19/11, `scratch/w67_matrix/matrix.py`, tính theo lượt):** tập SFT hiện có (vòng 1 + 2, thước
mới) có 2,4 % lượt "chuyển", 0,9 % "cấm chuyển"; bộ đo 4,8 % / 5,4 %. Dự phóng sau đợt 3 + T14 (tỉ lệ Tier A giả định
35–60 % ca chưa có mẫu, 55–80 % ca làm lại và T14): "chuyển" 7,5–8,4 %, "cấm chuyển" 5,7–6,6 % — gấp ~1,7 lần bộ đo
ở phía chuyển, chấp nhận được vì owner muốn khuyến khích hành vi này và ~92 % lượt còn lại đều là "không chuyển". Nếu
T14 vào `HARD_SUITES` (mẫu thứ hai DeepSeek tới 50 %/khung), "chuyển" lên ~11 % (gấp 2,3 lần) → dễ học thói chuyển thừa;
vì vậy T14 dùng trần 25 % và mẫu thứ hai chỉ qua Tier S.

## C. Kiểm "lọt rào" (`scripts/sft_templates/base.py`, `scripts/sft_utterances.py`)
- `Brief` thêm `rail_pass: bool = False`; `to_dict()` **chỉ ghi khóa khi `True`** (phiếu cũ trùng từng byte).
- Hàm kiểm một câu (cùng chỗ các luật 1–6 hiện có): nếu phiếu có `rail_pass` và
  `retailops.workflow.safety.safety_gate(text)` khác `None` → trượt với lý do `Bị rào an toàn chặn (<rail>)`; `fill`
  coi như câu trượt (viết lại theo vòng leo thang sẵn có), `verify` báo lỗi. Với khung nhiều lượt, kiểm từng lượt có cờ.
- Ghi chú phiếu (`notes`) của T14 nhắc Glimmer tránh cụm cố định kiểu "gặp nhân viên", "bóc phốt" khi viết có dấu
  (Codex tự diễn đạt; không cần liệt kê toàn bộ từ khóa rào).

## D. Khung đỡ (gợi ý lúc sinh, không có trong mẫu huấn luyện)
Mục tiêu: chạy lại Qwen — và DeepSeek cho ca Qwen vẫn thua, đặc biệt ca Trợ lý ca chế độ `draft` (mục E) — cho ca chưa
có mẫu đạt, kèm gợi ý quy trình; mẫu huấn luyện là **lời nhắc gốc (không gợi ý) + trả lời sinh ra khi có gợi ý**. Runner
`run_agent_scenarios.py` không sửa: gợi ý chèn ở **proxy** giữa runner và endpoint model (vLLM cục bộ hoặc API DeepSeek),
nên vết runner ghi lời nhắc gốc — không phải bóc gợi ý khỏi mẫu.

**D1. `scripts/sft_hint_proxy.py`** — HTTP proxy tương thích OpenAI, chỉ nghe `127.0.0.1`:
```
python scripts/sft_hint_proxy.py --listen 127.0.0.1:8002 --upstream http://127.0.0.1:8001|https://<API DeepSeek> \
  --cases DIR/cases_sft_v1_filled.jsonl --hints hints.jsonl --log hint_log.jsonl [--only-file ids.txt]
```
- Chuyển nguyên `GET /health`, `GET /v1/models`; `POST /v1/chat/completions`: tìm tin `role: user` cuối trong
  `messages`, tra **khớp chính xác** với lời khách các lượt của ca đã điền → `(case_id, turn)`; lấy gợi ý theo thứ tự ưu
  tiên `(case_id, turn)` → `(case_id, null)` → `(template, turn)` → `(template, null)` (phiếu theo ca dùng cho ca khó như
  T11 `draft`). Có gợi ý → nối vào cuối nội dung tin `system` đầu:
  `"\n\n<<<GOI_Y_SINH_DU_LIEU>>>\n" + hint + "\n<<<HET_GOI_Y>>>"`. Không khớp / khớp nhiều ca / không có gợi ý → chuyển
  nguyên, ghi `no_hint` (không lỗi). Ca Trợ lý ca (`staff_case_assist`): Codex kiểm runner gửi lời khách dạng nào và
  khớp cho đúng; không khớp được thì ghi rõ trong báo cáo.
- Không đổi `tools`, tin khác, tham số sinh; chuyển nguyên header `Authorization` (không ghi log, không in khóa).
- Log mỗi yêu cầu: thời điểm, `case_id`, `turn`, `hinted`, SHA256 của gợi ý, SHA256 thân yêu cầu — không ghi thân yêu
  cầu hay khóa.
- Đa luồng (runner chạy song song 16–24 luồng); thời gian chờ upstream đủ dài như runner. Upstream HTTPS (API DeepSeek):
  kiểm chứng chỉ, chuyển nguyên `Authorization` của runner; proxy không tự đọc khóa nào.

**D2. `scripts/sft_hints.py`** — phiếu đỡ:
- `export --scores S --adjudicated ADJ [ADJ…] --cases CASES --out sheet.csv [--templates …]`: mỗi dòng một
  `(template, turn)` có ca cần chạy lại (chưa có Tier A, không bị loại vì đầu vào đổi): `template, turn, so_ca, ky_vong`
  (tóm tắt `tools_called/any/not`, `sources`, `answer_not`, `human_support`), `loi_thuong_gap` (đếm `failures_v3` và lý
  do `khong_dat` của giám khảo, mỗi loại ≤ 120 ký tự, tối đa 8 loại), `goi_y` (trống). UTF-8 BOM, không ghi đè.
  `--per-case-templates T [T …]`: với các khung này xuất **một dòng mỗi ca** (thêm cột `case_id`, chế độ Trợ lý ca, mã
  đơn trong ca, lỗi riêng của ca đó) để soạn gợi ý theo ca.
- `import --csv sheet.csv --out hints.jsonl [--check-only]`: kiểm `goi_y` không trống, ≤ 800 ký tự, không chứa mã
  đơn/sản phẩm/khách (`extract_codes`), không chứa số tiền, không chứa chuỗi đánh dấu, không trùng 5-gram > 0,45 với câu bộ
  đo; ghi `{"template"|"case_id","turn","hint","sha256"}`. Gợi ý theo ca được nêu mã đơn **của chính ca đó** (đã có
  trong lời nhắc) nhưng vẫn không có số tiền hay câu trả lời mẫu. Nội dung `goi_y` do Claude soạn, owner duyệt — **Codex không điền**.

**D3. `sft_select score` nhận nhiều thư mục lượt chạy mỗi model:**
- Dạng mới (dạng cũ `--run-dir model=DIR` giữ nguyên): `--runs runs.json`, mỗi mục
  `{"label","model":"qwen|deepseek","dir","run_offset":int,"hinted":bool,"hint_log":path|null}`; số `run` của ứng viên =
  `run_offset + run` gốc (duy nhất theo model; trùng → dừng). Ứng viên có thêm `hinted`, `run_label`.
- **Đầu vào cũ (`stale_input`):** lời khách trong bản ghi lượt chạy khác lời khách của ca hiện tại → loại ứng viên với lý do
  `stale_input` (tự loại vết cũ của 64 ca W6.7.1 và ca T14/khung đổi phiếu sau này).
- **Lộ gợi ý (`hint_leak`):** với lượt có gợi ý, nội dung/suy luận trợ lý chứa `GOI_Y`, `HET_GOI_Y`, "gợi ý sinh dữ liệu",
  từ `hint` (nguyên từ, không phân biệt hoa thường) → loại, lý do `hint_leak`. Lượt có gợi ý mà `hint_log` không có dòng
  khớp → cờ `hint_unverified`.
- `select`: cùng tier, ưu tiên lượt **không gợi ý**, rồi rank (ghi vào luật chọn mẫu chính và mẫu thứ hai).

**D4. `sft_build`:** `meta.hinted` (true/false); thống kê theo `hinted` trong `stats.json`/`build_report.md`; **dừng lỗi**
nếu bất kỳ mẫu nào (mọi tin) còn chuỗi `<<<GOI_Y_SINH_DU_LIEU>>>` hoặc `<<<HET_GOI_Y>>>`.

## E. Tỉ trọng T11 (Trợ lý ca) và Tier S đúng chỗ (`scripts/sft_select.py`)
Đo 19/11 (vòng 1 + 2): T11 = 132/671 mẫu (19,7 %; bộ đo 6,8 % lượt). Theo chế độ — bộ đo S11: `draft` 50 %, `ask` 41 %,
`summary` 14 %; mẫu SFT đang có: `draft` 31 (23 %), `ask` 56 (42 %), `summary` 45 (34 %); 31 mẫu là mẫu thứ hai (luật 3/4
vì T11 ∈ `HARD_SUITES`). Quyết định owner: **Tier S chỉ dùng đúng chỗ của nó** — làm mẫu thứ hai của chính ca/lượt đã
chấm cặp, không dùng để bù tỉ trọng chế độ hay khung khác; ca `draft` chưa có mẫu được làm kỹ khung đỡ cho DeepSeek viết.
- E1. **T11 ra khỏi `HARD_SUITES`** → mẫu thứ hai của T11 chỉ qua Tier S (luật 1, 2, 5) của chính ca đó.
- E2. **Trần tỉ trọng tùy chọn** (mặc định tắt — tắt thì kết quả trùng từng byte như trước):
  `select --suite-cap T11=0.12 --mode-cap T11:summary=0.25,T11:ask=0.45`. Áp sau trần khung và trần DeepSeek; vượt
  trần thì bỏ theo thứ tự: mẫu thứ hai của chế độ vượt trần → mẫu chính của chế độ vượt trần (rank thấp, băm seed). **Không
  bao giờ bỏ mẫu `draft`**, không đổi mẫu giữa các chế độ hay khung (mẫu S của `ask`/`summary` không thay chỗ cho `draft`).
  Báo cáo ghi số mẫu bỏ theo bộ × chế độ × vai.
- E3. `sft_hints export --per-case-templates` dùng cho các khung T11 chế độ `draft` (mục D2).

## Câu hỏi mở (Codex hỏi lại nếu gặp, kèm đề xuất)
- Fixture thiếu đơn đúng trạng thái cho khung nào → đề xuất giảm `target` khung đó hay dùng lại đơn (≤ 3 lần).
- Cách runner gửi lời khách ở ca Trợ lý ca (khớp gợi ý ở D1).
