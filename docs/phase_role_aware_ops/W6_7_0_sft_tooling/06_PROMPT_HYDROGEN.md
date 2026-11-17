# 06 — Prompt cho Gemini 4 Hydrogen "H-code"

Carbon dán prompt này cho H-code, mỗi phần một lần (đổi `<PHẦN>` thành `A` hoặc `B`). HANDOFF = thư mục này.

```text
Bạn là executor cho repo CSKH_ban_le (RetailOps). Việc: W6.7.0 phần <PHẦN> — công cụ sinh dữ liệu chưng cất SFT.

Đọc trước (chỉ đọc), theo thứ tự:
  <HANDOFF>/README.md
  <HANDOFF>/01_HIEN_TRANG.md
  <HANDOFF>/02_PHAM_VI_VA_TIEU_CHI.md
  <HANDOFF>/03_THIET_KE_PHAN_A.md      (phần A)
  <HANDOFF>/04_DANH_MUC_KHUNG_CA.md    (phần A)
  <HANDOFF>/05_THIET_KE_PHAN_B.md      (phần B)
  và kế hoạch: docs/phase_role_aware_ops/W6_7_sft_data/README.md trên main.
Đọc thêm trong repo khi cần: evals/suites/S*.jsonl (định dạng ca, không chép nội dung), scripts/run_agent_scenarios.py, scripts/eval_dataset_v2.py, scripts/eval_regrade.py, retailops/business/store.py (BusinessStore.seed), retailops/integration/demo_seed.py, marketplace_sim/, data/knowledge/.

Làm:
1. Tạo nhánh phase-r1-w6-7-0-<a|b> từ origin/main mới nhất (phần B: sau khi PR phần A đã merge).
2. Làm đúng các mục của phần <PHẦN> trong 02 và thiết kế 03/04 (A) hoặc 05 (B). Chỉ sửa/tạo các tệp liệt kê ở 02.
3. Viết test như 03 mục A6 (A) hoặc 05 mục B3 (B). Test tự dựng dữ liệu nhỏ, không đọc ổ E:, không gọi mạng.
4. Chạy toàn bộ test của repo như CI (python -m unittest discover -s tests) và scripts/check_docs_contract.py; báo số pass/fail/skip. Trên Windows có 5 test W4 (ClamAV/PDF/tệp đính kèm) hỏng sẵn trên main — ghi rõ, không sửa.
5. Phần A, chạy thêm và ghi kết quả vào báo cáo:
   - python scripts/build_sft_fixture.py hai lần → cùng SHA-256; số sự kiện, đơn, khách; 0 mã trùng tệp chuẩn.
   - python scripts/sft_cases.py generate --out <thư mục tạm ngoài repo> (đủ 1.200 ca) và --pilot 100; số khung, ca mỗi khung (≤15), phân bổ theo bộ, giọng.
   - python scripts/sft_cases.py check trên đủ 1.200 ca → runner --fake đạt 100% (nếu không, sửa khung, không nới kỳ vọng tùy tiện).
   - scripts/eval_dataset_v2 validate_suites --final 250 ca và SHA 12/12 vẫn như cũ.
   Phần B: chạy select/build trên dữ liệu giả của test, dán thống kê mẫu.
6. Viết báo cáo docs/phase_role_aware_ops/W6_7_0_<A|B>_EXECUTION_REPORT_<ngày>.md: tệp đã sửa/tạo, kết quả test, kết quả mục 5, điểm còn ngờ, chỗ lệch thiết kế (nếu có, kèm lý do).
7. Commit theo từng bước rõ ràng, push nhánh, mở PR vào main. KHÔNG merge.

Cấm: sửa retailops/, agent_protocol.py, retailops_providers.py, data/knowledge/, evals/suites/*, data/demo_events/store_events.jsonl, scripts/eval_dataset_v2.py, logic chấm của runner; thêm thư viện; gọi bất kỳ API LLM thật nào (DeepSeek chỉ qua client giả trong test); dán khóa; merge; push main; force-push/rebase/reset/stash; đổi biến/secret repo; chạy workflow deploy/live-e2e; chạm EC2, SSM, DB production, Colab.
Khi thiết kế mâu thuẫn với code thật hoặc thiếu thông tin: hỏi owner bằng câu hỏi trắc nghiệm ngắn, không tự đoán.
```
