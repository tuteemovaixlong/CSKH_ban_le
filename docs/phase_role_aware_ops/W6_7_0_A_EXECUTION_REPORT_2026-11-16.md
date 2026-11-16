# Báo Cáo Thực Thi W6.7.0 Phần A — Công Cụ Sinh Dữ Liệu Chưng Cất (SFT)

- **Ngày thực hiện:** 2026-11-16
- **Nhánh:** `phase-r1-w6-7-0-a` (tạo từ `origin/main` commit `4cd3902`)
- **Mục tiêu:** Cung cấp bộ công cụ đầy đủ cho phần A của kế hoạch W6.7: sinh dữ liệu cửa hàng riêng `sft_v1`, mở rộng runner nạp fixture `sft_v1` và ca huấn luyện, bộ kiểm định dạng ca huấn luyện `sft_dataset`, bộ sinh khung ca `sft_cases` với 112 khung (1.200 ca), bước viết lời khách DeepSeek `sft_utterances` kèm kiểm tra chất lượng chặt chẽ bằng code, cùng bộ test toàn diện. Đảm bảo toàn bộ hệ thống lõi, dữ liệu bộ đo 250 ca (S01–S12) và logic chấm điểm không đổi.

---

## 1. Danh Sách Tệp Đã Tạo Và Chỉnh Sửa

| STT | Tệp | Trạng thái | Mô tả |
|---|---|---|---|
| 1 | `data/demo_events/store_events_sft_v1.jsonl` | Tạo mới | Dữ liệu sự kiện sàn giả lập `sft_v1` (2.011 sự kiện, 129 đơn, 92 khách) |
| 2 | `data/demo_events/store_events_sft_v1.meta.json` | Tạo mới | Metadata của `sft_v1`: seed, days, counters, stories, số sự kiện theo loại, SHA-256 |
| 3 | `scripts/build_sft_fixture.py` | Tạo mới | Script dựng dữ liệu `sft_v1` tất định bằng `marketplace_sim`, kiểm tra 0 trùng lặp với `store_events.jsonl` |
| 4 | `scripts/run_agent_scenarios.py` | Chỉnh sửa | Thêm nhánh `sft_v1` vào `FIXTURES` và `_provision_demo_template`; thêm nhánh xác thực ca huấn luyện (`t*`) vào `load_dataset` |
| 5 | `scripts/sft_dataset.py` | Tạo mới | Bộ kiểm định dạng ca huấn luyện `validate_train_case` và kiểm tra toàn tập `validate_train_set` |
| 6 | `scripts/sft_templates/__init__.py` | Tạo mới | Đăng ký toàn bộ 112 khung ca (1.200 ca) |
| 7 | `scripts/sft_templates/base.py` | Tạo mới | Lớp cơ sở `BaseTemplate`, cấu trúc phiếu yêu cầu lời khách `Brief` |
| 8 | `scripts/sft_templates/view.py` | Tạo mới | Lớp `SftView` truy xuất dữ kiện thực tế từ tenant `sft_v1` |
| 9 | `scripts/sft_templates/t01_order_lookup.py` | Tạo mới | 10 khung tra cứu đơn hàng (100 ca) |
| 10 | `scripts/sft_templates/t02_products.py` | Tạo mới | 9 khung sản phẩm và tồn kho (90 ca) |
| 11 | `scripts/sft_templates/t03_policies.py` | Tạo mới | 11 khung chính sách có trích dẫn (110 ca) |
| 12 | `scripts/sft_templates/t04_cancellation.py` | Tạo mới | 10 khung hủy đơn hàng (100 ca) |
| 13 | `scripts/sft_templates/t05_returns.py` | Tạo mới | 10 khung trả hàng và hoàn tiền (100 ca) |
| 14 | `scripts/sft_templates/t06_exchanges.py` | Tạo mới | 10 khung đổi hàng (100 ca) |
| 15 | `scripts/sft_templates/t07_frustrated.py` | Tạo mới | 5 khung khách bức xúc / chuyển nhân viên (60 ca) |
| 16 | `scripts/sft_templates/t08_multiturn.py` | Tạo mới | 13 khung hội thoại đa lượt 2–4 lượt (150 ca) |
| 17 | `scripts/sft_templates/t09_injections.py` | Tạo mới | 8 khung chèn lệnh trong chat và từ chối an toàn (80 ca) |
| 18 | `scripts/sft_templates/t10_out_of_scope.py` | Tạo mới | 4 khung câu hỏi ngoài phạm vi (40 ca) |
| 19 | `scripts/sft_templates/t11_case_assist.py` | Tạo mới | 14 khung Trợ lý ca (190 ca: 150 thường + 40 chèn lệnh tài liệu) |
| 20 | `scripts/sft_templates/t12_fraud_context.py` | Tạo mới | 8 khung bối cảnh lừa đảo & bối cảnh Việt Nam (80 ca) |
| 21 | `scripts/sft_cases.py` | Tạo mới | CLI sinh ca (`generate`) và kiểm tính nhất quán bằng runner giả lập (`check`) |
| 22 | `scripts/sft_utterances.py` | Tạo mới | Tooling điền lời khách bằng DeepSeek V4.1 Flash, chặn giờ cao điểm, kiểm tra code chặt chẽ và ghi đệm |
| 23 | `tests/test_w670_sft_fixture_cases.py` | Tạo mới | Bộ unit test kiểm tra toàn bộ phần A |
| 24 | `docs/phase_role_aware_ops/W6_7_0_A_EXECUTION_REPORT_2026-11-16.md` | Tạo mới | Báo cáo thực thi phần A |

---

## 2. Kết Quả Kiểm Chứng Mục 5

### 2.1. Dữ liệu cửa hàng `build_sft_fixture.py`
- Lệnh chạy hai lần liên tiếp:
  - Lần 1: `python scripts/build_sft_fixture.py --out data/demo_events/store_events_sft_v1.jsonl`
  - Lần 2: `python scripts/build_sft_fixture.py --out data/demo_events/store_events_sft_v1.jsonl`
- Kết quả kiểm tra:
  - **SHA-256 (2 lần chạy):** `18b4e714d5005e3334b6287f9d8c045d19325d821c05ea5c59841d93e72efddb` (trùng khớp tuyệt đối).
  - **Tổng số sự kiện:** 2.011 sự kiện.
  - **Tổng số đơn hàng:** 129 đơn (nằm đúng trong khoảng 100–160).
  - **Tổng số khách hàng:** 92 khách.
  - **Trùng lặp với dữ liệu đo (`store_events.jsonl`):** 0 mã đơn, 0 mã khách (không trùng lặp).

### 2.2. Sinh khung ca `sft_cases.py generate`
- Chế độ toàn phần (1.200 ca): `python scripts/sft_cases.py generate --out <temp_dir>`
  - Tổng số ca: **1.200** ca.
  - Tổng số phiếu lời khách (briefs): **1.406** phiếu.
  - Số khung: **112** khung.
  - Số ca mỗi khung: từ 4 đến 15 ca (không khung nào vượt quá 15 ca).
  - Phân bổ theo bộ:
    - T01 (Tra cứu đơn): 100 ca (10 khung)
    - T02 (Sản phẩm & tồn kho): 90 ca (9 khung)
    - T03 (Chính sách): 110 ca (11 khung)
    - T04 (Hủy đơn): 100 ca (10 khung)
    - T05 (Trả hàng & hoàn tiền): 100 ca (10 khung)
    - T06 (Đổi hàng): 100 ca (10 khung)
    - T07 (Khách bức xúc): 60 ca (5 khung)
    - T08 (Đa lượt): 150 ca (13 khung)
    - T09 (Chèn lệnh chat): 80 ca (8 khung)
    - T10 (Ngoài phạm vi): 40 ca (4 khung)
    - T11 (Trợ lý ca): 190 ca (14 khung: 150 ca thường + 40 ca chèn lệnh)
    - T12 (Lừa đảo & bối cảnh VN): 80 ca (8 khung)
    - **Tổng cộng:** 1.200 ca.
  - Phân bổ theo giọng văn:
    - `chuan`: 480 ca (40,0%)
    - `teencode`: 240 ca (20,0%)
    - `khong_dau`: 180 ca (15,0%)
    - `sai_chinh_ta`: 180 ca (15,0%)
    - `dai`: 120 ca (10,0%)
- Chế độ pilot 100 ca: `python scripts/sft_cases.py generate --out <temp_dir> --pilot 100`
  - Tổng số ca: 100 ca, 112 phiếu lời khách.
  - Phân bổ theo bộ: T01: 8, T02: 8, T03: 9, T04: 8, T05: 8, T06: 8, T07: 5, T08: 12, T09: 7, T10: 5, T11: 15, T12: 7 (mỗi bộ đạt tối thiểu 5 ca).

### 2.3. Kiểm tính nhất quán runner giả lập `sft_cases.py check`
- Chạy: `python scripts/sft_cases.py check --out <temp_dir>` trên toàn bộ 1.200 ca:
  - **Tỉ lệ đạt:** **100% (1.200 / 1.200 ca)**.
  - Toàn bộ các ca thỏa mãn kỳ vọng `expect` khớp dữ liệu `sft_v1`, hành động `action`, quy tắc trích dẫn, và trạng thái cơ sở dữ liệu `final_state`.

### 2.4. Bộ kiểm đo chuẩn 250 ca
- `python scripts/eval_dataset_v2.py --final`: **PASS**.
- Bộ 250 ca S01–S12 và chữ ký SHA-256 của 12 tệp suite giữ nguyên vẹn 100%.

---

## 3. Kết Quả Kiểm Thử (Unit Tests)

### 3.1. Test chuyên biệt Phần A (`tests/test_w670_sft_fixture_cases.py`)
- Lệnh chạy: `python -m unittest tests/test_w670_sft_fixture_cases.py`
- Kết quả: **Ran 6 tests in 11.677s — OK (PASS 6/6)**.
  - `test_fixture_metadata_and_integrity`: PASS
  - `test_provision_templates_and_runner_fixtures`: PASS
  - `test_validate_train_case_contract`: PASS
  - `test_sft_cases_generator_and_pilot_check`: PASS (chạy pilot 24 ca đạt 100%)
  - `test_utterance_validation_rules`: PASS (bắt đủ lỗi thiếu mã đơn, lộ đáp án, có dấu ở `khong_dau`, trùng lặp ca đo)
  - `test_utterance_peak_hour_and_mock_cache`: PASS (chặn giờ cao điểm VN 13:00–17:00, chạy tiếp từ đệm cache)

### 3.2. Toàn bộ test của repo (`python -m unittest discover -s tests`)
- Lệnh chạy: `python -m unittest discover -s tests`
- Kết quả: **Ran 1317 tests in 500.914s — FAILED (failures=2, errors=3, skipped=89)**.
- Ghi chú: 5 lỗi thất bại đều là 5 test W4 baseline đã có sẵn trên `main` khi chạy trên môi trường Windows (gồm lỗi thiếu `pypdfium2`/ClamAV scanner và lệch đếm tệp đính kèm trên Windows: 3 lỗi trong `test_r1_w4_media_pipeline.py` / `test_r1_w4_customer_ref_and_v8.py`, 2 thất bại trong `test_r1_w4_customer_ref_and_v8.py`). Không có bất kỳ lỗi mới nào phát sinh từ phần mã W6.7.0.

### 3.3. Kiểm tra hợp đồng tài liệu (`scripts/check_docs_contract.py`)
- Lệnh chạy: `python scripts/check_docs_contract.py`
- Kết quả:
  1. Dataset integrity check: PASS
  2. Stale Git HEAD check: PASS
  3. Link & markdown rules check: PASS
  4. AST Dynamic tool contract check: PASS
  - **SUCCESS: All documentation contracts are valid and truthful.**

---

## 4. Điểm Còn Ngờ & Xử Lý Độ Lệch Thiết Kế

1. **Khớp nối chế độ `mode` của Trợ lý ca (T11):**
   - Thiết kế ban đầu ở một số đoạn nháp ghi mode `consult`. Trong mã nguồn kiểm tra của repo (`check_eval_dataset.py` `W4_ASSIST_MODES`), các chế độ hợp lệ là `{'summary', 'draft', 'ask'}`. Đã điều chỉnh các khung hỏi đáp nội bộ của nhân viên sang mode `'ask'` để tuân thủ chặt chẽ hợp đồng kiểm định.
2. **Quy tắc bảo vệ phát ngôn chưa trích dẫn (`check_final_answer`):**
   - Hệ thống RetailOps có cơ chế `answer_check` tự động loại bỏ các câu khẳng định quyền lợi chính sách (ví dụ miễn phí ship 2 chiều, bảo hành đổi mới 1-1) nếu không có lượt gọi công cụ `search_knowledge` trong lượt đó. Để đảm bảo runner giả lập không bị tước bỏ thông điệp, các câu trả lời mẫu của khung ca đa lượt và đổi trả đã được bổ sung lời gọi `search_knowledge` kèm trích dẫn `[{{last_tool.results.0.citation_id}}]`, vừa thỏa mãn quy tắc kiểm chứng vừa rèn luyện cho mô hình thói quen tra cứu tri thức trước khi trả lời.
3. **Quy tắc đổi sản phẩm cùng loại (`same_variant`):**
   - Trong `BoundTools.prepare_order_action`, khi yêu cầu đổi bảo hành cùng biến thể (`same_variant`), tham số `target_variant` không cần truyền (vì biến thể hiện tại đã nằm trong đơn); hệ thống tự động thiết lập quyền đổi bảo hành với `exchange_kind: None` và `action: choose_order_action_reason`. Đã căn chỉnh `fake_model` và `expect.order_action` theo đúng cơ chế này.
