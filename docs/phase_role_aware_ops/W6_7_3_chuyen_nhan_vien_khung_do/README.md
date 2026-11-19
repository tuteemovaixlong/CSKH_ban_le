# W6.7.3 — Thước "chuyển nhân viên", khung T14 và cơ chế khung đỡ (bàn giao cho Codex)

Soạn 19/11/2026 (Claude). Người thực thi: **Codex** — chỉ viết code + test, đẩy nhánh, báo cáo; KHÔNG mở PR, KHÔNG
merge. Sau đó Claude kiểm, mở PR, chạy CI GitHub Actions và merge (owner giao 19/11).

## Vì sao
Chuyển nhân viên (`request_human_support`) là nghiệp vụ cốt lõi (SOP 5, SOP 6) nhưng tập SFT gần như không dạy nó:
32/1.200 ca kỳ vọng chuyển, chỉ 11 ca có mẫu Tier A; rào an toàn trong code chỉ bắt từ khóa có dấu nên câu không dấu
hay diễn đạt khác đi thẳng tới model. Song song, ~389 ca Qwen chưa có mẫu đạt cần chạy lại **có khung đỡ** (gợi ý
quy trình chèn lúc sinh, không có trong mẫu huấn luyện).

## Đọc theo thứ tự
1. [01_HIEN_TRANG.md](01_HIEN_TRANG.md) — số liệu đo 19/11 và các quyết định của owner.
2. [02_PHAM_VI_TIEU_CHI.md](02_PHAM_VI_TIEU_CHI.md) — trong/ngoài phạm vi, bất biến, khi nào là xong.
3. [03_THIET_KE_CHI_TIET.md](03_THIET_KE_CHI_TIET.md) — năm hạng mục A–E.
4. [04_TEST_BAO_CAO.md](04_TEST_BAO_CAO.md) — test, lệnh kiểm, mẫu báo cáo.
5. [05_PROMPT_CODEX.md](05_PROMPT_CODEX.md) — prompt dán cho Codex.
6. [06_SAU_MERGE.md](06_SAU_MERGE.md) — việc của Claude/owner sau merge (phiếu đỡ, Glimmer, quỹ đạo, chấm).

## Điều kiện bắt đầu
- `main` chứa W6.7.2 (#132) và thư mục này.
- Codex rẽ nhánh `phase-r1-w6-7-3-khung-do` từ `origin/main`.

## Quy tắc không đổi
- Không sửa `evals/suites/`, system prompt (`agent_protocol.py`), `retailops/` (kể cả rào `retailops/workflow/safety.py`),
  runner `scripts/run_agent_scenarios.py`.
- Codex **không viết lời khách** và **không viết nội dung phiếu đỡ** (gợi ý) — chỉ viết phiếu (brief), kỳ vọng, công cụ
  và test. Lời khách do Glimmer viết; nội dung phiếu đỡ do Claude soạn từ system prompt/mô tả tool/KB, owner duyệt.
- Không chạy model, không gọi API, không Colab, không đụng Drive hay ổ E:; test bằng dữ liệu giả.
- 250 ca đo không bao giờ vào huấn luyện; không giá trị giả nào của bộ đo lọt vào ca/phiếu SFT.
