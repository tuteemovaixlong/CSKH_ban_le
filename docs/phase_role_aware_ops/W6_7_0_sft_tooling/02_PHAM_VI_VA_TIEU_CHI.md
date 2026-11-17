# 02 — Phạm vi và tiêu chí nghiệm thu

## Phần A (PR 1, nhánh `phase-r1-w6-7-0-a`)

| # | Việc | Tệp |
|---|---|---|
| A1 | Bộ dựng dữ liệu cửa hàng `sft_v1` (tất định) + tệp sự kiện đã dựng + tệp mô tả | `scripts/build_sft_fixture.py`, `data/demo_events/store_events_sft_v1.jsonl`, `data/demo_events/store_events_sft_v1.meta.json` |
| A2 | Runner nạp fixture `sft_v1`; nhận tệp ca huấn luyện | `scripts/run_agent_scenarios.py` (chỉ thêm nhánh) |
| A3 | Bộ kiểm định dạng ca huấn luyện | `scripts/sft_dataset.py` |
| A4 | Bộ sinh khung ca: 80–120 khung → 1.200 ca + phiếu yêu cầu lời khách | `scripts/sft_cases.py`, `scripts/sft_templates/` |
| A5 | Bước viết lời khách bằng DeepSeek + kiểm bằng code + lọc trùng với 250 ca | `scripts/sft_utterances.py` |
| A6 | Test | `tests/test_w670_sft_fixture_cases.py` |

**Nghiệm thu A:**
- Toàn bộ test của repo xanh; **mọi test cũ về bộ đo không đổi kết quả** (fixture `standard`, `late_voucher_issued`, `validate_suites --final` 250 ca, SHA 12/12).
- `build_sft_fixture.py` chạy hai lần cho ra **cùng SHA-256** tệp sự kiện; 0 mã đơn và 0 mã khách trùng với `store_events.jsonl`.
- Runner chạy `--fake` được một tệp ca huấn luyện mẫu trên fixture `sft_v1` (có ca giả đạt).
- `sft_cases.py generate` sinh đủ 1.200 ca theo phân bổ ở [04](04_DANH_MUC_KHUNG_CA.md), mọi ca qua `sft_dataset.validate_train_case`; có chế độ `--pilot 100` (phân tầng theo bộ); báo số khung, số ca mỗi khung (không khung nào quá 15 ca), phân bổ theo bộ, giọng văn.
- Kiểm tính nhất quán: chạy runner `--fake` với **câu trả lời mẫu do khung sinh** (`fake_model`) trên toàn bộ 1.200 ca → **đạt 100%** (chứng minh `expect` khớp dữ liệu `sft_v1`).
- `sft_utterances.py` chạy được với client giả; từ chối chạy giờ cao điểm DeepSeek (13:00–17:00 giờ Việt Nam ngày thường) trừ khi có `--allow-peak`; kiểm và viết lại tối đa 3 lần các câu hỏng kiểm.

## Phần B (PR 2, nhánh `phase-r1-w6-7-0-b`)

| # | Việc | Tệp |
|---|---|---|
| B1 | Chọn lượt: chấm code, xếp hạng, xuất gói giám khảo, gộp phiếu, xếp tier, chọn mẫu cuối | `scripts/sft_select.py` |
| B2 | Dựng tập SFT từ vết của mẫu được chọn | `scripts/sft_build.py` |
| B3 | Test | `tests/test_w670_sft_select_build.py` |

**Nghiệm thu B:**
- Toàn bộ test xanh; test chạy trên thư mục kết quả giả tự dựng (không đọc ổ E:).
- Quy tắc chọn đúng [05](05_THIET_KE_PHAN_B.md): Qwen trước, DeepSeek lấp chỗ; chỉ tier A; trích dẫn của giám khảo được code kiểm; gộp bảo thủ hai nhóm.
- `sft_build.py` xuất JSONL hội thoại (`messages`, `tools`, `meta`) đúng định dạng ở [05](05_THIET_KE_PHAN_B.md); tách train/val theo khung; báo thống kê độ dài, tỉ lệ nguồn Qwen/DeepSeek, số mẫu mỗi bộ; **từ chối** mọi mẫu có `case_id` bắt đầu bằng `s` hoặc lời khách trùng 250 ca.

## Ngoài phạm vi

- Notebook Colab (Claude làm sau khi PR A merge).
- Chạy model thật, gọi API thật, huấn luyện.
- Sửa hệ thống, sửa bộ đo, sửa bộ chấm.
