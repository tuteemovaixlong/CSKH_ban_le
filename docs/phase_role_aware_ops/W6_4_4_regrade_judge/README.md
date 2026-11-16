# W6.4.4 — Chấm lại W6.4: bộ chuẩn hóa v2 và giám khảo Gemini

Thư mục handoff. Đọc theo thứ tự 01 → 08. **Owner bắt đầu từ [09_BA_TASK.md](09_BA_TASK.md)**: ba task (sửa bộ chấm, chấm Qwen, chấm DeepSeek) với prompt đã điền sẵn.

> **Cập nhật 2026-11-16:** owner yêu cầu Claude làm luôn task 1 (sửa bộ chấm). Code nằm trên nhánh `phase-r1-w6-4-4` (`scripts/eval_regrade.py`, runner lưu đủ câu trả lời, `tests/test_w644_eval_regrade.py`). Không cần Carbon/H-code; 05 và 08 chỉ còn để tra cứu. Sau khi PR merge, làm tiếp task 2 và 3 theo 09.

## Vì sao

Mổ 75 ca DeepSeek hỏng ở bước tham chiếu (`../W6_4_measurement/04_DEEPSEEK_REF_2026-11-16.md`) cho thấy bộ chấm tự động đánh hỏng nhiều câu trả lời đúng ý: chỉ tìm đúng cụm chữ, không hiểu chữ đậm chen giữa cụm, `huỷ`/`hủy`, phủ định, trích dẫn để cảnh báo. Bộ ca 250 ca **đóng băng, không sửa**. Thay vào đó, owner chốt (2026-11-16):

1. **Bộ chuẩn hóa v2 bằng code** cho phần máy móc (markdown, vị trí dấu thanh), áp **giống hệt** cho mọi model.
2. **Giám khảo Gemini 4 Hydrogen** (nhiều phiên chấm song song, hai nhóm độc lập; Carbon chỉ điều phối phần code) cho phần ý nghĩa, chỉ ở các kiểm tra chữ đã hỏng, theo hướng dẫn chấm viết sẵn, có trích dẫn được code kiểm.
3. **Owner chấm tay một mẫu** để đo độ khớp với giám khảo.

Kết quả báo **ba con số** cho mỗi model: chính thức (bộ chấm gốc, không đổi) → v2 (chuẩn hóa) → đã xem xét (sau giám khảo). Số chính thức vẫn là số chính.

## Phân vai

Hai pha. **Pha 1 (code):** owner dán [08](08_PROMPT_CARBON_DIEU_PHOI.md) cho Carbon; Carbon điều phối một bot Hydrogen viết code, dừng ở cổng 1. **Pha 2 (chấm):** không qua Carbon; owner giao thẳng cho các phiên Hydrogen theo [06](06_PROMPT_GIAM_KHAO.md).

| Ai | Việc | Tệp |
|---|---|---|
| Carbon | Pha 1: điều phối và kiểm phần code, dừng ở cổng 1 (PR) | [08](08_PROMPT_CARBON_DIEU_PHOI.md) |
| Hydrogen "H-code" | Pha 1: viết `scripts/eval_regrade.py` + sửa runner lưu đủ câu trả lời + test; mở PR | [05](05_PROMPT_HYDROGEN_CODE.md) |
| Claude → owner | **Cổng 1:** Claude kiểm PR một lượt; owner merge | — |
| Hydrogen "H-op" | Pha 2: chạy `v2`, `export`, `import` (không chấm) | [06](06_PROMPT_GIAM_KHAO.md) bước 1, 4 |
| Các phiên Hydrogen giám khảo | Pha 2: chấm song song theo lô; hai nhóm A và B độc lập | [04](04_HUONG_DAN_CHAM.md), [06](06_PROMPT_GIAM_KHAO.md) bước 2–3 |
| Owner | Chấm tay 40 mục kiểm định, chạy `audit` | [07](07_SAU_KHI_MERGE.md) |
| Claude | Đọc `summary.md` và kết quả kiểm định (không đọc lại từng ca), viết báo cáo W6.4 | — |

## Dữ liệu (trên máy owner)

- DeepSeek tham chiếu: `E:\hệ thống\deepseek_ref-20261116T081916Z-1-001\deepseek_ref\A`
- Qwen A: thư mục `qwen_rec\A` sau khi owner tải về (chưa có lúc viết).
- Bộ ca: `evals/suites/S*.jsonl` trong repo (đóng băng, SHA 12/12).
- Mỗi thư mục bước có `merged.json` (báo cáo, câu trả lời cắt 600 ký tự), `shard-NN.jsonl` (vết từng lần gọi model), `manifest.json`.

## Quy tắc

- Không sửa `evals/suites/*`. Không sửa `grade_turn`/`squash` trong runner (số chính thức phải giữ nguyên); bộ v2 nằm trong script riêng.
- Executor không merge, không push `main`, không deploy, không chạm EC2/Colab/production, không gọi API LLM nào từ code, không thêm thư viện.
- Giám khảo chỉ đọc gói chấm đã ẩn danh; không mở tệp ánh xạ `map.json`, không đọc vết gốc, không biết câu trả lời của model nào.
- Dữ liệu là dữ liệu mô phỏng (đã che PII); gói chấm không chứa khóa.

## Quyết định cần ghi §32 khi đẩy batch tài liệu

- W6.4-D18: chỉ chạy bước A; B, C, D, regression thành tùy chọn (owner, 16/11).
- W6.4-D19: tham chiếu DeepSeek `deepseek-flash` cấu hình production trên 250 ca × 1, chỉ để so (owner, 16/11).
- W6.4-D20: chấm lại bằng bộ chuẩn hóa v2 + giám khảo Gemini hai lượt độc lập + owner chấm tay mẫu kiểm định; số chính thức không đổi (owner, 16/11).
