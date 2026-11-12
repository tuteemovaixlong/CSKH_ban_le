# Phase R1 — W6.3.3 Hotfix Handoff: rào bức xúc bắt nhầm "livestream", "quay clip"; tin không dấu bị đẩy sang chế độ trò chuyện chung

> **Trạng thái:** phát hành ngày 2026-11-12 sau khi Claude kiểm bộ S02, xem [biên bản](IMPLEMENTATION_READINESS_BLOCKED_2026-10-27.md#2026-11-12-s02-check-and-w632-first-verification). Có hiệu lực khi owner merge §27. Executor: Codex.
> **Quyết định áp dụng:** [§27](W0_OWNER_DECISION_DELTA_2026-10-29.md#27-w633-owner-decisions-2026-11-12); F33, F34 trong [W6 backlog](W6_BACKLOG_2026-11-06.md). Cả hai lỗi đang có trên production. Owner chọn tách khỏi W6.3.2.
> **Thứ tự:** chỉ bắt đầu sau khi PR #98 (W6.3.2) merge, vì hai PR cùng đổi `notebooks/colab_agent.ipynb`. Tạo nhánh từ `origin/main` đã có W6.3.2.
> **Nguyên tắc:** sửa theo quy tắc chung, không thêm nhánh riêng cho câu chữ của ca S02. **Không sửa, không commit** tệp S02, S03. Gặp quyết định chưa có trong tài liệu thì **dừng và hỏi owner**.

## 1. Hiện trạng

1. **F33.** `EXTREME_RAGE_KEYWORDS` trong `retailops/workflow/safety.py` có hai từ khóa đứng riêng là `"livestream"` và `"quay clip"`. Mọi tin có hai chữ này đều bị rào bức xúc chuyển nhân viên kèm `RAGE_REPLY` ("…cam kết chịu trách nhiệm xử lý thỏa đáng 100%. Em đã gửi cảnh báo đỏ…"), dù khách đang hỏi bình thường. Claude đã thử:
   - "Hôm qua mình xem livestream của shop thấy áo này đẹp, còn size M không?" → bị chặn;
   - "Hàng nhận về khác màu so với lúc xem livestream, mình muốn đổi." → bị chặn;
   - "Em có quay clip lúc mở hàng, áo bị rách một đường, em muốn đổi ạ." → bị chặn.

   Mua qua livestream và quay clip lúc mở hàng làm bằng chứng là chuyện rất thường gặp ở Việt Nam (`eval_pack/02` mục B; S12 có tình huống "hàng khác lúc xem livestream").
2. **F34.** `request_mode` trong `agent_protocol.py` đẩy tin sang chế độ `general` (không có tool RetailOps) khi khớp một từ trong `_GENERAL_TERMS` mà không khớp `_RETAIL_TERMS`. `_GENERAL_TERMS` có `" sac"`, `"sac "` (viết tắt Soft Actor-Critic). Tin không dấu có "mau sac" (màu sắc), "sac" (sạc pin) và cả "chinh sach" (chính sách, vì " sach" chứa " sac") vì thế bị đẩy sang `general`. `_RETAIL_TERMS` lại chỉ có từ có dấu, và mã sản phẩm `P-xxx` không được tính là tín hiệu bán lẻ. Claude đã thử:
   - "ao P-101 co mau sac nao khac khong" → `general`;
   - "may hut bui P-506 sac day mat bao lau" → `general`;
   - "shop tu van giup minh hai mau ao polo nam P-203 voi P-501 khac nhau ve gia ban, chat vai va mau sac nhu the nao nha" → `general`; model gọi `get_product` bị từ chối và lượt hỏng với `agent_response_failed`;
   - "cho minh hoi chinh sach doi tra ben shop the nao" → `general`; mọi câu hỏi chính sách viết không dấu đều không tra được kho chính sách (`s03_028` của bộ S03).

   Khách nhắn không dấu chiếm khoảng 15% bộ đánh giá.

## 2. Phạm vi và tiêu chí chấp nhận

Nhánh mới từ `origin/main` (sau khi #98 merge), không theo dõi `main`. Không migration, không thêm thư viện. Code chỉ đổi trong `retailops/workflow/safety.py` và `agent_protocol.py`, cộng test.

| # | Việc phải làm | Tiêu chí chấp nhận, test cô lập |
|---|---|---|
| 1 | **F33 (W6.3.3-D1).** Bỏ hai từ khóa đứng riêng `"livestream"` và `"quay clip"` khỏi `EXTREME_RAGE_KEYWORDS`. Hai chữ này chỉ tính là bức xúc khi đi cùng ý đe dọa công khai trong cùng tin: bóc phốt, tố cáo, đăng lên (mạng, Facebook, TikTok, hội nhóm), "cho mọi người biết", "cho cả mạng biết", "bêu". Các từ khóa có sẵn như `"quay clip đăng tiktok"`, `"quay clip tiktok bóc phốt"`, `"đăng tiktok bóc phốt"` giữ nguyên. | Test, không bị rào bức xúc: ba câu ở mục 1.1; "Mình mua áo này lúc shop livestream tối qua, giờ muốn đổi size ạ."; "Shop có livestream bán hàng vào tối nay không?"; "Em quay clip lúc mở hộp rồi, gửi kèm ảnh được không?". Vẫn bị rào bức xúc: "Tôi sẽ livestream bóc phốt shop cho mọi người biết."; "Shop giao sai hàng, tôi sẽ quay clip đăng tiktok bóc phốt."; "Tôi quay clip lại rồi, mai đăng lên mạng tố cáo shop."; "Tôi sẽ lên livestream tố cáo cái shop này.". Test rào an toàn hiện có (W6.2, W6.2.1) vẫn đạt. Viết test trước, chạy trên code chưa sửa để thấy FAIL. |
| 2 | **F34 (W6.3.3-D2).** Trong `classify_user_text`, tín hiệu bán lẻ thắng từ khóa chủ đề chung. Tín hiệu bán lẻ gồm thêm: mã sản phẩm dạng `P-` cộng 3 chữ số; mã đơn dạng `SIM-O-`; các cụm bán lẻ viết không dấu ("don hang", "ma don", "san pham", "con hang", "het hang", "giao hang", "phi ship", "doi tra", "doi size", "hoan tien", "bao hanh", "thanh toan", "van don"). Bỏ hai mục viết tắt đứng riêng `" sac"`, `"sac "` khỏi `_GENERAL_TERMS`; giữ "soft actor-critic", "soft actor critic", "thuật toán" và các mục khác. | Test `classify_user_text` hoặc `request_mode` ra `retail`: ba câu ở mục 1.2; "san pham nay con hang size M khong"; "phi ship don nay bao nhieu"; "cho minh hoi chinh sach doi tra ben shop the nao"; "chinh sach bao hanh may hut bui bao lau". Vẫn ra `general`: "giải thích thuật toán SAC giúp mình"; "Soft Actor-Critic là gì?"; "explain the soft actor-critic algorithm". Test hiện có của định tuyến chế độ vẫn đạt. Viết test trước, thấy FAIL. |
| 3 | **Kiểm với S02 và S03, không commit.** Tệp `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/scratch/S02_v2.jsonl` (18 ca, SHA-256 `35cd5b0df89c4b174547d1a94d86c5d428e67cca8df98f1128fd3d12517ef54d`). Thêm tệp `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/scratch/S03_30ca.jsonl` (30 ca, SHA-256 `0bc3b70a4d9eac2d910908e380dc0a2bcea9077e9f6eee9a0b959c7b224e3941`). Chép hai tệp vào thư mục tạm dưới tên `S02.jsonl`, `S03.jsonl`, chạy `scripts/check_eval_dataset.py <thư mục tạm>` và runner `--fake --dataset-dir <thư mục tạm>`. | Trên `main` đã có W6.3.2, trước khi sửa: S02 16/18, hỏng `s02_010` (F33), `s02_013` (F34); S03 29/30, hỏng `s03_028` (F34). Sau khi sửa: 18/18 và 30/30. `evals/suites` vẫn 100%. Ca nào còn hỏng thì ghi câu trả lời thật vào báo cáo, không sửa ca. |

Thứ tự bắt buộc với hàng 1, 2: viết test trước, chạy trên code chưa sửa để thấy FAIL, ghi lại dòng lỗi, rồi mới sửa.

## 3. Ngoài phạm vi

- Sửa hoặc commit S02, S03 và mọi ca trong `evals/suites/`; sửa 44 kịch bản hồi quy hoặc nới điều kiện chấm.
- Đổi `RAGE_REPLY`, system prompt, nội dung `data/knowledge/`, `answer_check`.
- Rà lại toàn bộ danh sách từ khóa bức xúc hay gặp người. Nếu thấy từ khóa khác cũng bắt nhầm câu bình thường, **ghi vào báo cáo**, không sửa.
- Mọi việc của W6.4 trở đi.

## 4. Kiểm tra và báo cáo

Chạy và báo đúng số pass, fail, skip của từng lệnh:
- `python -m unittest discover -s tests -q`
- test JS theo `.github/workflows/ci.yml`, chạy bằng Node thật
- `python scripts/build_agent_notebook.py --check`
- `python scripts/build_eval_pack.py --check`
- `python scripts/check_docs_contract.py`
- `python scripts/check_deployment_contract.py`
- `python scripts/check_live_e2e_contract.py`
- `python scripts/check_eval_dataset.py` và `python scripts/check_eval_dataset.py evals/suites`
- runner `--fake` cho hai tệp hồi quy, `06_vi_du.jsonl`, `evals/suites` (phải 100%) và S02, S03 theo hàng 3
- `git diff --check`

Báo cáo ghi vào `docs/phase_role_aware_ops/W6_3_3_EXECUTION_REPORT_2026-11-12.md`, gồm:
- tệp đổi theo từng hàng;
- bằng chứng FAIL trước khi sửa của hàng 1, 2;
- kết quả S02, S03 trước và sau;
- kết quả từng lệnh;
- DONE hoặc BLOCKED từng hàng;
- URL PR và kết quả CI.

Thêm một dòng mới vào cột của bạn trong [W1 execution log](W1_EXECUTION_LOG_2026-10-31.md), ghi rõ là W6.3.3; không sửa dòng cũ.

**Cấm:** merge; push vào `main`; force-push, rebase, reset, stash; đổi variable hoặc secret của repo; chạy workflow deploy hoặc live-e2e; truy cập EC2, SSM, DB production, Colab hoặc LLM thật, dữ liệu khách hàng; thêm thư viện; commit hoặc sửa S02, S03.

## 5. Sau khi báo cáo

Claude chỉ chạy **một** lượt kiểm chứng theo tiêu chí ở mục 2; owner quyết định merge. Deploy bình thường, không migration, đi cùng W6.3.1 và W6.3.2. Smoke trên trình duyệt:
- "Hôm qua mình xem livestream thấy áo `<mã sản phẩm>` đẹp, còn size M không?" phải được trả lời về tồn kho, không chuyển nhân viên;
- "ao `<mã sản phẩm>` co mau sac nao" phải tra được sản phẩm;
- "chinh sach doi tra ben shop the nao" phải trả lời có trích dẫn.
