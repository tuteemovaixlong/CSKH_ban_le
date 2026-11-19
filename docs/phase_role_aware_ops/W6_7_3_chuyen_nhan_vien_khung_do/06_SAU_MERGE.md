# 06 — Sau khi merge (Claude và owner)

1. **Claude** kiểm nhánh Codex trên dữ liệu thật (ngoài repo): sinh ca ở đầu nhánh; 1.406 phiếu cũ trùng v4; chấm lại
   vết hiện có bằng thước mới (`sft_select score` → `scores_v5`), đối chiếu số mẫu trượt ở 4 khung mục A với bảng ở 01;
   proxy chạy thử với upstream giả. Mở PR, CI, merge.
2. **Phiếu đỡ** (Claude soạn, owner duyệt): `sft_hints export` → `sheet.csv` cho mọi `(khung, lượt)` có ca cần chạy lại
   (~389 ca Qwen chưa đạt + ca trượt do thước mới + ca T14 và 64 ca W6.7.1 nếu lượt thường thất bại). Gợi ý chỉ là **quy
   trình**, rút từ system prompt, mô tả tool và KB: tool nào phải gọi trước, điều gì không được khẳng định, khi nào chuyển
   nhân viên — không có câu trả lời mẫu, không dữ kiện đơn (phiếu theo ca chỉ được nêu mã đơn của chính ca). Ví dụ hướng (không phải nội dung chốt):
   - nhóm chuyển nhân viên: "việc chỉ nhân viên làm được → gọi `request_human_support` ngay trong lượt, không hỏi lại;
     báo đã chuyển; không nói đã tự làm; không hứa thời gian";
   - khiếu nại shipper: "tra vận đơn và `search_knowledge` trước; chỉ chuyển khi khách nhờ khiếu nại hãng/giao lại";
   - đối chứng: "khách chỉ hỏi thông tin → trả lời từ KB/dữ liệu, không chuyển".
   `sft_hints import` → `hints.jsonl` (lưu ngoài repo, ghi SHA vào notebook).
   **T11 chế độ `draft`** (~69 ca chưa có mẫu): phiếu **theo ca**, soạn kỹ — đơn nào trong ca phải tra, bản nháp gửi khách
   nằm trong `<draft_reply>` còn ghi chú nội bộ ở ngoài, không hứa thay nhân viên (hoàn tiền/đổi trước khi duyệt), nêu đúng
   trạng thái từng đơn — để **DeepSeek có gợi ý** viết (giờ thấp điểm), lấy mẫu Tier A/S cho Qwen học.
3. **Notebook Colab "đợt 3b — dữ liệu"** (Claude soạn, owner chạy A100): sinh ca ở `main` mới; đệm v4 + Glimmer viết
   phiếu T14 mới (có kiểm lọt rào) → `verify` → bộ **v5** trên Drive.
4. **Notebook "đợt 3 — quỹ đạo"** (A100 + CPU): Qwen ×4 **không gợi ý** cho 180 ca T14 + 64 ca W6.7.1; Qwen ×4 **có
   gợi ý** (qua `sft_hint_proxy`, `run_offset` 4) cho ca chưa có mẫu đạt; DeepSeek ×2 **có gợi ý** (proxy trước API
   DeepSeek) cho ca Qwen vẫn thua và cho T11 `draft` (mẫu DeepSeek sẵn có dùng trước, giờ thấp điểm). Vết ghi Drive theo SHA.
   Sau chấm: chạy lại `scratch/w67_matrix/matrix.py` với số thật rồi mới chốt `--suite-cap`/`--mode-cap`.
5. **Chấm vòng 3** (giám khảo A: Neon High, B: Codex; seed riêng) → nhập → trọng tài nếu có `khong_chac` → **Tier S vòng 2**
   cho cặp mới → `select` (trần khung, trần DeepSeek, ưu tiên không gợi ý) → `sft_cjk` đợt sau → `sft_build`.
6. Huấn luyện LoRA + đầu MTP → đo lại 250 ca × 3 trên L4 (ứng dụng không đổi so với lần đo model gốc).
7. Ngoài W6.7.3 (backlog): F59 rào bắt cả câu không dấu, F60 hàng đợi ưu tiên SOP 5 cho mọi lượt chuyển vì đe dọa,
   F61 sửa câu `RAGE_REPLY` hứa quá — làm sau đợt đo, hoặc trước nếu owner chấp nhận đo lại model gốc.
