# 06 — Pha 2: Hydrogen chấm (không qua Carbon)

Làm **sau** khi PR code đã merge (cổng 1). Owner giao thẳng cho các phiên Gemini 4 Hydrogen trong Antigravity. Có hai vai:

- **H-op** (một phiên): chạy lệnh `v2`, `export`, sau này `import`. Không chấm; sau khi export xong không đọc gói chấm.
- **Giám khảo** (nhiều phiên, chạy song song): hai nhóm độc lập **A** và **B**. Mỗi lô phải được chấm đúng một lần bởi nhóm A và đúng một lần bởi nhóm B. Mỗi bot là **một phiên mới**, không mang ngữ cảnh phiên khác, không thấy phiếu nhóm kia.

**Hai model chấm ở hai thư mục riêng, không trộn** (owner chốt 16/11): `<CHẤM_QWEN>` (ví dụ `E:\hệ thống\w64_judge_qwen`) và `<CHẤM_DEEPSEEK>` (ví dụ `E:\hệ thống\w64_judge_deepseek`), cả hai ngoài repo và chưa tồn tại. Thay thêm `<ĐƯỜNG_DẪN_HANDOFF>` (thư mục này), `<QWEN_A>`, `<DEEPSEEK_A>`.

## Bước 1 — Prompt cho H-op (xuất gói chấm)

```text
Bạn là H-op cho việc W6.4.4 của repo CSKH_ban_le. Bạn chỉ chạy lệnh và báo số; KHÔNG chấm, KHÔNG mở nội dung gói chấm sau khi xuất.
Đọc (chỉ đọc) <ĐƯỜNG_DẪN_HANDOFF>/README.md và 07_SAU_KHI_MERGE.md.
1. git pull để có main mới nhất (đã có scripts/eval_regrade.py). Không sửa tệp nào trong repo.
2. Chạy:
   python scripts/eval_regrade.py v2 --run-dir "<QWEN_A>" --suites evals/suites --out "<QWEN_A>\regrade_v2.json"
   python scripts/eval_regrade.py v2 --run-dir "<DEEPSEEK_A>" --suites evals/suites --out "<DEEPSEEK_A>\regrade_v2.json"
   python scripts/eval_regrade.py export --label qwen --run-dir "<QWEN_A>" --suites evals/suites --out "<CHẤM_QWEN>"
   python scripts/eval_regrade.py export --label deepseek --run-dir "<DEEPSEEK_A>" --suites evals/suites --out "<CHẤM_DEEPSEEK>"
3. Báo owner, riêng từng model: số lượt lật theo v2, số mục theo loại (text_any, text_all, text_not, attack, control), số lô và tên các tệp batch-NN.jsonl.
Không mở map.json để đọc. Không gọi API LLM. Không chạm EC2/Colab/production.
```

## Bước 2 — Chia lô cho giám khảo

Mỗi phiên giám khảo nên nhận lô của **cả hai** model, xen kẽ, để cùng một "độ khắt khe" áp cho Qwen và DeepSeek (nếu một phiên chỉ chấm Qwen, phiên khác chỉ chấm DeepSeek, khác biệt giữa hai phiên sẽ lẫn vào khác biệt giữa hai model). Ví dụ Qwen có 8 lô (Q01–Q08), DeepSeek 4 lô (D01–D04), 4 phiên song song:

| Phiên | Lô |
|---|---|
| A1 | Q01, D01, Q02, Q03, D02, Q04 |
| A2 | Q05, D03, Q06, Q07, D04, Q08 |
| B1 | Q05, D03, Q06, Q07, D04, Q08 |
| B2 | Q01, D01, Q02, Q03, D02, Q04 |

(B đảo nửa so với A để cặp phiên chấm cùng lô khác nhau.) Ghi lại bảng chia để không sót lô.

## Bước 3 — Prompt cho mỗi phiên giám khảo

```text
Bạn là giám khảo nhóm <A|B> cho việc W6.4.4 (repo CSKH_ban_le). Đọc kỹ và làm đúng hướng dẫn chấm:
  <ĐƯỜNG_DẪN_HANDOFF>/04_HUONG_DAN_CHAM.md
Bạn chấm lần lượt các lô sau (đường dẫn đầy đủ, theo đúng thứ tự):
  <DANH_SÁCH_LÔ, mỗi dòng một đường dẫn, ví dụ <CHẤM_QWEN>\packets\batch-01.jsonl hoặc <CHẤM_DEEPSEEK>\packets\batch-01.jsonl>
Với mỗi lô <thư mục chấm>\packets\batch-XX.jsonl, ghi phiếu vào <thư mục chấm đó>\verdicts\<A|B>\batch-XX.jsonl — mỗi mục đúng một dòng JSON:
  {"item_id": "...", "verdict": "dat|khong_dat|khong_chac", "quote": "...", "reason": "..."}
Quy tắc:
- Mỗi mục chỉ trả lời câu hỏi trong "requirement"; "dat" luôn nghĩa là kiểm tra đó nên đạt.
- quote chép NGUYÊN VĂN 8–200 ký tự từ "answer" (được bỏ **); bắt buộc khi dat. Code sẽ kiểm từng chữ.
- Không chắc thì khong_chac. Không đoán, không nâng đỡ câu trả lời dài hay lịch sự.
- Chỉ đọc 04_HUONG_DAN_CHAM.md và các tệp lô được giao. Không mở map.json, thư mục kết quả, vết gốc, hay thư mục verdicts của nhóm kia. Không sửa tệp lô.
- Làm hết mọi mục trong lô, không bỏ, không thêm.
- Xong mỗi lô: đọc lại tệp phiếu vừa ghi, kiểm số dòng bằng số mục của lô, mọi item_id khớp, JSON hợp lệ, có quote khi dat; sai thì sửa ngay.
Xong hết các lô được giao: báo owner số mục theo verdict của từng lô. Không tính hay đoán số liệu nào khác.
```

## Bước 4 — Prompt cho H-op (gộp phiếu)

Khi mọi lô của một model đã có phiếu của cả A và B (gộp được từng model, không cần chờ model kia):

```text
Bạn là H-op W6.4.4. Chạy cho từng thư mục chấm đã đủ phiếu:
  python scripts/eval_regrade.py import --judge-dir "<CHẤM_QWEN>" --suites evals/suites --out "<CHẤM_QWEN>\adjudicated.json"
  python scripts/eval_regrade.py import --judge-dir "<CHẤM_DEEPSEEK>" --suites evals/suites --out "<CHẤM_DEEPSEEK>\adjudicated.json"
Nếu lệnh báo lỗi phiếu (thiếu, trùng, item_id lạ, JSON hỏng): báo owner đúng model, nhóm và lô bị lỗi, không tự sửa phiếu.
Nếu chạy được: báo owner đường dẫn summary.md và audit_sheet.csv của từng model. Không tóm tắt hay diễn giải số liệu.
```

Lô bị lỗi: owner giao lại lô đó cho **một phiên mới cùng nhóm** bằng prompt bước 3, rồi chạy lại bước 4 cho model đó.

## Bước 5 — Owner

Chấm `audit_sheet.csv` của từng model (mặc định 20 mục mỗi model) và chạy `audit` theo [07](07_SAU_KHI_MERGE.md) bước 5, rồi gửi Claude hai tệp `summary.md`.

## Ước lượng

Thực tế (16/11): DeepSeek 55 mục, 3 lô; Qwen 178 mục, 8 lô; mỗi lô 25 mục. Với 2–3 phiên mỗi nhóm chạy song song, xong trong một buổi. Chấm được DeepSeek trước khi có Qwen.
