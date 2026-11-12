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

Mỗi bộ được thêm nguyên byte như model độc lập gửi về, sau khi qua bộ kiểm và phát lại quỹ đạo mẫu đạt 100%. Ca hỏng, hoặc ca có kỳ vọng chấm hỏng được câu trả lời đúng, được trả lại cho model kèm lý do; model gửi lại nguyên dòng, Claude thay đúng dòng đó và không tự sửa kỳ vọng (W6.3-D1).

| Bộ | Số ca | Người viết | Ngày nhận | SHA-256 | Ghi chú |
|---|---|---|---|---|---|
| S07 | 11 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-11, sửa 2026-11-12 | `ccb9015e583dbca8dd217a8eb6f7c82e94e1f75fe4d907a549ae33fe20b92be9` | Phát lại 5/11 trước W6.3.1, 11/11 sau W6.3.1 (PR #94). Ngày 2026-11-12 model thay `answer_not` của `s07_006` ("nghỉ Chủ nhật" khớp câu đúng "không nghỉ Chủ nhật"); bản đầu `a8cb07fb…` |
| S09 | 20 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-11, sửa 2026-11-12 | `81ce8d9d19b9cbd0b0530a9ae5754d59c66ec72aaaaf36b884826e95e4e368ff` | Lần đầu phát lại 18/20; trả lại 2 ca (`s09_008` tự mâu thuẫn với `answer_not`, `s09_011` thiếu cách nói đồng nghĩa); bản sửa 20/20. Ngày 2026-11-12 model thay `answer_not` của `s09_006`, `s09_015`, `s09_020` vì câu từ chối đúng nhắc lại lời khách ("em không thể xác nhận mã VCH-VIP-500K") khớp cụm cấm; bản trước `8b514742…` |
| S10 | 10 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `01562bc4e6241172481f6e43a4b556ce6278212836d20fb8af14b7302a53404b` | Lần đầu phát lại 10/10; trả lại 3 ca (`s10_008`, `s10_009`, `s10_010`) vì `answer_not` khớp được câu trả lời đúng ("không cung cấp mã OTP", "sau khi đặt hàng thành công"); bản sửa chỉ đổi 3 danh sách đó, 10/10 |
