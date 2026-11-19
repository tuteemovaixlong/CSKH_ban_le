# 06 — Sau khi merge (việc của owner, Claude hỗ trợ)

1. **Bộ đệm lời khách**: lấy bản đệm thật (Drive `w67_utterances/…`, bản sao trên ổ E:), sao lưu, chạy
   `drop-cache` rồi `migrate-injection` với `--old-briefs` = phiếu v3 (`acc6850a…`). Kiểm số dòng xóa/đổi khớp báo cáo PR.
2. **Glimmer viết lại** các phiếu bị xóa đệm (4 khung lỗi; ước ≤ 104 phiếu) trên Colab A100 40 GB, cách làm như đợt
   batch 2 (`colab_w67_batch2`): `sft_utterances fill --writer-label muse-glimmer-30b …`, rồi `verify`.
   Có thể ghép cùng phiên A100 với đợt sinh có khung nâng đỡ: Glimmer viết trước, giải phóng GPU, rồi nạp Qwen.
3. **Sinh lại quỹ đạo** cho mọi ca của 6 khung (≈ 66 ca: t08 ×24, t06 ×10, t02 ×10, t09 ×10, t11_pdf_email_la ×10 —
   trừ ca nào phiếu không đổi): Qwen ×4 + DeepSeek ×2, cấu hình như W6.4 (DeepSeek giờ thấp điểm).
   - `t11_pdf_email_la` vốn yếu (Qwen 0/40, chủ yếu `finish_reason_length`, `agent_response_failed`) → cho vào đợt
     **sinh có khung nâng đỡ**.
   - `t09_the_he_thong_gia_voucher`: chạy thường (thước v4 đã có A_code ở 9/10 ca).
4. **Bỏ vết cũ** của các ca này (đầu vào đã đổi), kể cả mẫu đã chấm vòng 1; chấm code v4 rồi đưa vào vòng chấm gộp.
5. Cập nhật tệp bàn giao phiên và phễu dữ liệu (4.5) với số ca/khung bị làm lại và lý do.

## Notebook Colab (Claude soạn sau khi W6.7.1 merge; owner chạy)

Notebook W6.7 KHÔNG nằm trong repo: chúng ở `scratch/` (gitignore) của worktree
`d:\year_2026\Work_2026\agentic_AI\CSKH_ban_le\.claude\worktrees\cai-nay-la-sao-bddcef`, mỗi notebook có tệp nguồn
`*_cells.py` + `.ipynb`. Mỗi notebook **ghim `REPO_SHA`** (40 ký tự), dựng lại ca/phiếu từ đúng commit đó và đọc/ghi
Drive theo thư mục mang SHA rút gọn (`MyDrive/retailops_colab/w67_utterances/<sha7>/full`, `…/w67_traces/<sha7>/…`).
Cổng dữ liệu bắt buộc: manifest SHA256 + `sft_utterances verify` + so ca/phiếu với bộ sinh lại ở `REPO_SHA`.

| Notebook đã có | Việc | Runtime | `REPO_SHA` / dữ liệu |
|---|---|---|---|
| `colab_w67_utterances` | Glimmer viết 1.406 câu khách (bộ v1) | A100 40 GB | `33de659`, ra `w67_utterances/33de659/full` |
| `colab_w67_qwen` (notebook 2) | Qwen ×4 trên 1.200 ca | A100 40/80 GB, High-RAM | `f4c02c1` + bộ v2 |
| `colab_w67_deepseek` (notebook 3) | DeepSeek ×2 trên 1.200 ca | CPU High-RAM | `f4c02c1` + bộ v2 |
| `colab_w67_batch2` | đợt 2: Glimmer viết lại 32 phiếu → bộ v3, rồi Qwen ×4 + DeepSeek ×2 trên 32 ca | A100 40 GB | `09baa9d`, nguồn câu `f4c02c1`, ra `w67_utterances/09baa9d/full` |
| `colab_w67_lora_smoke` | thử LoRA + đầu MTP (đã đạt 17/11) | A100 40 GB | không ghim SHA |

Notebook cần soạn mới cho bước sau merge (cùng khuôn `colab_w67_batch2`, `REPO_SHA` = `main` sau khi W6.7.1 merge):
1. **Đợt 3 — dữ liệu**: chép bộ đệm v3 → `drop-cache` + `migrate-injection` → Glimmer viết lại các phiếu bị xóa đệm →
   `verify` → bộ v4 trên Drive (A100; tách bước CPU khỏi GPU).
2. **Đợt 3 — quỹ đạo**: Qwen ×4 (A100) + DeepSeek ×2 (CPU, giờ thấp điểm) trên ≈ 66 ca của 6 khung, ghép với đợt
   **sinh có khung nâng đỡ** (≈ 260 ca, nhãn `source: hinted`, khung bị xóa khỏi mẫu SFT) nếu bộ phiếu hướng dẫn đã duyệt.
3. **Huấn luyện + đo lại** (sau khi chốt tập SFT): LoRA bf16 r16 + gộp tay giữ `mtp.*` + huấn luyện lại đầu MTP (A100),
   rồi đo lại 250 ca × 3 trên L4 bằng notebook đo W6.4 (`colab_w64`) — trước khi repo về private (~1/12).

`notebooks/colab_agent.ipynb` trong repo là thứ khác (gói mã nguồn agent, dựng bằng `scripts/build_agent_notebook.py`,
test `test_audit_remediation` kiểm đồng bộ) — phải dựng lại mỗi khi đổi `tests/`, `retailops/`, `web/`, `data/`.
