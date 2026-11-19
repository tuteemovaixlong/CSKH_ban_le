# 01 — Hiện trạng (19/11/2026)

## Số liệu (thước v4, `main` = `302f54b`)
- 1.200 ca SFT; mỗi ca Qwen ×4 + DeepSeek ×2 = 7.200 lượt; chấm code v4: 1.052 ca có ứng viên.
- Phần B vòng 1 (hai nhóm giám khảo) + **trọng tài Neon High** cho 81 mục `khong_chac` (76 `dat` / 5 `khong_dat`),
  owner chọn **luật bàn giao**: trọng tài giải mọi `khong_chac`. Tier ứng viên A 548 / B 76 / C 394.
- Nhóm ca (trừ 64 ca của 6 khung làm lại ở W6.7.1):

| Nhóm | Ca |
|---|---|
| Có Tier A | 542 (Qwen 391, DeepSeek 151) |
| Còn A_code của Qwen chưa chấm | 193 |
| Không còn A_code của Qwen (→ sinh có khung đỡ ở W6.7.3) | 389 + 12 ca rào |

- Ca có Tier A của Qwen mà còn A_code DeepSeek chưa chấm: **290** (94 ở 5 bộ khó). Trên các ca này DeepSeek gọi số tool
  như Qwen (chênh trung vị 0), dài hơn ~14%; 55% cặp khác chuỗi tool; độ giống câu chữ luôn thấp (trung vị 0,05 suy
  luận / 0,14 trả lời) → **không dùng độ giống câu chữ để đo khác biệt giữa hai model**.
- Chữ Hán/Nhật/Hàn: **115 câu trả lời của Qwen** (DeepSeek 0), trong đó **20 mẫu Tier A sẽ vào tập** (21 đoạn); suy
  luận 6 mẫu. Giám khảo vòng 1 không được dặn kiểm ngôn ngữ nên để lọt.

## Quyết định của owner (19/11)
1. **Qwen trước**: vòng 2 chấm A_code kế tiếp của Qwen; DeepSeek chỉ ở chỗ Qwen thua (ngưỡng thua: 4 lượt gốc + 4 lượt
   có khung đỡ — phần sinh ở W6.7.3).
2. **Mẫu thứ hai, có trần**: tối đa 2 mẫu/ca. Ở 5 bộ khó (T05, T06, T08, T11, T12) mẫu thứ hai ưu tiên DeepSeek Tier A,
   không có thì một lượt Qwen khác (độ giống < 0,85).
3. **Hai model cùng Tier A** trên một ca: mẫu Qwen vào tập; mẫu DeepSeek chỉ vào nếu đạt **Tier S** và khác cách xử lý.
4. **Tier S** (mẫu xuất sắc, cả Qwen lẫn DeepSeek): Tier A + đủ 7 tiêu chí (03 mục C), chấm cặp bằng Neon High. Hai mẫu S
   khác chuỗi tool hoặc khác cách xử lý / khác thông tin hữu ích → giữ cả hai; chỉ khác câu chữ → giữ một (ưu tiên Qwen).
5. **Trần**: mẫu thứ hai theo khung (≤ 50% số ca Tier A của khung; T09, T10 ≤ 25%); tỉ trọng DeepSeek ≤ 35% toàn tập.
6. **Chữ Hán**: owner tự sửa tay qua tệp CSV; nạp lại thành lớp phủ khi dựng tập, không sửa vết gốc.

## Bản thử của Claude (tham chiếu, chạy được, trong `scratch/` của worktree ở README; bản sao ở `E:\hệ thống\w67_ket_qua_2026-11-19`)
| Tệp | Làm gì |
|---|---|
| `scratch/w67_trong_tai/export_arbiter.py`, `import_arbiter.py`, `check_arbiter.py` | gói trọng tài (8.000 ký tự, giữ `item_id` vòng 1), kiểm phiếu, nhập theo luật bàn giao / `--strict-kckc` |
| `scratch/w67_cjk/export_cjk.py`, `import_cjk.py` | xuất đoạn chữ Hán từ vết gốc ra CSV; nhập bản owner sửa thành `owner_edits_cjk.jsonl` có kiểm |
| `scratch/w67_audit/regen_v4.py`, `sim_v4.py` | sinh lại ca, so kỳ vọng, chấm lại so sánh |

Dữ liệu thật dùng sau merge: `scratch/w67_audit/scores_v4.json` (SHA `711d7946…`),
`scratch/w67_trong_tai/adjudicated_r1_trong_tai.json` (`9a802ac1…`), ca điền v4 `…/gen_v4/cases_sft_v1_filled_v4.jsonl`
(`7e0d090c…`). Neon KHÔNG cần và không được mở dữ liệu thật.
