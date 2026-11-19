# W6.7.1 — Sửa 4 khung lỗi + 2 chỗ trùng giá trị bộ đo (bàn giao cho Codex)

Soạn 19/11/2026 (Claude). Người thực thi: **Codex** (sửa code, đẩy nhánh, báo cáo; KHÔNG mở PR, KHÔNG merge).
Sau đó **Claude** kiểm một lượt, commit sửa nhỏ nếu cần, mở PR, chạy CI GitHub Actions và merge (owner giao 19/11).

## Đọc theo thứ tự
1. [01_HIEN_TRANG.md](01_HIEN_TRANG.md) — vì sao phải sửa, số liệu, bằng chứng.
2. [02_PHAM_VI_TIEU_CHI.md](02_PHAM_VI_TIEU_CHI.md) — làm gì, không làm gì, khi nào là xong.
3. [03_THIET_KE_CHI_TIET.md](03_THIET_KE_CHI_TIET.md) — sửa từng khung, công cụ đệm lời khách, test chống trùng bộ đo.
4. [04_TEST_BAO_CAO.md](04_TEST_BAO_CAO.md) — lệnh kiểm và mẫu báo cáo.
5. [05_PROMPT_CODEX.md](05_PROMPT_CODEX.md) — prompt dán cho Codex.
6. [06_SAU_MERGE.md](06_SAU_MERGE.md) — việc của owner sau khi merge (Glimmer viết lại lời khách, sinh lại quỹ đạo).

## Điều kiện bắt đầu
- `main` phải chứa **thước v4** (8 khung lấy thước theo ca đo sinh đôi + cờ tấn công tính lại; SHA ca `8ee92db6…`,
  phiếu `acc6850a…`) và chính thư mục bàn giao này — cả hai lên `main` cùng một PR. Codex `git fetch` rồi rẽ nhánh từ
  `origin/main` mới đó và đọc bàn giao ngay trong repo.

## Quy tắc không đổi (của owner)
- Không sửa `evals/suites`; 250 ca đo không bao giờ vào huấn luyện, kể cả giá trị giả (mã, email, tên miền) của chúng.
- Không sửa system prompt, app hay runner để chữa dữ liệu huấn luyện.
- Codex/Claude **không viết lời khách** (điều khoản OpenAI/Anthropic cấm dùng đầu ra để phát triển model khác;
  tách vai 4 họ model — §34 W6.7-D1). Lời khách mới do Muse Glimmer viết ở bước sau merge.
- Chỉ commit/push lên nhánh `phase-r1-w6-7-1-sua-khung`; không mở PR, không merge, không push `main`; không chạy model,
  không Colab, không gọi API.
