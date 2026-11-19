# 06 — Sau khi merge

1. **Claude** chạy `export --round 2` trên dữ liệu thật (`scores_v4.json`, `--after adjudicated_r1_trong_tai.json`,
   `--max-tool-chars 8000`, loại 6 khung W6.7.1 + `t07_doa_dang_bai`), đối chiếu số lớp (`q_next` 193, `ds_pair` ≤ 290),
   dựng hai bộ giám khảo trên ổ E: như vòng 1 (rubric vòng 1, `PROMPT_ANTIGRAVITY.md`, `packets/`, `verdicts/` trống).
   **Đã làm 19/11:** 505 ứng viên (`q_next` 193, `ds_pair` 290, `q_second` 22), 539 mục / 22 lô, `--seed 20261119`;
   bộ giám khảo ở `E:\hệ thống\w67_giam_khao_vong2` (RUBRIC in bằng `--print-rubric --max-tool-chars 8000`). Ghi chép:
   `scratch/w67_vong2/README.md` (worktree festive-gagarin).
   **Seed riêng mỗi lần xuất:** `item_id` sinh từ `random.Random(seed)`, cùng seed thì vòng sau trùng `item_id` vòng
   trước (đo: 539/539 với seed mặc định). Nhập vẫn đúng vì khớp theo `map.json` từng vòng, nhưng chép nhầm phiếu giữa
   hai vòng sẽ khớp sai mà không báo — nên vòng 2, trọng tài vòng 2 và gói Tier S đều dùng seed khác nhau.
2. **Hai nhóm giám khảo** chấm vòng 2 (như vòng 1); **Claude** nhập, xuất trọng tài cho mục `khong_chac`;
   **Neon High** làm trọng tài; **Claude** nhập.
3. **Claude** xuất gói Tier S (chấm cặp) → **Neon High** chấm → **Claude** nhập.
4. **Claude** chạy `select` (trần khung, trần DeepSeek) → `sft_cjk export` cho các mẫu đã chọn → **owner** điền
   `sua_thanh` (hướng dẫn: `E:\hệ thống\w67_sua_chu_han\HUONG_DAN.md`; đợt 1 = 21 đoạn / 20 mẫu đã xuất sẵn) →
   **Claude** `sft_cjk import` → lớp phủ cho `sft_build`.
   **Cần sửa trước khi build:** `sft_build --owner-edits` dừng khi có dòng lớp phủ không áp lần nào — kể cả dòng thuộc
   lượt chạy không được chọn (03 mục E viết chưa rõ). Sau Tier S, mẫu chính của vài ca trong 20 mẫu đợt 1 có thể đổi →
   build dừng. Sửa: dòng thuộc lượt không có trong `selection.json` thì bỏ qua và ghi báo cáo; dòng thuộc lượt được
   chọn mà không áp được vẫn dừng.
5. Song song: **W6.7.3** (phiếu khung đỡ + sinh có khung đỡ Qwen ×4 cho ~389 ca + cờ tắt rào nếu owner chọn, notebook
   Colab, dữ liệu đợt 3 của W6.7.1). Ca Qwen vẫn thua sau 4 + 4 lượt → DeepSeek (mẫu sẵn có trước, rồi sinh có khung đỡ).
6. `sft_build` → huấn luyện LoRA + đầu MTP → đo lại 250 ca × 3 trên L4 trước khi repo về private (~1/12).
