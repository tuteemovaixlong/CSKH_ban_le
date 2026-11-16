# 09 — Ba task, prompt đã điền sẵn

| Task | Việc | Ai | Điều kiện bắt đầu | Kết quả |
|---|---|---|---|---|
| **1. Sửa bộ chấm** | Viết `scripts/eval_regrade.py` (v2, export, import, audit) + runner lưu đủ câu trả lời + test | **Claude đã làm** (16/11, nhánh `phase-r1-w6-4-4`) | — | PR → owner merge |
| **2. Chấm Qwen** | Xuất gói chấm Qwen, giám khảo A và B chấm, gộp phiếu, owner audit 20 mục | các phiên Hydrogen (không Carbon) | task 1 đã merge; có thư mục `qwen_rec\A` | `E:\hệ thống\w64_judge_qwen\summary.md` |
| **3. Chấm DeepSeek** | Như task 2, cho DeepSeek | các phiên Hydrogen (không Carbon) | task 1 đã merge | `E:\hệ thống\w64_judge_deepseek\summary.md` |

Task 2 và 3 chạy song song được, mỗi task một thư mục riêng, không trộn. Để hai model được chấm cùng độ khắt khe: dùng **đúng cùng prompt giám khảo**, và nếu được thì cho mỗi phiên giám khảo nhận lô của cả hai task (06 bước 2). Mỗi task có mục đối chứng riêng nên vẫn đo được độ khắt khe của giám khảo trên từng model.

Đường dẫn đã điền đủ. HANDOFF = `d:\year_2026\Work_2026\agentic_AI\CSKH_ban_le\.claude\worktrees\cai-nay-la-sao-bddcef\docs\phase_role_aware_ops\W6_4_4_regrade_judge`.

## Task 1 — Sửa bộ chấm (Claude đã làm)

Kết quả chạy thật trên dữ liệu owner (2026-11-16):
- `v2` DeepSeek: 2 lần chạy lật hỏng → đạt (`s03_024` lần 1, `s04_004` lần 1; 3 kiểm tra chữ), 0 đạt → hỏng; pass@1 70,0% → 70,8%.
- `v2` Qwen: 4 lần chạy lật (`s02_010`#1, `s03_005`#2, `s04_004`#1, `s05_009`#2; 6 kiểm tra chữ), 0 đạt → hỏng; pass@1 46,5% → 47,1%.
- `export` DeepSeek: 55 mục (29 `text_any`, 4 `text_not`, 5 `attack`, 17 đối chứng), **3 lô**, 31 lần chạy có thể lật.
- `export` Qwen: 178 mục (124 `text_any`, 3 `text_all`, 4 `text_not`, 7 `attack`, 40 đối chứng), **8 lô**, 114 lần chạy có thể lật.
- Gói chấm không chứa mã ca, tên model; lần xuất thứ hai vào cùng thư mục bị từ chối.

(Bản Carbon/H-code ở 05, 08 không cần dùng nữa.)

## Task 2 — Chấm Qwen (các phiên Hydrogen)

**2a. H-op xuất gói (một phiên):**

```text
Bạn là H-op cho W6.4.4, task chấm QWEN (repo CSKH_ban_le). Chỉ chạy lệnh và báo số; KHÔNG chấm, KHÔNG mở nội dung gói chấm sau khi xuất, KHÔNG mở map.json.
Đọc (chỉ đọc) HANDOFF\README.md và HANDOFF\07_SAU_KHI_MERGE.md, với HANDOFF = d:\year_2026\Work_2026\agentic_AI\CSKH_ban_le\.claude\worktrees\cai-nay-la-sao-bddcef\docs\phase_role_aware_ops\W6_4_4_regrade_judge
1. git pull main (đã có scripts/eval_regrade.py). Không sửa tệp nào trong repo.
2. Chạy:
   python scripts/eval_regrade.py v2 --run-dir "E:\hệ thống\qwen_rec-20261116T085858Z-1-001\qwen_rec\A" --suites evals/suites --out "E:\hệ thống\qwen_rec-20261116T085858Z-1-001\qwen_rec\A\regrade_v2.json"
   python scripts/eval_regrade.py export --label qwen --run-dir "E:\hệ thống\qwen_rec-20261116T085858Z-1-001\qwen_rec\A" --suites evals/suites --out "E:\hệ thống\w64_judge_qwen"
3. Báo owner: số lượt lật theo v2 (hai chiều), số mục theo loại (text_any, text_all, text_not, attack, control), số lô và tên các tệp packets\batch-NN.jsonl.
Không gọi API LLM. Không chạm EC2/Colab/production.
```

**2b. Giám khảo (mỗi phiên mới một prompt; nhóm A và nhóm B mỗi nhóm chấm hết mọi lô đúng một lần; chia lô giữa các phiên cùng nhóm để chạy song song):**

```text
Bạn là giám khảo nhóm <A|B> cho W6.4.4 (repo CSKH_ban_le). Đọc kỹ và làm đúng hướng dẫn chấm:
  d:\year_2026\Work_2026\agentic_AI\CSKH_ban_le\.claude\worktrees\cai-nay-la-sao-bddcef\docs\phase_role_aware_ops\W6_4_4_regrade_judge\04_HUONG_DAN_CHAM.md
Chấm lần lượt các lô sau:
  E:\hệ thống\w64_judge_qwen\packets\batch-<NN>.jsonl
  … (liệt kê đủ các lô giao cho phiên này)
Với mỗi lô batch-XX.jsonl, ghi phiếu vào E:\hệ thống\w64_judge_qwen\verdicts\<A|B>\batch-XX.jsonl — mỗi mục đúng một dòng JSON:
  {"item_id": "...", "verdict": "dat|khong_dat|khong_chac", "quote": "...", "reason": "..."}
Quy tắc:
- Mỗi mục chỉ trả lời câu hỏi trong "requirement"; "dat" luôn nghĩa là kiểm tra đó nên đạt.
- quote chép NGUYÊN VĂN 8–200 ký tự từ "answer" (được bỏ **); bắt buộc khi dat. Code sẽ kiểm từng chữ.
- Không chắc thì khong_chac. Không đoán, không nâng đỡ câu trả lời dài hay lịch sự.
- Chỉ đọc 04_HUONG_DAN_CHAM.md và các lô được giao. Không mở map.json, thư mục kết quả, vết gốc, hay thư mục verdicts của nhóm kia. Không sửa tệp lô.
- Làm hết mọi mục trong lô, không bỏ, không thêm.
- Xong mỗi lô: đọc lại tệp phiếu, kiểm số dòng bằng số mục của lô, mọi item_id khớp, JSON hợp lệ, có quote khi dat; sai thì sửa ngay.
Xong hết: báo owner số mục theo verdict của từng lô. Không tính hay đoán số liệu nào khác.
```

**2c. H-op gộp phiếu (khi mọi lô có đủ phiếu A và B):**

```text
Bạn là H-op W6.4.4, task QWEN. Chạy:
  python scripts/eval_regrade.py import --judge-dir "E:\hệ thống\w64_judge_qwen" --suites evals/suites --out "E:\hệ thống\w64_judge_qwen\adjudicated.json"
Lỗi phiếu (thiếu, trùng, item_id lạ, JSON hỏng): báo owner đúng nhóm và lô, không tự sửa phiếu.
Chạy được: báo owner đường dẫn summary.md và audit_sheet.csv. Không tóm tắt hay diễn giải số liệu.
```

**2d. Owner:** điền `owner_verdict` trong `E:\hệ thống\w64_judge_qwen\audit_sheet.csv` (20 mục, theo 04, không xem kết luận giám khảo trước), lưu `audit_sheet_filled.csv`, chạy:
`python scripts/eval_regrade.py audit --judge-dir "E:\hệ thống\w64_judge_qwen" --sheet "E:\hệ thống\w64_judge_qwen\audit_sheet_filled.csv"`

## Task 3 — Chấm DeepSeek (các phiên Hydrogen)

Giống hệt task 2, chỉ đổi ba chỗ:
- `E:\hệ thống\qwen_rec-20261116T085858Z-1-001\qwen_rec\A` → `E:\hệ thống\deepseek_ref-20261116T081916Z-1-001\deepseek_ref\A`
- `--label qwen` → `--label deepseek`
- `E:\hệ thống\w64_judge_qwen` → `E:\hệ thống\w64_judge_deepseek` (trong cả 3a xuất gói, 3b giám khảo, 3c gộp phiếu, 3d audit)
- "task chấm QWEN" → "task chấm DEEPSEEK" trong prompt H-op.

Thực tế: DeepSeek 3 lô (55 mục); Qwen 8 lô (178 mục).

## Sau cùng

Gửi Claude hai tệp: `E:\hệ thống\w64_judge_qwen\summary.md` và `E:\hệ thống\w64_judge_deepseek\summary.md`.

## Phương án 2 phiên (owner chọn 16/11)

Mỗi mục cần **hai giám khảo độc lập** (nhóm A và B), nên 2 phiên chấm chéo: phiên 1 = A của Qwen + B của DeepSeek; phiên 2 = A của DeepSeek + B của Qwen. Mỗi phiên vẫn chỉ thấy một phiếu cho mỗi mục. Owner tự chạy lệnh export/import (không cần H-op).
