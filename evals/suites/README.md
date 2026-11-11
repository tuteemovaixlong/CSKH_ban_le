# Bộ đánh giá W6.3

Thư mục này dành cho `S01.jsonl` … `S12.jsonl` của bộ đánh giá 250 ca theo
`khoa_luan/eval_pack/04_DINH_DANG_VA_CHAM.md` bản 2 và phân bổ ở `05_PHAN_BO_CA.md`.
Chưa có ca thì CI báo 0 ca và đạt. Bốn ví dụ định dạng nằm riêng trong
`khoa_luan/eval_pack/06_vi_du.jsonl`, không tính vào 250 ca.

210 ca mô phỏng do model độc lập viết; 40 ca chuyển thể do Claude làm sau khi công cụ
được merge. Executor phần code không viết hay sửa ca trong thư mục này.

```sh
python scripts/check_eval_dataset.py
python scripts/check_eval_dataset.py evals/suites --final
python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0
```

Trước W6.4, đóng băng SHA-256 từng file. Báo cáo runner lưu hash byte gốc của từng file;
`eval_stats compare` từ chối khi khác tập mã ca hoặc khác hash.

## Nguồn gốc từng bộ

Mỗi bộ được thêm nguyên byte như model độc lập gửi về, sau khi qua bộ kiểm và phát lại quỹ đạo mẫu đạt 100%. Ca hỏng được trả lại cho model kèm lý do; Claude không sửa kỳ vọng (W6.3-D1).

| Bộ | Số ca | Người viết | Ngày nhận | SHA-256 | Ghi chú |
|---|---|---|---|---|---|
| S07 | 11 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-11 | `a8cb07fbb35eb6f336d762204b69b555db4390e06dd71132865218be1b37c72a` | Phát lại 5/11 trước W6.3.1, 11/11 sau W6.3.1 (PR #94) |
