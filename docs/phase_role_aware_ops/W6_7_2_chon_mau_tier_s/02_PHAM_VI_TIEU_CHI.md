# 02 — Vùng việc của Neon và tiêu chí xong

## Trong vùng (6 hạng mục, chi tiết ở 03)
| Mục | Tệp chính | Nội dung |
|---|---|---|
| A | `scripts/sft_select.py` | `export --round 2` theo luật Qwen trước, ba lớp ứng viên, nhiều tệp `--after` |
| B | `scripts/sft_select.py` | chế độ trọng tài: `export --arbiter`, `import --arbiter` (đưa bản thử vào repo) |
| C | `scripts/sft_select.py` | Tier S: xuất gói chấm cặp, kiểm và nhập phiếu, nhãn S + loại khác biệt |
| D | `scripts/sft_select.py` | `select` mới: Qwen trước, tối đa 2 mẫu/ca, luật mẫu thứ hai, trần khung, trần DeepSeek |
| E | `scripts/sft_build.py` | nhiều mẫu/ca, nhãn `source`/`tier`/`owner_edit`, lớp phủ sửa chữ Hán, chặn mẫu còn chữ Hán |
| F | `scripts/sft_cjk.py` (mới) | `export` CSV đoạn chữ Hán, `import` bản owner sửa → lớp phủ (đưa bản thử vào repo) |

Kèm: test cho từng mục (dữ liệu giả), dựng lại `notebooks/colab_agent.ipynb`, báo cáo thực thi.

## Ngoài vùng
- Sinh có khung đỡ, phiếu khung đỡ, cờ tắt rào, notebook Colab (→ W6.7.3).
- Viết/sửa bất kỳ chữ nào của mẫu huấn luyện (kể cả chữ thay cho chữ Hán) — owner làm.
- `evals/suites`, system prompt, `retailops/`, runner; chạy model; dữ liệu thật trên ổ E:/Drive/scratch.
- Rubric vòng 2 giữ nguyên rubric vòng 1 (`RUBRIC_TEXT`), chỉ đổi số ký tự cắt theo `--max-tool-chars`.

## Tiêu chí xong
- Mỗi mục A–F có test bằng dữ liệu giả, gồm ca biên nêu trong 03; các test W6.7.0/W6.7.1 hiện có vẫn xanh.
- `export --round 1` và `import` vòng 1 cho kết quả **trùng từng byte** với hành vi trước (không phá vòng 1 đã chấm).
- `select` cũ (1 mẫu/ca) vẫn chạy được bằng một cờ (ví dụ `--max-per-case 1`) để so sánh.
- Bộ test đầy đủ không thêm lỗi ngoài 5 lỗi có sẵn trên Windows (xem `W6_7_1_sua_khung/02`).
- Nhánh `phase-r1-w6-7-2-chon-mau` đã push (không PR), kèm báo cáo theo mẫu ở 04.
