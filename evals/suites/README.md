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
| S09 | 20 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-11, sửa 2026-11-12 | `ceb9584d4602a9aeb7385f0e8e2272e0b3ced14e54a7307a266db62412c69f94` | Lần đầu phát lại 18/20; trả lại 2 ca (`s09_008` tự mâu thuẫn với `answer_not`, `s09_011` thiếu cách nói đồng nghĩa); bản sửa 20/20. Ngày 2026-11-12 model thay `answer_not` của `s09_006`, `s09_015`, `s09_020` vì câu từ chối đúng nhắc lại lời khách ("em không thể xác nhận mã VCH-VIP-500K") khớp cụm cấm; bản trước `8b514742…` |
| S10 | 10 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `01562bc4e6241172481f6e43a4b556ce6278212836d20fb8af14b7302a53404b` | Lần đầu phát lại 10/10; trả lại 3 ca (`s10_008`, `s10_009`, `s10_010`) vì `answer_not` khớp được câu trả lời đúng ("không cung cấp mã OTP", "sau khi đặt hàng thành công"); bản sửa chỉ đổi 3 danh sách đó, 10/10 |
| S01 | 26 | Gemini 4 Carbon (Google AI Studio, phiên chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `6742499c31f1ced367b90eb2a29a1e543c22f9b502b21ef7ce5260c555c568d4` | Hai phần, ghép thành một tệp (CRLF đổi thành LF, nội dung từng dòng giữ nguyên). Trả 5 ca: `s01_012`, `s01_013` (quỹ đạo mẫu gọi mã ngoài dữ liệu demo), `s01_018` (nhận câu trấn an không căn cứ), `s01_022`, `s01_026` (nhãn `vn_context`). Lộ ra F30, F31, F32 (W6.3.2): 18/26 trước, 26/26 sau |
| S02 | 18 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `35cd5b0df89c4b174547d1a94d86c5d428e67cca8df98f1128fd3d12517ef54d` | Trả 3 ca (`s02_010`, `s02_016` thiếu cách nói đồng nghĩa; `s02_018` kiểm nội dung khách không hỏi). Lộ ra F33, F34 (W6.3.3): 14/18 trên `main` cũ, 18/18 sau W6.3.2 và W6.3.3 |
| S03 | 30 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `9142f8b7f2b57dd2913ad18b9e5646d7453226d0ff97f87864301b5d341340a5` | Hai phần, ghép thành một tệp. Trả 5 ca: `s03_002`, `s03_005`, `s03_007`, `s03_009` (câu chính sách thứ hai thiếu trích dẫn), `s03_022` (`answer_not` bẫy phủ định, thiếu dạng liệt kê). `s03_028` hỏng do F34 cho tới W6.3.3; 30/30 |
| S04 | 13 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `d7734277f505a41e0c823e2059228e5f0b055f3ecbc8be6a576e195f89cda1af` | Trả 1 ca: `s04_010` có `knowledge` mà câu trả lời không trích dẫn (`knowledge_citation_missing`); 13/13 |
| S05 | 20 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-12 | `2143a51c1b80969d22ccf2d4411e62dcb53486844a7e58d7f90fc453acaa0db1` | Lần đầu 20/20. Trả 1 ca: `s05_017` câu mẫu nêu biến thể XL không có trong catalog P-202 |
| S06 | 14 | Gemini 4 Carbon (phiên AI Studio thứ hai, mở từ S02; chỉ đọc `eval_pack` bản 2) | 2026-11-13 | `27b1de0a7b5a64f52cb4f56be7501317ee4f3a36a10c38cac9663c179d2e7f11` | Trả 1 ca: `s06_004` lượt 2 mở form cho đơn chỉ được nêu sau `list_orders`, chưa được focus; thêm `get_order` ở lượt 1; 14/14 |
