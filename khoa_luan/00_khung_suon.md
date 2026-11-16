# Khung sườn khóa luận

Ngành Khoa học máy tính, chuyên ngành Trí tuệ nhân tạo. Cấu trúc 4 chương theo CDIO, nội dung viết theo kiểu luận văn AI: phát biểu bài toán hình thức, câu hỏi nghiên cứu, baseline, chỉ số đo, thí nghiệm loại bỏ thành phần, phân tích lỗi, mối đe dọa tính hợp lệ. Tổng khoảng 55 trang Word.

Đề tài: **XÂY DỰNG HỆ THỐNG TRỢ LÝ ẢO TÍCH HỢP AI HỖ TRỢ CHĂM SÓC KHÁCH HÀNG CHO KINH DOANH BÁN LẺ**

Tài sản trong repo dùng được cho khóa luận: chế độ `legacy` làm baseline; bộ đánh giá 250 ca trong 12 bộ `evals/suites` đã đóng băng; 44 kịch bản hồi quy kiểu τ-bench gồm 32 kịch bản W3.2 và 12 kịch bản W4; benchmark truy hồi 250 câu một lượt có qrels; các tài liệu Phase 4 về ablation, thống kê, threats to validity, failure taxonomy; `scripts/run_agent_scenarios.py`, `scripts/run_benchmark_eval.py`.

Ký hiệu trạng thái: ✅ đã viết · ✍️ viết được ngay · ⏳ chờ số liệu W6 trên Colab.

---

## Phần đầu

- ✅ Bìa (sinh viên tự làm trong Word)
- ✅ Lời cảm ơn → `01_loi_cam_on.md`
- ✅ Lời cam đoan → `02_loi_cam_doan.md`
- Mục lục, danh mục bảng, danh mục hình: Word tự tạo ở bước cuối, từ Heading 1/2/3 và Insert Caption
- Danh mục từ viết tắt: gom khi viết xong các chương. Đã có: CSKH, LLM, RAG, RQ, CDIO, GPU

## MỞ ĐẦU (3 trang) ✅ → `03_mo_dau.md`

Lý do chọn đề tài · Mục tiêu · Câu hỏi nghiên cứu · Đối tượng và phạm vi · Phương pháp · Đóng góp · Bố cục.

## CHƯƠNG 1. HÌNH THÀNH Ý TƯỞNG: BÀI TOÁN VÀ CƠ SỞ LÝ THUYẾT (15 trang) ✍️

### 1.1 Bài toán CSKH bán lẻ (1,5 trang)
Các loại yêu cầu thường gặp; ràng buộc nghiệp vụ như quyền sở hữu đơn, điều kiện đổi trả, chính sách theo cửa hàng; chi phí khi AI trả lời sai.

### 1.2 Phát biểu bài toán hình thức (2 trang)
Phần tạo độ sâu AI cho cả luận văn.
- Hội thoại là quá trình ra quyết định tuần tự: lịch sử $h_t$, hành động $a_t \in \mathcal{T} \cup \{\text{answer}, \text{handoff}\}$ với $\mathcal{T}$ là tập công cụ, quan sát $o_t$ là kết quả công cụ.
- Chính sách $\pi_\theta(a_t \mid h_t)$ do LLM sinh ra, chịu tập ràng buộc $\mathcal{C}$: không ghi dữ liệu, chỉ trong phạm vi khách, ngân sách bước, bắt buộc trích dẫn.
- Mục tiêu: cực đại xác suất hoàn thành tác vụ với điều kiện số vi phạm $\mathcal{C}$ bằng 0.
- Đánh giá theo trạng thái cuối kiểu τ-bench thay vì chấm từng token.

### 1.3 Cơ sở lý thuyết (8 trang)
- 1.3.1 Mô hình ngôn ngữ lớn: Transformer, self-attention, sinh tự hồi quy, cửa sổ ngữ cảnh, instruction tuning. Hình: sơ đồ khối Transformer.
- 1.3.2 Huấn luyện bổ sung cho tác tử và chưng cất tri thức: SFT trên quỹ đạo tác tử [AgentTuning, FireAct], KD kinh điển [Hinton 2015], KD mức chuỗi [Kim & Rush 2016], học theo ưu tiên DPO [Rafailov 2023]; vì sao model nhỏ thế hệ mới gọi công cụ tốt; giới hạn. Là nền cho phần tùy chọn W6.7 (chưng cất quỹ đạo DeepSeek vào Qwen3.5-9B bằng LoRA, §31 W6.4-D12); không kịp làm thì rút gọn và chuyển sang hướng phát triển.
- 1.3.3 Suy luận từng bước: chain-of-thought [Wei 2022], chế độ thinking; đánh đổi giữa token suy luận, độ trễ và độ chính xác.
- 1.3.4 Tác tử gọi công cụ: function calling theo JSON schema, ReAct [Yao 2023], Toolformer, Gorilla; đơn tác tử so với supervisor và đa tác tử; ngân sách bước, vòng lặp, gọi trùng.
- 1.3.5 Truy hồi tăng cường: dense retrieval [DPR], embedding, ANN với pgvector, top-k; trích dẫn và độ trung thành; Lost in the Middle [Liu 2023] làm cơ sở cho nén ngữ cảnh.
- 1.3.6 An toàn của hệ tác tử: ảo giác; chèn lệnh trực tiếp và gián tiếp [Greshake 2023]; OWASP LLM Top 10; rào an toàn trong code so với trong prompt; con người phê duyệt; fail-closed.
- 1.3.7 Phục vụ mô hình hiệu quả: PagedAttention và vLLM [Kwon 2023], continuous batching, prefix caching, lượng tử FP8 khi nạp; giải mã suy đoán [Leviathan 2023] và dự đoán nhiều token, gọi tắt là MTP [Gloeckle 2024]; kiến trúc lai với attention tuyến tính Gated DeltaNet [Yang 2025] giảm bộ nhớ KV cache; ảnh hưởng của độ dài ngữ cảnh lên bộ nhớ.
- 1.3.8 Đánh giá tác tử và RAG: τ-bench, τ²-bench, pass^k, Recall@k, MRR, nDCG, qrels.

### 1.4 Nghiên cứu liên quan (2 trang)
Chatbot dựa luật và intent; trợ lý LLM thương mại; hệ tác tử nghiên cứu. Bảng 1.1 so sánh theo tiêu chí: tự lập kế hoạch, bám dữ liệu, an toàn khi ghi, tiếng Việt, chạy tại chỗ; vị trí của đề tài.

### 1.5 Câu hỏi nghiên cứu và yêu cầu hệ thống (1,5 trang)
- RQ1: agent-first có hoàn thành tác vụ tốt hơn supervisor định tuyến theo từ khóa không.
- RQ2: chế độ suy luận và độ dài ngữ cảnh 8k so với 16k ảnh hưởng thế nào tới độ chính xác, độ trễ, chi phí.
- RQ3: truy hồi có đúng tài liệu không, câu trả lời có bám bằng chứng không, có biết từ chối không.
- RQ4: rào an toàn trong code cùng con người phê duyệt có ngăn thao tác trái phép, lộ dữ liệu chéo khách, chèn lệnh không.
- RQ5: Qwen3.5-9B trên một GPU L4 24 GB, lượng tử FP8 và giải mã suy đoán MTP, có đạt độ trễ chấp nhận được không.
- Yêu cầu chức năng và phi chức năng rút từ các RQ. Hình: use case 3 vai trò.

## CHƯƠNG 2. THIẾT KẾ: PHƯƠNG PHÁP ĐỀ XUẤT (13 trang) ✍️

### 2.1 Tổng quan kiến trúc (1,5 trang)
Người dùng → cổng ứng dụng → vòng tác tử → lớp công cụ → dữ liệu và kho tri thức; model chạy riêng trên GPU. Hình 2.1.

### 2.2 Lựa chọn mô hình (1,5 trang)
Tiêu chí: vừa một GPU 24 GB, gọi công cụ gốc, tiếng Việt, có thinking, license. Chọn `Qwen/Qwen3.5-9B` bản chính hãng: Apache 2.0; đa phương thức; ngữ cảnh gốc 262k; kiến trúc lai Gated DeltaNet; có đầu MTP cho giải mã suy đoán; model card tự báo τ²-bench 79,1 và BFCL-V4 66,1. Không có bản FP8 chính hãng cho 9B nên lượng tử FP8 khi nạp trên L4. Bảng 2.1 các model ứng viên, gồm Gemma 4 12B bản bên thứ ba (`yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2`) của thiết kế ban đầu, và lý do đổi (§31 W6.4-D1): model chính hãng, nhẹ hơn, nhanh hơn nhờ kiến trúc lai và MTP, lượt thử trên L4 đạt cổng kiểm. DeepSeek-V4.1-Flash qua API chỉ dùng cho bản demo trên production (W6.4-D5), không dùng để đánh giá.

### 2.3 Thiết kế tác tử (4 trang), trọng tâm
- 2.3.1 Baseline supervisor định tuyến và các worker theo từ khóa; vì sao gãy: câu trả lời soạn sẵn, mất ngữ cảnh ở câu hỏi tiếp nối.
- 2.3.2 Agent-first: một chính sách duy nhất, model tự lập kế hoạch; ngân sách 6 lượt gọi model, 10 lượt gọi tool mỗi lượt chat, một bước được dùng hết ngân sách tool (W6.4-D17); chặn gọi trùng; nén kết quả tool; kiểm câu trả lời cuối; chuẩn hóa lịch sử cho chat template. Hình 2.2 vòng lặp; Thuật toán 2.1 pseudo-code.
- 2.3.3 Không gian hành động: tool chỉ đọc; `prepare_order_action` chỉ chuẩn bị, không ghi; lý do không cho AI quyền ghi; schema và mô tả tool. Bảng 2.2.
- 2.3.4 Context engineering: prompt theo nguyên tắc, không theo kịch bản; ngữ cảnh do server gắn, model không đổi được phạm vi; nén và cắt lịch sử.
- 2.3.5 Trợ lý ca: cùng vòng tác tử, khác hồ sơ (prompt, tool chỉ đọc gói trong ca, lịch sử riêng từng người).

### 2.4 Thiết kế truy hồi tri thức (1,5 trang)
Chia đoạn tài liệu chính sách, embedding, top-k, định dạng trích dẫn, quy tắc từ chối khi không có bằng chứng. Lưu ý: embedding hiện là băm đặc trưng `feature-hash-v1` 384 chiều, chấm điểm lai 0,75 cosine + 0,25 `ts_rank_cd`; mô tả đúng như vậy, xem `04_so_do_du_lieu_rag_ngu_canh.md` mục S4.

### 2.5 Thiết kế an toàn và con người phê duyệt (2 trang)
3 rào an toàn trong code (chủ đề cấm, khách quá bức xúc, yêu cầu gặp người); tách dữ liệu theo khách và cửa hàng; RBAC 3 vai trò; luồng AI đề xuất người duyệt cho hủy, trả, đổi. Hình 2.3 sơ đồ tuần tự; Hình 2.4 máy trạng thái yêu cầu đơn. Đa phương thức an toàn: làm sạch ảnh, quét PDF bằng ClamAV, giới hạn ảnh gửi model.

### 2.6 Thiết kế đánh giá (2,5 trang)
- Dữ liệu: bộ chính 250 ca trong 12 bộ `evals/suites`, đóng băng 2026-11-14, chi tiết ở `05_thiet_ke_bo_danh_gia.md`; 44 kịch bản hồi quy W3.2 và W4; benchmark truy hồi 250 câu có qrels.
- Baseline: chế độ `legacy`.
- Chỉ số: tỉ lệ hoàn thành, pass^k, tỉ lệ tool call hợp lệ, số bước, tỉ lệ vi phạm ràng buộc, Recall@k, MRR, độ trễ p50/p95, token mỗi lượt.
- Thống kê: chạy lặp k lần, khoảng tin cậy bootstrap, McNemar cho cặp cấu hình trên cùng kịch bản.
- Kế hoạch ablation: Bảng 2.3.

## CHƯƠNG 3. HIỆN THỰC (9 trang) ✍️

- 3.1 Môi trường và công nghệ (1 trang): Python, LangGraph, PostgreSQL + pgvector, vLLM, Docker.
- 3.2 Phục vụ model trên L4 (1,5 trang): vLLM có sẵn của Colab, lượng tử FP8 khi nạp, MTP 2 token nháp, ngữ cảnh 16k, parser `qwen3` cho suy luận và `qwen3_coder` cho tool; runner, vLLM và PostgreSQL có pgvector chạy cùng máy, gọi `127.0.0.1`, khóa ngẫu nhiên, không ngrok; repo ghim đúng SHA; chia shard song song, chạy tiếp được khi phiên ngắt (`notebooks/colab_eval_w64.py`). Thiết kế endpoint 2 lớp bảo vệ qua ngrok giữ cho việc nối production với Colab (C1, W6.6).
- 3.3 Vòng tác tử trên LangGraph (2 trang): trích đoạn mã có chú thích, checkpoint, `trace`, lỗi model, cơ chế dừng lượt.
- 3.4 Lớp công cụ và kiểm soát phía server (1,5 trang): kiểm quyền sở hữu, transaction, khóa theo version, idempotency.
- 3.5 Pipeline RAG (1 trang): đánh chỉ mục, truy vấn, gắn trích dẫn.
- 3.6 Bộ công cụ đánh giá (1 trang): `run_agent_scenarios.py` với gateway giả và endpoint thật, `run_benchmark_eval.py`, test tự động, CI.
- 3.7 Giao diện (1 trang): ảnh chụp khung chat khách, Staff Desk, Trợ lý ca, Manager Console.

## CHƯƠNG 4. VẬN HÀNH VÀ ĐÁNH GIÁ (13 trang)

- 4.1 Triển khai thực tế (1,5 trang) ✍️: CI/CD, migration có kiểm soát, 2 sự cố thật (mount cũ che dữ liệu ở W3.2; phiên SSM rớt ở W4) và bài học; chi tiết đưa vào phụ lục.
- 4.2 Thiết lập thực nghiệm (1 trang) ⏳: phần cứng (L4 24 GB), model Qwen3.5-9B, phiên bản vLLM, tham số lấy mẫu theo khuyến nghị Qwen (`temperature 1.0, top_p 0.95, top_k 20, presence_penalty 1.5`, W6.4-D10) và `max_tokens`, số lần lặp; khối `provenance` trong mỗi báo cáo.
- 4.3 RQ1 agent-first so với supervisor (2,5 trang) ⏳: bảng theo nhóm kịch bản, pass^k, McNemar, biểu đồ cột.
- 4.4 RQ2 suy luận và độ dài ngữ cảnh (1,5 trang) ⏳: thinking bật/tắt, 8k/16k, đồ thị Pareto độ chính xác và độ trễ.
- 4.5 RQ3 truy hồi và độ bám bằng chứng (1,5 trang) ⏳: Recall@k, MRR trên qrels, tỉ lệ trích dẫn đúng, tỉ lệ từ chối đúng.
- 4.6 RQ4 an toàn (1,5 trang) ⏳: kịch bản chèn lệnh, đơn của khách khác, đơn không đủ điều kiện; tỉ lệ vi phạm.
- 4.7 RQ5 hiệu năng (1 trang) ⏳: p50/p95, token mỗi lượt, token sinh mỗi giây, tỉ lệ chấp nhận token nháp MTP, chi phí token mỗi ảnh.
- 4.8 Ablation (1 trang) ⏳: lần lượt bỏ chặn gọi trùng, nén kết quả, kiểm câu trả lời cuối, chuẩn hóa lịch sử.
- 4.9 Phân tích lỗi, thảo luận, mối đe dọa tính hợp lệ (1,5 trang) ⏳: phân loại lỗi theo failure taxonomy Phase 4; dữ liệu giả lập, bộ kịch bản nhỏ, một model, rủi ro contamination (Qwen3.5-9B tự báo τ²-bench 79,1, nên báo riêng nhóm `tau2_retail`).

Lưu ý: W6 nên chạy đúng các thí nghiệm ở mục 2.6 để một lần đo đủ số liệu cho khóa luận. Không dùng số liệu chạy bằng DeepSeek cho phần đánh giá Qwen3.5-9B.

## KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN (2 trang) ⏳
Trả lời ngắn từng RQ; hạn chế; hướng phát triển: chưng cất và DPO bằng LoRA cho Qwen3.5-9B nếu W6.7 chưa làm, DPO trên dữ liệu chosen/rejected đã thu thập, mở rộng benchmark, GPU cloud, dữ liệu thật.

## TÀI LIỆU THAM KHẢO (25–35 mục)
Vaswani 2017; Hinton 2015; Kim & Rush 2016; Wei 2022; Yao 2023 ReAct; Schick 2023 Toolformer; Patil 2023 Gorilla; Zeng 2023 AgentTuning; Chen 2023 FireAct; Yao 2024 τ-bench; Barres 2025 τ²-bench; Lewis 2020 RAG; Karpukhin 2020 DPR; Liu 2023 Lost in the Middle; Greshake 2023; Kwon 2023 vLLM; Leviathan 2023 giải mã suy đoán; Gloeckle 2024 MTP; Yang 2025 Gated DeltaNet; Rafailov 2023 DPO; Qwen3.5 model card hoặc technical report; OWASP LLM Top 10; tài liệu CDIO.

Trong bản nháp, trích dẫn ghi tạm theo tác giả và năm, ví dụ [Yao 2023]; đổi sang số khi chốt danh mục.

## PHỤ LỤC
A. Schema công cụ · B. Trace mẫu một lượt nhiều bước · C. Bộ kịch bản đánh giá · D. Runbook deploy và migration · E. Hướng dẫn cài đặt.
